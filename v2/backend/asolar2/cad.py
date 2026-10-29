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
MAX_POINTS = 600000               # budżet punktów SVG (ok. 10 MB) — duże rysunki są upraszczane
SVG_SIZE = 10000.0                # dłuższy bok viewBox SVG
TEXT_TYPES = ("TEXT", "MTEXT", "ATTRIB")
# Nazwy nadawane automatycznie przez AutoCAD przy kopiuj–wklej jako blok (np. „A$Cd2c4f12b”) — to nie komponenty.
AUTO_BLOCK = re.compile(r"^A\$C[0-9A-Fa-f]{8}$")


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
    installed = installed_oda()
    if installed:
        return "oda", installed
    found = shutil.which("dwg2dxf")
    if found:
        return "libredwg", found
    return None


def installed_oda() -> str | None:
    """ODA File Converter instaluje się do folderu z numerem wersji (np. „ODAFileConverter 27.9.0”) —
    domyślne wyszukiwanie ezdxf go nie znajduje. Bierzemy najnowszą wersję."""
    roots = [Path(os.environ.get(name, "")) / "ODA" for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)") if os.environ.get(name)]
    roots += [Path("/usr/bin"), Path("/opt/ODAFileConverter"), Path("/Applications/ODAFileConverter.app/Contents/MacOS")]
    candidates = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates += list(root.glob("ODAFileConverter*/ODAFileConverter.exe")) + list(root.glob("ODAFileConverter.exe")) + list(root.glob("ODAFileConverter"))
    files = [path for path in candidates if path.is_file()]
    version = lambda path: tuple(int(part) for part in re.findall(r"\d+", path.parent.name)) or (0,)
    return str(max(files, key=version)) if files else None


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
    """Plik DXF czyta ezdxf sam (kodowanie, sekcje binarne, DXF binarny). Uszkodzony plik — tryb naprawy."""
    data = dwg_to_dxf(content) if fmt == "dwg" else content
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as handle:
        handle.write(data)
        temp = handle.name
    try:
        try:
            return ezdxf.readfile(temp)
        except ezdxf.DXFStructureError:
            from ezdxf import recover
            doc, auditor = recover.readfile(temp)
            if auditor.has_errors:
                raise CadError(f"Rysunek DXF jest uszkodzony ({len(auditor.errors)} błędów struktury) — zapisz go ponownie w programie CAD.")
            return doc
    except CadError:
        raise
    except Exception as error:
        raise CadError(f"Nie udało się odczytać rysunku DXF ({type(error).__name__}: {str(error)[:200]}).") from None
    finally:
        os.unlink(temp)


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


def blocks_with_text(doc) -> set[str]:
    """Bloki, które (bezpośrednio lub przez zagnieżdżone bloki) zawierają teksty — tylko te warto rozwijać."""
    direct, children = set(), {}
    for block in doc.blocks:
        kinds = [entity.dxftype() for entity in block]
        if any(kind in ("TEXT", "MTEXT") for kind in kinds):
            direct.add(block.name)
        children[block.name] = {entity.dxf.name for entity in block if entity.dxftype() == "INSERT"}
    result, changed = set(direct), True
    while changed:
        changed = False
        for name, inner in children.items():
            if name not in result and inner & result:
                result.add(name)
                changed = True
    return result


def iter_texts(msp):
    """(tekst, warstwa, x, y, wysokość) z przestrzeni modelu, atrybutów bloków i tekstów wewnątrz bloków."""
    expanded = 0
    with_text = blocks_with_text(msp.doc)
    for entity in msp:
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT"):
            yield from _text_record(entity, entity.dxf.layer)
        elif kind == "INSERT":
            for attrib in getattr(entity, "attribs", []):
                yield from _text_record(attrib, attrib.dxf.layer or entity.dxf.layer)
            # Rozwijamy tylko bloki z tekstami (np. drzewa czy śruby bez opisu pomijamy — oszczędza czas).
            if expanded < MAX_INSERTS_EXPANDED and entity.dxf.name in with_text:
                expanded += 1
                yield from _texts_in_insert(entity, entity.dxf.layer, with_text, depth=0)


def _texts_in_insert(insert, layer, with_text, depth):
    """Teksty z wnętrza bloku, także z bloków zagnieżdżonych (np. tabliczka z numerem w bloku stołu)."""
    try:
        inner_entities = list(insert.virtual_entities())
    except Exception:
        return
    for inner in inner_entities:
        kind = inner.dxftype()
        own_layer = inner.dxf.layer if inner.dxf.layer not in ("0", "") else layer
        if kind in ("TEXT", "MTEXT"):
            yield from _text_record(inner, own_layer)
        elif kind == "INSERT" and depth < 3:
            for attrib in getattr(inner, "attribs", []):
                yield from _text_record(attrib, attrib.dxf.layer or own_layer)
            if inner.dxf.name in with_text:
                yield from _texts_in_insert(inner, own_layer, with_text, depth + 1)


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
        if not name or name.startswith("*") or name.startswith("_") or AUTO_BLOCK.match(name):
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
    """Kadr rysunku: obszar, w którym leży niemal cała zawartość. Pojedyncze obiekty daleko poza budową
    (np. punkt odniesienia w 0,0 przy współrzędnych geodezyjnych) nie mogą zmniejszyć rysunku do kropki."""
    cache = ezdxf_bbox.Cache()
    block_boxes: dict[str, object] = {}
    centers = []
    for entity in doc.modelspace():
        if entity.dxftype() == "INSERT":
            box = _insert_box(doc, entity, block_boxes, cache)
        else:
            box = ezdxf_bbox.extents([entity], fast=True, cache=cache)
        if box is not None and box.has_data:
            centers.append(((box.extmin.x + box.extmax.x) / 2, (box.extmin.y + box.extmax.y) / 2, box))
    if not centers:
        raise CadError("Rysunek nie zawiera geometrii w przestrzeni modelu.")
    if len(centers) >= 50:
        xs, ys = sorted(c[0] for c in centers), sorted(c[1] for c in centers)
        low, high = int(len(xs) * 0.005), int(len(xs) * 0.995) - 1
        core = (xs[low], ys[low], xs[high], ys[high])
        margin_x, margin_y = (core[2] - core[0]) * 0.05 or 1, (core[3] - core[1]) * 0.05 or 1
        keep = [c[2] for c in centers if core[0] - margin_x <= c[0] <= core[2] + margin_x and core[1] - margin_y <= c[1] <= core[3] + margin_y]
    else:
        keep = [c[2] for c in centers]
    min_x = min(b.extmin.x for b in keep); min_y = min(b.extmin.y for b in keep)
    max_x = max(b.extmax.x for b in keep); max_y = max(b.extmax.y for b in keep)
    if max_x - min_x <= 0 or max_y - min_y <= 0:
        raise CadError("Rysunek nie zawiera geometrii w przestrzeni modelu.")
    return min_x, min_y, max_x, max_y


def _insert_box(doc, insert, block_boxes, cache):
    """Obrys wstawienia bloku: obrys definicji bloku liczony raz na blok i przekształcony macierzą wstawienia
    (setki drzew czy śrub nie są rozwijane osobno)."""
    name = insert.dxf.name
    if name not in block_boxes:
        block = doc.blocks.get(name)
        block_boxes[name] = ezdxf_bbox.extents(block, fast=True, cache=cache) if block is not None else None
    local = block_boxes[name]
    if local is None or not local.has_data:
        return None
    try:
        matrix = insert.matrix44()
        corners = [matrix.transform((x, y, 0)) for x in (local.extmin.x, local.extmax.x) for y in (local.extmin.y, local.extmax.y)]
    except Exception:
        return None
    return ezdxf_bbox.BoundingBox(corners)


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
        tolerance = max(max_x - min_x, max_y - min_y) / 2500
        points_total = 0
        by_color: dict[str, list[str]] = defaultdict(list)
        texts = []
        count = 0
        for entity in _primitives(doc):
            if count >= MAX_PRIMITIVES or points_total >= MAX_POINTS:
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
                # Poza kadrem (odległe obiekty) — nie rysujemy.
                if all(p.x < min_x or p.x > max_x or p.y < min_y or p.y > max_y for p in points):
                    continue
                points_total += len(points)
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
