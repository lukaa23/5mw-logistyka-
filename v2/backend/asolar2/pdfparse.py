"""Lokalny parser PDF: wyciąga z dokumentów budowy propozycje danych do zatwierdzenia.

Nic tu nie jest wpisane na sztywno dla konkretnego producenta. Parser działa na:
- tabelach (pdfplumber) z rozpoznawaniem nagłówków w kilku językach (PL/EN/IT/DE),
- liniach tekstu pod nagłówkiem tabeli (gdy tabela rozpada się na fragmenty),
- wzorcach: typy konstrukcji (1x28, 2P×60, 1x56+1x42), strefy, numeracja stołów/trackerów,
  momenty dokręcania śrub.

Każda propozycja ma źródło (plik, strona), fragment tekstu i pewność. Wynik NIE trafia do
danych budowy automatycznie — trafia na ekran przeglądu, gdzie kierownik zatwierdza, poprawia
lub odrzuca. Strony zapisane jako obraz (skany) są wykrywane i opisywane jako „wymaga OCR”.
"""
from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pdfplumber

PARSER_VERSION = "2.0-etap2"
MAX_PAGES = 400

# --- nagłówki kolumn (porównanie po normalizacji) ------------------------------------------------
HEADERS = {
    "no": {"no", "nr", "lp", "l.p", "pos", "poz", "pozycja", "#", "n", "item"},
    "name": {"description", "opis", "nazwa", "name", "component", "komponent", "part", "element", "material", "materiał", "descrizione", "denominazione", "bezeichnung", "designation"},
    "code": {"item no", "itemno", "part no", "partno", "p/n", "pn", "kod", "code", "nr katalogowy", "indeks", "index", "sku", "article", "art", "codice", "codice articolo", "artikelnummer", "artikel", "drawing no", "ref"},
    "qty": {"quantities", "quantity", "qty", "q.ty", "ilość", "ilosc", "szt", "pcs", "quantità", "quantita", "q.tà", "menge", "anzahl", "amount"},
    "unit": {"unit", "jm", "j.m", "uom", "unità", "unita", "einheit"},
    "spec": {"spec", "specification", "specyfikacja", "wymiar", "wymiary", "dimension", "dimensions", "size", "specifiche", "abmessung", "model"},
    "remark": {"remark", "remarks", "uwagi", "note", "notes", "note/remark", "bemerkung"},
}
NOT_NUMBERING = {"M"}  # M10, M16… to rozmiary śrub, nie numery stołów
ELECTRICAL_PREFIXES = {"INV", "MPPT", "CB", "SB", "QE", "QF", "DC", "AC", "STR", "CAB", "QG", "TR-E"}
ADDRESS_CUES = re.compile(r"\b(co\.|ltd|road|street|province|city|economic|development|technological|ul\.|tel\.?|e-?mail|www\.)", re.I)
TYPE_PATTERN = re.compile(r"(?<![\w.×*])([1-4])\s*[PpXx×]\s*(\d{2,3})(?:\s*\+\s*(?:([1-4])\s*[PpXx×]\s*)?(\d{2,3}))?(?![\w.]|\s*[x×*]\s*\d)")
ZONE_PATTERN = re.compile(r"\b(Strefa|Strefy|Zone|Zona|Sektor|Sector|Field|Pole|Area|Obszar|Blok|Block|Campo|Sottocampo|Sottosistema)\s+([A-Z]{1,2}\d{0,2}|\d{1,3}|[IVX]{1,4})\b")
CODE_TOKEN = re.compile(r"^([A-Za-z]{1,4})[-_.]?(\d{1,4})$")
TORQUE_PATTERN = re.compile(r"\b(M\d{1,2})\b[^\n]{0,90}?(\d{1,4}(?:[.,]\d+)?)\s*(?:[-–~÷]\s*(\d{1,4}(?:[.,]\d+)?))?\s*N[·.\s]?m\b")
ITEM_CODE = re.compile(r"^[A-Z]{1,5}\d*[-_][\w.-]+$|^[A-Z]{2,}\d{2,}[\w.-]*$")
DIMENSION = re.compile(r"[\d.,]+\s*[x×*]\s*[\d.,]+|^[A-Z]?\d+[x×*]\d")


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def header_kind(cell: str) -> str | None:
    text = norm(cell).lower().rstrip(".:").replace("º", "").replace("°", "")
    for kind, aliases in HEADERS.items():
        if text in aliases:
            return kind
    if text.startswith("quantit") or text.startswith("ilo"):
        return "qty"
    return None


def parse_number(value) -> float | None:
    text = norm(value).replace(" ", "")
    if not re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return None
    return float(text.replace(",", "."))


def normalize_type(match: re.Match) -> str:
    rows, modules, rows2, modules2 = match.groups()
    base = f"{rows}x{modules}"
    if modules2:
        return f"{base}+{rows2 or rows}x{modules2}"
    return base


@dataclass
class Suggestion:
    kind: str                      # bom_line | component | structure_type | zone | numbering | torque
    key: str                       # klucz scalania (ten sam element z wielu stron/plików = jedna propozycja)
    payload: dict
    page: int
    excerpt: str
    confidence: float


@dataclass
class Analysis:
    pages: int = 0
    text_pages: int = 0
    image_pages: list[int] = field(default_factory=list)
    tables: int = 0
    skipped_electrical: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)

    def summary(self) -> dict:
        kinds = Counter(item.kind for item in self.suggestions)
        return {"pages": self.pages, "text_pages": self.text_pages, "image_pages": self.image_pages, "tables": self.tables,
                "suggestions": dict(kinds), "skipped_electrical": self.skipped_electrical, "parser": PARSER_VERSION}


# --- tabele ------------------------------------------------------------------------------------

def clean_table(table: list[list]) -> list[list[str]]:
    rows = [[norm(cell) for cell in row] for row in table if row]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    keep = [index for index in range(width) if any(row[index] for row in rows)]
    return [[row[index] for index in keep] for row in rows if any(row[index] for index in keep)]


def find_header(rows: list[list[str]]) -> tuple[int, dict] | None:
    for index, row in enumerate(rows[:6]):
        mapping = {}
        for column, cell in enumerate(row):
            kind = header_kind(cell)
            if kind and kind not in mapping:
                mapping[kind] = column
        if "name" in mapping and len(mapping) >= 2:
            return index, mapping
    return None


def page_type_context(text: str) -> str | None:
    """Typ konstrukcji z tytułu strony / podpisu tabeli (np. „List of materials for 1x42 …”)."""
    for line in text.splitlines():
        if re.search(r"(materia|bom|list|wykaz|zestawienie|distinta|stückliste)", line, re.I):
            match = TYPE_PATTERN.search(line)
            if match:
                return normalize_type(match)
    return None


TOOLS_CUE = re.compile(r"(\btools?\b|narzędzi|narzedzi|attrezz|werkzeug|\bpattern\b)", re.I)


def text_above(page, bbox, height: float = 90) -> str:
    """Tekst bezpośrednio nad tabelą (podpis typu „Table 3: List of materials for 1x56 …”)."""
    x0, top, x1, _ = bbox
    try:
        return page.crop((0, max(0, top - height), page.width, top)).extract_text() or ""
    except Exception:
        return ""


def type_in(text: str) -> str | None:
    matches = [normalize_type(match) for line in text.splitlines()[-3:] for match in TYPE_PATTERN.finditer(line)]
    return matches[-1] if matches else None


def as_tool(item: "Suggestion") -> "Suggestion":
    payload = {"name": item.payload["name"], "spec": item.payload.get("spec", "")}
    return Suggestion("tool", f"tool|{payload['name'].lower()}|{payload['spec'].lower()}", payload, item.page, item.excerpt, 0.7)


def caption_for(text: str) -> str:
    for line in text.splitlines():
        if re.search(r"\b(table|tabela|tabella|tab\.)\s*[\w.-]*\s*:", line, re.I) or re.search(r"(list of materials|wykaz materiał|zestawienie materiał|bill of material)", line, re.I):
            return norm(line)[:200]
    return ""


def bom_from_table(rows: list[list[str]], page: int, group: str | None, caption: str) -> list[Suggestion]:
    header = find_header(rows)
    if not header:
        return []
    start, mapping = header
    result = []
    for row in rows[start + 1:]:
        cell = lambda kind: row[mapping[kind]] if kind in mapping and mapping[kind] < len(row) else ""
        name, code, spec, unit = cell("name"), cell("code"), cell("spec"), cell("unit")
        if not name or header_kind(name):
            continue
        code = "" if code in ("/", "-", "—") else code
        qty = parse_number(cell("qty")) if "qty" in mapping else None
        excerpt = " | ".join(value for value in row if value)[:240]
        if qty is not None:
            payload = {"name": name, "code": code, "spec": spec, "quantity": qty, "unit": unit or "szt.", "group": group or "", "caption": caption}
            key = f"bom|{(group or '').lower()}|{(code or name).lower()}|{spec.lower()}|{qty:g}"
            result.append(Suggestion("bom_line", key, payload, page, excerpt, 0.9 if code or spec else 0.8))
        elif "qty" not in mapping:
            key = f"component|{(code or name).lower()}|{spec.lower()}"
            result.append(Suggestion("component", key, {"name": name, "code": code, "spec": spec}, page, excerpt, 0.7))
    return result


def bom_from_text_lines(text: str, page: int, group: str | None, caption: str) -> list[Suggestion]:
    """Rezerwa: wiersze pod tekstowym nagłówkiem tabeli, gdy pdfplumber nie złożył tabeli."""
    lines = [norm(line) for line in text.splitlines()]
    result = []
    in_table = False
    for line in lines:
        tokens = line.split(" ")
        lowered = line.lower()
        header_hits = sum(1 for kind in ("description", "opis", "nazwa", "quantit", "ilość", "qty", "spec", "item no", "kod") if kind in lowered)
        if header_hits >= 2 and re.match(r"^(no\.?|nr|lp\.?|pos\.?)\b", lowered):
            in_table = True
            continue
        if not in_table:
            continue
        if not re.match(r"^\d{1,3}\s", line):
            if re.match(r"^(figure|rys|table|tabela|note|uwaga)", lowered):
                in_table = False
            continue
        # Ilość musi być ostatnim tokenem wiersza, a wiersz musi mieć kod albo wymiar —
        # odrzuca zdania instrukcji typu „2 Torque 8 N.m” czy „Hex bolt (1 big flat washer…”.
        qty = parse_number(tokens[-1]) if len(tokens) >= 3 else None
        if qty is None:
            continue
        qty_index = len(tokens) - 1
        body = tokens[1:qty_index]
        code = next((token for token in body if ITEM_CODE.match(token)), "")
        spec = next((token for token in body if token != code and DIMENSION.search(token)), "")
        if not code and not spec:
            continue
        name = " ".join(token for token in body if token not in (code, spec))
        if not name:
            continue
        payload = {"name": name, "code": code, "spec": spec, "quantity": qty, "unit": "szt.", "group": group or "", "caption": caption}
        key = f"bom|{(group or '').lower()}|{(code or name).lower()}|{spec.lower()}|{qty:g}"
        result.append(Suggestion("bom_line", key, payload, page, line[:240], 0.65))
    return result


# --- wzorce w tekście ---------------------------------------------------------------------------

def scan_text(text: str, page: int, types: Counter, type_pages: dict, zones: Counter, zone_pages: dict, torques: list):
    for line in text.splitlines():
        if ADDRESS_CUES.search(line):
            continue
        for match in TYPE_PATTERN.finditer(line):
            value = normalize_type(match)
            modules = int(match.group(2))
            if 10 <= modules <= 200:
                types[value] += 1
                type_pages[value].add(page)
        for match in ZONE_PATTERN.finditer(line):
            name = f"{match.group(1).capitalize()} {match.group(2)}"
            zones[name] += 1
            zone_pages[name].add(page)
        for match in TORQUE_PATTERN.finditer(line):
            low = parse_number(match.group(2))
            high = parse_number(match.group(3)) if match.group(3) else low
            if low and 1 <= low <= 2000:
                torques.append(Suggestion("torque", f"torque|{match.group(1).upper()}|{low:g}|{high:g}", {"bolt": match.group(1).upper(), "min_nm": low, "max_nm": high, "context": norm(line)[:160]}, page, norm(line)[:240], 0.6))


def numbering_suggestions(codes: dict, analysis: Analysis) -> list[Suggestion]:
    result = []
    for prefix, numbers in codes.items():
        values = sorted({entry[0] for entry in numbers})
        if prefix in ELECTRICAL_PREFIXES:
            analysis.skipped_electrical[prefix] = len(values)
            continue
        if len(values) < 10 or prefix in NOT_NUMBERING:
            continue
        pages = sorted({entry[1] for entry in numbers})
        sample = codes_sample(numbers)
        missing = sorted(set(range(values[0], values[-1] + 1)) - set(values))
        payload = {"prefix": prefix, "count": len(values), "first": values[0], "last": values[-1], "missing": missing[:50], "example": sample, "label": f"{prefix} {values[0]}–{values[-1]}"}
        confidence = 0.75 if len(missing) <= max(2, len(values) // 10) else 0.5
        result.append(Suggestion("numbering", f"numbering|{prefix}", payload, pages[0], f"{len(values)} oznaczeń {prefix} (np. {sample}) na stronach {', '.join(map(str, pages[:8]))}", confidence))
    return result


def codes_sample(numbers) -> str:
    return numbers[0][2] if numbers and len(numbers[0]) > 2 else ""


# --- analiza dokumentu --------------------------------------------------------------------------

def analyze_pdf(content: bytes) -> Analysis:
    analysis = Analysis()
    types, zones = Counter(), Counter()
    type_pages, zone_pages = defaultdict(set), defaultdict(set)
    torques: list[Suggestion] = []
    codes: dict[str, list] = defaultdict(list)
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        analysis.pages = len(pdf.pages)
        if analysis.pages > MAX_PAGES:
            analysis.warnings.append(f"Przeanalizowano pierwsze {MAX_PAGES} z {analysis.pages} stron.")
        for number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
            text = page.extract_text() or ""
            meaningful = "\n".join(line for line in text.splitlines() if not ADDRESS_CUES.search(line))
            if meaningful.strip():
                analysis.text_pages += 1
            if page.images and len(meaningful.strip()) < 80:
                analysis.image_pages.append(number)
            group = page_type_context(text)
            caption = caption_for(text)
            page_bom: list[Suggestion] = []
            try:
                found = page.find_tables()
            except Exception:
                found = []
            for table in found:
                try:
                    rows = clean_table(table.extract())
                except Exception:
                    continue
                if len(rows) < 2:
                    continue
                analysis.tables += 1
                above = text_above(page, table.bbox)
                table_group = type_in(above) or group
                table_caption = caption_for(above) or caption
                items = bom_from_table(rows, number, table_group, table_caption)
                if TOOLS_CUE.search(above) or TOOLS_CUE.search(" ".join(rows[0])):
                    items = [as_tool(item) for item in items]
                page_bom.extend(items)
            if not any(item.kind == "bom_line" for item in page_bom):
                page_bom.extend(bom_from_text_lines(text, number, group, caption))
            analysis.suggestions.extend(page_bom)
            scan_text(text, number, types, type_pages, zones, zone_pages, torques)
            for word in page.extract_words():
                match = CODE_TOKEN.match(word["text"])
                if match:
                    codes[match.group(1).upper()].append((int(match.group(2)), number, word["text"]))
    for value, count in types.items():
        pages = sorted(type_pages[value])
        confidence = 0.85 if count >= 3 else 0.6 if count == 2 else 0.4
        analysis.suggestions.append(Suggestion("structure_type", f"type|{value}", {"code": value, "occurrences": count, "modules": modules_of(value)}, pages[0], f"„{value}” występuje {count}× (strony {', '.join(map(str, pages[:8]))})", confidence))
    for name, count in zones.items():
        pages = sorted(zone_pages[name])
        analysis.suggestions.append(Suggestion("zone", f"zone|{name.lower()}", {"name": name, "occurrences": count}, pages[0], f"„{name}” występuje {count}× (strony {', '.join(map(str, pages[:8]))})", 0.8 if count >= 2 else 0.55))
    analysis.suggestions.extend(numbering_suggestions(codes, analysis))
    seen = set()
    for item in torques:
        if item.key not in seen:
            seen.add(item.key)
            analysis.suggestions.append(item)
    if analysis.image_pages:
        analysis.warnings.append(f"Strony zapisane jako obraz (skan) — bez OCR nie da się odczytać ich treści: {', '.join(map(str, analysis.image_pages[:30]))}{'…' if len(analysis.image_pages) > 30 else ''}.")
    if not analysis.text_pages:
        analysis.warnings.append("Dokument nie zawiera warstwy tekstowej. Do odczytu potrzebny jest OCR (planowany jako opcja).")
    flag_conflicts(analysis.suggestions)
    return analysis


def modules_of(code: str) -> int:
    total = 0
    for part in code.split("+"):
        rows, modules = part.split("x")
        total += int(rows) * int(modules)
    return total


def flag_conflicts(suggestions: list[Suggestion]):
    """Ta sama pozycja BOM (typ + kod/nazwa + specyfikacja) z różnymi ilościami = rozbieżność do sprawdzenia."""
    groups = defaultdict(set)
    for item in suggestions:
        if item.kind == "bom_line":
            base = item.key.rsplit("|", 1)[0]
            groups[base].add(item.payload["quantity"])
    for item in suggestions:
        if item.kind == "bom_line":
            quantities = groups[item.key.rsplit("|", 1)[0]]
            if len(quantities) > 1:
                item.payload["conflict"] = sorted(quantities)
                item.confidence = min(item.confidence, 0.5)
