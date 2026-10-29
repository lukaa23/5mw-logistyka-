"""Etap 3: zatwierdzone propozycje zasilają strukturę budowy (strefy, typy, BOM, stoły, katalog, momenty).

Zasada: nic nie powstaje bez zatwierdzenia kierownika i nic nie jest dopowiadane. Brakujące dane
(np. liczba słupów na stół, typ stołu) zostają puste i są pokazywane jako „wymaga potwierdzenia”.
Każdy rekord utworzony z propozycji pamięta jej id — cofnięcie decyzji usuwa go, o ile nie jest
już używany (wtedy serwer odmawia z wyjaśnieniem, zamiast po cichu kasować przypisania).
"""
import re
from collections import defaultdict

from sqlalchemy import func, or_, select

from .imports import loads
from .tenancy import BomItem, CatalogItem, Photo, ProjectEvent, SiteRow, SiteTable, StructureType, Suggestion, TableNote, TorqueSpec, Zone

MAX_TABLES_FROM_NUMBERING = 5000
TYPE_CODE = re.compile(r"^([1-4])x(\d{1,3})(?:\+([1-4])x(\d{1,3}))?$")


class ApplyError(Exception):
    """Propozycji nie da się zastosować / cofnąć — komunikat dla kierownika."""


def normalize_type_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower().replace("×", "x").replace("p", "x")


def modules_of(code: str) -> int:
    match = TYPE_CODE.match(code)
    if not match:
        return 0
    total = int(match.group(1)) * int(match.group(2))
    if match.group(4):
        total += int(match.group(3) or 1) * int(match.group(4))
    return total


def material_key(code: str, name: str, spec: str, unit: str) -> str:
    """Stały klucz materiału: kod (albo nazwa) + specyfikacja + jednostka, bez wielkości liter.
    Wiąże pozycje WZ z zapotrzebowaniem niezależnie od typu konstrukcji."""
    ident = (code or "").strip().lower() or (name or "").strip().lower()
    return f"{ident}|{(spec or '').strip().lower()}|{(unit or 'szt.').strip().lower()}"[:400]


def table_code(prefix: str, number: int) -> str:
    return f"{prefix.strip().upper()}-{int(number)}"


def same_item(model, code: str, name: str, spec: str):
    """Ta sama pozycja: zgodny kod (gdy jest) albo nazwa, oraz ta sama specyfikacja (bez wielkości liter)."""
    identity = func.lower(model.code) == code.lower() if code else func.lower(model.name) == name.lower()
    return identity, func.lower(model.spec) == spec.lower()


def find_same_bom(session, type_id: int, code: str, name: str, spec: str):
    """Ta sama pozycja BOM w typie. Bez specyfikacji (np. tabela w instrukcji) porównujemy po nazwie —
    inaczej „Pole 1” z instrukcji i „Pole 1 / C120…” z BOM policzyłyby się dwa razy."""
    if code:
        return session.scalar(select(BomItem).where(BomItem.structure_type_id == type_id, func.lower(BomItem.code) == code.lower()))
    same_name = session.scalars(select(BomItem).where(BomItem.structure_type_id == type_id, func.lower(BomItem.name) == name.lower())).all()
    if spec:
        exact = [b for b in same_name if b.spec.lower() == spec.lower()]
        if exact:
            return exact[0]
        unspecified = [b for b in same_name if not b.spec]
        return unspecified[0] if unspecified else None
    if len(same_name) > 1:
        raise ApplyError(f"Typ ma kilka pozycji „{name}” różniących się specyfikacją — uzupełnij specyfikację (Popraw), żeby wskazać właściwą")
    return same_name[0] if same_name else None


def get_or_create_type(session, code: str, modules: int = 0, source_id: int | None = None) -> StructureType:
    code = normalize_type_code(code)
    item = session.scalar(select(StructureType).where(StructureType.code == code))
    if item is None:
        item = StructureType(code=code, modules=modules or modules_of(code), source_suggestion_id=source_id)
        session.add(item)
        session.flush()
    elif not item.modules and (modules or modules_of(code)):
        item.modules = modules or modules_of(code)
    return item


# --- zastosowanie zatwierdzonej propozycji -------------------------------------------------------

def apply_suggestion(session, item: Suggestion, user_id: int | None, confirm_only: bool = False) -> str:
    """Najpierw walidacja (ApplyError przed jakimkolwiek zapisem), potem zapis. Zwraca applied_ref."""
    p = loads(item.payload_json, {})
    kind = item.kind
    if kind == "zone":
        name = str(p.get("name", "")).strip()
        if not name:
            raise ApplyError("Strefa bez nazwy")
        zone = session.scalar(select(Zone).where(func.lower(Zone.name) == name.lower()))
        if zone is None:
            order = (session.scalar(select(func.max(Zone.sort_order))) or 0) + 1
            zone = Zone(name=name, description="Z dokumentów PDF (zatwierdzona propozycja)", sort_order=order, created_by=user_id, source_suggestion_id=item.id)
            session.add(zone)
            session.flush()
            session.add(ProjectEvent(user_id=user_id, action="create", entity="zone", entity_id=zone.id, details=f"{name} (z propozycji PDF)"))
        return f"zone:{zone.id}"

    if kind == "structure_type":
        code = normalize_type_code(p.get("code", ""))
        if not code:
            raise ApplyError("Typ konstrukcji bez oznaczenia")
        structure = get_or_create_type(session, code, int(p.get("modules") or 0), item.id)
        if structure.source_suggestion_id is None:
            # Typ utworzony wcześniej pośrednio (przez pozycję BOM) — teraz zatwierdzony wprost.
            structure.source_suggestion_id = item.id
        if p.get("tables"):
            structure.planned_tables = int(p["tables"])
        return f"type:{structure.id}"

    if kind == "bom_line":
        group = normalize_type_code(p.get("group", ""))
        name, code, spec = str(p.get("name", "")).strip(), str(p.get("code", "")).strip(), str(p.get("spec", "")).strip()
        if not group:
            raise ApplyError(f"„{name}”: brak typu konstrukcji — uzupełnij pole „Typ konstrukcji” (Popraw), żeby wiedzieć, do którego stołu należy ilość")
        if p.get("quantity") is None:
            raise ApplyError(f"„{name}”: brak ilości")
        structure = session.scalar(select(StructureType).where(StructureType.code == group))
        if structure is not None:
            clash = find_same_bom(session, structure.id, code, name, spec)
            if clash is not None and clash.source_suggestion_id != item.id:
                if abs(clash.quantity - float(p["quantity"])) < 1e-9:
                    # To samo z innego dokumentu (np. BOM i instrukcja) — potwierdzenie, nie druga pozycja.
                    return f"bom:{clash.id}"
                raise ApplyError(f"Typ {group} ma już pozycję „{clash.name}”{f' ({clash.spec})' if clash.spec else ''} w ilości {clash.quantity:g} {clash.unit} na stół, "
                                 f"a ta propozycja podaje {float(p['quantity']):g}. Odrzuć jedną z wersji albo popraw istniejącą pozycję w zakładce „Konstrukcje i BOM”.")
            if clash is not None:
                return f"bom:{clash.id}"
        if confirm_only:
            # Pozycja bez typu przypisana zbiorczo do typu, który ma już BOM: tylko potwierdza istniejące pozycje.
            # Dodanie jej pod inną nazwą policzyłoby ten sam materiał dwa razy.
            raise ApplyError(f"„{name}”{f' ({spec})' if spec else ''} nie występuje w BOM typu {group} — nie dodano, żeby nie liczyć materiału dwa razy. "
                             "Jeśli to brakujący materiał, popraw nazwę na zgodną z BOM albo dodaj pozycję ręcznie w „Konstrukcje i BOM”.")
        structure = structure or get_or_create_type(session, group)
        bom = BomItem(structure_type_id=structure.id, name=name, code=code, spec=spec, quantity=float(p["quantity"]), unit=str(p.get("unit") or "szt."), source_suggestion_id=item.id)
        session.add(bom)
        session.flush()
        return f"bom:{bom.id}"

    if kind in ("component", "tool"):
        name, code, spec = str(p.get("name", "")).strip(), str(p.get("code", "")).strip(), str(p.get("spec", "")).strip()
        identity, same_spec = same_item(CatalogItem, code, name, spec)
        existing = session.scalar(select(CatalogItem).where(CatalogItem.kind == kind, identity, same_spec))
        if existing is None:
            existing = CatalogItem(kind=kind, name=name, code=code, spec=spec, source_suggestion_id=item.id)
            session.add(existing)
            session.flush()
        return f"catalog:{existing.id}"

    if kind == "drawing_block":
        # Blok z rysunku CAD: liczba wstawień w całym rysunku (nie „na stół”) — trafia do katalogu jako ilość kontrolna.
        name, count = str(p.get("name", "")).strip(), p.get("count")
        if not name or count is None:
            raise ApplyError("Blok z rysunku bez nazwy lub liczby")
        existing = session.scalar(select(CatalogItem).where(CatalogItem.kind == "block", func.lower(CatalogItem.name) == name.lower()))
        layers = ", ".join(p.get("layers") or [])
        if existing is None:
            existing = CatalogItem(kind="block", name=name, spec=layers[:160], quantity=float(count), source_suggestion_id=item.id)
            session.add(existing)
            session.flush()
        elif existing.source_suggestion_id != item.id and existing.quantity != float(count):
            raise ApplyError(f"Blok „{name}” jest już w katalogu z liczbą {existing.quantity:g} (inny rysunek). Odrzuć jedną z wersji.")
        return f"catalog:{existing.id}"

    if kind == "torque":
        bolt, low, high = str(p.get("bolt", "")).strip().upper(), float(p.get("min_nm") or 0), float(p.get("max_nm") or 0)
        if not bolt or low <= 0 or high < low:
            raise ApplyError("Moment dokręcania: podaj śrubę oraz zakres min ≤ max")
        existing = session.scalar(select(TorqueSpec).where(TorqueSpec.bolt == bolt, TorqueSpec.min_nm == low, TorqueSpec.max_nm == high))
        if existing is None:
            existing = TorqueSpec(bolt=bolt, min_nm=low, max_nm=high, context=str(p.get("context", "")), source_suggestion_id=item.id)
            session.add(existing)
            session.flush()
        return f"torque:{existing.id}"

    if kind == "numbering":
        prefix = str(p.get("prefix", "")).strip().upper()
        first, last = int(p.get("first") or 0), int(p.get("last") or 0)
        if not prefix or first < 0 or last < first:
            raise ApplyError("Numeracja: podaj prefiks i zakres od ≤ do")
        # Tworzymy tylko numery odczytane z dokumentu: luki w zakresie (missing) nie są dopowiadane.
        missing = {int(value) for value in p.get("missing") or []}
        numbers = [number for number in range(first, last + 1) if number not in missing]
        if len(numbers) > MAX_TABLES_FROM_NUMBERING:
            raise ApplyError(f"Zakres obejmuje {len(numbers)} stołów — maksymalnie {MAX_TABLES_FROM_NUMBERING} naraz")
        codes = {table_code(prefix, number): number for number in numbers}
        existing = set(session.scalars(select(SiteTable.code).where(SiteTable.code.in_(list(codes) or [""]))).all())
        for code, number in codes.items():
            if code not in existing:
                session.add(SiteTable(code=code, prefix=prefix, number=number, source_suggestion_id=item.id))
        session.flush()
        return f"tables:{prefix}:{len(codes) - len(existing)}"

    raise ApplyError(f"Nieznany rodzaj propozycji: {kind}")


# --- cofnięcie decyzji ---------------------------------------------------------------------------

def revert_suggestion(session, item: Suggestion):
    """Usuwa rekordy utworzone z tej propozycji, jeśli nic z nich nie korzysta."""
    sid = item.id
    if item.kind == "zone":
        zone = session.scalar(select(Zone).where(Zone.source_suggestion_id == sid))
        if zone is not None:
            used = session.scalar(select(func.count(SiteTable.id)).where(SiteTable.zone_id == zone.id)) or 0
            used += session.scalar(select(func.count(SiteRow.id)).where(SiteRow.zone_id == zone.id)) or 0
            if used:
                raise ApplyError(f"Strefa „{zone.name}” ma już przypisane stoły lub rzędy — najpierw je przepnij albo usuń strefę ręcznie")
            session.delete(zone)
    elif item.kind == "structure_type":
        structure = session.scalar(select(StructureType).where(StructureType.source_suggestion_id == sid))
        if structure is not None:
            tables = session.scalar(select(func.count(SiteTable.id)).where(SiteTable.structure_type_id == structure.id)) or 0
            bom = session.scalar(select(func.count(BomItem.id)).where(BomItem.structure_type_id == structure.id)) or 0
            if tables or bom:
                raise ApplyError(f"Typ {structure.code} jest używany ({tables} stołów, {bom} pozycji BOM) — nie można cofnąć zatwierdzenia")
            session.delete(structure)
    elif item.kind == "bom_line":
        for bom in session.scalars(select(BomItem).where(BomItem.source_suggestion_id == sid)).all():
            session.delete(bom)
    elif item.kind in ("component", "tool", "drawing_block"):
        for entry in session.scalars(select(CatalogItem).where(CatalogItem.source_suggestion_id == sid)).all():
            session.delete(entry)
    elif item.kind == "torque":
        for entry in session.scalars(select(TorqueSpec).where(TorqueSpec.source_suggestion_id == sid)).all():
            session.delete(entry)
    elif item.kind == "numbering":
        tables = session.scalars(select(SiteTable).where(SiteTable.source_suggestion_id == sid)).all()
        assigned = [table for table in tables if table.zone_id or table.row_id or table.structure_type_id]
        if assigned:
            raise ApplyError(f"{len(assigned)} stołów z tej numeracji ma już przypisaną strefę, rząd lub typ — najpierw usuń przypisania")
        with_work = tables_with_field_data(session, [table.id for table in tables])
        if with_work:
            raise ApplyError(f"{len(with_work)} stołów z tej numeracji ma zapisany postęp, notatki lub zdjęcia — nie można cofnąć zatwierdzenia")
        for table in tables:
            session.delete(table)
    session.flush()


def tables_with_field_data(session, ids: list[int]) -> set[int]:
    """Stoły z danymi z budowy (montaż, odbiór, notatki, zdjęcia) — ich usunięcie skasowałoby pracę ekip."""
    if not ids:
        return set()
    result = set(session.scalars(select(SiteTable.id).where(SiteTable.id.in_(ids), or_(SiteTable.built.is_(True), SiteTable.qc_checked.is_(True)))).all())
    result |= set(session.scalars(select(TableNote.table_id).where(TableNote.table_id.in_(ids))).all())
    result |= set(session.scalars(select(Photo.table_id).where(Photo.table_id.in_(ids))).all())
    return result


# --- zapotrzebowanie materiałów -------------------------------------------------------------------

def requirements(session, zone_id: int | None = None) -> dict:
    """Ilości = ilość BOM na stół × liczba stołów danego typu (opcjonalnie w jednej strefie)."""
    query = select(SiteTable.structure_type_id, func.count(SiteTable.id)).group_by(SiteTable.structure_type_id)
    if zone_id is not None:
        query = query.where(SiteTable.zone_id == zone_id)
    counts = {type_id: count for type_id, count in session.execute(query).all()}
    without_type = counts.pop(None, 0)
    types = session.scalars(select(StructureType).order_by(StructureType.code)).all()
    bom_by_type = defaultdict(list)
    for bom in session.scalars(select(BomItem).order_by(BomItem.id)).all():
        bom_by_type[bom.structure_type_id].append(bom)
    per_type, totals = [], {}
    posts_known, posts_total = True, 0
    for structure in types:
        count = counts.get(structure.id, 0)
        lines = [{"name": b.name, "code": b.code, "spec": b.spec, "unit": b.unit, "per_table": b.quantity, "total": b.quantity * count} for b in bom_by_type[structure.id]]
        for line in lines:
            key = material_key(line["code"], line["name"], line["spec"], line["unit"])
            entry = totals.setdefault(key, {"key": key, "name": line["name"], "code": line["code"], "spec": line["spec"], "unit": line["unit"], "total": 0, "types": []})
            entry["total"] += line["total"]
            if count:
                entry["types"].append(structure.code)
        if count:
            if structure.posts_per_table is None:
                posts_known = False
            else:
                posts_total += structure.posts_per_table * count
        per_type.append({"type_id": structure.id, "code": structure.code, "modules": structure.modules, "tables": count, "planned_tables": structure.planned_tables, "posts_per_table": structure.posts_per_table,
                         "modules_total": structure.modules * count, "bom_missing": not lines, "lines": lines})
    warnings = []
    if without_type:
        warnings.append(f"{without_type} stołów nie ma przypisanego typu konstrukcji — ich materiały nie są policzone (wymaga potwierdzenia).")
    for entry in per_type:
        if entry["tables"] and entry["bom_missing"]:
            warnings.append(f"Typ {entry['code']}: {entry['tables']} stołów, ale brak zatwierdzonego BOM (wymaga potwierdzenia).")
    for structure in types:
        assigned = counts.get(structure.id, 0)
        if zone_id is None and structure.planned_tables and assigned != structure.planned_tables:
            warnings.append(f"Typ {structure.code}: wg BOM {structure.planned_tables} stołów, w budowie przypisano {assigned} — utwórz lub przypisz stoły (Konstrukcje i BOM → „Utwórz stoły”).")
    if not posts_known:
        warnings.append("Liczba słupów na stół nie jest podana dla wszystkich użytych typów — suma słupów niepełna (wymaga potwierdzenia).")
    return {"types": per_type, "totals": sorted((e for e in totals.values() if e["total"]), key=lambda e: (e["name"].lower(), e["spec"])),
            "tables_total": sum(counts.values()) + without_type, "tables_without_type": without_type,
            "modules_total": sum(e["modules_total"] for e in per_type), "posts_total": posts_total, "posts_complete": posts_known, "warnings": warnings}


def find_tables(session, zone_id=None, row_id=None, type_id=None, q: str = "", unassigned: bool = False):
    query = select(SiteTable).order_by(SiteTable.prefix, SiteTable.number, SiteTable.code)
    if zone_id is not None:
        query = query.where(SiteTable.zone_id == zone_id) if zone_id else query.where(SiteTable.zone_id.is_(None))
    if row_id is not None:
        query = query.where(SiteTable.row_id == row_id) if row_id else query.where(SiteTable.row_id.is_(None))
    if type_id is not None:
        query = query.where(SiteTable.structure_type_id == type_id) if type_id else query.where(SiteTable.structure_type_id.is_(None))
    if unassigned:
        query = query.where(or_(SiteTable.zone_id.is_(None), SiteTable.structure_type_id.is_(None)))
    if q:
        query = query.where(func.lower(SiteTable.code).contains(q.strip().lower()))
    return session.scalars(query).all()
