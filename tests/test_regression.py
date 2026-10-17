"""Testy regresyjne ASOLAR 4.5.1: role, trwałość, planimetria, warianty, BOM, dostawy, raporty, WebSocket i źródła."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'asolar-regression-test.db'}")
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret")

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfReader

import app.main as main
from app.database import SessionLocal
from app.main import app
from app.models import Attachment, Component, ConstructionRow, RowType, User
from app.services.source_basis import SOURCE_DIR, build_eset_demand, load_eset_bom, load_source_manifest

VARIANTS = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def counts_payload(mapping):
    return {"items": [{"variant_code": code, "row_count": mapping.get(code, 0)} for code in VARIANTS]}


class RegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman = cls.login("brygadzista1", "Brygada1-2026!")
        cls.foreman2 = cls.login("brygadzista2", "Brygada2-2026!")

    @classmethod
    def login(cls, username, password):
        response = cls.client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def project(self, name):
        response = self.client.post("/api/projects", headers=self.manager, json={"name": name, "location": "Test", "capacity_mw": 1, "structure_type": "Tracker ESET"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def zone(self, project_id, name, mapping):
        zone = self.client.post("/api/tracker-zones", headers=self.manager, json={"project_id": project_id, "name": name})
        self.assertEqual(zone.status_code, 200, zone.text)
        configured = self.client.put(f"/api/tracker-zones/{zone.json()['id']}/config", headers=self.foreman, json=counts_payload(mapping))
        self.assertEqual(configured.status_code, 200, configured.text)
        return configured.json()

    def rows(self, project_id):
        return self.client.get(f"/api/projects/{project_id}/operational-rows", headers=self.manager).json()

    def drop(self, project_id):
        self.client.patch(f"/api/projects/{project_id}", headers=self.manager, json={"archived": True})
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 200)

    # --- logowanie i role -------------------------------------------------------------------

    def test_login_roles_and_backend_permissions(self):
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "kierownik", "password": "zle-haslo"}).status_code, 401)
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/projects", headers={"Authorization": "Bearer falszywy.token"}).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.foreman).json()["role"], "brygadzista")

        self.assertEqual(self.client.get("/api/users", headers=self.foreman).status_code, 403)
        self.assertEqual(self.client.post("/api/users", headers=self.foreman, json={"username": "x1", "full_name": "X Y", "role": "kierownik", "password": "12345678"}).status_code, 403)
        self.assertEqual(self.client.post("/api/projects", headers=self.foreman, json={"name": "Nie"}).status_code, 403)
        team = self.client.get("/api/team", headers=self.foreman)
        self.assertEqual(team.status_code, 200)
        self.assertNotIn("password_hash", json.dumps(team.json()))

        created = self.client.post("/api/users", headers=self.manager, json={"username": "brygadzista3", "full_name": "Brygadzista 3", "role": "brygadzista", "password": "Haslo-testowe-3"})
        self.assertEqual(created.status_code, 200, created.text)
        new_headers = self.login("brygadzista3", "Haslo-testowe-3")
        self.assertEqual(self.client.get("/api/auth/me", headers=new_headers).json()["username"], "brygadzista3")
        deactivated = self.client.patch(f"/api/users/{created.json()['id']}", headers=self.manager, json={"active": False})
        self.assertEqual(deactivated.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=new_headers).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "brygadzista3", "password": "Haslo-testowe-3"}).status_code, 403)
        manager_id = self.client.get("/api/auth/me", headers=self.manager).json()["id"]
        self.assertEqual(self.client.patch(f"/api/users/{manager_id}", headers=self.manager, json={"active": False}).status_code, 400)
        with SessionLocal() as db:
            stored = db.query(User).filter_by(username="brygadzista3").one().password_hash
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn("Haslo-testowe-3", stored)

    def test_restart_does_not_reset_existing_passwords(self):
        user = self.client.post("/api/users", headers=self.manager, json={"username": "restart-test", "full_name": "Restart Test", "role": "brygadzista", "password": "Pierwsze-haslo-1"}).json()
        self.client.patch(f"/api/users/{user['id']}", headers=self.manager, json={"password": "Zmienione-haslo-2"})
        with SessionLocal() as db:
            before = {item.username: item.password_hash for item in db.query(User).all()}
        main.seed()  # symulacja ponownego uruchomienia serwera
        with SessionLocal() as db:
            after = {item.username: item.password_hash for item in db.query(User).all()}
        self.assertEqual(before, after)
        self.login("restart-test", "Zmienione-haslo-2")

    def test_server_mode_requires_password_environment(self):
        previous = os.environ.pop("ASOLAR_FOREMAN2_PASSWORD", None)
        os.environ["ASOLAR_REQUIRE_PASSWORDS"] = "1"
        try:
            with self.assertRaises(RuntimeError):
                main.startup_password("ASOLAR_FOREMAN2_PASSWORD")
            os.environ["ASOLAR_FOREMAN2_PASSWORD"] = "z-serwera-123"
            self.assertEqual(main.startup_password("ASOLAR_FOREMAN2_PASSWORD"), "z-serwera-123")
        finally:
            os.environ.pop("ASOLAR_REQUIRE_PASSWORDS", None)
            os.environ.pop("ASOLAR_FOREMAN2_PASSWORD", None)
            if previous is not None:
                os.environ["ASOLAR_FOREMAN2_PASSWORD"] = previous

    # --- rzędy, historia, sortowanie ------------------------------------------------------

    def test_status_rules_notes_photos_and_history_survive_count_changes(self):
        project_id = self.project("Historia rzędów")
        zone = self.zone(project_id, "Strefa A — północ", {"1x28": 3})
        rows = self.rows(project_id)
        self.assertEqual([row["code"] for row in rows], ["1", "2", "3"])
        third = rows[2]

        self.assertEqual(self.client.patch(f"/api/rows/{third['id']}", headers=self.manager, json={"qc_checked": True}).status_code, 400)
        built = self.client.patch(f"/api/rows/{third['id']}", headers=self.foreman, json={"built": True}).json()
        self.assertEqual(built["built_by"], "Brygadzista 1")
        self.assertIsNotNone(built["built_at"])
        self.assertEqual(self.client.patch(f"/api/rows/{third['id']}", headers=self.foreman, json={"qc_checked": True}).status_code, 403)
        qc = self.client.patch(f"/api/rows/{third['id']}", headers=self.manager, json={"qc_checked": True}).json()
        self.assertTrue(qc["qc_checked"])
        self.assertEqual(qc["last_changed_by"], "Kierownik Budowy")
        self.client.post(f"/api/rows/{third['id']}/notes", headers=self.foreman, json={"text": "Notatka 1", "client_id": "hist-1"})
        self.client.post(f"/api/rows/{third['id']}/notes", headers=self.foreman2, json={"text": "Notatka 2", "client_id": "hist-2"})
        for index in range(2):
            uploaded = self.client.post(f"/api/row/{third['id']}/photos", headers=self.foreman, files={"file": (f"foto{index}.png", PNG_BYTES, "image/png")})
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(self.client.post(f"/api/row/{third['id']}/photos", headers=self.foreman, files={"file": ("x.pdf", PDF_BYTES, "application/pdf")}).status_code, 400)
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        self.assertEqual(self.client.post(f"/api/row/{third['id']}/photos", headers=self.foreman, files={"file": ("x.svg", svg, "image/svg+xml")}).status_code, 400)

        # Zmniejszenie liczby rzędów ukrywa rekord, ale go nie usuwa.
        self.client.put(f"/api/tracker-zones/{zone['id']}/config", headers=self.manager, json=counts_payload({"1x28": 2}))
        self.assertNotIn(third["id"], [row["id"] for row in self.rows(project_id)])
        with SessionLocal() as db:
            hidden = db.get(ConstructionRow, third["id"])
            self.assertFalse(hidden.active)
            self.assertTrue(hidden.qc_checked)
            self.assertEqual(db.query(Attachment).filter_by(entity_type="row", entity_id=third["id"]).count(), 2)
            self.assertTrue(all(item.content_blob for item in db.query(Attachment).filter_by(entity_type="row", entity_id=third["id"])))

        # Ponowne zwiększenie przywraca ten sam rekord z historią.
        self.client.put(f"/api/tracker-zones/{zone['id']}/config", headers=self.manager, json=counts_payload({"1x28": 3}))
        restored = next(row for row in self.rows(project_id) if row["id"] == third["id"])
        self.assertTrue(restored["built"] and restored["qc_checked"])
        self.assertEqual(restored["notes_count"], 2)
        self.assertEqual(restored["photos"], 2)
        photos = self.client.get(f"/api/row/{third['id']}/photos", headers=self.foreman2).json()
        self.assertEqual({item["uploaded_by"] for item in photos}, {"Brygadzista 1"})
        self.assertEqual(self.client.get(photos[0]["url"], headers=self.foreman2).content, PNG_BYTES)

        # Cofnięcie montażu cofa odbiór.
        undone = self.client.patch(f"/api/rows/{third['id']}", headers=self.foreman, json={"built": False}).json()
        self.assertFalse(undone["qc_checked"])
        self.assertIsNone(undone["qc_by"])
        self.drop(project_id)

    def test_manual_order_is_persisted_and_ids_stay_bound_to_history(self):
        project_id = self.project("Kolejność")
        self.zone(project_id, "Strefa sortowania", {"1x28": 1, "1x56": 1, "1x56+1x42": 1})
        rows = self.rows(project_id)
        self.assertEqual([row["variant_name"] for row in rows], ["1x28", "1x56", "1x56+1x42"])
        combined = rows[2]
        self.client.post(f"/api/rows/{combined['id']}/notes", headers=self.foreman, json={"text": "Rząd łączony przy drodze", "client_id": "order-1"})
        self.assertTrue(self.client.post(f"/api/rows/{combined['id']}/move", headers=self.foreman, json={"direction": "up"}).json()["moved"])
        self.assertTrue(self.client.post(f"/api/rows/{combined['id']}/move", headers=self.foreman, json={"direction": "up"}).json()["moved"])
        self.assertFalse(self.client.post(f"/api/rows/{combined['id']}/move", headers=self.foreman, json={"direction": "up"}).json()["moved"])
        self.assertEqual(self.client.post(f"/api/rows/{combined['id']}/move", headers=self.foreman, json={"direction": "bok"}).status_code, 400)
        after = self.rows(project_id)
        self.assertEqual([row["variant_name"] for row in after], ["1x56+1x42", "1x28", "1x56"])
        self.assertEqual(after[0]["id"], combined["id"])
        self.assertEqual(after[0]["code"], "1")
        notes = self.client.get(f"/api/rows/{combined['id']}/notes", headers=self.manager).json()
        self.assertEqual(notes[0]["text"], "Rząd łączony przy drodze")
        self.assertEqual(self.client.get(f"/api/rows/{after[1]['id']}/notes", headers=self.manager).json(), [])
        self.drop(project_id)

    # --- BOM i zapotrzebowanie ------------------------------------------------------------

    def test_combined_variants_are_exact_sum_of_base_variants(self):
        bom = load_eset_bom()
        for variant in bom["variants"]:
            if "composition" not in variant:
                continue
            combined = {item["key"]: item["quantity_per_row"] for item in next(v for v in build_eset_demand({variant["code"]: 1})["variants"] if v["code"] == variant["code"])["per_row"]}
            expected = {}
            for base in variant["composition"]:
                for key, quantity in bom["quantities"][base].items():
                    expected[key] = expected.get(key, 0) + quantity
            self.assertEqual(combined, expected, variant["code"])

    def test_row_bom_overrides_are_flagged_and_change_demand_by_delta(self):
        project_id = self.project("Korekty BOM")
        zone = self.zone(project_id, "Strefa korekt", {"1x28": 2})
        row = self.rows(project_id)[0]
        bom = self.client.get(f"/api/rows/{row['id']}/bom", headers=self.foreman).json()
        self.assertEqual(bom["overrides_count"], 0)
        item = next(entry for entry in bom["items"] if entry["category"] == "Śruby i zestawy")
        source_total = next(entry for entry in zone["demand"]["grand_total"] if entry["key"] == item["key"])["quantity_total"]

        self.assertEqual(self.client.put(f"/api/rows/{row['id']}/bom-overrides", headers=self.foreman, json={"overrides": {item["key"]: 1}}).status_code, 403)
        self.assertEqual(self.client.put(f"/api/rows/{row['id']}/bom-overrides", headers=self.manager, json={"overrides": {"NIEISTNIEJE": 1}}).status_code, 400)
        updated = self.client.put(f"/api/rows/{row['id']}/bom-overrides", headers=self.manager, json={"overrides": {item["key"]: item["source_quantity"] + 5}}).json()
        changed = next(entry for entry in updated["items"] if entry["key"] == item["key"])
        self.assertTrue(changed["overridden"])
        self.assertEqual(changed["source_quantity"], item["source_quantity"])
        self.assertEqual(changed["quantity"], item["source_quantity"] + 5)

        zones = self.client.get(f"/api/projects/{project_id}/tracker-zones", headers=self.manager).json()
        line = next(entry for entry in zones[0]["demand"]["grand_total"] if entry["key"] == item["key"])
        self.assertEqual(line["source_quantity_total"], source_total)
        self.assertEqual(line["override_delta"], 5)
        self.assertEqual(line["quantity_total"], source_total + 5)
        farm = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        self.assertEqual(next(entry for entry in farm["grand_total"] if entry["key"] == item["key"])["quantity_total"], source_total + 5)
        self.assertEqual(farm["overrides"]["rows"], 1)

        reset = self.client.put(f"/api/rows/{row['id']}/bom-overrides", headers=self.manager, json={"overrides": {item["key"]: None}}).json()
        self.assertEqual(reset["overrides_count"], 0)
        self.drop(project_id)

    def test_demand_is_independent_from_deliveries_and_deliveries_start_at_zero(self):
        project_id = self.project("Dostawy niezależne")
        self.zone(project_id, "Strefa D", {"1x42": 2, "1x56+1x28": 1})
        before = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        status = self.client.get(f"/api/projects/{project_id}/bom-delivery-status", headers=self.manager).json()
        self.assertTrue(all(item["delivered"] == 0 and item["damaged"] == 0 and item["available"] == 0 for item in status["items"]))
        self.assertEqual(status["summary"]["deliveries_count"], 0)
        self.assertGreater(status["summary"]["catalogue_items"], 3)
        component = next(item for item in status["items"] if item["required"] > 0)

        payload = {"project_id": project_id, "delivery_date": "2026-10-16", "wz_number": "WZ/T/1", "supplier": "Dostawca", "note": "", "client_id": "wz-dedup-1", "items": [{"component_id": component["component_id"], "quantity_received": component["required"] + 3, "quantity_damaged": 1}]}
        first = self.client.post("/api/bom-deliveries", headers=self.foreman, json=payload)
        second = self.client.post("/api/bom-deliveries", headers=self.foreman, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(second.json()["deduplicated"])
        self.assertEqual(second.json()["id"], first.json()["id"])
        bad = dict(payload, client_id="wz-bad", items=[{"component_id": component["component_id"], "quantity_received": 1, "quantity_damaged": 2}])
        self.assertEqual(self.client.post("/api/bom-deliveries", headers=self.foreman, json=bad).status_code, 400)

        after = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()
        self.assertEqual(after["grand_total"], before["grand_total"])
        line = next(item for item in self.client.get(f"/api/projects/{project_id}/bom-delivery-status", headers=self.manager).json()["items"] if item["component_id"] == component["component_id"])
        self.assertEqual(line["delivered"], component["required"] + 3)
        self.assertEqual(line["available"], component["required"] + 2)
        self.assertEqual(line["balance"], 2)
        history = self.client.get(f"/api/bom-deliveries?project_id={project_id}", headers=self.manager).json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["created_by"], "Brygadzista 1")
        self.drop(project_id)

    # --- dokumenty i planimetria ----------------------------------------------------------

    def test_planimetry_permissions_listing_and_protection(self):
        project_id = self.project("Planimetria")
        self.assertEqual(self.client.post("/api/planimetry", headers=self.foreman, data={"project_id": str(project_id), "title": "x"}, files={"file": ("plan.pdf", PDF_BYTES, "application/pdf")}).status_code, 403)
        self.assertEqual(self.client.post("/api/planimetry", headers=self.manager, data={"project_id": str(project_id)}, files={"file": ("plan.dwg", b"AC1027", "application/octet-stream")}).status_code, 400)
        created = self.client.post("/api/planimetry", headers=self.manager, data={"project_id": str(project_id), "title": "  "}, files={"file": ("Rewizja 03.pdf", PDF_BYTES, "application/pdf")})
        self.assertEqual(created.status_code, 200, created.text)
        plans = self.client.get(f"/api/planimetry?project_id={project_id}", headers=self.foreman).json()
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["title"], "Rewizja 03")
        self.assertEqual(plans[0]["uploaded_by"], "Kierownik Budowy")
        self.assertTrue(plans[0]["deletable"])
        self.assertFalse(plans[0]["approved_source"])
        self.assertEqual(self.client.get(plans[0]["file_url"], headers=self.foreman).content, PDF_BYTES)
        self.assertEqual(self.client.delete(f"/api/planimetry/{plans[0]['id']}", headers=self.foreman).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/planimetry/{plans[0]['id']}", headers=self.manager).status_code, 200)
        self.assertEqual(self.client.get(f"/api/planimetry?project_id={project_id}", headers=self.foreman).json(), [])
        self.drop(project_id)

    def test_supplemental_uploads_are_analyzed_without_changing_technical_base(self):
        project_id = self.project("Pliki pomocnicze")
        with SessionLocal() as db:
            counts = (db.query(Component).count(), db.query(RowType).count())
        demand_before = self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json()

        workbook = Workbook(); sheet = workbook.active
        sheet.append(["sku", "nazwa", "ilosc", "jednostka"]); sheet.append(["X-1", "Element spoza bazy", 99, "szt."])
        buffer = io.BytesIO(); workbook.save(buffer)
        dxf = "0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nTRACKERY\n10\n0\n0\nTEXT\n8\nOPISY\n1\nR-12 1x56\n0\nENDSEC\n0\nEOF\n"
        cases = {
            "bom.xlsx": (buffer.getvalue(), "przeanalizowany"),
            "rysunek.dxf": (dxf.encode(), "przeanalizowany"),
            "rysunek.dwg": (b"AC1032 binary", "zapisany"),
            "skan.pdf": (b"not a real pdf", "zapisany"),
        }
        for filename, (content, expected) in cases.items():
            response = self.client.post("/api/documents", headers=self.foreman, data={"project_id": str(project_id)}, files={"file": (filename, content, "application/octet-stream")})
            self.assertEqual(response.status_code, 200, response.text)
            analysis = response.json()["analysis"]
            self.assertEqual(analysis["processing_status"], expected, filename)
            self.assertFalse(analysis["approved_source"])
            self.assertFalse(analysis["approved_for_calculations"])
        documents = {item["filename"]: item for item in self.client.get(f"/api/documents?project_id={project_id}", headers=self.manager).json()}
        self.assertEqual(documents["rysunek.dxf"]["analysis"]["summary"]["entity_types"], {"LINE": 1, "TEXT": 1})
        self.assertIn("R-12 1x56", documents["rysunek.dxf"]["analysis"]["preview"]["texts"])
        self.assertIn("parsera DWG", " ".join(documents["rysunek.dwg"]["analysis"]["warnings"]))
        self.assertEqual(documents["bom.xlsx"]["analysis"]["summary"]["bom_rows"], 1)
        self.assertEqual(self.client.post("/api/documents", headers=self.foreman, data={"project_id": str(project_id)}, files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code, 400)
        with SessionLocal() as db:
            self.assertEqual((db.query(Component).count(), db.query(RowType).count()), counts)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/tracker-config", headers=self.manager).json(), demand_before)
        self.drop(project_id)

    def test_source_manifest_matches_supplied_documents_and_bom_references(self):
        manifest = load_source_manifest()
        bom = load_eset_bom()
        names = {item["filename"] for item in manifest["documents"]}
        self.assertEqual(len(names), 10)
        for entry in manifest["documents"]:
            path = SOURCE_DIR / entry["filename"]
            self.assertTrue(path.exists(), entry["filename"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"], entry["filename"])
        for key, component in bom["components"].items():
            self.assertTrue(component.get("source"), key)
            self.assertTrue(any(name in component["source"] for name in names), f"{key}: {component['source']}")
        for code, quantities in bom["quantities"].items():
            self.assertTrue(set(quantities) <= set(bom["components"]), code)
        self.assertEqual([item["code"] for item in bom["variants"]], list(VARIANTS))

    # --- meldunki, RFI, KPI, raport -------------------------------------------------------

    def test_worklogs_rfi_kpi_forecast_and_pdf_report(self):
        project_id = self.project("KPI i raport")
        self.zone(project_id, "Strefa K", {"1x28": 10})
        rows = self.rows(project_id)
        for row in rows[:4]:
            self.client.patch(f"/api/rows/{row['id']}", headers=self.foreman, json={"built": True})
        self.client.patch(f"/api/rows/{rows[0]['id']}", headers=self.manager, json={"qc_checked": True})

        first = {"project_id": project_id, "work_date": "2026-10-14", "team": "Brygada 1", "stage": "Montaż rur i płatwi — dowolny opis", "people": 4, "hours": 8, "rows_completed": 2, "qc_notes": "Kontrola momentów", "note": "", "client_id": "log-kpi-1"}
        created = self.client.post("/api/worklogs", headers=self.foreman, json=first)
        self.assertTrue(self.client.post("/api/worklogs", headers=self.foreman, json=first).json()["deduplicated"])
        one_day = self.client.get(f"/api/dashboard?project_id={project_id}", headers=self.manager).json()
        self.assertIsNone(one_day["forecast_days"])
        self.assertIn("za mało danych", one_day["forecast_status"])
        self.client.post("/api/worklogs", headers=self.foreman2, json=dict(first, work_date="2026-10-15", team="Brygada 2", rows_completed=2, people=2, client_id="log-kpi-2"))
        kpi = self.client.get(f"/api/dashboard?project_id={project_id}", headers=self.manager).json()
        self.assertEqual((kpi["rows_total"], kpi["rows_built"], kpi["rows_qc"]), (10, 4, 1))
        self.assertEqual(kpi["completion_pct"], 40.0)
        self.assertEqual(kpi["manhours"], 48.0)
        self.assertAlmostEqual(kpi["productivity"], 4 / 48, places=4)
        self.assertEqual(kpi["forecast_days"], 3.0)
        self.assertIsNotNone(kpi["forecast_date"])
        self.assertGreaterEqual(len(kpi["forecast_assumptions"]), 3)

        logs = self.client.get(f"/api/worklogs?project_id={project_id}", headers=self.manager).json()
        self.assertEqual({item["author"] for item in logs}, {"Brygadzista 1", "Brygadzista 2"})
        other = next(item for item in logs if item["author"] == "Brygadzista 2")
        self.assertEqual(self.client.patch(f"/api/worklogs/{other['id']}", headers=self.foreman, json={"note": "x"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/worklogs/{created.json()['id']}", headers=self.foreman, json={"note": "własny"}).status_code, 200)
        uploaded = self.client.post(f"/api/worklog/{created.json()['id']}/photos", headers=self.foreman, files={"file": ("m.png", PNG_BYTES, "image/png")})
        self.assertEqual(uploaded.status_code, 200)

        foreman2_id = next(item["id"] for item in self.client.get("/api/team", headers=self.foreman).json() if item["full_name"] == "Brygadzista 2")
        rfi = self.client.post("/api/rfis", headers=self.foreman, json={"project_id": project_id, "row_id": rows[1]["id"], "title": "Kolizja słupa", "description": "Opis", "priority": "wysoki", "assigned_to_id": foreman2_id, "client_id": "rfi-kpi-1"})
        self.assertEqual(rfi.status_code, 200, rfi.text)
        self.assertEqual(self.client.post("/api/rfis", headers=self.foreman, json={"project_id": project_id, "title": "x", "description": "y", "priority": "pilne"}).status_code, 422)
        listed = self.client.get(f"/api/rfis?project_id={project_id}", headers=self.manager).json()[0]
        self.assertEqual(listed["assigned_to"], "Brygadzista 2")
        self.assertEqual(listed["created_by"], "Brygadzista 1")
        self.assertIn("Strefa K", listed["row_label"])
        self.assertEqual(self.client.patch(f"/api/rfis/{listed['id']}", headers=self.foreman, json={"status": "zamknięty"}).status_code, 403)
        self.assertEqual(kpi["open_rfi"], 0)
        self.assertEqual(self.client.get(f"/api/dashboard?project_id={project_id}", headers=self.manager).json()["open_rfi"], 1)

        report = self.client.get(f"/api/reports/daily?project_id={project_id}&report_date=2026-10-15", headers=self.foreman)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.content.startswith(b"%PDF"))
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(report.content)).pages)
        for expected in ("RAPORT DZIENNY", "Roboczogodziny", "QA/QC", "Kolizja słupa", "Brygadzista 2", "4/10"):
            self.assertIn(expected, text)
        self.drop(project_id)

    def test_project_delete_requires_archive_and_manager(self):
        project_id = self.project("Usuwanie kontrolowane")
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.foreman).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/projects/{project_id}", headers=self.manager).status_code, 409)
        self.drop(project_id)

    # --- WebSocket i serwowanie frontendu -------------------------------------------------

    def test_websocket_ping_and_change_events(self):
        token = self.foreman["Authorization"].split(" ", 1)[1]
        with self.client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_text("ping")
            self.assertEqual(ws.receive_text(), "pong")
            project_id = self.project("WebSocket")
            event = ws.receive_json()
            self.assertEqual(event["event"], "project.changed")
            self.assertEqual(event["payload"]["id"], project_id)
            self.client.post("/api/tracker-zones", headers=self.foreman, json={"project_id": project_id, "name": "Strefa WS"})
            self.assertEqual(ws.receive_json()["event"], "tracker-zone.changed")
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws?token=zly") as ws:
                ws.receive_text()
        self.drop(project_id)

    def test_frontend_missing_script_is_404_not_html(self):
        if not main.FRONTEND.exists():
            self.skipTest("Brak zbudowanego frontendu")
        self.assertEqual(self.client.get("/assets/nie-istnieje.js").status_code, 404)
        self.assertEqual(self.client.get("/brak-pliku.js").status_code, 404)
        page = self.client.get("/raporty/dzienny")
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers["content-type"])
        self.assertEqual(self.client.get("/api/nie-ma-takiego").status_code, 404)


if __name__ == "__main__":
    unittest.main()
