"""Rysunki CAD (DXF, DWG): od wgrania przez analizę i przegląd propozycji do Planimetrii.

DWG wymaga zewnętrznego konwertera. W testach zastępuje go mały skrypt Pythona, który „konwertuje”,
zapisując przygotowany DXF — sprawdzamy tak całą ścieżkę: wywołanie polecenia, odczyt wyniku, analizę.
Prawdziwy DWG: ASOLAR_TEST_DWG=ścieżka (i zainstalowany konwerter) uruchamia dodatkowy test.
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ezdxf

from asolar2 import cad
from test_structure import StructureBase

FAKE_CONVERTER = '''
import os, shutil, sys
args = sys.argv[1:]
fixture = os.environ["ASOLAR_TEST_FIXTURE_DXF"]
if args and args[0] == "-y":                       # LibreDWG: dwg2dxf -y -o out.dxf in.dwg
    source, target = args[3], args[2]
elif len(args) == 7:                               # ODA: in_dir out_dir ACAD2018 DXF 0 1 *.DWG
    source, target = os.path.join(args[0], "rysunek.dwg"), os.path.join(args[1], "rysunek.dxf")
else:                                              # szablon: {input} {output}
    source, target = args[0], args[1]
assert open(source, "rb").read(6).startswith(b"AC10"), "konwerter dostał nie-DWG"
shutil.copyfile(fixture, target)
'''


def drawing_dxf(tables=24, posts_per_table=11, zone="Campo 1") -> bytes:
    """Rysunek jak w layoutach PV: stoły jako bloki z typem, numery na osobnej warstwie, pale jako bloki."""
    doc = ezdxf.new("R2018")
    doc.layers.add("NUMERI", color=1)
    doc.layers.add("STOLY", color=3)
    doc.layers.add("PALI", color=5)
    post = doc.blocks.new("PALO")
    post.add_circle((0, 0), 0.1)
    table = doc.blocks.new("TAVOLO_2x26")
    table.add_lwpolyline([(0, 0), (40, 0), (40, 4.5), (0, 4.5)], close=True)
    table.add_text("2x26", dxfattribs={"height": 0.5}).set_placement((1, 1))
    doc.blocks.new("*U12")  # blok anonimowy — nie liczymy
    msp = doc.modelspace()
    for index in range(tables):
        x, y = (index % 6) * 50, (index // 6) * 10
        msp.add_blockref("TAVOLO_2x26", (x, y), dxfattribs={"layer": "STOLY"})
        msp.add_text(f"T-{index + 1}", dxfattribs={"height": 1.0, "layer": "NUMERI"}).set_placement((x, y + 5))
        for k in range(posts_per_table):
            msp.add_blockref("PALO", (x + k * 4, y), dxfattribs={"layer": "PALI"})
    msp.add_text(zone, dxfattribs={"height": 3}).set_placement((0, 50))
    msp.add_mtext("Coppia di serraggio bulloni M10: 32 N.m", dxfattribs={"char_height": 1}).set_location((0, 60))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


FAKE_DWG = b"AC1032" + b"\x00" * 128  # nagłówek DWG 2018; treść czyta (udawany) konwerter


class CadParserTest(unittest.TestCase):
    def test_format_detection_by_content(self):
        self.assertEqual(cad.detect_format("x.bin", drawing_dxf(tables=1)), "dxf")
        self.assertEqual(cad.detect_format("x", FAKE_DWG), "dwg")
        self.assertEqual(cad.detect_format("x.pdf", b"%PDF-1.7"), "pdf")
        self.assertEqual(cad.detect_format("x.dwg", b"hello"), "")

    def test_texts_layers_blocks_types_zones_torque(self):
        result = cad.analyze_cad(drawing_dxf(), "plan.dxf")
        by_kind = {}
        for item in result.suggestions:
            by_kind.setdefault(item.kind, []).append(item.payload)
        numbering = by_kind["numbering"][0]
        self.assertEqual((numbering["prefix"], numbering["first"], numbering["last"], numbering["layers"]), ("T", 1, 24, ["NUMERI"]))
        blocks = {block["name"]: block for block in by_kind["drawing_block"]}
        self.assertEqual(blocks["PALO"]["count"], 24 * 11)
        self.assertEqual(blocks["PALO"]["layers"], ["PALI"])
        self.assertEqual(blocks["TAVOLO_2x26"]["count"], 24)
        self.assertFalse(any(name.startswith("*") for name in blocks))
        self.assertEqual(by_kind["structure_type"][0]["code"], "2x26")  # tekst wewnątrz bloku stołu
        self.assertEqual(by_kind["zone"][0]["name"], "Campo 1")
        self.assertEqual((by_kind["torque"][0]["bolt"], by_kind["torque"][0]["min_nm"]), ("M10", 32))

    def test_missing_converter_message(self):
        with mock.patch.object(cad, "find_converter", return_value=None):
            with self.assertRaises(cad.CadError) as raised:
                cad.analyze_cad(FAKE_DWG, "plan.dwg")
        self.assertIn("zapisz rysunek jako DXF", str(raised.exception))


class CadConverterTest(unittest.TestCase):
    """Wywołanie konwertera w trzech konwencjach (szablon, ODA, LibreDWG) — prawdziwy podproces."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="asolar2-cad-test-")
        cls.script = Path(cls.folder, "fake_converter.py")
        cls.script.write_text(FAKE_CONVERTER, encoding="utf-8")
        cls.fixture = Path(cls.folder, "fixture.dxf")
        cls.fixture.write_bytes(drawing_dxf(tables=12))
        os.environ["ASOLAR_TEST_FIXTURE_DXF"] = str(cls.fixture)

    def converted(self, converter):
        with mock.patch.object(cad, "find_converter", return_value=converter):
            return cad.dwg_to_dxf(FAKE_DWG)

    def test_template_command(self):
        template = f'"{sys.executable}" "{self.script}" {{input}} {{output}}'
        with mock.patch.dict(os.environ, {"ASOLAR_DWG_CONVERTER": template}):
            self.assertEqual(cad.find_converter()[0], "template")
            data = cad.dwg_to_dxf(FAKE_DWG)
        self.assertIn(b"SECTION", data[:200])

    def test_oda_and_libredwg_conventions(self):
        wrapper = Path(self.folder, "wrapper.cmd" if os.name == "nt" else "wrapper.sh")
        if os.name == "nt":
            wrapper.write_text(f'@"{sys.executable}" "{self.script}" %*\r\n', encoding="utf-8")
        else:
            wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.script}" "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
        self.assertIn(b"SECTION", self.converted(("oda", str(wrapper)))[:200])
        self.assertIn(b"SECTION", self.converted(("libredwg", str(wrapper)))[:200])

    def test_failing_converter_reports_error(self):
        template = f'"{sys.executable}" -c "import sys; sys.exit(3)" {{input}} {{output}}'
        with mock.patch.dict(os.environ, {"ASOLAR_DWG_CONVERTER": template}):
            with self.assertRaises(cad.CadError) as raised:
                cad.dwg_to_dxf(FAKE_DWG)
        self.assertIn("kod 3", str(raised.exception))


class CadFlowTest(StructureBase):
    def upload_file(self, name, content):
        response = self.client.post(f"{self.base}/documents", headers=self.admin, files=[("files", (name, content, "application/octet-stream"))])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_dxf_upload_review_approve_and_planimetria(self):
        body = self.upload_file("layout.dxf", drawing_dxf())
        self.assertEqual(body["accepted"][0]["format"], "dxf")
        document = self.get("/documents")[0]
        self.assertEqual((document["status"], document["pages"]), ("gotowy", 1))
        kinds = {item["kind"] for item in self.get("/suggestions")}
        self.assertTrue({"numbering", "drawing_block", "structure_type", "zone", "torque"} <= kinds)

        ids = [item["id"] for item in self.get("/suggestions", status="nowa")]
        result = self.call("POST", "/suggestions/bulk", {"ids": ids, "status": "zatwierdzona"})
        self.assertEqual(result["failed"], [])
        self.assertEqual(len(self.get("/tables")), 24)
        blocks = {item["name"]: item for item in self.get("/catalog")["items"] if item["kind"] == "block"}
        self.assertEqual((blocks["PALO"]["quantity"], blocks["PALO"]["spec"]), (264, "PALI"))

        plan = self.get(f"/documents/{document['id']}/plan")
        self.assertEqual((plan["format"], plan["pages"], len(plan["markers"]), plan["tables_not_on_page"]), ("dxf", 1, 24, 0))
        marker = next(m for m in plan["markers"] if m["code"] == "T-1")
        self.assertTrue(0 <= marker["x"] <= 0.05 and 0 <= marker["y"] <= 1)
        svg = self.client.get(f"{self.base}/documents/{document['id']}/pages/1.svg", headers=self.admin)
        self.assertEqual(svg.headers["content-type"], "image/svg+xml")
        self.assertTrue(svg.content.startswith(b"<svg") and b"<path" in svg.content and b"T-1" in svg.content)
        self.assertEqual(self.client.get(f"{self.base}/documents/{document['id']}/plan", headers=self.admin, params={"page": 2}).status_code, 400)
        download = self.client.get(f"{self.base}/documents/{document['id']}/file", headers=self.admin)
        self.assertIn("attachment", download.headers["content-disposition"])

        # Cofnięcie bloku usuwa go z katalogu.
        block = next(item for item in self.get("/suggestions", kind="drawing_block") if item["payload"]["name"] == "PALO")
        self.call("PATCH", f"/suggestions/{block['id']}", {"status": "nowa"})
        self.assertNotIn("PALO", {item["name"] for item in self.get("/catalog")["items"]})

    def test_dwg_without_converter_fails_with_instructions(self):
        with mock.patch.object(cad, "find_converter", return_value=None):
            self.upload_file("GA.dwg", FAKE_DWG)
        document = self.get("/documents")[0]
        self.assertEqual(document["status"], "ręcznie")
        self.assertIn("ODA File Converter", document["error"])
        self.assertIn("DXF", document["error"])

    def test_dwg_with_converter_full_flow(self):
        folder = tempfile.mkdtemp(prefix="asolar2-cad-flow-")
        script, fixture = Path(folder, "fake.py"), Path(folder, "fixture.dxf")
        script.write_text(FAKE_CONVERTER, encoding="utf-8")
        fixture.write_bytes(drawing_dxf(tables=15, zone="Campo 2"))
        template = f'"{sys.executable}" "{script}" {{input}} {{output}}'
        with mock.patch.dict(os.environ, {"ASOLAR_DWG_CONVERTER": template, "ASOLAR_TEST_FIXTURE_DXF": str(fixture)}):
            self.upload_file("GA Drawing.dwg", FAKE_DWG)
            document = self.get("/documents")[0]
            self.assertEqual((document["status"], document["format"]), ("gotowy", "dwg"), document["error"])
            numbering = self.get("/suggestions", kind="numbering")[0]["payload"]
            self.assertEqual((numbering["first"], numbering["last"]), (1, 15))
            self.call("PATCH", f"/suggestions/{self.get('/suggestions', kind='numbering')[0]['id']}", {"status": "zatwierdzona"})
            plan = self.get(f"/documents/{document['id']}/plan")
            self.assertEqual(len(plan["markers"]), 15)

    def test_unknown_file_rejected_and_dxf_without_extension_renamed(self):
        body = self.upload_file("notatki.txt", b"hello")
        self.assertIn("PDF, DWG ani DXF", body["rejected"][0]["reason"])
        body = self.upload_file("eksport_bez_rozszerzenia", drawing_dxf(tables=2))
        self.assertEqual(body["accepted"][0]["filename"], "eksport_bez_rozszerzenia.dxf")


@unittest.skipUnless(os.getenv("ASOLAR_TEST_DWG") and cad.find_converter(), "brak prawdziwego DWG lub konwertera")
class RealDwgTest(unittest.TestCase):
    def test_real_dwg_is_converted_and_analyzed(self):
        result = cad.analyze_cad(Path(os.environ["ASOLAR_TEST_DWG"]).read_bytes(), "real.dwg")
        self.assertEqual(result.pages, 1)
        self.assertTrue(result.suggestions or result.warnings)


class CadRealWorldFixesTest(unittest.TestCase):
    """Poprawki po testach na prawdziwych rysunkach (ODA, bloki z kopiuj-wklej, odległe obiekty)."""

    def test_oda_found_in_versioned_install_folder(self):
        root = Path(tempfile.mkdtemp(prefix="asolar2-pf-"))
        for version in ("26.4.0", "27.9.0"):
            folder = root / "ODA" / f"ODAFileConverter {version}"
            folder.mkdir(parents=True)
            (folder / "ODAFileConverter.exe").write_bytes(b"MZ")
        with mock.patch.dict(os.environ, {"ProgramFiles": str(root), "ProgramW6432": str(root)}):
            found = cad.installed_oda()
        self.assertTrue(found.endswith(os.path.join("ODAFileConverter 27.9.0", "ODAFileConverter.exe")))

    def test_autocad_copy_paste_blocks_are_not_components(self):
        doc = ezdxf.new("R2018")
        doc.blocks.new("A$Cd2c4f12b")
        doc.blocks.new("TRK 56 tipo S")
        msp = doc.modelspace()
        msp.add_blockref("A$Cd2c4f12b", (0, 0))
        for index in range(3):
            msp.add_blockref("TRK 56 tipo S", (index * 10, 0))
        self.assertEqual([(b["name"], b["count"]) for b in cad.block_counts(doc)], [("TRK 56 tipo S", 3)])

    def test_far_away_object_does_not_shrink_the_drawing(self):
        doc = ezdxf.new("R2018")
        msp = doc.modelspace()
        for index in range(100):
            msp.add_line((index, 0), (index, 10))
        msp.add_point((1_000_000, 1_000_000))  # np. punkt odniesienia daleko od budowy
        min_x, min_y, max_x, max_y = cad._extents(doc)
        self.assertLess(max_x - min_x, 200)
        self.assertLess(max_y - min_y, 200)

    def test_blocks_with_text_are_expanded_for_labels_only(self):
        doc = ezdxf.new("R2018")
        tree = doc.blocks.new("ALBERO")
        tree.add_circle((0, 0), 1)
        tag = doc.blocks.new("TARGA")
        tag.add_text("T-7", dxfattribs={"height": 1})
        outer = doc.blocks.new("STOL")
        outer.add_blockref("TARGA", (0, 0))
        self.assertEqual(cad.blocks_with_text(doc) & {"ALBERO", "TARGA", "STOL"}, {"TARGA", "STOL"})
        doc.modelspace().add_blockref("STOL", (5, 5))
        self.assertEqual([t[0] for t in cad.iter_texts(doc.modelspace())], ["T-7"])
