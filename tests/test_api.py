import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "asolar-universal-test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["ASOLAR_SECRET"] = "test-only-secret"

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.database import SessionLocal
from app.main import app
from app.services.parser import analyze


class UniversalWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman = cls.login("brygadzista", "Brygada2026!")
        cls.warehouse = cls.login("magazynier", "Magazyn2026!")

    @classmethod
    def login(cls, username, password):
        response = cls.client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_flexible_project_rows_templates_reports_and_field_stock(self):
        created = self.client.post(
            "/api/projects", headers=self.manager,
            json={"name": "Universal PV", "location": "Poznań", "capacity_mw": 7.25, "structure_type": "tracker 1-noga / wariant własny"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["id"]

        edited = self.client.patch(
            f"/api/projects/{project_id}", headers=self.manager,
            json={"name": "Universal PV — etap 2", "structure_type": "tracker mieszany: 1-noga i 2-nogi"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertIn("2-nogi", edited.json()["structure_type"])

        materials = self.client.get(f"/api/projects/{project_id}/materials", headers=self.manager).json()
        self.assertEqual(len(materials), 3)
        initial_stock = self.client.get(f"/api/logistics/stock?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(len(initial_stock), 3)
        self.assertTrue(all(item["available"] == 0 for item in initial_stock))

        demand_payload = {"items": [
            {"slot_number": 1, "name": "Rury momentowe", "unit": "szt.", "required_quantity": 100},
            {"slot_number": 2, "name": "Płatwie", "unit": "szt.", "required_quantity": 280},
            {"slot_number": 3, "name": "Zestawy śrubowe", "unit": "kpl.", "required_quantity": 560},
        ]}
        response = self.client.put(f"/api/projects/{project_id}/materials", headers=self.warehouse, json=demand_payload)
        self.assertEqual(response.status_code, 200, response.text)
        materials = self.client.get(f"/api/projects/{project_id}/materials", headers=self.manager).json()

        template = self.client.post(
            "/api/material-templates", headers=self.foreman,
            json={"project_id": project_id, "name": "1x28", "structure_type": "tracker 1-noga", "default_length_m": 38.45, "specification": "Konfiguracja zapisana przez użytkownika", "materials": {"1": 5, "2": 30, "3": 60}},
        )
        self.assertEqual(template.status_code, 200, template.text)
        template_id = template.json()["id"]

        calculated = self.client.post(
            "/api/calculator", headers=self.manager,
            json={"project_id": project_id, "template_id": template_id, "variant_name": "1x28 po korekcie", "length_m": 123.456, "row_count": 4, "materials": {"1": 7, "2": 31, "3": 65}},
        )
        self.assertEqual(calculated.status_code, 200, calculated.text)
        result = calculated.json()
        self.assertEqual(len(result["materials"]), 3)
        self.assertEqual(result["materials"][0]["per_row"], 7)
        self.assertEqual(result["materials"][0]["total"], 28)
        self.assertEqual(result["input"]["length_m"], 123.456)

        zone = self.client.post("/api/zones", headers=self.manager, json={"project_id": project_id, "name": "Strefa użytkownika"})
        section = self.client.post("/api/sections", headers=self.manager, json={"zone_id": zone.json()["id"], "name": "Sekcja dowolna"})
        section_id = section.json()["id"]
        row_one = self.client.post(
            "/api/rows", headers=self.foreman,
            json={"section_id": section_id, "code": "R-A01", "template_id": template_id, "variant_name": "1x28", "length_m": 38.45, "specification": "Standard plus korekta ręczna", "material_quantities": {"1": 5, "2": 30, "3": 61}},
        )
        row_two = self.client.post(
            "/api/rows", headers=self.foreman,
            json={"section_id": section_id, "code": "R-A02-X", "template_id": None, "variant_name": "1x42 nietypowy", "length_m": 61.987, "specification": "Układ całkowicie ręczny", "material_quantities": {"1": 9, "2": 44, "3": 93}},
        )
        self.assertEqual(row_one.status_code, 200, row_one.text)
        self.assertEqual(row_two.status_code, 200, row_two.text)
        row_one_id, row_two_id = row_one.json()["id"], row_two.json()["id"]

        changed_row = self.client.patch(
            f"/api/rows/{row_two_id}", headers=self.foreman,
            json={"length_m": 62.111, "variant_name": "układ specjalny po pomiarze", "material_quantities": {"1": 10, "2": 45, "3": 96}},
        )
        self.assertEqual(changed_row.status_code, 200, changed_row.text)
        self.assertEqual(changed_row.json()["length_m"], 62.111)
        self.assertEqual(changed_row.json()["material_quantities"]["3"], 96)

        self.assertEqual(self.client.patch(f"/api/rows/{row_one_id}", headers=self.foreman, json={"built": True}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/rows/{row_one_id}", headers=self.foreman, json={"qc_checked": True}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/rows/{row_one_id}", headers=self.manager, json={"qc_checked": True}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/sections/{section_id}/archive", headers=self.manager).status_code, 409)
        self.client.patch(f"/api/rows/{row_two_id}", headers=self.foreman, json={"built": True})
        self.client.patch(f"/api/rows/{row_two_id}", headers=self.manager, json={"qc_checked": True})
        self.assertEqual(self.client.post(f"/api/sections/{section_id}/archive", headers=self.manager).status_code, 200)

        arbitrary_work = "Nietypowa korekta osi rury i ręczna modyfikacja wspornika według decyzji kierownika"
        worklog = self.client.post(
            "/api/worklogs", headers=self.foreman,
            json={"project_id": project_id, "work_date": "2026-10-14", "team": "Brygada mobilna", "stage": arbitrary_work, "people": 6, "hours": 8, "rows_completed": 2, "qc_notes": "Sprawdzono geometrię. Rząd R-A02-X do ponownej kontroli momentu.", "note": "Meldunek z telefonu", "row_id": row_two_id, "client_id": "universal-log-1"},
        )
        self.assertEqual(worklog.status_code, 200, worklog.text)
        worklog_id = worklog.json()["id"]
        photo = self.client.post(
            f"/api/worklog/{worklog_id}/photos", headers=self.foreman,
            files={"file": ("teren.jpg", b"test-image-content", "image/jpeg")},
        )
        self.assertEqual(photo.status_code, 200, photo.text)
        history = self.client.get(f"/api/worklog/{worklog_id}/photos", headers=self.manager).json()
        self.assertEqual(len(history), 1)
        logs = self.client.get(f"/api/worklogs?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(logs[0]["stage"], arbitrary_work)
        self.assertIn("geometrię", logs[0]["qc_notes"])
        self.assertEqual(logs[0]["photos"], 1)

        delivery = self.client.post(
            "/api/deliveries", headers=self.warehouse,
            json={"project_id": project_id, "delivery_date": "2026-10-14", "wz_number": "WZ/FIELD/1", "supplier": "Dostawca", "client_id": "field-delivery-1", "items": [{"material_id": materials[0]["id"], "quantity_received": 40, "quantity_damaged": 2}]},
        )
        self.assertEqual(delivery.status_code, 200, delivery.text)
        stock = self.client.get(f"/api/logistics/stock?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(len(stock), 3)
        self.assertEqual(stock[0]["available"], 38)
        self.assertEqual(stock[1]["available"], 0)

        report = self.client.get(f"/api/reports/daily?project_id={project_id}&report_date=2026-10-14", headers=self.manager)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.content.startswith(b"%PDF"))

        archived = self.client.patch(f"/api/projects/{project_id}", headers=self.manager, json={"archived": True})
        self.assertTrue(archived.json()["archived"])
        active_projects = self.client.get("/api/projects", headers=self.manager).json()
        self.assertFalse(any(item["id"] == project_id for item in active_projects))
        all_projects = self.client.get("/api/projects?include_archived=true", headers=self.manager).json()
        self.assertTrue(any(item["id"] == project_id for item in all_projects))
        deleted = self.client.delete(f"/api/projects/{project_id}", headers=self.manager)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        after_delete = self.client.get("/api/projects?include_archived=true", headers=self.manager).json()
        self.assertFalse(any(item["id"] == project_id for item in after_delete))

    def test_excel_bom_import_still_works_for_document_analysis(self):
        path = Path(tempfile.gettempdir()) / "asolar-universal-bom.xlsx"
        workbook = Workbook(); sheet = workbook.active
        sheet.append(["typ_rzedu", "typ_konstrukcji", "dlugosc_m", "sku", "nazwa", "kategoria", "ilosc", "jednostka", "moment_min", "moment_max"])
        sheet.append(["DOWOLNY", "2-nogi", 51.2, "USR-M12", "Śruba własna M12", "Śruby", 84, "szt.", 45, 55])
        workbook.save(path)
        with SessionLocal() as db: result = analyze(path, ".xlsx", db)
        self.assertEqual(result["summary"]["relations"], 1)


if __name__ == "__main__":
    unittest.main()
