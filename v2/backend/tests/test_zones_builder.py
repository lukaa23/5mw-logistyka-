"""Strefy i rzędy jak w v1: strefa → rzędy z zakresu → warianty budowy; usuwanie strefy z rzędami; protokół PDF."""
import io

import pdfplumber

from test_structure import StructureBase


class ZonesBuilderTest(StructureBase):
    def build_zone(self, name="Strefa A", prefix="A", first=1, last=10, variant=None):
        zone = self.call("POST", "/zones", {"name": name, "description": "północ"})
        body = {"prefix": prefix, "first": first, "last": last, "zone_id": zone["id"]}
        if variant:
            body["structure_type_id"] = variant
        self.call("POST", "/tables/range", body)
        return zone

    def test_three_steps_zone_rows_variants(self):
        # Krok 3: warianty zdefiniowane dla tej budowy (nic na sztywno w kodzie).
        long_variant = self.call("POST", "/types", {"code": "1x56+1x42"})["id"]
        short_variant = self.call("POST", "/types", {"code": "1X28"})["id"]
        self.assertEqual({t["code"]: t["modules"] for t in self.get("/types")}, {"1x56+1x42": 98, "1x28": 28})
        zone = self.build_zone(variant=long_variant)  # krok 1 i 2: strefa + rzędy A-1…A-10
        tables = self.get("/tables", zone_id=zone["id"])
        self.assertEqual([t["code"] for t in tables], [f"A-{n}" for n in range(1, 11)])
        self.assertTrue(all(t["structure_type_id"] == long_variant for t in tables))
        # Przypisanie innego wariantu do zakresu A-8…A-10.
        self.call("POST", "/tables/assign", {"ids": [t["id"] for t in tables[7:]], "structure_type_id": short_variant})
        counts = {}
        for table in self.get("/tables", zone_id=zone["id"]):
            counts[table["structure_type_id"]] = counts.get(table["structure_type_id"], 0) + 1
        self.assertEqual(counts, {long_variant: 7, short_variant: 3})
        listed = next(z for z in self.get("/zones") if z["id"] == zone["id"])
        self.assertEqual(listed["stats"], {"total": 10, "built": 0, "qc": 0})

    def test_delete_zone_with_rows_protects_field_data(self):
        zone = self.build_zone()
        first = self.get("/tables", zone_id=zone["id"])[0]
        self.call("PATCH", f"/tables/{first['id']}/progress", {"built": True})
        refused = self.call("DELETE", f"/zones/{zone['id']}?with_tables=true", expect=409)
        self.assertIn("montaż, notatki lub zdjęcia", refused["detail"])
        self.call("PATCH", f"/tables/{first['id']}/progress", {"built": False})
        self.call("DELETE", f"/zones/{zone['id']}?with_tables=true")
        self.assertEqual(self.get("/tables"), [])
        # Bez with_tables rzędy zostają (bez strefy).
        other = self.build_zone("Strefa B", "B", 1, 3)
        self.call("DELETE", f"/zones/{other['id']}")
        self.assertEqual(len(self.get("/tables", zone_id=0)), 3)

    def test_zone_protocol_pdf_lists_rows_with_who_and_when(self):
        variant = self.call("POST", "/types", {"code": "1x28"})["id"]
        zone = self.build_zone(last=3, variant=variant)
        tables = self.get("/tables", zone_id=zone["id"])
        self.call("PATCH", f"/tables/{tables[0]['id']}/progress", {"built": True})
        self.call("PATCH", f"/tables/{tables[0]['id']}/progress", {"qc_checked": True})
        self.call("POST", f"/tables/{tables[1]['id']}/notes", {"text": "brak śruby"})
        response = self.client.get(f"{self.base}/zones/{zone['id']}/protocol", headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers["content-disposition"])
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        for expected in ("PROTOKÓŁ MONTAŻU I ODBIORU STREFY", "Strefa A", "A-1", "A-3", "1x28", "Kierownik Budowy", "zamontowanych: 1", "odebranych QA/QC: 1"):
            self.assertIn(expected, text)
