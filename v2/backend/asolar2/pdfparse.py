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

PARSER_VERSION = "3.0"
MIN_CONFIDENCE = 0.5
MAX_PAGES = 400

# --- nagłówki kolumn (porównanie po normalizacji) ------------------------------------------------
HEADERS = {
    "no": {"no", "nr", "lp", "l.p", "pos", "poz", "pozycja", "#", "n", "item", "n°", "nº"},
    "name": {"part name", "item name", "description", "opis", "nazwa", "name", "component", "komponent", "part", "element", "descrizione", "denominazione", "bezeichnung", "designation", "nome", "nome parte"},
    "code": {"item no", "itemno", "part no", "partno", "p/n", "pn", "kod", "code", "nr katalogowy", "indeks", "index", "sku", "article", "art", "codice", "codice articolo", "artikelnummer", "artikel", "drawing no", "ref"},
    "qty": {"quantities", "quantity", "qty", "q.ty", "ilość", "ilosc", "szt", "pcs", "quantità", "quantita", "q.tà", "menge", "anzahl", "amount", "number", "liczba", "numero", "total qty", "qty total", "actual total qty"},
    "unit": {"unit", "jm", "j.m", "uom", "unità", "unita", "einheit"},
    "spec": {"spec", "specification", "specyfikacja", "wymiar", "wymiary", "dimension", "dimensions", "size", "specifiche", "abmessung", "model"},
    "remark": {"remark", "remarks", "uwagi", "note", "notes", "note/remark", "bemerkung"},
    "material": {"material", "materiał", "materials", "grade", "gatunek", "werkstoff", "materiale"},
}
# Kolejność ważności kolumny nazwy, gdy tabela ma kilka kandydatów (np. „Part Name” i „Description”).
NAME_PRIORITY = ["part name", "item name", "nazwa", "name", "description", "opis", "descrizione", "denominazione", "bezeichnung", "designation", "nome", "nome parte", "component", "komponent", "part", "element"]
# Kolumna ilości na jeden stół danego typu, np. „QTY per 2*26Array”, „Ilość na 1x28”.
PER_TYPE_HEADER = re.compile(r"^(?:qty|q\.?ty|quantity|quantit\w*|ilo\w*|menge|number|liczba)\s*(?:per|na|/|pro|for)\s*(.+)$", re.I)
TYPE_IN_HEADER = re.compile(r"(?<!\d)([1-4])\s*[*xX×Pp]\s*(\d{1,3})(?:\s*\+\s*(?:([1-4])\s*[*xX×Pp]\s*)?(\d{1,3}))?(?!\d)")
# Liczba stołów danego typu, np. „Number of array”, „Liczba stołów”.
COUNT_HEADER = re.compile(r"^(?:number|no\.?|qty|quantity|liczba|ilo\w*|numero|anzahl)\s*(?:of\s*)?(?:arrays?|tables?|trackers?|structures?|stołów|stolow|konstrukcji|strutture|tavoli|units?)$", re.I)
IGNORED_HEADER = re.compile(r"(weight|waga|peso|gewicht|rate|%|spare|zapas|ricambi|coating|anti-?corrosion|powłok)", re.I)
NOT_NUMBERING = {"M"}  # M10, M16… to rozmiary śrub, nie numery stołów
ELECTRICAL_PREFIXES = {"INV", "MPPT", "CB", "SB", "QE", "QF", "DC", "AC", "STR", "CAB", "QG", "TR-E"}
ADDRESS_CUES = re.compile(r"\b(co\.|ltd|road|street|province|city|economic|development|technological|ul\.|tel\.?|e-?mail|www\.)", re.I)
TYPE_PATTERN = re.compile(r"(?<![\w.×*])([1-4])\s*[PpXx×]\s*(\d{2,3})(?:\s*\+\s*(?:([1-4])\s*[PpXx×]\s*)?(\d{2,3}))?(?![\w.]|\s*[x×*]\s*\d)")
ZONE_PATTERN = re.compile(r"\b(Strefa|Strefy|Zone|Zona|Sektor|Sector|Field|Pole|Area|Obszar|Blok|Block|Campo|Sottocampo|Sottosistema)\s+([A-Z]{1,2}\d{0,2}|\d{1,3}|[IVX]{1,4})\b")
CODE_TOKEN = re.compile(r"^([A-Za-z]{1,4})[-_.]?(\d{1,4})$")
TORQUE_PATTERN = re.compile(r"\b(M\d{1,2})\b[^\n]{0,90}?(\d{1,4}(?:[.,]\d+)?)\s*(?:[-–~÷]\s*(\d{1,4}(?:[.,]\d+)?))?\s*\(?\s*N[·.\s]?m\b")
ITEM_CODE = re.compile(r"^[A-Z]{1,5}\d*[-_][\w.-]+$|^[A-Z]{2,}\d{2,}[\w.-]*$")
DIMENSION = re.compile(r"[\d.,]+\s*[x×*]\s*[\d.,]+|^[A-Z]?\d+[x×*]\d")


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def header_kind(cell: str) -> str | None:
    text = norm(cell).lower().rstrip(".:").replace("º", "").replace("°", "")
    if not text or IGNORED_HEADER.search(text):
        return None
    if COUNT_HEADER.match(text):
        return "count"
    if PER_TYPE_HEADER.match(text) and TYPE_IN_HEADER.search(text):
        return "per_type"
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


def header_type(cell: str) -> str | None:
    match = TYPE_IN_HEADER.search(norm(cell))
    return normalize_type(match) if match else None


def find_header(rows: list[list[str]]) -> tuple[int, dict] | None:
    """Wiersz nagłówka i mapowanie kolumn. Klucz „per_type” = lista (kolumna, typ, kolumna liczby stołów)."""
    for index, row in enumerate(rows[:6]):
        mapping: dict = {}
        names = []
        per_type = []
        for column, cell in enumerate(row):
            kind = header_kind(cell)
            if kind == "name":
                names.append((NAME_PRIORITY.index(norm(cell).lower().rstrip(".:")) if norm(cell).lower().rstrip(".:") in NAME_PRIORITY else 99, column))
            elif kind == "per_type":
                per_type.append([column, header_type(cell), None])
            elif kind == "count":
                # Liczba stołów należy do najbliższej kolumny „ilość na typ” po lewej.
                for entry in reversed(per_type):
                    if entry[2] is None and entry[0] < column:
                        entry[2] = column
                        break
            elif kind == "qty":
                mapping.setdefault("qty_all", []).append(column)
                mapping.setdefault("qty", column)
            elif kind and kind not in mapping:
                mapping[kind] = column
        if names:
            mapping["name"] = min(names)[1]
        if per_type:
            mapping["per_type"] = per_type
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


def bom_key(group: str, no: str, name: str, code: str, spec: str, qty: float) -> str:
    # Numer pozycji w kluczu: ta sama śruba użyta w różnych miejscach (inne pozycje BOM) to nie „rozbieżność”.
    return f"bom|{group.lower()}|{no}|{(code or name).lower()}|{spec.lower()}|{qty:g}"


def bom_from_table(rows: list[list[str]], page: int, group: str | None, caption: str) -> list[Suggestion]:
    header = find_header(rows)
    if not header:
        return []
    start, mapping = header
    per_type = [entry for entry in mapping.get("per_type", []) if entry[1]]
    result = []
    counts: dict[str, Counter] = defaultdict(Counter)
    carried = ""
    for row in rows[start + 1:]:
        cell = lambda column: row[column] if column is not None and column < len(row) else ""
        get = lambda kind: cell(mapping.get(kind)) if kind in mapping else ""
        name, code, spec, unit, material, no = get("name"), get("code"), get("spec"), get("unit"), get("material"), get("no")
        if header_kind(name) or header_kind(spec):
            continue
        no = no if re.fullmatch(r"\d{1,4}", no or "") else ""
        if name:
            carried = name
        elif spec and carried and (no or per_type):
            # Komórka scalona w PDF (np. „Purlin fixing bolts” dla śruby, podkładki i nakrętki) — nazwa z wiersza wyżej.
            name = carried
        if not name:
            continue
        code = "" if code in ("/", "-", "—") else code
        excerpt = " | ".join(value for value in row if value)[:240]
        base = {"name": name, "code": code, "spec": spec, "unit": unit or "szt.", "caption": caption}
        if material:
            base["material"] = material
        if no:
            base["position"] = no
        if per_type:
            totals = [parse_number(cell(column)) for column in mapping.get("qty_all", [])]
            lines, expected = [], 0.0
            for column, type_code, count_column in per_type:
                qty = parse_number(cell(column))
                tables = parse_number(cell(count_column)) if count_column is not None else None
                if tables:
                    counts[type_code][tables] += 1
                if qty:
                    lines.append((type_code, qty))
                    expected += qty * (tables or 0)
            # Kontrola: ilość na stół × liczba stołów = kolumna ilości całkowitej (bez zapasu) → wysoka pewność.
            verified = bool(lines) and any(total is not None and abs(total - expected) < 0.5 for total in totals)
            for type_code, qty in lines:
                payload = {**base, "quantity": qty, "group": type_code, "per_table": True}
                if totals and not verified:
                    payload["check"] = f"ilość na stół × liczba stołów = {expected:g}, a w kolumnie ilości: {', '.join(f'{t:g}' for t in totals if t is not None)}"
                result.append(Suggestion("bom_line", bom_key(type_code, no, name, code, spec, qty), payload, page, excerpt, 0.95 if verified else 0.7))
            continue
        qty = parse_number(get("qty")) if "qty" in mapping else None
        if qty is not None:
            payload = {**base, "quantity": qty, "group": group or ""}
            result.append(Suggestion("bom_line", bom_key(group or "", no, name, code, spec, qty), payload, page, excerpt, 0.9 if code or spec else 0.8))
        elif "qty" not in mapping:
            key = f"component|{(code or name).lower()}|{spec.lower()}"
            result.append(Suggestion("component", key, {"name": name, "code": code, "spec": spec}, page, excerpt, 0.7))
    # Typy konstrukcji z nagłówków tabeli, z liczbą stołów odczytaną z kolumny „Number of …”.
    for column, type_code, _count_column in per_type:
        tables = counts[type_code].most_common(1)[0][0] if counts[type_code] else None
        payload = {"code": type_code, "occurrences": 1, "modules": modules_of(type_code)}
        if tables:
            payload["tables"] = int(tables)
        excerpt = f"Kolumna „{norm(rows[start][column])}”" + (f", liczba stołów: {int(tables)}" if tables else "")
        result.append(Suggestion("structure_type", f"type|{type_code}", payload, page, excerpt, 0.9 if tables else 0.7))
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
            analysis.suggestions.extend(page_bom)
            scan_text(text, number, types, type_pages, zones, zone_pages, torques)
            for word in page.extract_words():
                match = CODE_TOKEN.match(word["text"])
                if match:
                    codes[match.group(1).upper()].append((int(match.group(2)), number, word["text"]))
    from_tables = {item.payload["code"] for item in analysis.suggestions if item.kind == "structure_type"}
    for value, count in types.items():
        if value in from_tables:
            continue
        pages = sorted(type_pages[value])
        confidence = 0.85 if count >= 3 else 0.6 if count == 2 else 0.4
        analysis.suggestions.append(Suggestion("structure_type", f"type|{value}", {"code": value, "occurrences": count, "modules": modules_of(value)}, pages[0], f"„{value}” występuje {count}× (strony {', '.join(map(str, pages[:8]))})", confidence))
    item_names = {item.payload["name"].strip().lower() for item in analysis.suggestions if item.kind in ("bom_line", "component", "tool")}
    for name, count in zones.items():
        if name.lower() in item_names:
            analysis.warnings.append(f"„{name}” pominięto jako strefę — to nazwa pozycji w tabeli materiałów.")
            continue
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
    # Bez zgadywania: propozycje o niskiej pewności (np. typ wspomniany raz w tekście) pomijamy.
    analysis.suggestions = [item for item in analysis.suggestions if item.confidence >= MIN_CONFIDENCE or "conflict" in item.payload]
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
