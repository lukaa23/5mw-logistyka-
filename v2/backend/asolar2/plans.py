"""Etap 4c: Planimetria — strona rysunku PDF jako obraz + położenie stołów odczytane z rysunku.

Pozycje znaczników NIE są zgadywane: to współrzędne słów z warstwy tekstowej PDF, które po
normalizacji (T.48, T-48, T48 → T-48) odpowiadają oznaczeniom stołów istniejących w budowie.
Rysunek bez warstwy tekstowej (skan) wyświetla się bez znaczników — z wyjaśnieniem.
"""
import io
import re
import threading
from collections import OrderedDict

import pdfplumber
import pypdfium2

CODE = re.compile(r"^([A-Za-z]{1,4})[-_.]?(\d{1,4})$")
MAX_SCALE = 4.0
MAX_PIXELS = 40_000_000  # ok. 6300×6300 — chroni serwer przed ogromnymi arkuszami
_cache: "OrderedDict[tuple, object]" = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 24


def _cached(key, build):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    value = build()
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return value


def normalize_code(text: str) -> str | None:
    match = CODE.match(text.strip())
    return f"{match.group(1).upper()}-{int(match.group(2))}" if match else None


def page_info(sha: str, content: bytes, page_number: int) -> dict:
    """Wymiary strony, liczba stron i słowa-kody z pozycjami (0..1 względem strony)."""
    def build():
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = len(pdf.pages)
            if not 1 <= page_number <= pages:
                raise ValueError(f"Dokument ma {pages} stron")
            page = pdf.pages[page_number - 1]
            width, height = float(page.width), float(page.height)
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            codes = []
            for word in words:
                code = normalize_code(word["text"])
                if code:
                    codes.append({"code": code, "x": word["x0"] / width, "y": word["top"] / height,
                                  "w": (word["x1"] - word["x0"]) / width, "h": (word["bottom"] - word["top"]) / height})
            return {"pages": pages, "width": width, "height": height, "has_text": bool(words), "codes": codes}
    return _cached(("info", sha, page_number), build)


def render_png(sha: str, content: bytes, page_number: int, scale: float) -> bytes:
    scale = max(0.5, min(MAX_SCALE, scale))

    def build():
        document = pypdfium2.PdfDocument(content)
        try:
            if not 1 <= page_number <= len(document):
                raise ValueError(f"Dokument ma {len(document)} stron")
            page = document[page_number - 1]
            width, height = page.get_size()
            effective = scale
            if width * height * effective * effective > MAX_PIXELS:
                effective = (MAX_PIXELS / (width * height)) ** 0.5
            image = page.render(scale=effective).to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=False)
            return output.getvalue()
        finally:
            document.close()
    return _cached(("png", sha, page_number, round(scale, 2)), build)


def markers(info: dict, tables: dict[str, dict]) -> dict:
    """Łączy kody z rysunku ze stołami budowy. Ten sam kod kilka razy na stronie = pierwsze wystąpienie."""
    found, seen, unmatched = [], set(), set()
    for item in info["codes"]:
        table = tables.get(item["code"])
        if table is None:
            unmatched.add(item["code"])
            continue
        if item["code"] in seen:
            continue
        seen.add(item["code"])
        found.append({**item, "table_id": table["id"], "built": table["built"], "qc_checked": table["qc_checked"]})
    return {"markers": found, "unmatched_codes": len(unmatched), "tables_not_on_page": len(tables) - len(seen)}
