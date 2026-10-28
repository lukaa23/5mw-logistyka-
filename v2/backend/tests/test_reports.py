"""ASOLAR v2, etap 4c: Planimetria (znaczniki z rysunku), pulpit postępu, raport dzienny PDF."""
import io
import unittest
from datetime import UTC, date, datetime, timedelta

import pdfplumber

from test_documents import SOURCES, synthetic_pdf
from test_structure import StructureBase


class PlanTest(StructureBase):
    def setUp(self):
        super().setUp()
        self.upload(("plan.pdf", synthetic_pdf(trackers=12)))
        self.document = self.get("/documents")[0]
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 12})

    def test_markers_come_from_codes_printed_on_drawing(self):
        tables = {t["code"]: t for t in self.get("/tables")}
        self.call("PATCH", f"/tables/{tables['T-3']['id']}/progress", {"built": True})
        plan = self.get(f"/documents/{self.document['id']}/plan", page=1)
        self.assertEqual((plan["pages"], plan["has_text"]), (1, True))
        found = {m["code"]: m for m in plan["markers"]}
        self.assertEqual(set(found), {f"T-{n}" for n in range(1, 13)})
        self.assertTrue(all(0 <= m["x"] <= 1 and 0 <= m["y"] <= 1 for m in plan["markers"]))
        self.assertTrue(found["T-3"]["built"])
        self.assertEqual(found["T-3"]["table_id"], tables["T-3"]["id"])
        self.assertEqual(plan["tables_not_on_page"], 0)

    def test_page_image_and_errors(self):
        image = self.client.get(f"{self.base}/documents/{self.document['id']}/pages/1.png", headers=self.admin, params={"scale": 1})
        self.assertEqual(image.status_code, 200, image.text)
        self.assertTrue(image.content.startswith(b"\x89PNG"))
        self.assertEqual(self.client.get(f"{self.base}/documents/{self.document['id']}/plan", headers=self.admin, params={"page": 5}).status_code, 400)
        self.assertEqual(self.client.get(f"{self.base}/documents/{self.document['id']}/pages/1.png", headers=self.admin, params={"scale": 50}).status_code, 422)

    def test_document_category_by_manager_only(self):
        user, headers = self.make_user("bryg")
        self.add_member(self.project["id"], user["id"], "brygadzista")
        self.call("PATCH", f"/documents/{self.document['id']}", {"category": "rysunek"}, 403, headers)
        self.assertEqual(self.call("PATCH", f"/documents/{self.document['id']}", {"category": "rysunek"})["category"], "rysunek")
        self.call("PATCH", f"/documents/{self.document['id']}", {"category": "nieznana"}, 422)


@unittest.skipUnless((SOURCES / "planimetria 6,5mw.pdf").exists(), "brak plików project_sources")
class RealPlanTest(StructureBase):
    def test_real_layout_places_tracker_markers(self):
        self.upload(("planimetria 6,5mw.pdf", (SOURCES / "planimetria 6,5mw.pdf").read_bytes()))
        document = self.get("/documents")[0]
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 55})
        plan = self.get(f"/documents/{document['id']}/plan")
        self.assertEqual(len(plan["markers"]), 55)
        self.assertEqual(plan["tables_not_on_page"], 0)

    def test_scanned_layout_has_no_text_layer(self):
        self.upload(("planimetria.pdf", (SOURCES / "planimetria.pdf").read_bytes()))
        document = self.get("/documents")[0]
        plan = self.get(f"/documents/{document['id']}/plan")
        self.assertEqual((plan["markers"], plan["codes_on_page"]), ([], 0))


class DashboardReportTest(StructureBase):
    def setUp(self):
        super().setUp()
        self.call("POST", "/tables/range", {"prefix": "T", "first": 1, "last": 10})
        self.tables = self.get("/tables")

    def build(self, index, days_ago):
        when = datetime.now(UTC) - timedelta(days=days_ago)
        self.call("PATCH", f"/tables/{self.tables[index]['id']}/progress", {"built": True, "client_time": when.isoformat()})

    def test_forecast_needs_two_days_and_states_assumptions(self):
        self.build(0, 0)
        first = self.get("/dashboard")
        self.assertIsNone(first["forecast_days"])
        self.assertIn("za mało danych", first["forecast_status"])
        self.build(1, 1)
        self.build(2, 1)
        result = self.get("/dashboard")
        self.assertEqual((result["tables_built"], result["tables_remaining"], result["built_today"]), (3, 7, 1))
        self.assertEqual(result["daily_rate"], 1.5)  # 3 stoły / 2 dni z montażem
        self.assertEqual(result["forecast_days"], 5)  # ceil(7 / 1.5)
        self.assertEqual(len(result["history"]), 14)
        self.assertTrue(any("nie uwzględnia przerw" in line for line in result["forecast_assumptions"]))

    def test_daily_report_pdf_contains_day_data(self):
        self.build(0, 0)
        self.call("POST", f"/tables/{self.tables[0]['id']}/notes", {"text": "Brak podkładki"})
        self.call("POST", "/worklogs", {"work_date": str(date.today()), "team": "Brygada Ż", "stage": "Montaż płatwi", "people": 3, "hours": 8})
        response = self.client.get(f"{self.base}/reports/daily", headers=self.admin, params={"report_date": str(date.today())})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers["content-disposition"])
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        for expected in ("RAPORT DZIENNY", "T-1", "Brak podkładki", "Montaż płatwi", "24.0"):
            self.assertIn(expected, text)
