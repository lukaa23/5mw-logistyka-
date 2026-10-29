"""Uproszczony import: rodzaj dokumentu decyduje o odczycie, tryb ręczny zamiast błędów, wpisy ręczne."""
from test_bom_per_type import bom_pdf, manual_pdf
from test_documents import synthetic_pdf
from test_structure import StructureBase


class SimpleImportTest(StructureBase):
    def upload_as(self, category, name, content):
        response = self.client.post(f"{self.base}/documents", headers=self.admin, params={"category": category},
                                    files=[("files", (name, content, "application/pdf"))])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["accepted"][0]

    def kinds(self, document_id):
        return {item["kind"] for item in self.get("/suggestions") if any(s["document_id"] == document_id for s in item["sources"])}

    def test_category_decides_what_is_extracted(self):
        # Ten sam rysunek z tabelą: jako „rysunek” — numeracja/strefy/typy, bez pozycji BOM.
        drawing = self.upload_as("rysunek", "plan.pdf", synthetic_pdf())
        self.assertNotIn("bom_line", self.kinds(drawing["id"]))
        self.assertIn("numbering", self.kinds(drawing["id"]))
        bom = self.upload_as("bom", "bom.pdf", bom_pdf())
        self.assertEqual(self.kinds(bom["id"]), {"bom_line", "structure_type"})
        manual = self.upload_as("instrukcja", "manual.pdf", manual_pdf())
        # Instrukcja: moment tak, lista „Number” bez typu konstrukcji — nie (nie zgadujemy stołu).
        self.assertEqual(self.kinds(manual["id"]), {"torque"})

    def test_changing_document_type_reads_it_again(self):
        document = self.upload_as("rysunek", "plan.pdf", synthetic_pdf())
        self.assertNotIn("bom_line", self.kinds(document["id"]))
        self.call("PATCH", f"/documents/{document['id']}", {"category": "bom"})
        self.assertIn("bom_line", self.kinds(document["id"]))

    def test_nothing_found_or_unreadable_means_manual_mode(self):
        # Rysunek bez numeracji, stref i typów → nic do odczytu → tryb ręczny (nie błąd).
        empty = self.upload_as("rysunek", "pusty.pdf", manual_pdf())
        saved = next(d for d in self.get("/documents") if d["id"] == empty["id"])
        self.assertEqual((saved["status"], saved["pages"]), ("ręcznie", 1))
        broken = self.upload_as("bom", "skan.pdf", b"%PDF-1.4\nuszkodzony")
        saved = next(d for d in self.get("/documents") if d["id"] == broken["id"])
        self.assertEqual(saved["status"], "ręcznie")
        self.assertIn("ręcznie", saved["error"])

    def test_manual_items_next_to_preview(self):
        document = self.upload_as("bom", "skan.pdf", b"%PDF-1.4\nuszkodzony")
        type_item = self.call("POST", "/suggestions", {"kind": "structure_type", "payload": {"code": "2 X 26"}, "document_id": document["id"], "page": 2, "approve": True})
        self.assertEqual((type_item["status"], type_item["payload"]["code"], type_item["payload"]["modules"]), ("zatwierdzona", "2x26", 52))
        line = self.call("POST", "/suggestions", {"kind": "bom_line", "payload": {"name": "Pole 1", "quantity": 11, "group": "2x26"}, "document_id": document["id"]})
        self.assertEqual((line["status"], line["sources"][0]["filename"], line["sources"][0]["page"]), ("nowa", "skan.pdf", 1))
        self.call("PATCH", f"/suggestions/{line['id']}", {"status": "zatwierdzona"})
        bom = next(t for t in self.get("/types") if t["code"] == "2x26")["bom"]
        self.assertEqual([(b["name"], b["quantity"]) for b in bom], [("Pole 1", 11)])
        self.call("POST", "/suggestions", {"kind": "bom_line", "payload": {"name": "Pole 2"}}, expect=400)
        self.call("POST", "/suggestions", {"kind": "zone", "payload": {"name": "X", "count": 3}}, expect=400)
        # Ponowny odczyt pliku nie kasuje wpisów ręcznych.
        self.call("POST", f"/documents/{document['id']}/reanalyze")
        self.assertIn(line["id"], [item["id"] for item in self.get("/suggestions")])


class SqliteConcurrencyTest(StructureBase):
    """Wgrywanie kolejnego pliku w trakcie zapisu analizy poprzedniego nie może kończyć się „database is locked”."""

    def test_parallel_read_then_write_sessions_do_not_deadlock(self):
        import threading
        import time

        from asolar2 import tenancy
        from asolar2.tenancy import Zone
        from sqlalchemy import func, select

        if tenancy.IS_POSTGRES:
            self.skipTest("dotyczy SQLite (tryb lokalny)")
        key = tenancy.storage_key_for(self.project["id"])
        errors = []

        def worker(name):
            try:
                with tenancy.project_session(key) as session:
                    session.scalar(select(func.count(Zone.id)))  # odczyt…
                    time.sleep(0.3)                               # …dłuższa praca…
                    session.add(Zone(name=name))                  # …potem zapis
                    session.commit()
            except Exception as error:  # pragma: no cover - błąd testu
                errors.append(repr(error))

        threads = [threading.Thread(target=worker, args=(f"Strefa {index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.get("/zones")), 4)
