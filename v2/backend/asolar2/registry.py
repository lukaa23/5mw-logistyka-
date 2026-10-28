"""Rejestr centralny: konta, lista budów i uprawnienia do nich.

Rejestr NIE przechowuje danych budów — każda budowa ma własną przestrzeń (patrz tenancy.py).
"""
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import DATABASE_URL, IS_POSTGRES

PROJECT_ROLES = ("kierownik", "brygadzista")


def now():
    return datetime.now(UTC).replace(tzinfo=None)


engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300, connect_args={} if IS_POSTGRES else {"check_same_thread": False})
if not IS_POSTGRES:
    @event.listens_for(engine, "connect")
    def _sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

RegistrySession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class RegistryBase(DeclarativeBase):
    pass


class User(RegistryBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(300))
    # Administrator tworzy budowy, zarządza kontami i ma dostęp do wszystkich budów.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Project(RegistryBase):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    location: Mapped[str] = mapped_column(String(180), default="")
    capacity_mw: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Nazwa schematu PostgreSQL (proj_12) albo pliku SQLite (proj_12.db) z danymi tej budowy.
    storage_key: Mapped[str] = mapped_column(String(80), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    memberships: Mapped[list["Membership"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Membership(RegistryBase):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    user: Mapped[User] = relationship(back_populates="memberships")
    project: Mapped[Project] = relationship(back_populates="memberships")


class RegistryEvent(RegistryBase):
    """Dziennik zmian w rejestrze (tworzenie i usuwanie budów, uprawnienia, konta)."""
    __tablename__ = "registry_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(120))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


def init_registry():
    RegistryBase.metadata.create_all(engine)
