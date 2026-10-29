"""Rysunki CAD (DXF, DWG): teksty z warstw, zliczone bloki, geometria do Planimetrii.

DXF czytamy bezpośrednio (ezdxf). DWG to zamknięty format binarny — najpierw zamieniamy go na DXF
zewnętrznym konwerterem, w kolejności:
  1. ASOLAR_DWG_CONVERTER — szablon polecenia z {input} i {output}, np.  dwg2dxf -y -o {output} {input}
  2. ODA File Converter (bezpłatny, Open Design Alliance) — wykrywany przez ezdxf.addons.odafc lub PATH,
  3. LibreDWG „dwg2dxf” w PATH.
Bez konwertera dokument dostaje czytelny komunikat (zapisz jako DXF albo zainstaluj konwerter) —
aplikacja nie udaje, że odczytała rysunek. Wyniki trafiają do tego samego ekranu propozycji co PDF.
"""
from __future__ import annotations

import io
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf import path as ezdxf_path
from ezdxf.colors import aci2rgb

from . import plans
from .pdfparse import CODE_TOKEN, Analysis, Suggestion, modules_of, numbering_suggestions, scan_text

CAD_FORMATS = {".dwg": "dwg", ".dxf": "dxf"}
DWG_MAGIC = re.compile(rb"^AC10\d\d")
CONVERT_TIMEOUT = 180
MAX_INSERTS_EXPANDED = 20000      # rozwijanie bloków (teksty i geometria wewnątrz) — ochrona przed ogromnymi rysunkami
MAX_PRIMITIVES = 250000
SVG_SIZE = 10000.0                # dłuższy bok viewBox SVG
TEXT_TYPES = ("TEXT", "MTEXT", "ATTRIB")


class CadError(Exception):
    """Rysunku nie da się odczytać — komunikat dla użytkownika."""


def detect_format(filename: str, content: bytes) -> str:
    """pdf | dwg | dxf | '' (nieobsługiwany)."""
    head = content[:2048]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if DWG_MAGIC.match(head):
        return "dwg"
    if head.startswith(b"AutoCAD Binary DXF"):
        return "dxf"
    text = head.decode("latin-1", errors="ignore")
    if re.match(r"^\s*(?:999\s*\n.*\n\s*)?0\s*\r?\n\s*SECTION", text, re.S):
        return "dxf"
    return ""


def format_of(filename: str) -> str:
    return CAD_FORMATS.get(Path(filename or "").suffix.lower(), "pdf")


# --- konwersja DWG → DXF ------------------------------------------------------------------------

def find_converter() -> tuple[str, list[str] | str] | None:
    """(rodzaj, polecenie) albo None. Rodzaj: template | oda | libredwg."""
    template = os.getenv("ASOLAR_DWG_CONVERTER", "").strip()
    if template:
        return "template", template
    try:
        from ezdxf.addons import odafc
        if odafc.is_installed():
            return "oda", "ezdxf-odafc"
    except Exception:
        pass
    for name in ("ODAFileConverter", "ODAFileConverter.exe"):
        found = shutil.which(name)
        if found:
            return "oda", found
    found = shutil.which("dwg2dxf")
    if found:
        return "libredwg", found
    return None


MISSING_CONVERTER = ("Plik DWG wymaga konwertera, którego nie ma na tym serwerze. Najprościej: w AutoCAD/DWG TrueView "
                     "zapisz rysunek jako DXF (Zapisz jako → DXF) i wgraj plik .dxf. Albo zainstaluj bezpłatny ODA File Converter "
                     "(Open Design Alliance) lub LibreDWG (dwg2dxf) i przeanalizuj dokument ponownie.")


def dwg_to_dxf(content: bytes) -> bytes:
    converter = find_converter()
    if converter is None:
        raise CadError(MISSING_CONVERTER)
    kind, command = converter
    with tempfile.TemporaryDirectory(prefix="asolar2-dwg-") as folder:
        source_dir, target_dir = Path(folder, "in"), Path(folder, "out")
        source_dir.mkdir(); target_dir.mkdir()
        source, target = source_dir / "rysunek.dwg", target_dir / "rysunek.dxf"
        source.write_bytes(content)
        try:
            if kind == "oda" and command == "ezdxf-odafc":
                from ezdxf.addons import odafc
                odafc.convert(str(source), str(target), version="R2018", replace=True)
            else:
                if kind == "template":
                    args = [part.replace("{input}", str(source)).replace("{output}", str(target)) for part in shlex.split(command.replace("\\", "/"))]
                elif kind == "oda":
                    args = [command, str(source_dir), str(target_dir), "ACAD2018", "DXF", "0", "1", "*.DWG"]
                else:
                    args = [command, "-y", "-o", str(target), str(source)]
                result = subprocess.run(args, capture_output=True, timeout=CONVERT_TIMEOUT, check=False)
                if not target.exists():
                    detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")[-400:]
                    raise CadError(f"Konwerter DWG nie utworzył pliku DXF (kod {result.returncode}). {detail}".strip())
        except subprocess.TimeoutExpired:
            raise CadError(f"Konwersja DWG trwała dłużej niż {CONVERT_TIMEOUT} s i została przerwana.") from None
        except CadError:
            raise
        except Exception as error:
            raise CadError(f"Konwersja DWG nie powiodła się ({type(error).__name__}: {str(error)[:200]}).") from None
        if not target.exists():
            raise CadError("Konwerter DWG nie utworzył pliku DXF.")
        return target.read_bytes()


def load_document(content: bytes, fmt: str):
    data = dwg_to_dxf(content) if fmt == "dwg" else content
    try:
        if data.startswith(b"AutoCAD Binary DXF"):
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as handle:
                handle.write(data)
                temp = handle.name
            try:
                return ezdxf.readfile(temp)
            finally:
                os.unlink(temp)
        return ezdxf.read(io.StringIO(data.decode(_encoding(data), errors="replace")))
    except CadError:
        raise
    except Exception as error:
        raise CadError(f"Nie udało się odczytać rysunku DXF ({type(error).__name__}: {str(error)[:200]}).") from None


def _encoding(data: bytes) -> str:
    match = re.search(rb"\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*(\S+)", data[:20000])
    version = re.search(rb"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*AC(\d{4})", data[:20000])
    if version and int(version.group(1)) >= 1021:
        return "utf-8"  # od AutoCAD 2007 DXF jest w UTF-8
    codepage = match.group(1).decode().lower() if match else ""
    return {"ansi_1250": "cp1250", "ansi_1252": "cp1252", "ansi_1251": "cp1251"}.get(codepage, "utf-8")


def cached_document(sha: str, content: bytes, fmt: str):
    """Konwersja DWG i parsowanie są kosztowne — wynik trzymamy w tej samej pamięci podręcznej co strony PDF."""
    return plans._cached(("cad", sha), lambda: load_document(content, fmt))


# --- teksty, bloki ------------------------------------------------------------------------------

def _text_of(entity) -> str:
    try:
        if entity.dxftype() == "MTEXT":
            return entity.plain_text()
        return entity.dxf.text or ""
    except Exception:
        return ""


def iter_texts(msp):
    """(tekst, warstwa, x, y, wysokość) z przestrzeni modelu, atrybutów bloków i tekstów wewnątrz bloków."""
    expanded = 0
    for entity in msp:
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT"):
            yield from _text_record(entity, entity.dxf.layer)
        elif kind == "INSERT":
            for attrib in getattr(entity, "attribs", []):
                yield from _text_record(attrib, attrib.dxf.layer or entity.dxf.layer)
            if expanded < MAX_INSERTS_EXPANDED:
                expanded += 1
                try:
                    for inner in entity.virtual_entities():
                        if inner.dxftype() in ("TEXT", "MTEXT"):
                            layer = inner.dxf.layer if inner.dxf.layer not in ("0", "") else entity.dxf.layer
                            yield from _text_record(inner, layer)
                except Exception:
                    continue


def _text_record(entity, layer):
    value = re.sub(r"\s+", " ", _text_of(entity)).strip()
    if not value:
        return
    try:
        point = entity.dxf.insert
        height = float(entity.dxf.char_height if entity.dxftype() == "MTEXT" else entity.dxf.height) or 1.0
    except Exception:
        return
    yield value, layer or "0", float(point.x), float(point.y), height


def block_counts(doc) -> list[dict]:
    """Bloki wstawione w przestrzeni modelu: nazwa, liczba, warstwy. Bez bloków anonimowych i odnośników zewnętrznych."""
    counts, layers = Counter(), defaultdict(Counter)
    for insert in doc.modelspace().query("INSERT"):
        name = insert.dxf.name
        if not name or name.startswith("*") or name.startswith("_"):
            continue
        block = doc.blocks.get(name)
        if block is not None and (block.block.is_xref or block.block.is_xref_overlay):
            continue
        counts[name] += 1
        layers[name][insert.dxf.layer] += 1
    return [{"name": name, "count": count, "layers": [layer for layer, _ in layers[name].most_common(3)]} for name, count in counts.most_common()]


def analyze_cad(content: bytes, filename: str) -> Analysis:
    fmt = detect_format(filename, content) or format_of(filename)
    analysis = Analysis(pages=1)
    doc = load_document(content, fmt)
    msp = doc.modelspace()
    types, zones = Counter(), Counter()
    type_pages, zone_pages = defaultdict(set), defaultdict(set)
    torques: list[Suggestion] = []
    codes: dict[str, list] = defaultdict(list)
    code_layers: dict[str, Counter] = defaultdict(Counter)
    lines = []
    for value, layer, _x, _y, _h in iter_texts(msp):
        lines.append(value)
        match = CODE_TOKEN.match(value)
        if match:
            prefix = match.group(1).upper()
            codes[prefix].append((int(match.group(2)), 1, value))
            code_layers[prefix][layer] += 1
    if lines:
        analysis.text_pages = 1
    scan_text("\n".join(lines), 1, types, type_pages, zones, zone_pages, torques)
    for item in numbering_suggestions(codes, analysis):
        layers = [layer for layer, _ in code_layers[item.payload["prefix"]].most_common(3)]
        item.payload["layers"] = layers
        item.excerpt = f"{item.payload['count']} oznaczeń {item.payload['prefix']} (np. {item.payload['example']}) na warstwach: {', '.join(layers)}"
        analysis.suggestions.append(item)
    for value, count in types.items():
        analysis.suggestions.append(Suggestion("structure_type", f"type|{value}", {"code": value, "occurrences": count, "modules": modules_of(value)}, 1,
                                               f"„{value}” występuje {count}× w tekstach rysunku", 0.85 if count >= 3 else 0.6 if count == 2 else 0.4))
    for name, count in zones.items():
        analysis.suggestions.append(Suggestion("zone", f"zone|{name.lower()}", {"name": name, "occurrences": count}, 1, f"„{name}” występuje {count}× w tekstach rysunku", 0.8 if count >= 2 else 0.55))
    seen = set()
    for item in torques:
        if item.key not in seen:
            seen.add(item.key)
            analysis.suggestions.append(item)
    for block in block_counts(doc):
        payload = {"name": block["name"], "count": block["count"], "layers": block["layers"]}
        analysis.suggestions.append(Suggestion("drawing_block", f"block|{block['name'].lower()}", payload, 1,
                                               f"Blok „{block['name']}” wstawiony {block['count']}× (warstwy: {', '.join(block['layers'])})", 0.6))
    if not lines:
        analysis.warnings.append("Rysunek nie zawiera tekstów (TEXT/MTEXT/atrybutów) — numeracji i stref nie da się odczytać.")
    if not any(item.kind == "drawing_block" for item in analysis.suggestions):
        analysis.warnings.append("W przestrzeni modelu nie ma nazwanych bloków do zliczenia.")
    return analysis


# --- Planimetria: geometria i położenie oznaczeń ---------------------------------------------------

def _extents(doc):
    box = ezdxf_bbox.extents(doc.modelspace(), fast=True)
    if not box.has_data or box.size.x <= 0 or box.size.y <= 0:
        raise CadError("Rysunek nie zawiera geometrii w przestrzeni modelu.")
    return box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y


def plan_info(sha: str, content: bytes, fmt: str) -> dict:
    """Ten sam kształt co plans.page_info dla PDF: wymiary i kody (0..1 względem obrazu)."""
    def build():
        doc = cached_document(sha, content, fmt)
        min_x, min_y, max_x, max_y = _extents(doc)
        width, height = max_x - min_x, max_y - min_y
        codes = []
        for value, _layer, x, y, h in iter_texts(doc.modelspace()):
            code = plans.normalize_code(value)
            if not code:
                continue
            w = max(len(value) * h * 0.6, h)
            codes.append({"code": code, "x": (x - min_x) / width, "y": (max_y - (y + h)) / height, "w": w / width, "h": h / height})
        return {"pages": 1, "width": width, "height": height, "has_text": bool(codes), "codes": codes}
    return plans._cached(("cad-info", sha), build)


def _color(doc, entity) -> str:
    try:
        color = entity.dxf.color
        if color in (0, 256):  # BYBLOCK / BYLAYER
            color = doc.layers.get(entity.dxf.layer).color
        r, g, b = aci2rgb(abs(color) if 0 < abs(color) < 256 else 7)
        if r > 230 and g > 230 and b > 230:  # biały na białym tle → ciemny szary
            return "#333"
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#333"


def _primitives(doc):
    """Encje do narysowania; wstawienia bloków rozwijane (do limitu)."""
    expanded = 0
    for entity in doc.modelspace():
        if entity.dxftype() == "INSERT":
            if expanded >= MAX_INSERTS_EXPANDED:
                continue
            expanded += 1
            try:
                for inner in entity.virtual_entities():
                    if inner.dxftype() == "INSERT":
                        try:
                            yield from inner.virtual_entities()
                        except Exception:
                            continue
                    else:
                        if inner.dxf.layer in ("0", ""):
                            inner.dxf.layer = entity.dxf.layer
                        yield inner
            except Exception:
                continue
        else:
            yield entity


def render_svg(sha: str, content: bytes, fmt: str) -> bytes:
    def build():
        doc = cached_document(sha, content, fmt)
        min_x, min_y, max_x, max_y = _extents(doc)
        scale = SVG_SIZE / max(max_x - min_x, max_y - min_y)
        view_w, view_h = (max_x - min_x) * scale, (max_y - min_y) * scale
        tolerance = max(max_x - min_x, max_y - min_y) / 4000
        by_color: dict[str, list[str]] = defaultdict(list)
        texts = []
        count = 0
        for entity in _primitives(doc):
            if count >= MAX_PRIMITIVES:
                break
            kind = entity.dxftype()
            if kind in ("TEXT", "MTEXT"):
                for value, _layer, x, y, h in _text_record(entity, entity.dxf.layer):
                    size = h * scale
                    if size >= 2:
                        texts.append(f'<text x="{(x - min_x) * scale:.1f}" y="{(max_y - y) * scale:.1f}" font-size="{size:.1f}" fill="{_color(doc, entity)}">{_escape(value[:80])}</text>')
                continue
            try:
                path = ezdxf_path.make_path(entity)
            except Exception:
                continue
            for sub in path.sub_paths() if path.has_sub_paths else [path]:
                points = list(sub.flattening(tolerance))
                if len(points) < 2:
                    continue
                coords = " L".join(f"{(p.x - min_x) * scale:.1f},{(max_y - p.y) * scale:.1f}" for p in points)
                by_color[_color(doc, entity)].append(f"M{coords}")
                count += 1
        groups = []
        for color, paths in by_color.items():
            d = " ".join(paths)
            groups.append(f'<path d="{d}" stroke="{color}" fill="none" stroke-width="{max(view_w, view_h) / 2500:.2f}" vector-effect="non-scaling-stroke"/>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.1f} {view_h:.1f}" width="{view_w:.0f}" height="{view_h:.0f}">'
               f'<rect width="100%" height="100%" fill="#fff"/>{"".join(groups)}<g font-family="Arial, sans-serif">{"".join(texts)}</g></svg>')
        return svg.encode("utf-8")
    return plans._cached(("cad-svg", sha), build)


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
