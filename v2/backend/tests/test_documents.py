"""ASOLAR v2, etap 2: lokalny parser PDF, wgrywanie wielu dokumentów, przegląd propozycji."""
import io
import unittest
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from asolar2.pdfparse import analyze_pdf
from test_projects import V2Base

SOURCES = Path(__file__).resolve().parents[3] / "project_sources"


def synthetic_pdf(group="1x42", purlin_qty=44, zone_text=("Zone A1", "Zone A1", "Zone B2"), trackers=12, image_page=False, extra=""):
    """PDF z tabelą materiałów pod podpisem, strefami, numeracją trackerów i momentem dokręcania."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, 800, f"Table 3: List of materials for {group} tracker")
    rows = [["No.", "Description", "Item No.", "Spec", "Quantities"],
            ["1", "Purlin 1", "PU-001", "2000x60", str(purlin_qty)],
            ["2", "Clamp", "CL-7", "M8", "88"],
            ["3", "Torque tube", "TT-3", "6000", "3"]]
    table = Table(rows)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    _, height = table.wrapOn(pdf, 500, 300)
    table.drawOn(pdf, 50, 780 - height)
    y = 600
    for line in zone_text:
        pdf.drawString(50, y, f"Layout of {line} with {group} trackers")
        y -= 16
    pdf.drawString(50, y, "Tighten bolt M10 to 25-32 N.m")
    y -= 16
    if extra:
        pdf.drawString(50, y, extra)
    for index in range(1, trackers + 1):
        pdf.drawString(50 + (index % 8) * 60, 300 - (index // 8) * 16, f"T-{index}")
    pdf.showPage()
    if image_page:
        from PIL import Image
        image = Image.new("RGB", (200, 200), (180, 180, 180))
        data = io.BytesIO()
        image.save(data, format="PNG")
        data.seek(0)
        pdf.drawImage(ImageReader(data), 50, 400, 400, 400)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def by_kind(suggestions, kind):
    return [item for item in suggestions if item.kind == kind]


class ParserSyntheticTest(unittest.TestCase):
    def test_bom_table_under_caption_gets_structure_type_and_quantities(self):
        result = analyze_pdf(synthetic_pdf())
        lines = {item.payload["name"]: item.payload for item in by_kind(result.suggestions, "bom_line")}
        self.assertEqual(lines["Purlin 1"]["quantity"], 44)
        self.assertEqual(lines["Purlin 1"]["group"], "1x42")
        self.assertEqual(lines["Purlin 1"]["code"], "PU-001")
        self.assertEqual(lines["Clamp"]["quantity"], 88)
        self.assertTrue(all(item.page == 1 for item in by_kind(result.suggestions, "bom_line")))

    def test_patterns_types_zones_numbering_torque(self):
        result = analyze_pdf(synthetic_pdf())
        self.assertIn("1x42", {item.payload["code"] for item in by_kind(result.suggestions, "structure_type")})
        zones = {item.payload["name"]: item for item in by_kind(result.suggestions, "zone")}
        self.assertEqual(set(zones), {"Zone A1", "Zone B2"})
        self.assertGreater(zones["Zone A1"].confidence, zones["Zone B2"].confidence)  # 2 wystąpienia vs 1
        numbering = by_kind(result.suggestions, "numbering")
        self.assertEqual([(n.payload["prefix"], n.payload["first"], n.payload["last"]) for n in numbering], [("T", 1, 12)])
        torque = by_kind(result.suggestions, "torque")
        self.assertEqual([(t.payload["bolt"], t.payload["min_nm"], t.payload["max_nm"]) for t in torque], [("M10", 25, 32)])

    def test_short_numbering_and_bolt_sizes_are_not_tracker_numbers(self):
        result = analyze_pdf(synthetic_pdf(trackers=6))
        self.assertEqual(by_kind(result.suggestions, "numbering"), [])

    def test_image_only_page_is_reported_as_needing_ocr(self):
        result = analyze_pdf(synthetic_pdf(image_page=True))
        self.assertEqual(result.image_pages, [2])
        self.assertTrue(any("OCR" in warning for warning in result.warnings))

    def test_address_lines_are_not_zones(self):
        result = analyze_pdf(synthetic_pdf(zone_text=(), extra="Xuzhou Economic Development Zone 3, Road 12"))
        self.assertEqual(by_kind(result.suggestions, "zone"), [])


@unittest.skipUnless((SOURCES / "montaż mechaniczny.pdf").exists(), "brak plików project_sources")
class ParserRealDocumentsTest(unittest.TestCase):
    """Dokumenty z repozytorium — sprawdzamy, że parser odczytuje znane wartości (bez wpisywania ich w kod)."""

    def test_assembly_manual_bom_per_structure_type(self):
        result = analyze_pdf((SOURCES / "montaż mechaniczny.pdf").read_bytes())
        purlins = {item.payload["group"]: item.payload["quantity"] for item in by_kind(result.suggestions, "bom_line")
                   if item.page == 53 and item.payload["name"] == "Purlin 1"}
        self.assertEqual(purlins.get("1x42"), 44)
        self.assertEqual(purlins.get("1x56"), 58)
        self.assertEqual(purlins.get("1x70"), 73)
        types = {item.payload["code"] for item in by_kind(result.suggestions, "structure_type")}
        self.assertTrue({"1x28", "1x42", "1x56", "1x70"} <= types)
        self.assertTrue(by_kind(result.suggestions, "tool"))

    def test_layout_numbering_and_electrical_codes_skipped(self):
        result = analyze_pdf((SOURCES / "planimetria 6,5mw.pdf").read_bytes())
        numbering = {item.payload["prefix"]: item.payload for item in by_kind(result.suggestions, "numbering")}
        self.assertEqual((numbering["T"]["first"], numbering["T"]["last"]), (1, 55))
        self.assertNotIn("INV", numbering)
        self.assertNotIn("M", numbering)

    def test_scanned_layout_needs_ocr(self):
        result = analyze_pdf((SOURCES / "planimetria.pdf").read_bytes())
        self.assertTrue(result.image_pages)
        self.assertTrue(any("OCR" in warning for warning in result.warnings))


class DocumentsApiTest(V2Base):
    def upload(self, project_id, files, headers=None):
        payload = [("files", (name, content, "application/pdf")) for name, content in files]
        return self.client.post(f"/api/projects/{project_id}/documents", headers=headers or self.admin, files=payload)

    def suggestions(self, project_id, **params):
        response = self.client.get(f"/api/projects/{project_id}/suggestions", headers=self.admin, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_upload_many_analyze_merge_and_dedupe(self):
        project = self.make_project()
        first, second = synthetic_pdf(), synthetic_pdf(zone_text=("Zone A1", "Zone C3"), trackers=20, extra="Other layout")
        response = self.upload(project["id"], [("bom-a.pdf", first), ("layout-b.pdf", second), ("kopia.pdf", first), ("notatka.pdf", b"hello")])
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([doc["filename"] for doc in body["accepted"]], ["bom-a.pdf", "layout-b.pdf"])
        self.assertEqual(body["duplicates"][0]["filename"], "kopia.pdf")
        self.assertEqual(body["rejected"][0]["filename"], "notatka.pdf")

        documents = self.client.get(f"/api/projects/{project['id']}/documents", headers=self.admin).json()
        self.assertEqual({doc["status"] for doc in documents}, {"gotowy"})
        self.assertTrue(all(doc["pages"] == 1 for doc in documents))

        zones = {item["payload"]["name"]: item for item in self.suggestions(project["id"], kind="zone")}
        self.assertEqual(set(zones), {"Zone A1", "Zone B2", "Zone C3"})
        # Ta sama strefa w dwóch plikach = jedna propozycja z dwoma źródłami.
        self.assertEqual({source["filename"] for source in zones["Zone A1"]["sources"]}, {"bom-a.pdf", "layout-b.pdf"})
        self.assertEqual(zones["Zone A1"]["payload"]["occurrences"], 3)
        numbering = self.suggestions(project["id"], kind="numbering")
        self.assertEqual(len(numbering), 1)

        again = self.upload(project["id"], [("ponownie.pdf", first)]).json()
        self.assertEqual(again["accepted"], [])
        self.assertEqual(again["duplicates"][0]["existing"], "bom-a.pdf")

        file = self.client.get(f"/api/projects/{project['id']}/documents/{documents[-1]['id']}/file", headers=self.admin)
        self.assertEqual(file.status_code, 200)
        self.assertTrue(file.content.startswith(b"%PDF-"))

    def test_documents_and_suggestions_are_isolated_per_project(self):
        a, b = self.make_project(), self.make_project()
        self.assertEqual(self.upload(a["id"], [("a.pdf", synthetic_pdf())]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/projects/{b['id']}/documents", headers=self.admin).json(), [])
        self.assertEqual(self.suggestions(b["id"]), [])
        # Ten sam plik w innej budowie to nie duplikat — każda budowa ma własną przestrzeń.
        self.assertEqual(len(self.upload(b["id"], [("a.pdf", synthetic_pdf())]).json()["accepted"]), 1)
        doc_a = self.client.get(f"/api/projects/{a['id']}/documents", headers=self.admin).json()[0]
        self.assertEqual(self.client.get(f"/api/projects/{b['id']}/documents/{doc_a['id'] + 1000}/file", headers=self.admin).status_code, 404)
        stats = self.client.get(f"/api/projects/{a['id']}", headers=self.admin).json()["stats"]
        self.assertEqual(stats["documents"], 1)
        self.assertGreater(stats["pending_suggestions"], 0)

    def test_foreman_can_view_but_not_upload_or_review(self):
        project = self.make_project()
        user, headers = self.make_user("bryg")
        self.add_member(project["id"], user["id"], "brygadzista")
        self.assertEqual(self.upload(project["id"], [("x.pdf", synthetic_pdf())], headers=headers).status_code, 403)
        self.upload(project["id"], [("x.pdf", synthetic_pdf())])
        items = self.client.get(f"/api/projects/{project['id']}/suggestions", headers=headers)
        self.assertEqual(items.status_code, 200)
        target = items.json()[0]["id"]
        self.assertEqual(self.client.patch(f"/api/projects/{project['id']}/suggestions/{target}", headers=headers, json={"status": "zatwierdzona"}).status_code, 403)
        outsider = self.make_user("obcy")[1]
        self.assertEqual(self.client.get(f"/api/projects/{project['id']}/documents", headers=outsider).status_code, 404)

    def test_review_approve_zone_creates_zone_edit_and_reject(self):
        project = self.make_project()
        self.upload(project["id"], [("plan.pdf", synthetic_pdf())])
        zone = next(item for item in self.suggestions(project["id"], kind="zone") if item["payload"]["name"] == "Zone A1")
        edited = self.client.patch(f"/api/projects/{project['id']}/suggestions/{zone['id']}", headers=self.admin,
                                   json={"payload": {"name": "Strefa A1"}, "status": "zatwierdzona"})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["payload"]["name"], "Strefa A1")
        self.assertEqual(edited.json()["original"]["name"], "Zone A1")
        self.assertTrue(edited.json()["edited"])
        self.assertTrue(edited.json()["applied_ref"].startswith("zone:"))
        zones = self.client.get(f"/api/projects/{project['id']}/zones", headers=self.admin).json()
        self.assertEqual([item["name"] for item in zones], ["Strefa A1"])

        line = next(item for item in self.suggestions(project["id"], kind="bom_line") if item["payload"]["name"] == "Clamp")
        bad = self.client.patch(f"/api/projects/{project['id']}/suggestions/{line['id']}", headers=self.admin, json={"payload": {"quantity": "dużo"}})
        self.assertEqual(bad.status_code, 400)
        forbidden = self.client.patch(f"/api/projects/{project['id']}/suggestions/{line['id']}", headers=self.admin, json={"payload": {"confidence": 1}})
        self.assertEqual(forbidden.status_code, 400)
        rejected = self.client.patch(f"/api/projects/{project['id']}/suggestions/{line['id']}", headers=self.admin, json={"status": "odrzucona"})
        self.assertEqual(rejected.json()["status"], "odrzucona")

        rest = [item["id"] for item in self.suggestions(project["id"], status="nowa")]
        bulk = self.client.post(f"/api/projects/{project['id']}/suggestions/bulk", headers=self.admin, json={"ids": rest, "status": "zatwierdzona"})
        self.assertEqual(bulk.json()["updated"], len(rest))
        self.assertEqual(self.suggestions(project["id"], status="nowa"), [])
        self.assertEqual(len(self.client.get(f"/api/projects/{project['id']}/zones", headers=self.admin).json()), 2)  # + Zone B2

    def test_reanalysis_keeps_decisions_and_edits(self):
        project = self.make_project()
        self.upload(project["id"], [("plan.pdf", synthetic_pdf())])
        line = next(item for item in self.suggestions(project["id"], kind="bom_line") if item["payload"]["name"] == "Purlin 1")
        self.client.patch(f"/api/projects/{project['id']}/suggestions/{line['id']}", headers=self.admin, json={"payload": {"unit": "kpl."}, "status": "zatwierdzona"})
        count = len(self.suggestions(project["id"]))
        document = self.client.get(f"/api/projects/{project['id']}/documents", headers=self.admin).json()[0]
        again = self.client.post(f"/api/projects/{project['id']}/documents/{document['id']}/reanalyze", headers=self.admin)
        self.assertEqual(again.status_code, 200, again.text)
        after = {item["id"]: item for item in self.suggestions(project["id"])}
        self.assertEqual(len(after), count)
        self.assertEqual(after[line["id"]]["status"], "zatwierdzona")
        self.assertEqual(after[line["id"]]["payload"]["unit"], "kpl.")
        zone = next(item for item in after.values() if item["kind"] == "zone" and item["payload"]["name"] == "Zone A1")
        self.assertEqual(zone["payload"]["occurrences"], 2)  # nie podwaja się po ponownej analizie

    def test_conflicting_quantities_between_files_are_flagged(self):
        project = self.make_project()
        self.upload(project["id"], [("rev-a.pdf", synthetic_pdf(purlin_qty=44)), ("rev-b.pdf", synthetic_pdf(purlin_qty=46, extra="Rev B"))])
        purlins = [item for item in self.suggestions(project["id"], kind="bom_line") if item["payload"]["name"] == "Purlin 1"]
        self.assertEqual(len(purlins), 2)
        self.assertTrue(all(item["payload"]["conflict"] == [44, 46] for item in purlins))
        clamps = [item for item in self.suggestions(project["id"], kind="bom_line") if item["payload"]["name"] == "Clamp"]
        self.assertEqual(len(clamps), 1)
        self.assertNotIn("conflict", clamps[0]["payload"])
        # Odrzucenie jednej wersji usuwa oznaczenie rozbieżności z drugiej.
        self.client.patch(f"/api/projects/{project['id']}/suggestions/{purlins[1]['id']}", headers=self.admin, json={"status": "odrzucona"})
        kept = next(item for item in self.suggestions(project["id"], kind="bom_line") if item["id"] == purlins[0]["id"])
        self.assertNotIn("conflict", kept["payload"])

    def test_delete_document_removes_only_undecided_suggestions(self):
        project = self.make_project()
        self.upload(project["id"], [("plan.pdf", synthetic_pdf())])
        zone = next(item for item in self.suggestions(project["id"], kind="zone"))
        self.client.patch(f"/api/projects/{project['id']}/suggestions/{zone['id']}", headers=self.admin, json={"status": "zatwierdzona"})
        document = self.client.get(f"/api/projects/{project['id']}/documents", headers=self.admin).json()[0]
        deleted = self.client.delete(f"/api/projects/{project['id']}/documents/{document['id']}", headers=self.admin)
        self.assertEqual(deleted.status_code, 200)
        remaining = self.suggestions(project["id"])
        self.assertEqual([item["id"] for item in remaining], [zone["id"]])
        self.assertEqual(remaining[0]["sources"], [])
        self.assertEqual(self.client.get(f"/api/projects/{project['id']}/documents", headers=self.admin).json(), [])

    def test_broken_pdf_marks_error_without_crashing(self):
        project = self.make_project()
        response = self.upload(project["id"], [("uszkodzony.pdf", b"%PDF-1.4\nto nie jest prawdziwy pdf")])
        self.assertEqual(response.status_code, 200)
        document = self.client.get(f"/api/projects/{project['id']}/documents", headers=self.admin).json()[0]
        # Bez czerwonego błędu: dokument czeka na ręczne uzupełnienie obok podglądu.
        self.assertEqual(document["status"], "ręcznie")
        self.assertIn("Uzupełnij pozycje ręcznie", document["error"])

    def test_archived_project_rejects_uploads(self):
        project = self.make_project()
        self.client.patch(f"/api/projects/{project['id']}", headers=self.admin, json={"archived": True})
        self.assertEqual(self.upload(project["id"], [("x.pdf", synthetic_pdf())]).status_code, 409)
