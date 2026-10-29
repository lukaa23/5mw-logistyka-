"""Etap 2: dokumenty PDF budowy, analiza lokalnym parserem i propozycje do przeglądu.

Każda propozycja ma stały klucz (np. `type|1x42`, `bom|1x42|purlin 1||44`). Ten sam element
znaleziony na wielu stronach lub w wielu plikach to jedna propozycja z listą źródeł. Ponowna
analiza dokumentu podmienia tylko jego źródła i nie rusza decyzji kierownika.
"""
import json
import logging
import threading
from collections import defaultdict

from sqlalchemy import select

from . import tenancy
from . import cad
from .pdfparse import PARSER_VERSION, analyze_pdf
from .tenancy import Document, ProjectEvent, Suggestion, now

log = logging.getLogger("asolar2.imports")

MAX_SOURCES = 30

# Rodzaj dokumentu wskazany przy wgrywaniu decyduje, co z niego wyciągamy — mniej szumu, nic „przy okazji”.
KINDS_BY_CATEGORY = {
    "bom": {"bom_line", "component", "structure_type"},
    "rysunek": {"numbering", "zone", "structure_type", "drawing_block"},
    "instrukcja": {"torque", "tool", "structure_type", "bom_line"},
}
MANUAL_NOTE = "Nie znaleziono danych do automatycznego odczytu (np. skan albo nietypowy układ). Uzupełnij pozycje ręcznie obok podglądu."


def for_category(suggestions, category: str):
    allowed = KINDS_BY_CATEGORY.get(category)
    if allowed is None:  # „auto”/„inne” i dokumenty sprzed tej wersji — wszystko
        return list(suggestions)
    result = [item for item in suggestions if item.kind in allowed]
    if category == "instrukcja":
        # Z instrukcji tylko pozycje przypisane do typu (tabela pod podpisem „… for 1x42”); listy bez typu
        # dublowałyby BOM i wymagały zgadywania, do którego stołu należą.
        result = [item for item in result if item.kind != "bom_line" or item.payload.get("group")]
    return result


def page_count(content: bytes, fmt: str) -> int:
    if fmt in ("dwg", "dxf"):
        return 1
    try:
        import pypdfium2
        document = pypdfium2.PdfDocument(content)
        try:
            return len(document)
        finally:
            document.close()
    except Exception:
        return 0
STATUSES = ("nowa", "zatwierdzona", "odrzucona")

# Pola, które kierownik może poprawić w propozycji danego rodzaju (reszta to dane diagnostyczne parsera).
EDITABLE = {
    "bom_line": {"name": str, "code": str, "spec": str, "quantity": float, "unit": str, "group": str},
    "component": {"name": str, "code": str, "spec": str},
    "tool": {"name": str, "spec": str},
    "structure_type": {"code": str, "modules": int, "tables": int},
    "zone": {"name": str},
    "numbering": {"prefix": str, "first": int, "last": int},
    "torque": {"bolt": str, "min_nm": float, "max_nm": float},
    "drawing_block": {"name": str, "count": int},
}

# Analizy wykonujemy po kolei — parser jest ciężki dla CPU, a scalanie propozycji jednej budowy
# nie może się przeplatać (unikalne klucze).
_analysis_lock = threading.Lock()


def loads(value, default):
    try:
        return json.loads(value) if value else default
    except ValueError:
        return default


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def document_dict(document: Document) -> dict:
    return {"id": document.id, "filename": document.filename, "format": cad.format_of(document.filename), "size": document.size, "category": document.category, "status": document.status,
            "pages": document.pages, "summary": loads(document.summary_json, {}), "warnings": loads(document.warnings_json, []), "error": document.error,
            "parser_version": document.parser_version, "uploaded_by": document.uploaded_by, "uploaded_at": document.uploaded_at, "analyzed_at": document.analyzed_at}


def suggestion_dict(item: Suggestion) -> dict:
    return {"id": item.id, "kind": item.kind, "key": item.key, "payload": loads(item.payload_json, {}), "original": loads(item.original_json, {}),
            "sources": loads(item.sources_json, []), "confidence": round(item.confidence, 2), "status": item.status, "edited": item.edited,
            "applied_ref": item.applied_ref, "reviewed_by": item.reviewed_by, "reviewed_at": item.reviewed_at, "created_at": item.created_at}


# --- scalanie wyników analizy ---------------------------------------------------------------------

def detach_document(session, document_id: int) -> int:
    """Usuwa źródła danego dokumentu z propozycji. Nierozpatrzone propozycje bez źródeł znikają;
    rozpatrzone zostają (decyzja kierownika jest ważniejsza niż obecność pliku). Zwraca liczbę usuniętych."""
    removed = 0
    for item in session.scalars(select(Suggestion)).all():
        sources = loads(item.sources_json, [])
        if item.key.startswith("manual|"):
            continue  # wpis ręczny należy do użytkownika, nie do odczytu pliku
        kept = [source for source in sources if source.get("document_id") != document_id]
        if len(kept) == len(sources):
            continue
        if not kept and item.status == "nowa":
            session.delete(item)
            removed += 1
        else:
            item.sources_json = dumps(kept)
            refresh_occurrences(item, kept)
            item.updated_at = now()
    return removed


def refresh_occurrences(item: Suggestion, sources: list):
    """Liczba wystąpień = suma liczników z poszczególnych dokumentów (pierwsze źródło dokumentu niesie jego licznik)."""
    payload = loads(item.payload_json, {})
    if "occurrences" in payload and not item.edited:
        payload["occurrences"] = sum(source.get("occurrences", 0) for source in sources)
        item.payload_json = dumps(payload)


def merge_analysis(session, document: Document, suggestions) -> dict:
    grouped: dict[str, list] = defaultdict(list)
    for found in suggestions:
        grouped[found.key[:400]].append(found)
    created = updated = 0
    existing = {item.key: item for item in session.scalars(select(Suggestion).where(Suggestion.key.in_(list(grouped) or [""]))).all()}
    for key, items in grouped.items():
        first = items[0]
        payload = dict(first.payload)
        if "occurrences" in payload:
            payload["occurrences"] = sum(item.payload.get("occurrences", 1) for item in items)
        new_sources = []
        for found in items:
            source = {"document_id": document.id, "filename": document.filename, "page": found.page, "excerpt": found.excerpt}
            if not any(s["page"] == source["page"] and s["excerpt"] == source["excerpt"] for s in new_sources):
                new_sources.append(source)
        if "occurrences" in payload:
            new_sources[0]["occurrences"] = payload["occurrences"]
        confidence = max(item.confidence for item in items)
        item = existing.get(key)
        if item is None:
            session.add(Suggestion(kind=first.kind, key=key, payload_json=dumps(payload), original_json=dumps(payload),
                                   sources_json=dumps(new_sources[:MAX_SOURCES]), confidence=confidence))
            created += 1
            continue
        sources = (loads(item.sources_json, []) + new_sources)[:MAX_SOURCES]
        item.sources_json = dumps(sources)
        item.confidence = max(item.confidence, confidence)
        if item.status == "nowa" and not item.edited:
            item.payload_json = dumps(payload)
            item.original_json = dumps(payload)
        refresh_occurrences(item, sources)
        item.updated_at = now()
        updated += 1
    session.flush()
    return {"created": created, "updated": updated}


def recompute_conflicts(session):
    """Ta sama pozycja BOM (typ + kod/nazwa + specyfikacja) z różnymi ilościami — także między plikami."""
    items = session.scalars(select(Suggestion).where(Suggestion.kind == "bom_line")).all()
    groups = defaultdict(set)
    for item in items:
        if item.status != "odrzucona":
            groups[item.key.rsplit("|", 1)[0]].add(loads(item.payload_json, {}).get("quantity"))
    for item in items:
        payload = loads(item.payload_json, {})
        quantities = sorted(q for q in groups[item.key.rsplit("|", 1)[0]] if q is not None)
        conflict = quantities if item.status != "odrzucona" and len(quantities) > 1 else None
        if payload.get("conflict") != conflict:
            if conflict:
                payload["conflict"] = conflict
            else:
                payload.pop("conflict", None)
            item.payload_json = dumps(payload)


def analyze_document(storage_key: str, document_id: int):
    """Zadanie w tle: analiza jednego PDF i scalenie propozycji. Błąd parsera nie przerywa pracy serwera."""
    with _analysis_lock:
        with tenancy.project_session(storage_key) as session:
            document = session.get(Document, document_id)
            if document is None:
                return
            document.status, document.error = "analiza", ""
            session.commit()
            content, filename, category = document.content, document.filename, document.category
        fmt = cad.detect_format(filename, content) or cad.format_of(filename)
        try:
            analysis = cad.analyze_cad(content, filename) if fmt in ("dwg", "dxf") else analyze_pdf(content)
        except Exception as error:
            # Nie „błąd”: plik zostaje, pokazujemy podgląd i formularz ręcznego uzupełnienia.
            if not isinstance(error, cad.CadError):
                log.warning("Analiza dokumentu %s/%s nie powiodła się: %s", storage_key, document_id, error)
            note = str(error) if isinstance(error, cad.CadError) else MANUAL_NOTE
            with tenancy.project_session(storage_key) as session:
                document = session.get(Document, document_id)
                if document is not None:
                    document.status, document.error = "ręcznie", note
                    document.pages = page_count(content, fmt)
                    document.analyzed_at, document.parser_version = now(), PARSER_VERSION
                    session.commit()
            return
        analysis.suggestions = for_category(analysis.suggestions, category)
        with tenancy.project_session(storage_key) as session:
            document = session.get(Document, document_id)
            if document is None:  # usunięty w trakcie analizy
                return
            detach_document(session, document.id)
            session.flush()
            result = merge_analysis(session, document, analysis.suggestions)
            recompute_conflicts(session)
            document.status = "gotowy" if analysis.suggestions else "ręcznie"
            document.error = "" if analysis.suggestions else MANUAL_NOTE
            document.pages = analysis.pages
            document.summary_json = dumps(analysis.summary())
            document.warnings_json = dumps(analysis.warnings)
            document.analyzed_at, document.parser_version = now(), PARSER_VERSION
            session.add(ProjectEvent(user_id=None, action="analyze", entity="document", entity_id=document.id,
                                     details=dumps({"plik": document.filename, "nowe": result["created"], "uzupełnione": result["updated"]})))
            session.commit()


def resume_pending(storage_keys):
    """Po restarcie serwera dokończ analizy przerwane w połowie (w tle, nie blokuje startu)."""
    pending = []
    for key in storage_keys:
        with tenancy.project_session(key) as session:
            for document in session.scalars(select(Document).where(Document.status.in_(("oczekuje", "analiza")))).all():
                document.status = "oczekuje"
                pending.append((key, document.id))
            session.commit()
    if pending:
        threading.Thread(target=lambda: [analyze_document(key, doc_id) for key, doc_id in pending], daemon=True, name="asolar2-resume").start()
    return len(pending)


# --- decyzje kierownika --------------------------------------------------------------------------

def clean_payload(kind: str, changes: dict) -> dict:
    allowed = EDITABLE.get(kind, {})
    result = {}
    for field, value in changes.items():
        if field not in allowed:
            raise ValueError(f"Pola „{field}” nie można edytować w propozycji tego rodzaju")
        cast = allowed[field]
        if cast is str:
            value = str(value or "").strip()
            if field in ("name", "code") and kind in ("zone", "structure_type") and not value:
                raise ValueError("Wartość nie może być pusta")
        else:
            try:
                value = cast(value)
            except (TypeError, ValueError):
                raise ValueError(f"Pole „{field}” musi być liczbą") from None
            if value < 0:
                raise ValueError(f"Pole „{field}” nie może być ujemne")
        result[field] = value
    if kind == "bom_line" and "name" in result and not result["name"]:
        raise ValueError("Nazwa pozycji nie może być pusta")
    return result
