"""BOM z ilościami „na stół” w kolumnach typów (np. „QTY per 2*26Array” + „Number of array”).

Układ jak w zestawieniach konstrukcji stałych: pozycje z numerem, komórki scalone (śruba, podkładka,
nakrętka pod jedną nazwą), wiersze sum „Total of …”, kolumna materiału, kolumna ilości całkowitej.
"""
import io

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from asolar2.pdfparse import analyze_pdf
from test_structure import StructureBase

HEADER = ["No.", "Part Name", "Specification", "Material", "Actual total weight", "Unit", "QTY per 2*26Array", "Number of array",
          "QTY per 2*13Array", "Number of array", "QTY", "Rate of spare parts", "Actual total QTY"]


def row(no, name, spec, material, per26, per13, total=None):
    total = per26 * 157 + per13 * 56 if total is None else total
    return [str(no), name, spec, material, "100", "PCS", str(per26), "157", str(per13), "56", str(total), "1%", str(total + 2)]


def bom_pdf(extra_text="", rows=None):
    data = [HEADER] + (rows or [
        row(1, "Pole 1", "C120*60*20*3.5*2255", "Q420", 11, 6),
        row(2, "Pole 2", "C120*60*20*3.5*3165", "Q420", 11, 6),
        ["3", "Total of class products", "", "", "9999", "", "", "", "", "", "", "", ""],
        row(4, "Purlin fixing bolts", "M12*35 Hexagon Head Bolt", "GR 8.8", 44, 24),
        row(5, "", "M12 Nut", "GR 8", 44, 24),
        row(6, "Bracing fixing bolts", "M12*35 Hexagon Head Bolt", "GR 8.8", 22, 12),
    ])
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(30, 560, "Fixed project - Bill of Material")
    if extra_text:
        pdf.drawString(30, 545, extra_text)
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0)), ("FONTSIZE", (0, 0), (-1, -1), 6)]))
    _, height = table.wrapOn(pdf, 800, 500)
    table.drawOn(pdf, 20, 530 - height)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def manual_pdf():
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, 800, "3.1 POLE INSTALLATION (M8 bolt tightening torque at 16 (N.m)).")
    table = Table([["Part Name", "Number", "Material", "Anti-corrosion"], ["Pole 1", "11", "Q420", "HDG"], ["Pole 2", "12", "Q420", "HDG"]])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    _, height = table.wrapOn(pdf, 400, 300)
    table.drawOn(pdf, 50, 780 - height)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def of(result, kind):
    return [item for item in result.suggestions if item.kind == kind]


class ParserPerTypeTest(StructureBase):
    def test_per_type_columns_give_types_with_table_counts_and_quantities_per_table(self):
        result = analyze_pdf(bom_pdf())
        types = {item.payload["code"]: item.payload for item in of(result, "structure_type")}
        self.assertEqual(types, {"2x26": {"code": "2x26", "occurrences": 1, "modules": 52, "tables": 157},
                                 "2x13": {"code": "2x13", "occurrences": 1, "modules": 26, "tables": 56}})
        lines = {(item.payload["position"], item.payload["group"]): item for item in of(result, "bom_line")}
        pole = lines[("1", "2x26")].payload
        self.assertEqual((pole["name"], pole["spec"], pole["material"], pole["quantity"]), ("Pole 1", "C120*60*20*3.5*2255", "Q420", 11))
        self.assertEqual(lines[("1", "2x13")].payload["quantity"], 6)
        # Ilość na stół × liczba stołów zgadza się z kolumną QTY → najwyższa pewność.
        self.assertTrue(all(item.confidence == 0.95 for item in lines.values()))

    def test_merged_names_subtotals_positions_and_no_false_conflicts(self):
        result = analyze_pdf(bom_pdf())
        lines = of(result, "bom_line")
        positions = {item.payload["position"] for item in lines}
        self.assertEqual(positions, {"1", "2", "4", "5", "6"})  # „Total of class products” pominięty
        nut = next(item.payload for item in lines if item.payload["position"] == "5")
        self.assertEqual((nut["name"], nut["spec"]), ("Purlin fixing bolts", "M12 Nut"))
        # Ta sama śruba w dwóch pozycjach (różne zastosowania) to nie rozbieżność ilości.
        self.assertFalse(any("conflict" in item.payload for item in lines))

    def test_mismatching_total_lowers_confidence_and_explains(self):
        result = analyze_pdf(bom_pdf(rows=[row(1, "Pole 1", "C120", "Q420", 11, 6, total=2000)]))
        line = next(item for item in of(result, "bom_line") if item.payload["group"] == "2x26")
        self.assertLess(line.confidence, 0.9)
        self.assertIn("2063", line.payload["check"])

    def test_item_names_are_not_zones_and_manual_tables_and_torque_in_brackets(self):
        result = analyze_pdf(bom_pdf(extra_text="Pole 1 and Pole 2 are C-profile posts"))
        self.assertEqual(of(result, "zone"), [])
        manual = analyze_pdf(manual_pdf())
        self.assertEqual({item.payload["name"]: item.payload["quantity"] for item in of(manual, "bom_line")}, {"Pole 1": 11, "Pole 2": 12})
        self.assertEqual([(t.payload["bolt"], t.payload["min_nm"]) for t in of(manual, "torque")], [("M8", 16)])


class PerTypeFlowTest(StructureBase):
    def test_approve_types_and_bom_then_create_tables_and_requirements(self):
        self.upload(("bom.pdf", bom_pdf()))
        ids = [item["id"] for item in self.get("/suggestions", status="nowa")]
        result = self.call("POST", "/suggestions/bulk", {"ids": ids, "status": "zatwierdzona"})
        self.assertEqual(result["failed"], [])
        types = {t["code"]: t for t in self.get("/types")}
        self.assertEqual((types["2x26"]["planned_tables"], types["2x13"]["planned_tables"]), (157, 56))
        self.assertEqual(len(types["2x26"]["bom"]), 5)
        warnings = self.get("/requirements")["warnings"]
        self.assertTrue(any("wg BOM 157 stołów" in w for w in warnings))
        created = self.call("POST", "/tables/range", {"prefix": "A", "first": 1, "last": 157, "structure_type_id": types["2x26"]["id"]})
        self.assertEqual(created["added"], 157)
        self.call("POST", "/tables/range", {"prefix": "B", "first": 1, "last": 56, "structure_type_id": types["2x13"]["id"]})
        totals = {(line["name"], line["spec"]): line["total"] for line in self.get("/requirements")["totals"]}
        self.assertEqual(totals[("Pole 1", "C120*60*20*3.5*2255")], 11 * 157 + 6 * 56)
        self.assertFalse(any("wg BOM" in w for w in self.get("/requirements")["warnings"]))

    def test_manual_lines_get_type_in_bulk_and_matching_quantities_confirm_bom(self):
        self.upload(("bom.pdf", bom_pdf()))
        ids = [item["id"] for item in self.get("/suggestions", status="nowa")]
        self.call("POST", "/suggestions/bulk", {"ids": ids, "status": "zatwierdzona"})
        self.upload(("manual.pdf", manual_pdf()))
        manual = [item for item in self.get("/suggestions", kind="bom_line", status="nowa") if not item["payload"]["group"]]
        self.assertEqual(len(manual), 2)
        result = self.call("POST", "/suggestions/bulk", {"ids": [item["id"] for item in manual], "status": "zatwierdzona", "group": "2x26"})
        # Pole 1 = 11 jak w BOM → potwierdzenie (bez drugiej pozycji); Pole 2 = 12 ≠ 11 → odmowa z wyjaśnieniem.
        self.assertEqual(result["updated"], 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("ta propozycja podaje 12", result["failed"][0]["reason"])
        bom = next(t for t in self.get("/types") if t["code"] == "2x26")["bom"]
        self.assertEqual(sum(1 for line in bom if line["name"] == "Pole 1"), 1)

    def test_untyped_lines_cannot_add_new_items_to_type_that_already_has_bom(self):
        self.upload(("bom.pdf", bom_pdf()))
        ids = [item["id"] for item in self.get("/suggestions", status="nowa")]
        self.call("POST", "/suggestions/bulk", {"ids": ids, "status": "zatwierdzona"})
        before = len(next(t for t in self.get("/types") if t["code"] == "2x26")["bom"])
        manual = io.BytesIO()
        pdf = canvas.Canvas(manual, pagesize=A4)
        table = Table([["Part Name", "Number", "Material"], ["Big Flat Washer M8", "208", "SUS304"]])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
        table.wrapOn(pdf, 400, 300)
        table.drawOn(pdf, 50, 700)
        pdf.showPage(); pdf.save()
        self.upload(("instrukcja.pdf", manual.getvalue()))
        line = next(item for item in self.get("/suggestions", kind="bom_line", status="nowa") if item["payload"]["name"] == "Big Flat Washer M8")
        result = self.call("POST", "/suggestions/bulk", {"ids": [line["id"]], "status": "zatwierdzona", "group": "2x26"})
        self.assertEqual(result["updated"], 0)
        self.assertIn("nie występuje w BOM typu 2x26", result["failed"][0]["reason"])
        self.assertEqual(len(next(t for t in self.get("/types") if t["code"] == "2x26")["bom"]), before)
        # Typ bez BOM: pozycje z instrukcji mogą go zasilić (jedyne źródło ilości).
        self.call("POST", "/types", {"code": "1x28"})
        result = self.call("POST", "/suggestions/bulk", {"ids": [line["id"]], "status": "zatwierdzona", "group": "1x28"})
        self.assertEqual(result["updated"], 1)
