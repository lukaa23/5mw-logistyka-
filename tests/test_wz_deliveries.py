"""Dostawy na budowę (WZ): przyjęcie, edycja, usunięcie i przeliczenie bilansu „Dostarczone vs Wymagane”."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'asolar-wz-test.db'}")
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret")

from fastapi.testclient import TestClient

from app.main import app

VARIANTS = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")


class WzDeliveriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman = cls.login("brygadzista1", "Brygada1-2026!")
        cls.project_id = cls.client.post("/api/projects", headers=cls.manager, json={"name": "WZ test", "location": "Pole", "capacity_mw": 1}).json()["id"]
        zone = cls.client.post("/api/tracker-zones", headers=cls.manager, json={"project_id": cls.project_id, "name": "Strefa WZ"}).json()
        cls.client.put(f"/api/tracker-zones/{zone['id']}/config", headers=cls.manager, json={"items": [{"variant_code": v, "row_count": 2 if v == "1x28" else 0} for v in VARIANTS]})

    @classmethod
    def tearDownClass(cls):
        cls.client.patch(f"/api/projects/{cls.project_id}", headers=cls.manager, json={"archived": True})
        cls.client.delete(f"/api/projects/{cls.project_id}", headers=cls.manager)

    @classmethod
    def login(cls, username, password):
        return {"Authorization": "Bearer " + cls.client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]}

    def status(self):
        return self.client.get(f"/api/projects/{self.project_id}/bom-delivery-status", headers=self.manager).json()

    def line(self, component_id):
        return next(item for item in self.status()["items"] if item["component_id"] == component_id)

    def test_full_wz_flow_add_edit_delete_recalculates_balance(self):
        items = [item for item in self.status()["items"] if item["required"] > 0]
        bolt = next(item for item in items if "M16" in item["name"] or "M16" in item["key"])
        tube = next(item for item in items if item["category"] == "Rury torsyjne")
        module = next(item for item in self.status()["items"] if item["category"] == "Moduły PV")
        self.assertEqual(self.line(bolt["component_id"])["delivered"], 0)
        demand_before = self.client.get(f"/api/projects/{self.project_id}/tracker-config", headers=self.manager).json()["grand_total"]

        # 1. Brygadzista przyjmuje WZ z trzema pozycjami (śruby, rury, moduły Jinko).
        created = self.client.post("/api/bom-deliveries", headers=self.foreman, json={
            "project_id": self.project_id, "delivery_date": "2026-10-17", "wz_number": " WZ/2026/101 ", "supplier": "ESET", "note": "Paleta 1/2", "client_id": "wz-flow-1",
            "items": [
                {"component_id": bolt["component_id"], "quantity_received": 50, "quantity_damaged": 2},
                {"component_id": tube["component_id"], "quantity_received": 4, "quantity_damaged": 0},
                {"component_id": module["component_id"], "quantity_received": 56, "quantity_damaged": 1},
            ]})
        self.assertEqual(created.status_code, 200, created.text)
        wz_id = created.json()["id"]

        history = self.client.get(f"/api/bom-deliveries?project_id={self.project_id}", headers=self.foreman).json()
        self.assertEqual(history[0]["id"], wz_id)
        self.assertEqual(history[0]["wz_number"], "WZ/2026/101")
        self.assertEqual(len(history[0]["items"]), 3)
        self.assertEqual(history[0]["created_by"], "Brygadzista 1")
        bolt_line = self.line(bolt["component_id"])
        self.assertEqual((bolt_line["delivered"], bolt_line["damaged"], bolt_line["available"]), (50, 2, 48))
        self.assertEqual(bolt_line["balance"], 48 - bolt["required"])
        self.assertEqual(self.line(module["component_id"])["available"], 55)
        self.assertEqual(self.status()["summary"]["deliveries_count"], 1)

        # 2. Brygadzista nie edytuje ani nie usuwa przyjętego WZ.
        update = {"delivery_date": "2026-10-18", "wz_number": "WZ/2026/101-K", "supplier": "ESET Polska", "note": "Korekta po przeliczeniu",
                  "items": [{"component_id": bolt["component_id"], "quantity_received": 60, "quantity_damaged": 0},
                            {"component_id": module["component_id"], "quantity_received": 56, "quantity_damaged": 1}]}
        self.assertEqual(self.client.put(f"/api/bom-deliveries/{wz_id}", headers=self.foreman, json=update).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/bom-deliveries/{wz_id}", headers=self.foreman).status_code, 403)

        # 3. Kierownik koryguje WZ: zmiana ilości, usunięcie pozycji rur — bilans przeliczony.
        edited = self.client.put(f"/api/bom-deliveries/{wz_id}", headers=self.manager, json=update)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.line(bolt["component_id"])["available"], 60)
        self.assertEqual(self.line(tube["component_id"])["delivered"], 0)
        history = self.client.get(f"/api/bom-deliveries?project_id={self.project_id}", headers=self.manager).json()
        self.assertEqual((history[0]["wz_number"], history[0]["supplier"], history[0]["delivery_date"]), ("WZ/2026/101-K", "ESET Polska", "2026-10-18"))
        self.assertEqual(history[0]["updated_by"], "Kierownik Budowy")
        self.assertIsNotNone(history[0]["updated_at"])
        self.assertEqual(history[0]["created_by"], "Brygadzista 1")

        # 4. Walidacja edycji jak przy dodawaniu.
        bad = dict(update, items=[{"component_id": bolt["component_id"], "quantity_received": 1, "quantity_damaged": 5}])
        self.assertEqual(self.client.put(f"/api/bom-deliveries/{wz_id}", headers=self.manager, json=bad).status_code, 400)
        duplicate = dict(update, items=update["items"] + [update["items"][0]])
        self.assertEqual(self.client.put(f"/api/bom-deliveries/{wz_id}", headers=self.manager, json=duplicate).status_code, 400)
        self.assertEqual(self.client.put(f"/api/bom-deliveries/{wz_id}", headers=self.manager, json=dict(update, items=[])).status_code, 422)
        self.assertEqual(self.client.put("/api/bom-deliveries/999999", headers=self.manager, json=update).status_code, 404)
        self.assertEqual(self.line(bolt["component_id"])["available"], 60)  # nieudana edycja nic nie zmienia

        # 5. Usunięcie WZ cofa bilans do zera; zapotrzebowanie projektowe bez zmian.
        self.assertEqual(self.client.delete(f"/api/bom-deliveries/{wz_id}", headers=self.manager).status_code, 200)
        self.assertEqual(self.line(bolt["component_id"])["delivered"], 0)
        self.assertEqual(self.line(module["component_id"])["available"], 0)
        self.assertEqual(self.status()["summary"]["deliveries_count"], 0)
        self.assertEqual(self.client.get(f"/api/bom-deliveries?project_id={self.project_id}", headers=self.manager).json(), [])
        demand_after = self.client.get(f"/api/projects/{self.project_id}/tracker-config", headers=self.manager).json()["grand_total"]
        self.assertEqual(demand_after, demand_before)

    def test_catalogue_contains_searchable_eset_and_jinko_items(self):
        items = self.status()["items"]
        text = " ".join(f"{item['name']} {item['key']} {item.get('spec', '')}" for item in items)
        for fragment in ("M16", "Płatew", "Jinko"):
            self.assertIn(fragment.lower(), text.lower(), fragment)
        self.assertTrue(any(item["category"] == "Rury torsyjne" for item in items))


if __name__ == "__main__":
    unittest.main()
