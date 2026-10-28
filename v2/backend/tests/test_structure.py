"""ASOLAR v2, etap 3: zatwierdzone propozycje zasilają strukturę budowy; zapotrzebowanie materiałów."""
from asolar2 import tenancy
from asolar2.tenancy import SiteTable
from test_documents import synthetic_pdf
from test_projects import V2Base


class StructureBase(V2Base):
    def setUp(self):
        self.project = self.make_project()
        self.base = f"/api/projects/{self.project['id']}"

    def get(self, path, **params):
        response = self.client.get(self.base + path, headers=self.admin, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def call(self, method, path, body=None, expect=200, headers=None):
        response = self.client.request(method, self.base + path, headers=headers or self.admin, json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def upload(self, *files):
        payload = [("files", (name, content, "application/pdf")) for name, content in files]
        response = self.client.post(f"{self.base}/documents", headers=self.admin, files=payload)
        self.assertEqual(response.status_code, 200, response.text)

    def suggestion(self, kind, **match):
        for item in self.get("/suggestions", kind=kind):
            if all(item["payload"].get(k) == v for k, v in match.items()):
                return item
        self.fail(f"brak propozycji {kind} {match}")

    def decide(self, item, status="zatwierdzona", expect=200, payload=None):
        body = {"status": status} if status else {}
        if payload:
            body["payload"] = payload
        return self.call("PATCH", f"/suggestions/{item['id']}", body, expect)


class ApplyTest(StructureBase):
    def test_approved_data_builds_types_bom_tables_and_requirements(self):
        self.upload(("bom.pdf", synthetic_pdf()))
        self.decide(self.suggestion("structure_type", code="1x42"))
        for name in ("Purlin 1", "Clamp", "Torque tube"):
            self.decide(self.suggestion("bom_line", name=name))
        self.decide(self.suggestion("numbering", prefix="T"))
        self.decide(self.suggestion("torque", bolt="M10"))

        types = self.get("/types")
        self.assertEqual([(t["code"], t["modules"], t["posts_per_table"]) for t in types], [("1x42", 42, None)])
        self.assertEqual({b["name"]: b["quantity"] for b in types[0]["bom"]}, {"Purlin 1": 44, "Clamp": 88, "Torque tube": 3})
        tables = self.get("/tables")
        self.assertEqual([t["code"] for t in tables], [f"T-{n}" for n in range(1, 13)])
        self.assertEqual(self.get("/catalog")["torques"][0]["bolt"], "M10")

        # Bez typu na stołach nic nie jest liczone — i jest o tym ostrzeżenie (nie zgadujemy).
        before = self.get("/requirements")
        self.assertEqual(before["totals"], [])
        self.assertTrue(any("12 stołów nie ma przypisanego typu" in w for w in before["warnings"]))

        ids = [t["id"] for t in tables[:10]]
        self.call("POST", "/tables/assign", {"ids": ids, "structure_type_id": types[0]["id"]})
        needs = self.get("/requirements")
        totals = {line["name"]: line["total"] for line in needs["totals"]}
        self.assertEqual(totals, {"Purlin 1": 440, "Clamp": 880, "Torque tube": 30})
        self.assertEqual(needs["modules_total"], 420)
        self.assertEqual(needs["tables_without_type"], 2)
        self.assertFalse(needs["posts_complete"])
        self.call("PATCH", f"/types/{types[0]['id']}", {"posts_per_table": 7})
        needs = self.get("/requirements")
        self.assertEqual((needs["posts_total"], needs["posts_complete"]), (70, True))

    def test_numbering_creates_only_numbers_seen_in_document(self):
        self.upload(("plan.pdf", synthetic_pdf(trackers=12)))
        item = self.suggestion("numbering", prefix="T")
        # Kierownik poszerza zakres do 15: numery 13–15 nie były w dokumencie, ale świadomie je dopisał.
        self.decide(item, payload={"last": 15})
        self.assertEqual(len(self.get("/tables")), 15)
        with tenancy.project_session(tenancy.storage_key_for(self.project["id"])) as session:
            self.assertEqual(session.query(SiteTable).filter(SiteTable.source_suggestion_id == item["id"]).count(), 15)

    def test_bom_line_without_structure_type_must_be_completed_first(self):
        self.upload(("bom.pdf", synthetic_pdf()))
        line = self.suggestion("bom_line", name="Clamp")
        self.decide(line, status=None, payload={"group": ""})
        refused = self.decide(line, expect=409)
        self.assertIn("brak typu konstrukcji", refused["detail"])
        self.assertEqual(self.get("/types"), [])
        self.assertEqual(next(s for s in self.get("/suggestions", kind="bom_line") if s["id"] == line["id"])["status"], "nowa")
        fixed = self.decide(line, payload={"group": "1x28"})
        self.assertTrue(fixed["applied_ref"].startswith("bom:"))
        self.assertEqual([t["code"] for t in self.get("/types")], ["1x28"])

    def test_conflicting_versions_cannot_both_become_bom(self):
        self.upload(("rev-a.pdf", synthetic_pdf(purlin_qty=44)), ("rev-b.pdf", synthetic_pdf(purlin_qty=46, extra="Rev B")))
        first, second = self.suggestion("bom_line", name="Purlin 1", quantity=44), self.suggestion("bom_line", name="Purlin 1", quantity=46)
        self.decide(first)
        refused = self.decide(second, expect=409)
        self.assertIn("ma już pozycję", refused["detail"])
        bom = self.get("/types")[0]["bom"]
        self.assertEqual([b["quantity"] for b in bom if b["name"] == "Purlin 1"], [44])

    def test_revert_removes_unused_records_and_refuses_when_used(self):
        self.upload(("plan.pdf", synthetic_pdf()))
        numbering = self.suggestion("numbering", prefix="T")
        zone = self.suggestion("zone", name="Zone A1")
        self.decide(numbering)
        self.decide(zone)
        zone_id = self.get("/zones")[0]["id"]
        table = self.get("/tables")[0]
        self.call("POST", "/tables/assign", {"ids": [table["id"]], "zone_id": zone_id})
        self.assertIn("przypisaną strefę", self.decide(numbering, status="nowa", expect=409)["detail"])
        self.assertIn("ma już przypisane stoły", self.decide(zone, status="odrzucona", expect=409)["detail"])
        self.call("POST", "/tables/assign", {"ids": [table["id"]], "zone_id": None})
        self.decide(numbering, status="nowa")
        self.assertEqual(self.get("/tables"), [])
        self.decide(zone, status="odrzucona")
        self.assertEqual(self.get("/zones"), [])

    def test_editing_approved_bom_line_reapplies(self):
        self.upload(("bom.pdf", synthetic_pdf()))
        line = self.decide(self.suggestion("bom_line", name="Clamp"))
        self.decide(line, status=None, payload={"quantity": 90})
        bom = self.get("/types")[0]["bom"]
        self.assertEqual([b["quantity"] for b in bom], [90])

    def test_bulk_approval_reports_refusals_and_applies_the_rest(self):
        self.upload(("bom.pdf", synthetic_pdf()))
        self.decide(self.suggestion("bom_line", name="Clamp"), status=None, payload={"group": ""})
        ids = [item["id"] for item in self.get("/suggestions", status="nowa")]
        result = self.call("POST", "/suggestions/bulk", {"ids": ids, "status": "zatwierdzona"})
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["updated"], len(ids) - 1)
        self.assertEqual(len(self.get("/tables")), 12)
        self.assertEqual(len(self.get("/suggestions", status="nowa")), 1)


class ManualStructureTest(StructureBase):
    def test_types_bom_rows_tables_manual_crud(self):
        type_id = self.call("POST", "/types", {"code": "1 X 28"})["id"]
        self.assertEqual(self.get("/types")[0]["code"], "1x28")
        self.assertEqual(self.get("/types")[0]["modules"], 28)
        self.call("POST", "/types", {"code": "1x28"}, expect=409)
        bom = self.call("POST", f"/types/{type_id}/bom", {"name": "Purlin", "quantity": 30})
        self.call("POST", f"/types/{type_id}/bom", {"name": "purlin", "quantity": 31}, expect=409)
        self.call("PATCH", f"/bom/{bom['id']}", {"name": "Purlin", "quantity": 32, "unit": "szt."})
        self.assertEqual(self.get("/types")[0]["bom"][0]["quantity"], 32)

        zone = self.call("POST", "/zones", {"name": "Strefa 1"})
        other = self.call("POST", "/zones", {"name": "Strefa 2"})
        row = self.call("POST", "/rows", {"name": "R1", "zone_id": zone["id"]})
        self.call("POST", "/rows", {"name": "r1", "zone_id": zone["id"]}, expect=409)
        self.assertEqual(self.call("POST", "/tables/range", {"prefix": "a", "first": 1, "last": 5}), {"added": 5, "skipped": 0})
        self.assertEqual(self.call("POST", "/tables/range", {"prefix": "A", "first": 4, "last": 6}), {"added": 1, "skipped": 2})
        tables = self.get("/tables")
        self.assertEqual([t["code"] for t in tables], ["A-1", "A-2", "A-3", "A-4", "A-5", "A-6"])
        ids = [t["id"] for t in tables[:3]]
        self.call("POST", "/tables/assign", {"ids": ids, "row_id": row["id"], "structure_type_id": type_id})
        assigned = self.get("/tables", row_id=row["id"])
        self.assertEqual({t["zone_id"] for t in assigned}, {zone["id"]})  # rząd wyznacza strefę
        self.call("POST", "/tables/assign", {"ids": ids, "zone_id": other["id"], "row_id": row["id"]}, expect=409)
        self.call("DELETE", f"/types/{type_id}", expect=409)
        self.assertEqual(len(self.get("/tables", zone_id=0)), 3)
        self.assertEqual(len(self.get("/tables", type_id=0)), 3)
        self.assertEqual(self.get("/requirements", zone_id=zone["id"])["totals"][0]["total"], 96)

        # Przeniesienie rzędu do innej strefy przenosi jego stoły.
        self.call("PATCH", f"/rows/{row['id']}", {"name": "R1", "zone_id": other["id"]})
        self.assertEqual({t["zone_id"] for t in self.get("/tables", row_id=row["id"])}, {other["id"]})
        self.call("DELETE", f"/rows/{row['id']}")
        self.assertEqual(len(self.get("/tables", row_id=0)), 6)
        self.call("POST", "/tables/delete", {"ids": [tables[-1]["id"]]})
        self.assertEqual(len(self.get("/tables")), 5)
        stats = self.get("")["stats"]
        self.assertEqual((stats["tables"], stats["types"]), (5, 1))

    def test_foreman_reads_structure_but_cannot_change_it(self):
        user, headers = self.make_user("bryg")
        self.add_member(self.project["id"], user["id"], "brygadzista")
        self.call("POST", "/types", {"code": "1x28"}, expect=403, headers=headers)
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 2}, expect=403, headers=headers)
        self.assertEqual(self.client.get(f"{self.base}/requirements", headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f"{self.base}/tables", headers=headers).status_code, 200)

    def test_structure_is_isolated_between_projects(self):
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 3})
        other = self.make_project()
        self.assertEqual(self.client.get(f"/api/projects/{other['id']}/tables", headers=self.admin).json(), [])
        self.assertEqual(self.client.get(f"/api/projects/{other['id']}/requirements", headers=self.admin).json()["tables_total"], 0)

    def test_migration_adds_new_columns_to_old_storage(self):
        key = tenancy.storage_key_for(self.project["id"])
        from sqlalchemy import inspect, text
        engine = tenancy.project_bind(key)
        with engine.begin() as connection:
            if tenancy.IS_POSTGRES:
                connection.execute(text(f'ALTER TABLE "{key}"."zones" DROP COLUMN source_suggestion_id'))
            else:
                connection.execute(text('ALTER TABLE "zones" DROP COLUMN source_suggestion_id'))
        tenancy.create_storage(key)
        with engine.connect() as connection:
            columns = {c["name"] for c in inspect(connection).get_columns("zones", schema=key if tenancy.IS_POSTGRES else None)}
        self.assertIn("source_suggestion_id", columns)
