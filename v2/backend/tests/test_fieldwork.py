"""ASOLAR v2, etap 4a: postęp stołów (montaż, QA/QC), notatki i zdjęcia — także z kolejki offline."""
from datetime import UTC, datetime, timedelta

from test_documents import synthetic_pdf
from test_structure import StructureBase

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FieldworkBase(StructureBase):
    def setUp(self):
        super().setUp()
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 4})
        self.tables = {t["code"]: t for t in self.get("/tables")}
        self.foreman, self.foreman_headers = self.make_user("bryg")
        self.add_member(self.project["id"], self.foreman["id"], "brygadzista")

    def progress(self, code, body, expect=200, headers=None):
        return self.call("PATCH", f"/tables/{self.tables[code]['id']}/progress", body, expect, headers)

    def photo(self, code, client_id=None, content=PNG, mime="image/png", headers=None):
        data = {"client_id": client_id} if client_id else {}
        return self.client.post(f"{self.base}/tables/{self.tables[code]['id']}/photos", headers=headers or self.admin, data=data, files={"file": ("foto.png", content, mime)})


class ProgressTest(FieldworkBase):
    def test_foreman_marks_built_manager_does_qc(self):
        self.progress("T-1", {"qc_checked": True}, expect=400)
        built = self.progress("T-1", {"built": True}, headers=self.foreman_headers)
        self.assertTrue(built["built"])
        self.assertIn("Odbiór QA/QC wykonuje kierownik", self.progress("T-1", {"qc_checked": True}, expect=403, headers=self.foreman_headers)["detail"])
        self.assertTrue(self.progress("T-1", {"qc_checked": True})["qc_checked"])
        # Cofnięcie montażu unieważnia odbiór.
        undone = self.progress("T-1", {"built": False}, headers=self.foreman_headers)
        self.assertEqual((undone["built"], undone["qc_checked"]), (False, False))

    def test_offline_client_time_is_used_but_not_from_future(self):
        earlier = datetime.now(UTC) - timedelta(hours=5)
        result = self.progress("T-2", {"built": True, "client_time": earlier.isoformat()})
        self.assertTrue(result["built_at"].startswith(earlier.replace(tzinfo=None).isoformat()[:16]))
        future = datetime.now(UTC) + timedelta(days=2)
        result = self.progress("T-3", {"built": True, "client_time": future.isoformat()})
        self.assertLess(datetime.fromisoformat(result["built_at"]), datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=1))

    def test_progress_summary_by_zone_and_type(self):
        zone = self.call("POST", "/zones", {"name": "Strefa 1"})
        type_id = self.call("POST", "/types", {"code": "1x28"})["id"]
        self.call("POST", "/tables/assign", {"ids": [self.tables["T-1"]["id"], self.tables["T-2"]["id"]], "zone_id": zone["id"], "structure_type_id": type_id})
        self.progress("T-1", {"built": True})
        self.progress("T-1", {"qc_checked": True})
        self.progress("T-3", {"built": True})
        summary = self.get("/progress")
        self.assertEqual((summary["total"], summary["built"], summary["qc"]), (4, 2, 1))
        zones = {z["name"]: z for z in summary["zones"]}
        self.assertEqual((zones["Strefa 1"]["total"], zones["Strefa 1"]["built"], zones["Strefa 1"]["qc"]), (2, 1, 1))
        self.assertEqual(zones["bez przypisania"]["built"], 1)
        self.assertEqual(self.get("/progress", zone_id=zone["id"])["total"], 2)

    def test_archived_project_refuses_field_writes(self):
        self.call("PATCH", "", {"archived": True})
        self.progress("T-1", {"built": True}, expect=409)


class NotesPhotosTest(FieldworkBase):
    def test_notes_are_idempotent_and_editable_by_author_or_manager(self):
        table_id = self.tables["T-1"]["id"]
        first = self.call("POST", f"/tables/{table_id}/notes", {"text": "Brak śruby M10", "client_id": "note-abc"}, headers=self.foreman_headers)
        again = self.call("POST", f"/tables/{table_id}/notes", {"text": "Brak śruby M10", "client_id": "note-abc"}, headers=self.foreman_headers)
        self.assertEqual(again, {"id": first["id"], "duplicate": True})
        manager_note = self.call("POST", f"/tables/{table_id}/notes", {"text": "Sprawdzić naciąg"})
        notes = self.get(f"/tables/{table_id}/notes")
        self.assertEqual([n["text"] for n in notes], ["Sprawdzić naciąg", "Brak śruby M10"])
        self.call("PATCH", f"/tables/{table_id}/notes/{manager_note['id']}", {"text": "zmiana"}, expect=403, headers=self.foreman_headers)
        self.call("PATCH", f"/tables/{table_id}/notes/{first['id']}", {"text": "Brak 2 śrub M10"}, headers=self.foreman_headers)
        edited = next(n for n in self.get(f"/tables/{table_id}/notes") if n["id"] == first["id"])
        self.assertEqual((edited["text"], edited["edited_by"]), ("Brak 2 śrub M10", self.foreman["full_name"]))
        self.call("DELETE", f"/tables/{table_id}/notes/{first['id']}")  # kierownik może usunąć cudzą
        self.call("DELETE", f"/tables/{table_id}/notes/{first['id']}", expect=404)
        self.assertEqual(self.get("/tables")[0]["notes"], 1)

    def test_photos_upload_dedupe_download_delete(self):
        sent = self.photo("T-2", client_id="photo-1", headers=self.foreman_headers)
        self.assertEqual(sent.status_code, 200, sent.text)
        again = self.photo("T-2", client_id="photo-1", headers=self.foreman_headers)
        self.assertEqual(again.json(), {"id": sent.json()["id"], "duplicate": True})
        self.assertEqual(self.photo("T-2", content=b"%PDF-1.4", mime="application/pdf").status_code, 400)
        photos = self.get(f"/tables/{self.tables['T-2']['id']}/photos")
        self.assertEqual(len(photos), 1)
        file = self.client.get(f"{self.base}/photos/{photos[0]['id']}/file", headers=self.admin)
        self.assertEqual((file.status_code, file.content), (200, PNG))
        other = self.photo("T-2")
        self.call("DELETE", f"/photos/{other.json()['id']}", expect=403, headers=self.foreman_headers)
        self.call("DELETE", f"/photos/{photos[0]['id']}", headers=self.foreman_headers)
        self.assertEqual(self.get("/tables")[1]["photos"], 1)

    def test_tables_with_field_data_are_protected_from_deletion(self):
        self.progress("T-1", {"built": True})
        self.call("POST", f"/tables/{self.tables['T-2']['id']}/notes", {"text": "uwaga"})
        refused = self.call("POST", "/tables/delete", {"ids": [t["id"] for t in self.tables.values()]}, expect=409)
        self.assertIn("T-1, T-2", refused["detail"])
        self.assertEqual(self.call("POST", "/tables/delete", {"ids": [self.tables["T-3"]["id"], self.tables["T-4"]["id"]]})["deleted"], 2)

    def test_numbering_revert_refused_when_tables_have_progress(self):
        self.upload(("plan.pdf", synthetic_pdf()))
        numbering = self.suggestion("numbering", prefix="T")
        self.decide(numbering)
        table = next(t for t in self.get("/tables") if t["code"] == "T-5")
        self.call("PATCH", f"/tables/{table['id']}/progress", {"built": True})
        self.assertIn("zapisany postęp", self.decide(numbering, status="nowa", expect=409)["detail"])

    def test_field_data_isolated_between_projects(self):
        self.call("POST", f"/tables/{self.tables['T-1']['id']}/notes", {"text": "tylko tu"})
        other = self.make_project()
        response = self.client.get(f"/api/projects/{other['id']}/tables/{self.tables['T-1']['id']}/notes", headers=self.admin)
        self.assertEqual(response.status_code, 404)
