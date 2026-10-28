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
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, MetaData, String, Text, create_engine, event, inspect, text
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
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

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
