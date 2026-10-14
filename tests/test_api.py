import os
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "asolar-enterprise-test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["ASOLAR_SECRET"] = "test-only-secret"

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.services.parser import analyze
from openpyxl import Workbook


class EnterpriseWorkflowTest(unittest.TestCase):
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

    def test_complete_construction_logistics_and_reporting_workflow(self):
        project = self.client.post(
            "/api/projects",
            headers=self.manager,
            json={"name": "Test PV", "location": "Polska", "capacity_mw": 5.0},
        )
        self.assertEqual(project.status_code, 200, project.text)
        project_id = project.json()["id"]

        zone = self.client.post("/api/zones", headers=self.manager, json={"project_id": project_id, "name": "Z1"})
        section = self.client.post("/api/sections", headers=self.manager, json={"zone_id": zone.json()["id"], "name": "S1"})
        section_id = section.json()["id"]
        row_type_id = self.client.get("/api/row-types", headers=self.manager).json()[0]["id"]

        rows = self.client.post(
            "/api/rows/bulk",
            headers=self.manager,
            json={"section_id": section_id, "prefix": "T", "start_number": 1, "count": 2, "row_type_id": row_type_id, "length_m": 40},
        )
        self.assertEqual(rows.status_code, 200, rows.text)
        row_ids = rows.json()["ids"]
        self.assertEqual(len(row_ids), 2)

        built = self.client.patch(f"/api/rows/{row_ids[0]}", headers=self.foreman, json={"built": True})
        self.assertEqual(built.status_code, 200, built.text)
        forbidden_qc = self.client.patch(f"/api/rows/{row_ids[0]}", headers=self.foreman, json={"qc_checked": True})
        self.assertEqual(forbidden_qc.status_code, 403)
        qc = self.client.patch(f"/api/rows/{row_ids[0]}", headers=self.manager, json={"qc_checked": True})
        self.assertEqual(qc.status_code, 200, qc.text)
        blocked_archive = self.client.post(f"/api/sections/{section_id}/archive", headers=self.manager)
        self.assertEqual(blocked_archive.status_code, 409)

        self.client.patch(f"/api/rows/{row_ids[1]}", headers=self.foreman, json={"built": True})
        self.client.patch(f"/api/rows/{row_ids[1]}", headers=self.manager, json={"qc_checked": True})
        archived = self.client.post(f"/api/sections/{section_id}/archive", headers=self.manager)
        self.assertEqual(archived.status_code, 200, archived.text)

        rfi = self.client.post(
            "/api/rfis",
            headers=self.foreman,
            json={"project_id": project_id, "row_id": row_ids[0], "title": "Kolizja", "description": "Test RFI", "priority": "wysoki", "client_id": "test-rfi-1"},
        )
        self.assertEqual(rfi.status_code, 200, rfi.text)
        self.assertEqual(self.client.get(f"/api/rfis?project_id={project_id}", headers=self.manager).json()[0]["status"], "otwarty")

        requirements = self.client.get(f"/api/requirements?project_id={project_id}", headers=self.manager).json()
        self.assertGreater(len(requirements), 0)
        delivery = self.client.post(
            "/api/deliveries",
            headers=self.warehouse,
            json={"project_id": project_id, "delivery_date": "2026-10-14", "wz_number": "WZ/1", "supplier": "Test", "client_id": "test-delivery-1", "items": [{"component_id": requirements[0]["component_id"], "quantity_received": requirements[0]["required"], "quantity_damaged": 0}]},
        )
        self.assertEqual(delivery.status_code, 200, delivery.text)

        worklog = self.client.post(
            "/api/worklogs",
            headers=self.foreman,
            json={"project_id": project_id, "work_date": "2026-10-14", "team": "Brygada T", "stage": "Montaż konstrukcji", "people": 4, "hours": 8, "rows_completed": 2, "client_id": "test-log-1"},
        )
        self.assertEqual(worklog.status_code, 200, worklog.text)
        dashboard = self.client.get(f"/api/dashboard?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(dashboard["rows_built"], 2)
        self.assertEqual(dashboard["rows_qc"], 2)
        self.assertEqual(dashboard["open_rfi"], 1)
        self.assertEqual(dashboard["manhours"], 32)

        calculated = self.client.post(
            "/api/calculator", headers=self.manager, json={"row_type_id": row_type_id, "length_m": 50, "row_count": 10}
        )
        self.assertEqual(calculated.status_code, 200, calculated.text)
        self.assertGreater(len(calculated.json()["materials"]), 0)
        self.assertGreater(len(calculated.json()["tools"]), 0)

        report = self.client.get(
            f"/api/reports/daily?project_id={project_id}&report_date=2026-10-14", headers=self.manager
        )
        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.content.startswith(b"%PDF"))

    def test_excel_bom_import_creates_relations_and_torque(self):
        path = Path(tempfile.gettempdir()) / "asolar-test-bom.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["typ_rzedu", "typ_konstrukcji", "dlugosc_m", "sku", "nazwa", "kategoria", "ilosc", "jednostka", "moment_min", "moment_max"])
        sheet.append(["TEST-1P", "tracker 1-noga", 61.5, "TEST-M12", "Śruba M12", "Śruby", 84, "szt.", 45, 55])
        workbook.save(path)
        with SessionLocal() as db:
            result = analyze(path, ".xlsx", db)
        self.assertEqual(result["summary"]["relations"], 1)
        self.assertEqual(result["summary"]["row_types"], 1)
        components = self.client.get("/api/components", headers=self.manager).json()
        imported = next(item for item in components if item["sku"] == "TEST-M12")
        self.assertEqual(imported["torque_min_nm"], 45)
        self.assertEqual(imported["torque_max_nm"], 55)


if __name__ == "__main__":
    unittest.main()
