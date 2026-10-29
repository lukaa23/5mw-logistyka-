"""Izolowana przestrzeń danych każdej budowy.

PostgreSQL (serwer): osobny schemat `proj_<id>` w tej samej bazie.
SQLite (lokalnie):   osobny plik `data/projects/proj_<id>.db`.

Modele budowy są zdefiniowane raz, ze schematem-zastępnikiem "project". Przy każdym żądaniu
SQLAlchemy podstawia schemat konkretnej budowy (schema_translate_map), więc zapytanie technicznie
nie może sięgnąć do tabel innej budowy. Identyfikatory użytkowników to zwykłe liczby (konta są
w rejestrze centralnym, który przy SQLite jest osobnym plikiem).
"""
import re
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, MetaData, String, Text, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import IS_POSTGRES, PROJECTS_DIR
from .registry import engine as registry_engine

PLACEHOLDER_SCHEMA = "project"
STORAGE_KEY = re.compile(r"^proj_\d+$")


def now():
    return datetime.now(UTC).replace(tzinfo=None)


class ProjectBase(DeclarativeBase):
    metadata = MetaData(schema=PLACEHOLDER_SCHEMA)


class Zone(ProjectBase):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # etap 3


# --- struktura budowy (etap 3) -------------------------------------------------------------------

class StructureType(ProjectBase):
    """Typ stołu/trackera (np. 1x42). posts_per_table puste = „wymaga potwierdzenia”."""
    __tablename__ = "structure_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    modules: Mapped[int] = mapped_column(Integer, default=0)
    posts_per_table: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_tables: Mapped[int | None] = mapped_column(Integer, nullable=True)  # liczba stołów tego typu wg BOM (np. „Number of array”)
    description: Mapped[str] = mapped_column(Text, default="")
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BomItem(ProjectBase):
    """Pozycja BOM: ilość na JEDEN stół danego typu."""
    __tablename__ = "bom_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    structure_type_id: Mapped[int] = mapped_column(ForeignKey("structure_types.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[str] = mapped_column(String(160), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="szt.")
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CatalogItem(ProjectBase):
    """Komponenty (bez ilości) i narzędzia z dokumentów."""
    __tablename__ = "catalog_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # component | tool
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[str] = mapped_column(String(160), default="")
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TorqueSpec(ProjectBase):
    __tablename__ = "torque_specs"
    id: Mapped[int] = mapped_column(primary_key=True)
    bolt: Mapped[str] = mapped_column(String(20))
    min_nm: Mapped[float] = mapped_column(Float)
    max_nm: Mapped[float] = mapped_column(Float)
    context: Mapped[str] = mapped_column(Text, default="")
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SiteRow(ProjectBase):
    """Rząd stołów (w strefie lub bez strefy)."""
    __tablename__ = "site_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SiteTable(ProjectBase):
    """Stół / tracker o konkretnym oznaczeniu (np. T-12) z przypisaniem do strefy, rzędu i typu."""
    __tablename__ = "site_tables"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    prefix: Mapped[str] = mapped_column(String(10), default="")
    number: Mapped[int] = mapped_column(Integer, default=0, index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    row_id: Mapped[int | None] = mapped_column(ForeignKey("site_rows.id", ondelete="SET NULL"), nullable=True, index=True)
    structure_type_id: Mapped[int | None] = mapped_column(ForeignKey("structure_types.id", ondelete="SET NULL"), nullable=True, index=True)
    source_suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # Etap 4: postęp prac (montaż, odbiór QA/QC). Kolumny dopuszczają NULL — migracja istniejących budów.
    built: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, index=True)
    built_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    built_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qc_checked: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, index=True)
    qc_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qc_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_changed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TableNote(ProjectBase):
    """Notatka do stołu. client_id z telefonu — ponowne wysłanie z kolejki offline nie tworzy duplikatu."""
    __tablename__ = "table_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("site_tables.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    edited_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Photo(ProjectBase):
    """Zdjęcie z budowy przypięte do stołu (zawartość w bazie budowy)."""
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("site_tables.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# --- logistyka i meldunki (etap 4b) ----------------------------------------------------------------

class Delivery(ProjectBase):
    """Dostawa na budowę (dokument WZ)."""
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    wz_number: Mapped[str] = mapped_column(String(100))
    supplier: Mapped[str] = mapped_column(String(180), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeliveryItem(ProjectBase):
    """Pozycja WZ. material_key wiąże ją z pozycją zapotrzebowania; nazwa/kod/spec to kopia z chwili przyjęcia."""
    __tablename__ = "delivery_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    material_key: Mapped[str] = mapped_column(String(400), index=True)
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[str] = mapped_column(String(160), default="")
    unit: Mapped[str] = mapped_column(String(20), default="szt.")
    quantity_received: Mapped[float] = mapped_column(Float)
    quantity_damaged: Mapped[float] = mapped_column(Float, default=0)


class WorkLog(ProjectBase):
    """Meldunek dzienny brygady (z telefonu, także offline)."""
    __tablename__ = "work_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    team: Mapped[str] = mapped_column(String(120))
    stage: Mapped[str] = mapped_column(Text)
    people: Mapped[int] = mapped_column(Integer)
    hours: Mapped[float] = mapped_column(Float)
    tables_completed: Mapped[float] = mapped_column(Float, default=0)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("site_tables.id", ondelete="SET NULL"), nullable=True)
    qc_notes: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkLogPhoto(ProjectBase):
    __tablename__ = "work_log_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    work_log_id: Mapped[int] = mapped_column(ForeignKey("work_logs.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProjectEvent(ProjectBase):
    """Dziennik zdarzeń tej budowy (kto, co i kiedy zmienił)."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Document(ProjectBase):
    """Plik PDF budowy (zawartość w bazie — przeżywa restart serwera) i stan jego analizy."""
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    category: Mapped[str] = mapped_column(String(40), default="auto")  # auto | bom | rysunek | instrukcja | inne
    status: Mapped[str] = mapped_column(String(20), default="oczekuje")  # oczekuje | analiza | gotowy | błąd
    pages: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")
    parser_version: Mapped[str] = mapped_column(String(40), default="")
    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Suggestion(ProjectBase):
    """Propozycja danych wyciągnięta z PDF — czeka na decyzję kierownika (zatwierdź / popraw / odrzuć)."""
    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    key: Mapped[str] = mapped_column(String(400), unique=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    original_json: Mapped[str] = mapped_column(Text, default="{}")  # wartości odczytane przez parser (przed poprawką)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")   # [{document_id, filename, page, excerpt}]
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="nowa", index=True)  # nowa | zatwierdzona | odrzucona
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_ref: Mapped[str] = mapped_column(String(80), default="")  # np. zone:12 po zastosowaniu w budowie
    reviewed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def storage_key_for(project_id: int) -> str:
    return f"proj_{int(project_id)}"


def _check_key(key: str) -> str:
    # Nazwa schematu trafia do DDL — dopuszczamy wyłącznie format proj_<liczba>.
    if not STORAGE_KEY.match(key or ""):
        raise ValueError(f"Nieprawidłowy klucz przestrzeni budowy: {key!r}")
    return key


_sqlite_engines: dict[str, object] = {}
_sqlite_lock = threading.Lock()


def _sqlite_path(key: str):
    return PROJECTS_DIR / f"{_check_key(key)}.db"


def _sqlite_engine(key: str):
    with _sqlite_lock:
        engine = _sqlite_engines.get(key)
        if engine is None:
            engine = create_engine(f"sqlite:///{_sqlite_path(key)}", connect_args={"check_same_thread": False})

            @event.listens_for(engine, "connect")
            def _fk(connection, _record):
                # Transakcje sterowane przez SQLAlchemy (inaczej sqlite3 psuje SAVEPOINT — przepis z dokumentacji).
                connection.isolation_level = None
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            @event.listens_for(engine, "begin")
            def _begin(connection):
                connection.exec_driver_sql("BEGIN")

            _sqlite_engines[key] = engine
        return engine


def project_bind(key: str):
    """Silnik skierowany na przestrzeń jednej budowy."""
    _check_key(key)
    if IS_POSTGRES:
        return registry_engine.execution_options(schema_translate_map={PLACEHOLDER_SCHEMA: key})
    return _sqlite_engine(key).execution_options(schema_translate_map={PLACEHOLDER_SCHEMA: None})


@contextmanager
def project_session(key: str):
    session = Session(bind=project_bind(key), autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


def create_storage(key: str) -> None:
    """Tworzy (lub uzupełnia o nowe tabele) przestrzeń budowy. Bezpieczne do wielokrotnego wywołania."""
    _check_key(key)
    if IS_POSTGRES:
        with registry_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{key}"'))
    with project_bind(key).begin() as connection:
        ProjectBase.metadata.create_all(connection)
        add_missing_columns(connection, key)


def add_missing_columns(connection, key: str) -> list[str]:
    """Prosta migracja: kolumny dodane w nowszych wersjach (zawsze dopuszczające NULL) trafiają
    do istniejących tabel budowy. create_all tworzy tylko brakujące tabele, nie kolumny."""
    inspector = inspect(connection)
    schema = key if IS_POSTGRES else None
    added = []
    for table in ProjectBase.metadata.sorted_tables:
        existing = {column["name"] for column in inspector.get_columns(table.name, schema=schema)}
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable:
                raise RuntimeError(f"Nowa kolumna {table.name}.{column.name} musi dopuszczać NULL")
            target = f'"{key}"."{table.name}"' if IS_POSTGRES else f'"{table.name}"'
            connection.execute(text(f'ALTER TABLE {target} ADD COLUMN "{column.name}" {column.type.compile(dialect=connection.dialect)}'))
            added.append(f"{table.name}.{column.name}")
    return added


def drop_storage(key: str) -> None:
    """Trwale usuwa dane jednej budowy (schemat albo plik). Nie dotyka innych budów."""
    _check_key(key)
    if IS_POSTGRES:
        with registry_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{key}" CASCADE'))
        return
    with _sqlite_lock:
        engine = _sqlite_engines.pop(key, None)
    if engine is not None:
        engine.dispose()
    _sqlite_path(key).unlink(missing_ok=True)


def storage_exists(key: str) -> bool:
    _check_key(key)
    if IS_POSTGRES:
        return key in inspect(registry_engine).get_schema_names()
    return _sqlite_path(key).exists()


def storage_tables(key: str) -> set[str]:
    """Nazwy tabel w przestrzeni budowy (do diagnostyki i testów izolacji)."""
    if IS_POSTGRES:
        return set(inspect(registry_engine).get_table_names(schema=_check_key(key)))
    return set(inspect(_sqlite_engine(key)).get_table_names())
