"""ASOLAR v2, etap 4b: dostawy WZ wobec zapotrzebowania, stan materiałów, meldunki dzienne."""
from datetime import date

from test_fieldwork import PNG
from test_structure import StructureBase


class LogisticsBase(StructureBase):
    def setUp(self):
        super().setUp()
        type_id = self.call("POST", "/types", {"code": "1x28"})["id"]
        self.call("POST", f"/types/{type_id}/bom", {"name": "Purlin", "code": "LT1", "spec": "J60", "quantity": 30})
        self.call("POST", f"/types/{type_id}/bom", {"name": "U bolt", "spec": "M10", "quantity": 60})
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 2})
        self.call("POST", "/tables/assign", {"ids": [t["id"] for t in self.get("/tables")], "structure_type_id": type_id})
        self.materials = {m["name"]: m for m in self.get("/materials")}
        self.foreman, self.foreman_headers = self.make_user("bryg")
        self.add_member(self.project["id"], self.foreman["id"], "brygadzista")

    def wz(self, number, lines, expect=200, headers=None, **extra):
        body = {"delivery_date": "2026-10-20", "wz_number": number, "items": lines, **extra}
        return self.call("POST", "/deliveries", body, expect, headers)

    def line(self, name, received, damaged=0):
        return {"material_key": self.materials[name]["key"], "quantity_received": received, "quantity_damaged": damaged}


class DeliveriesTest(LogisticsBase):
    def test_catalogue_comes_from_bom_with_requirements(self):
        self.assertEqual({name: m["required"] for name, m in self.materials.items()}, {"Purlin": 60, "U bolt": 120})

    def test_stock_balance_and_status(self):
        self.wz("WZ/1", [self.line("Purlin", 40, 2), self.line("U bolt", 120)], headers=self.foreman_headers)
        self.wz("WZ/2", [self.line("Purlin", 25)])
        stock = {item["name"]: item for item in self.get("/stock")["items"]}
        self.assertEqual((stock["Purlin"]["delivered"], stock["Purlin"]["damaged"], stock["Purlin"]["available"], stock["Purlin"]["status"]), (65, 2, 63, "komplet"))
        self.assertEqual(stock["U bolt"]["balance"], 0)
        summary = self.get("/stock")["summary"]
        self.assertEqual((summary["complete_items"], summary["missing_items"], summary["deliveries"]), (2, 0, 2))
        self.call("POST", "/tables/range", {"prefix": "T", "first": 3, "last": 3})
        table = next(t for t in self.get("/tables") if t["code"] == "T-3")
        self.call("POST", "/tables/assign", {"ids": [table["id"]], "structure_type_id": self.get("/types")[0]["id"]})
        stock = {item["name"]: item for item in self.get("/stock")["items"]}
        self.assertEqual((stock["U bolt"]["required"], stock["U bolt"]["status"]), (180, "brak"))

    def test_validation_and_offline_dedupe(self):
        self.assertIn("tylko raz", self.wz("WZ/x", [self.line("Purlin", 1), self.line("Purlin", 2)], expect=400)["detail"])
        self.assertIn("uszkodzona", self.wz("WZ/x", [self.line("Purlin", 1, 2)], expect=400)["detail"])
        self.assertIn("spoza katalogu", self.wz("WZ/x", [{"material_key": "wymyślony|x|szt.", "quantity_received": 5}], expect=400)["detail"])
        first = self.wz("WZ/9", [self.line("Purlin", 5)], client_id="wz-abc")
        again = self.wz("WZ/9", [self.line("Purlin", 5)], client_id="wz-abc")
        self.assertEqual(again, {"id": first["id"], "duplicate": True})
        self.assertEqual(len(self.get("/deliveries")), 1)

    def test_manager_edits_and_deletes_foreman_cannot(self):
        created = self.wz("WZ/1", [self.line("Purlin", 40)], headers=self.foreman_headers)
        body = {"delivery_date": "2026-10-21", "wz_number": "WZ/1-kor", "items": [self.line("Purlin", 38, 1), self.line("U bolt", 10)]}
        self.call("PUT", f"/deliveries/{created['id']}", body, 403, self.foreman_headers)
        self.call("PUT", f"/deliveries/{created['id']}", body)
        delivery = self.get("/deliveries")[0]
        self.assertEqual((delivery["wz_number"], len(delivery["items"]), delivery["updated_by"]), ("WZ/1-kor", 2, "Kierownik Budowy"))
        self.assertEqual({i["name"]: i["quantity_received"] for i in delivery["items"]}, {"Purlin": 38, "U bolt": 10})
        self.call("DELETE", f"/deliveries/{created['id']}", expect=403, headers=self.foreman_headers)
        self.call("DELETE", f"/deliveries/{created['id']}")
        self.assertEqual(self.get("/stock")["summary"]["deliveries"], 0)

    def test_delivered_material_removed_from_bom_stays_in_stock_and_editable(self):
        created = self.wz("WZ/1", [self.line("U bolt", 10)])
        type_ = self.get("/types")[0]
        bolt = next(b for b in type_["bom"] if b["name"] == "U bolt")
        self.call("DELETE", f"/bom/{bolt['id']}")
        stock = {item["name"]: item for item in self.get("/stock")["items"]}
        self.assertEqual((stock["U bolt"]["status"], stock["U bolt"]["delivered"]), ("poza zapotrzebowaniem", 10))
        body = {"delivery_date": "2026-10-20", "wz_number": "WZ/1", "items": [{"material_key": self.materials["U bolt"]["key"], "quantity_received": 12}]}
        self.call("PUT", f"/deliveries/{created['id']}", body)


class WorklogTest(LogisticsBase):
    def report(self, headers=None, expect=200, **extra):
        body = {"work_date": str(date.today()), "team": "Brygada A", "stage": "Montaż płatwi", "people": 4, "hours": 8, "tables_completed": 2, **extra}
        return self.call("POST", "/worklogs", body, expect, headers)

    def test_worklog_crud_permissions_and_dedupe(self):
        created = self.report(headers=self.foreman_headers, client_id="log-1", qc_notes="Momenty sprawdzone")
        self.assertEqual(self.report(headers=self.foreman_headers, client_id="log-1"), {"id": created["id"], "duplicate": True})
        logs = self.get("/worklogs")
        self.assertEqual((len(logs), logs[0]["manhours"], logs[0]["author"]), (1, 32, self.foreman["full_name"]))
        manager_log = self.report()
        body = {"work_date": str(date.today()), "team": "B", "stage": "x", "people": 1, "hours": 1}
        self.call("PATCH", f"/worklogs/{manager_log['id']}", body, 403, self.foreman_headers)
        self.call("PATCH", f"/worklogs/{created['id']}", {**body, "team": "Brygada A2"}, headers=self.foreman_headers)
        self.assertEqual(self.get("/worklogs", work_date=str(date.today()))[-1]["team"], "Brygada A2")
        self.call("DELETE", f"/worklogs/{created['id']}", expect=403, headers=self.foreman_headers)
        self.call("DELETE", f"/worklogs/{created['id']}")
        self.report(expect=422, people=0)
        self.report(expect=404, table_id=99999)

    def test_worklog_photos_also_by_offline_client_id(self):
        created = self.report(client_id="log-off")
        early = self.client.post(f"{self.base}/worklogs/by-client/nieznany/photos", headers=self.admin, files={"file": ("a.png", PNG, "image/png")})
        self.assertEqual(early.status_code, 404)
        sent = self.client.post(f"{self.base}/worklogs/by-client/log-off/photos", headers=self.admin, data={"client_id": "p-1"}, files={"file": ("a.png", PNG, "image/png")})
        self.assertEqual(sent.status_code, 200, sent.text)
        again = self.client.post(f"{self.base}/worklogs/{created['id']}/photos", headers=self.admin, data={"client_id": "p-1"}, files={"file": ("a.png", PNG, "image/png")})
        self.assertTrue(again.json()["duplicate"])
        photos = self.get(f"/worklogs/{created['id']}/photos")
        self.assertEqual(len(photos), 1)
        self.assertEqual(self.client.get(f"{self.base}/worklog-photos/{photos[0]['id']}/file", headers=self.admin).content, PNG)
        self.assertEqual(self.get("/worklogs")[0]["photos"], 1)
        self.call("DELETE", f"/worklogs/{created['id']}")
        self.assertEqual(self.get("/worklogs"), [])
