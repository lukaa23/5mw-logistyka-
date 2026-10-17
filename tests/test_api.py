import os
import tempfile
import unittest
import hashlib
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "asolar-universal-test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["ASOLAR_SECRET"] = "test-only-secret"

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.database import SessionLocal
from app.main import app
from app.models import Attachment, Document
from app.services.parser import analyze

VARIANT_CODES = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")


class UniversalWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman = cls.login("brygadzista1", "Brygada1-2026!")
        cls.warehouse = cls.login("brygadzista2", "Brygada2-2026!")

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

    def test_eset_variant_configuration_calculates_precise_project_demand(self):
        created = self.client.post(
            "/api/projects", headers=self.manager,
            json={"name": "ESET BOM", "location": "Momo", "capacity_mw": 1.0, "structure_type": "Tracker ESET 1P"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["id"]

        initial = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager)
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()["total_rows"], 0)
        self.assertEqual([item["code"] for item in initial.json()["variants"]], list(VARIANT_CODES))

        configured = self.client.put(
            f"/api/projects/{project_id}/tracker-config", headers=self.foreman,
            json={"items": [
                {"variant_code": "1x28", "row_count": 10},
                {"variant_code": "1x42", "row_count": 0},
                {"variant_code": "1x56", "row_count": 4},
                {"variant_code": "1x70", "row_count": 0},
                {"variant_code": "1x42+1x28", "row_count": 0},
                {"variant_code": "1x56+1x28", "row_count": 0},
                {"variant_code": "1x56+1x42", "row_count": 0},
            ]},
        )
        self.assertEqual(configured.status_code, 200, configured.text)
        demand = configured.json()
        self.assertEqual(demand["total_rows"], 14)
        self.assertEqual(demand["total_modules"], 504)
        totals = {item["key"]: item for item in demand["grand_total"]}
        self.assertEqual(totals["QZ1-3050"]["quantity_total"], 10)
        self.assertEqual(totals["QZ3-3024"]["quantity_total"], 4)
        self.assertEqual(totals["LT1-1450-18"]["quantity_total"], 532)
        self.assertEqual(totals["TCU"]["quantity_total"], 14)
        self.assertEqual(totals["B-M16-75"]["quantity_total"], 40)
        self.assertEqual(totals["B-M16-75"]["torque_min_nm"], 145)
        self.assertIn("podkładki", totals["B-M16-75"]["spec"])

        invalid = self.client.put(
            f"/api/projects/{project_id}/tracker-config", headers=self.manager,
            json={"items": [
                {"variant_code": "1x28", "row_count": 1},
                {"variant_code": "1x42", "row_count": 1},
                {"variant_code": "1x56", "row_count": 1},
                {"variant_code": "1x70", "row_count": 1},
                {"variant_code": "1x42+1x28", "row_count": 1},
                {"variant_code": "1x56+1x28", "row_count": 1},
                {"variant_code": "wariant-własny", "row_count": 1},
            ]},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 200)

    def test_only_ten_approved_files_drive_sources_templates_and_module_data(self):
        team = self.client.get("/api/users", headers=self.manager)
        self.assertEqual(team.status_code, 200, team.text)
        self.assertEqual(
            {item["username"] for item in team.json()},
            {"kierownik", "brygadzista1", "brygadzista2"},
        )
        self.assertEqual({item["role"] for item in team.json()}, {"kierownik", "brygadzista"})
        health = self.client.get("/api/health").json()
        self.assertEqual(health["version"], "4.5.0")
        self.assertEqual(health["file_storage"], "database")
        self.assertEqual(health["realtime"], "websocket")

        projects = self.client.get("/api/projects", headers=self.manager).json()
        source_project = next(item for item in projects if item["name"] == "RF-GIULIETTA")
        project_id = source_project["id"]
        self.assertEqual(source_project["capacity_mw"], 6.4915)

        basis = self.client.get(f"/api/source-basis?project_id={project_id}", headers=self.manager)
        self.assertEqual(basis.status_code, 200, basis.text)
        basis = basis.json()
        self.assertEqual(basis["registered_sources"], 10)
        self.assertEqual(basis["module"]["model"], "JKM710-735N-66HL5-BDV")
        self.assertEqual(basis["module"]["dimensions_mm"], "2384×1303×33")
        self.assertEqual([item["name"] for item in basis["templates"]], ["1x28", "1x42", "1x56", "1x70"])

        documents = self.client.get(f"/api/documents?project_id={project_id}", headers=self.manager).json()
        approved = [item for item in documents if item["approved_source"]]
        self.assertEqual(len(approved), 10)
        expected_names = {"łaczenia rur.pdf", "planimetria.pdf", "planimetria - warianty i BOM.pdf", "planimetria 6,5mw.pdf", "montaż mechaniczny.pdf", "manual v.2.pdf", "montaż mechaniczny 3.pdf", "montaż mechaniczny 4.pdf", "montaż mechaniczny 5.pdf", "JKM710-735N-66HL5-BDV-Z3-EN.pdf"}
        self.assertEqual({item["filename"] for item in approved}, expected_names)
        for item in approved:
            downloaded = self.client.get(f"/api/documents/{item['id']}/file", headers=self.manager)
            self.assertEqual(hashlib.sha256(downloaded.content).hexdigest(), item["sha256"])

        source_plans = self.client.get(f"/api/planimetry?project_id={project_id}", headers=self.foreman)
        self.assertEqual(source_plans.status_code, 200, source_plans.text)
        self.assertEqual(
            {item["filename"] for item in source_plans.json()},
            {"planimetria.pdf", "planimetria - warianty i BOM.pdf", "planimetria 6,5mw.pdf"},
        )
        self.assertTrue(all(not item["deletable"] for item in source_plans.json()))
        self.assertEqual(
            self.client.delete(f"/api/planimetry/{source_plans.json()[0]['id']}", headers=self.manager).status_code,
            409,
        )

        templates = self.client.get(f"/api/material-templates?project_id={project_id}", headers=self.manager).json()
        source_templates = {item["name"]: item for item in templates if item["source_based"]}
        self.assertEqual(source_templates["1x28"]["materials"], {"1": 5, "2": 30, "3": 30})
        self.assertEqual(source_templates["1x70"]["materials"], {"1": 13, "2": 73, "3": 73})

        before = self.client.get(f"/api/instructions?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(len(before), 9)
        self.assertTrue(all(item["source"] == "montaż mechaniczny.pdf" for item in before))
        supplemental = self.client.post(
            "/api/documents", headers=self.manager,
            data={"project_id": str(project_id)}, files={"file": ("obcy.pdf", b"not-an-approved-source", "application/pdf")},
        )
        self.assertEqual(supplemental.status_code, 200, supplemental.text)
        self.assertFalse(supplemental.json()["analysis"]["approved_source"])
        after = self.client.get(f"/api/instructions?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(after, before)

    def test_zones_generate_sequential_operational_rows_and_preserve_field_history(self):
        created = self.client.post(
            "/api/projects", headers=self.manager,
            json={"name": "ESET strefy", "location": "Momo", "capacity_mw": 2.0, "structure_type": "Tracker ESET 1P"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["id"]
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/tracker-zones", headers=self.manager).json(), [])

        zone_a = self.client.post("/api/tracker-zones", headers=self.foreman, json={"project_id": project_id, "name": "Strefa A"})
        zone_b = self.client.post("/api/tracker-zones", headers=self.manager, json={"project_id": project_id, "name": "Strefa B"})
        self.assertEqual(zone_a.status_code, 200, zone_a.text)
        self.assertEqual(zone_b.status_code, 200, zone_b.text)
        zone_a_id, zone_b_id = zone_a.json()["id"], zone_b.json()["id"]

        def config(zone_id, counts, headers=self.foreman):
            return self.client.put(
                f"/api/tracker-zones/{zone_id}/config", headers=headers,
                json={"items": [{"variant_code": code, "row_count": counts.get(code, 0)} for code in VARIANT_CODES]},
            )

        configured_a = config(zone_a_id, {"1x28": 2, "1x42": 1})
        configured_b = config(zone_b_id, {"1x42+1x28": 1, "1x56+1x28": 1, "1x56+1x42": 1}, self.manager)
        self.assertEqual(configured_a.status_code, 200, configured_a.text)
        self.assertEqual(configured_b.status_code, 200, configured_b.text)
        self.assertEqual(configured_a.json()["demand"]["total_rows"], 3)
        self.assertEqual(configured_a.json()["demand"]["total_modules"], 98)
        totals_a = {item["key"]: item["quantity_total"] for item in configured_a.json()["demand"]["grand_total"]}
        self.assertEqual(totals_a["LT1-1450-18"], 104)
        self.assertEqual(totals_a["TCU"], 3)
        variants_b = {item["code"]: item for item in configured_b.json()["demand"]["variants"]}
        self.assertEqual(configured_b.json()["demand"]["total_rows"], 3)
        self.assertEqual(configured_b.json()["demand"]["total_modules"], 252)
        for combined, left, right in (("1x42+1x28", "1x42", "1x28"), ("1x56+1x28", "1x56", "1x28"), ("1x56+1x42", "1x56", "1x42")):
            combined_items = {item["key"]: item["quantity_per_row"] for item in variants_b[combined]["per_row"]}
            left_items = {item["key"]: item["quantity_per_row"] for item in variants_b[left]["per_row"]}
            right_items = {item["key"]: item["quantity_per_row"] for item in variants_b[right]["per_row"]}
            self.assertEqual(combined_items, {key: left_items.get(key, 0) + right_items.get(key, 0) for key in left_items.keys() | right_items.keys()})

        rows = self.client.get(f"/api/projects/{project_id}/operational-rows", headers=self.manager).json()
        self.assertEqual(len(rows), 6)
        rows_a = [row for row in rows if row["zone_id"] == zone_a_id]
        self.assertEqual([row["code"] for row in rows_a], ["1", "2", "3"])
        self.assertEqual([row["variant_name"] for row in rows_a], ["1x28", "1x28", "1x42"])
        first_id, second_id, third_id = rows_a[0]["id"], rows_a[1]["id"], rows_a[2]["id"]

        moved = self.client.post(f"/api/rows/{third_id}/move", headers=self.warehouse, json={"direction": "up"})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertTrue(moved.json()["moved"])
        rows_a = self.client.get(f"/api/projects/{project_id}/operational-rows?zone_id={zone_a_id}", headers=self.manager).json()
        self.assertEqual([row["code"] for row in rows_a], ["1", "2", "3"])
        self.assertEqual([row["variant_name"] for row in rows_a], ["1x28", "1x42", "1x28"])
        self.assertEqual([row["id"] for row in rows_a], [first_id, third_id, second_id])

        built = self.client.patch(f"/api/rows/{first_id}", headers=self.foreman, json={"built": True, "note": "Kolizja sprawdzona w terenie"})
        self.assertEqual(built.status_code, 200, built.text)
        self.assertEqual(self.client.patch(f"/api/rows/{first_id}", headers=self.foreman, json={"qc_checked": True}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/rows/{first_id}", headers=self.manager, json={"qc_checked": True}).status_code, 200)
        photo = self.client.post(f"/api/row/{first_id}/photos", headers=self.foreman, files={"file": ("rzad.jpg", b"zone-row-photo", "image/jpeg")})
        self.assertEqual(photo.status_code, 200, photo.text)

        reduced = config(zone_a_id, {"1x28": 1, "1x42": 1})
        self.assertEqual(reduced.status_code, 200, reduced.text)
        reduced_rows = self.client.get(f"/api/projects/{project_id}/operational-rows?zone_id={zone_a_id}", headers=self.manager).json()
        self.assertEqual([row["code"] for row in reduced_rows], ["1", "2"])
        self.assertEqual(reduced_rows[0]["id"], first_id)
        self.assertTrue(reduced_rows[0]["built"])
        self.assertTrue(reduced_rows[0]["qc_checked"])
        self.assertEqual(reduced_rows[0]["note"], "Kolizja sprawdzona w terenie")
        self.assertEqual(reduced_rows[0]["photos"], 1)

        expanded = config(zone_a_id, {"1x28": 2, "1x42": 1})
        self.assertEqual(expanded.status_code, 200, expanded.text)
        expanded_rows = self.client.get(f"/api/projects/{project_id}/operational-rows?zone_id={zone_a_id}", headers=self.manager).json()
        self.assertEqual([row["code"] for row in expanded_rows], ["1", "2", "3"])
        self.assertEqual([row["variant_name"] for row in expanded_rows], ["1x28", "1x42", "1x28"])
        self.assertEqual(expanded_rows[2]["id"], second_id)

        renamed = self.client.patch(f"/api/tracker-zones/{zone_a_id}", headers=self.foreman, json={"name": "Strefa A — północ"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "Strefa A — północ")
        zones = self.client.get(f"/api/projects/{project_id}/tracker-zones", headers=self.manager).json()
        zone_a_after = next(zone for zone in zones if zone["id"] == zone_a_id)
        self.assertEqual(zone_a_after["stats"], {"total": 3, "built": 1, "qc": 1})

        self.assertEqual(self.client.delete(f"/api/tracker-zones/{zone_b_id}", headers=self.manager).status_code, 200)
        aggregate = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        self.assertEqual(aggregate["total_rows"], 3)
        self.assertEqual(aggregate["total_modules"], 98)
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 200)

    def test_zone_demand_scope_and_full_bom_deliveries_are_independent(self):
        created = self.client.post(
            "/api/projects", headers=self.manager,
            json={"name": "ESET dostawy", "location": "Momo", "capacity_mw": 1.0, "structure_type": "Tracker ESET 1P"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["id"]
        zone_a = self.client.post("/api/tracker-zones", headers=self.foreman, json={"project_id": project_id, "name": "Strefa A"}).json()
        zone_b = self.client.post("/api/tracker-zones", headers=self.manager, json={"project_id": project_id, "name": "Strefa B"}).json()

        def configure(zone_id, selected):
            response = self.client.put(
                f"/api/tracker-zones/{zone_id}/config", headers=self.foreman,
                json={"items": [{"variant_code": code, "row_count": selected.get(code, 0)} for code in VARIANT_CODES]},
            )
            self.assertEqual(response.status_code, 200, response.text)

        configure(zone_a["id"], {"1x28": 1})
        configure(zone_b["id"], {"1x42+1x28": 1})
        zones = self.client.get(f"/api/projects/{project_id}/tracker-zones", headers=self.manager).json()
        self.assertEqual({zone["name"]: zone["demand"]["total_modules"] for zone in zones}, {"Strefa A": 28, "Strefa B": 70})
        overall_before = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        self.assertEqual(overall_before["total_rows"], 2)
        self.assertEqual(overall_before["total_modules"], 98)

        initial = self.client.get(f"/api/projects/{project_id}/bom-delivery-status", headers=self.manager)
        self.assertEqual(initial.status_code, 200, initial.text)
        initial = initial.json()
        self.assertEqual(initial["summary"]["catalogue_items"], 68)
        self.assertEqual(initial["summary"]["deliveries_count"], 0)
        self.assertTrue(all(item["delivered"] == 0 and item["available"] == 0 for item in initial["items"]))
        catalogue = {item["key"]: item for item in initial["items"]}
        self.assertEqual(catalogue["TCU"]["required"], 3)
        self.assertEqual(catalogue["MODULE-JINKO-JKM710-735"]["required"], 98)
        self.assertIn("B-M16-75", catalogue)
        self.assertIn("QZ1-3050", catalogue)
        self.assertIn("LT1-1450-18", catalogue)

        payload = {
            "project_id": project_id, "delivery_date": "2026-10-15", "wz_number": "WZ/BOM/001",
            "supplier": "ESET / Jinko", "note": "Pierwszy transport", "client_id": "bom-delivery-001",
            "items": [
                {"component_id": catalogue["TCU"]["component_id"], "quantity_received": 2, "quantity_damaged": 0},
                {"component_id": catalogue["MODULE-JINKO-JKM710-735"]["component_id"], "quantity_received": 40, "quantity_damaged": 1},
            ],
        }
        delivery = self.client.post("/api/bom-deliveries", headers=self.foreman, json=payload)
        self.assertEqual(delivery.status_code, 200, delivery.text)
        duplicate = self.client.post("/api/bom-deliveries", headers=self.warehouse, json=payload)
        self.assertTrue(duplicate.json()["deduplicated"])

        after = self.client.get(f"/api/projects/{project_id}/bom-delivery-status", headers=self.manager).json()
        delivered = {item["key"]: item for item in after["items"]}
        self.assertEqual(delivered["TCU"]["delivered"], 2)
        self.assertEqual(delivered["TCU"]["balance"], -1)
        self.assertEqual(delivered["MODULE-JINKO-JKM710-735"]["delivered"], 40)
        self.assertEqual(delivered["MODULE-JINKO-JKM710-735"]["damaged"], 1)
        self.assertEqual(delivered["MODULE-JINKO-JKM710-735"]["available"], 39)
        self.assertEqual(after["summary"]["deliveries_count"], 1)
        history = self.client.get(f"/api/bom-deliveries?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["wz_number"], "WZ/BOM/001")

        overall_after = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        self.assertEqual(overall_after["grand_total"], overall_before["grand_total"])
        self.assertEqual(self.client.delete(f"/api/bom-deliveries/{delivery.json()['id']}", headers=self.warehouse).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/bom-deliveries/{delivery.json()['id']}", headers=self.manager).status_code, 200)
        cleared = self.client.get(f"/api/projects/{project_id}/bom-delivery-status", headers=self.manager).json()
        self.assertTrue(all(item["delivered"] == 0 for item in cleared["items"]))
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 200)

    def test_row_memory_history_and_planimetry_pdf_are_persistent(self):
        created = self.client.post(
            "/api/projects", headers=self.manager,
            json={"name": "ESET pamięć i mapa", "location": "Teren", "capacity_mw": 1.0, "structure_type": "Tracker ESET 1P"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["id"]
        zone = self.client.post("/api/tracker-zones", headers=self.foreman, json={"project_id": project_id, "name": "Strefa pamięci"}).json()
        configured = self.client.put(
            f"/api/tracker-zones/{zone['id']}/config", headers=self.foreman,
            json={"items": [{"variant_code": code, "row_count": 1 if code == "1x28" else 0} for code in VARIANT_CODES]},
        )
        self.assertEqual(configured.status_code, 200, configured.text)
        row = self.client.get(f"/api/projects/{project_id}/operational-rows", headers=self.foreman).json()[0]
        row_id = row["id"]
        self.assertEqual(row["notes_count"], 0)
        self.assertEqual(row["photos"], 0)

        first_note = {"text": "Kolizja przy obudowie łożyska — sprawdzić przed montażem.", "client_id": "row-memory-1"}
        note = self.client.post(f"/api/rows/{row_id}/notes", headers=self.foreman, json=first_note)
        self.assertEqual(note.status_code, 200, note.text)
        duplicate = self.client.post(f"/api/rows/{row_id}/notes", headers=self.foreman, json=first_note)
        self.assertTrue(duplicate.json()["deduplicated"])
        self.assertEqual(self.client.post(f"/api/rows/{row_id}/notes", headers=self.manager, json={"text": "Kontrola wykonana — można kontynuować.", "client_id": "row-memory-2"}).status_code, 200)
        notes = self.client.get(f"/api/rows/{row_id}/notes", headers=self.warehouse).json()
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["author"], "Kierownik Budowy")
        self.assertIn("Kontrola wykonana", notes[0]["text"])
        self.assertEqual(notes[1]["author"], "Brygadzista 1")

        for index in range(2):
            photo = self.client.post(
                f"/api/row/{row_id}/photos", headers=self.foreman,
                files={"file": (f"rząd-{index}.jpg", f"photo-{index}".encode(), "image/jpeg")},
            )
            self.assertEqual(photo.status_code, 200, photo.text)
        photos = self.client.get(f"/api/row/{row_id}/photos", headers=self.warehouse).json()
        self.assertEqual(len(photos), 2)
        self.assertTrue(all(item["uploaded_by"] == "Brygadzista 1" for item in photos))
        with SessionLocal() as db:
            self.assertTrue(all(db.get(Attachment, item["id"]).content_blob for item in photos))
        photo_view = self.client.get(photos[0]["url"], headers=self.manager)
        self.assertEqual(photo_view.status_code, 200, photo_view.text)
        self.assertIn("filename*=UTF-8''", photo_view.headers["content-disposition"])

        persisted = self.client.get(f"/api/projects/{project_id}/operational-rows", headers=self.manager).json()[0]
        self.assertEqual(persisted["notes_count"], 2)
        self.assertEqual(persisted["photos"], 2)
        self.assertEqual(persisted["last_changed_by"], "Brygadzista 1")
        self.assertIsNotNone(persisted["last_changed_at"])
        token = self.foreman["Authorization"].split(" ", 1)[1]
        with self.client.websocket_connect(f"/ws?token={token}") as socket:
            changed = self.client.patch(f"/api/rows/{row_id}", headers=self.foreman, json={"built": True})
            self.assertEqual(changed.status_code, 200, changed.text)
            event = socket.receive_json()
            self.assertEqual(event["event"], "row.changed")
            self.assertEqual(event["payload"]["id"], row_id)
        after_status = self.client.get(f"/api/projects/{project_id}/operational-rows", headers=self.manager).json()[0]
        self.assertTrue(after_status["built"])
        self.assertEqual(after_status["last_changed_by"], "Brygadzista 1")

        fake_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
        blocked = self.client.post(
            "/api/planimetry", headers=self.foreman, data={"project_id": str(project_id), "title": "Plan z terenu"},
            files={"file": ("plan.pdf", fake_pdf, "application/pdf")},
        )
        self.assertEqual(blocked.status_code, 403)
        uploaded = self.client.post(
            "/api/planimetry", headers=self.manager, data={"project_id": str(project_id), "title": "Planimetria oficjalna R03"},
            files={"file": ("planimetria-R03.pdf", fake_pdf, "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        plan_id = uploaded.json()["id"]
        with SessionLocal() as db:
            self.assertEqual(db.get(Document, plan_id).content_blob, fake_pdf)
        plans = self.client.get(f"/api/planimetry?project_id={project_id}", headers=self.foreman).json()
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["title"], "Planimetria oficjalna R03")
        self.assertEqual(plans[0]["uploaded_by"], "Kierownik Budowy")
        viewed = self.client.get(plans[0]["file_url"], headers=self.warehouse)
        self.assertEqual(viewed.status_code, 200, viewed.text)
        self.assertEqual(viewed.content, fake_pdf)
        self.assertEqual(self.client.delete(f"/api/planimetry/{plan_id}", headers=self.foreman).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/planimetry/{plan_id}", headers=self.manager).status_code, 200)
        self.assertEqual(self.client.get(f"/api/planimetry?project_id={project_id}", headers=self.manager).json(), [])
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 200)


if __name__ == "__main__":
    unittest.main()
