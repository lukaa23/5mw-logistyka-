from datetime import UTC, date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now():
    return datetime.now(UTC).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(30), index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    location: Mapped[str] = mapped_column(String(180), default="")
    capacity_mw: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    zones: Mapped[list["Zone"]] = relationship(back_populates="project", cascade="all, delete-orphan")

class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    project: Mapped[Project] = relationship(back_populates="zones")
    sections: Mapped[list["Section"]] = relationship(back_populates="zone", cascade="all, delete-orphan")

class Section(Base):
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    zone: Mapped[Zone] = relationship(back_populates="sections")
    rows: Mapped[list["ConstructionRow"]] = relationship(back_populates="section", cascade="all, delete-orphan")

class RowType(Base):
    __tablename__ = "row_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    structure_kind: Mapped[str] = mapped_column(String(80), default="tracker")
    reference_length_m: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    components: Mapped[list["RowTypeComponent"]] = relationship(back_populates="row_type", cascade="all, delete-orphan")

class ConstructionRow(Base):
    __tablename__ = "construction_rows"
    __table_args__ = (UniqueConstraint("section_id", "code", name="uq_row_section_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    row_type_id: Mapped[int | None] = mapped_column(ForeignKey("row_types.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(80))
    length_m: Mapped[float] = mapped_column(Float, default=0)
    built: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    built_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    built_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qc_checked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    qc_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    qc_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    section: Mapped[Section] = relationship(back_populates="rows")
    row_type: Mapped[RowType | None] = relationship()
    built_by: Mapped[User | None] = relationship(foreign_keys=[built_by_id])
    qc_by: Mapped[User | None] = relationship(foreign_keys=[qc_by_id])

class Component(Base):
    __tablename__ = "components"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80), default="Inne")
    unit: Mapped[str] = mapped_column(String(30), default="szt.")
    torque_min_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    torque_max_nm: Mapped[float | None] = mapped_column(Float, nullable=True)

class RowTypeComponent(Base):
    __tablename__ = "row_type_components"
    __table_args__ = (UniqueConstraint("row_type_id", "component_id", name="uq_type_component"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    row_type_id: Mapped[int] = mapped_column(ForeignKey("row_types.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    row_type: Mapped[RowType] = relationship(back_populates="components")
    component: Mapped[Component] = relationship()

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(80), default="wgrany")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class WorkLog(Base):
    __tablename__ = "work_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    team: Mapped[str] = mapped_column(String(120))
    stage: Mapped[str] = mapped_column(String(160))
    people: Mapped[int] = mapped_column(Integer)
    hours: Mapped[float] = mapped_column(Float)
    rows_completed: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class RFI(Base):
    __tablename__ = "rfis"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    row_id: Mapped[int | None] = mapped_column(ForeignKey("construction_rows.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normalny")
    status: Mapped[str] = mapped_column(String(30), default="otwarty", index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, default=date.today)
    wz_number: Mapped[str] = mapped_column(String(100))
    supplier: Mapped[str] = mapped_column(String(180), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    items: Mapped[list["DeliveryItem"]] = relationship(back_populates="delivery", cascade="all, delete-orphan")

class DeliveryItem(Base):
    __tablename__ = "delivery_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    quantity_received: Mapped[float] = mapped_column(Float)
    quantity_damaged: Mapped[float] = mapped_column(Float, default=0)
    delivery: Mapped[Delivery] = relationship(back_populates="items")
    component: Mapped[Component] = relationship()

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
