"""ASOLAR v2 — serwer wielu budów (etap 1: rejestr, izolacja, konta i role; etap 2: dokumenty PDF i propozycje)."""
import hashlib
import json
import os
from dataclasses import dataclass
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import APP_VERSION, IS_POSTGRES, SERVER_MODE
from .registry import Membership, Project, RegistryEvent, RegistrySession, User, init_registry, now
from .security import create_token, decode_token, hash_password, verify_password
from . import imports, logistics, plans, report, structure, tenancy
from .imports import document_dict, suggestion_dict
from .tenancy import (BomItem, CatalogItem, Delivery, DeliveryItem, Document, Photo, ProjectEvent, SiteRow, SiteTable, StructureType, Suggestion,
                      TableNote, TorqueSpec, WorkLog, WorkLogPhoto, Zone)

app = FastAPI(title="ASOLAR v2 — wiele budów", version=APP_VERSION)

# --- start: rejestr, konto administratora, przestrzenie budów ------------------------------------

LOCAL_ADMIN_PASSWORD = "Asolar2026!"


def bootstrap():
    init_registry()
    with RegistrySession() as db:
        if not db.scalar(select(func.count(User.id))):
            password = os.getenv("ASOLAR_ADMIN_PASSWORD", "")
            if not password:
                if SERVER_MODE:
                    raise RuntimeError("Brak zmiennej ASOLAR_ADMIN_PASSWORD — potrzebna do utworzenia pierwszego konta administratora.")
                password = LOCAL_ADMIN_PASSWORD
            username = os.getenv("ASOLAR_ADMIN_USERNAME", "kierownik")
            db.add(User(username=username, full_name="Kierownik Budowy", password_hash=hash_password(password), is_admin=True))
            db.commit()
        # Uzupełnia przestrzenie istniejących budów o tabele dodane w nowszych wersjach.
        keys = [project.storage_key for project in db.scalars(select(Project)).all() if project.storage_key]
        for key in keys:
            tenancy.create_storage(key)
    imports.resume_pending(keys)


bootstrap()


def registry_db():
    db = RegistrySession()
    try:
        yield db
    finally:
        db.close()


def log(db: Session, user: User | None, action: str, target: str, details=None):
    db.add(RegistryEvent(user_id=user.id if user else None, action=action, target=target, details=json.dumps(details or {}, ensure_ascii=False, default=str)))


# --- uwierzytelnianie i uprawnienia -------------------------------------------------------------

def current_user(authorization: str | None = Header(default=None), db: Session = Depends(registry_db)) -> User:
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = decode_token(token) if token else None
    if not user_id:
        raise HTTPException(401, "Wymagane logowanie")
    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(401, "Konto nieaktywne")
    return user


def admin_only(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Tę operację wykonuje administrator")
    return user


def role_in(db: Session, user: User, project: Project) -> str | None:
    if user.is_admin:
        return "kierownik"
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.project_id == project.id))
    return membership.role if membership else None


@dataclass
class Access:
    user: User
    project: Project
    role: str
    db: Session

    @property
    def is_manager(self):
        return self.role == "kierownik"

    def require_manager(self):
        if not self.is_manager:
            raise HTTPException(403, "Tę operację wykonuje kierownik budowy")


def project_access(project_id: int, user: User = Depends(current_user), db: Session = Depends(registry_db)) -> Access:
    project = db.get(Project, project_id)
    role = role_in(db, user, project) if project else None
    # Brak uprawnień = „nie znaleziono” — osoba spoza budowy nie dowiaduje się, że budowa istnieje.
    if not project or not role:
        raise HTTPException(404, "Nie znaleziono budowy")
    return Access(user=user, project=project, role=role, db=db)


def user_dict(user: User):
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "is_admin": user.is_admin, "active": user.active}


def project_dict(project: Project, role: str | None = None, stats: dict | None = None):
    return {"id": project.id, "name": project.name, "location": project.location, "capacity_mw": project.capacity_mw, "description": project.description,
            "archived": project.archived, "archived_at": project.archived_at, "created_at": project.created_at, "role": role, "stats": stats or {}}


def project_stats(project: Project) -> dict:
    with tenancy.project_session(project.storage_key) as session:
        zones = session.scalar(select(func.count(Zone.id))) or 0
        documents = session.scalar(select(func.count(Document.id))) or 0
        pending = session.scalar(select(func.count(Suggestion.id)).where(Suggestion.status == "nowa")) or 0
        tables = session.scalar(select(func.count(SiteTable.id))) or 0
        types = session.scalar(select(func.count(StructureType.id))) or 0
        last = session.scalar(select(func.max(ProjectEvent.created_at)))
    return {"zones": zones, "tables": tables, "types": types, "documents": documents, "pending_suggestions": pending, "members": len(project.memberships), "last_activity": last}


# --- API: konto ---------------------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "database": "postgresql" if IS_POSTGRES else "sqlite", "isolation": "schema-per-project" if IS_POSTGRES else "file-per-project"}


@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(registry_db)):
    user = db.scalar(select(User).where(User.username == data.username.strip()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Nieprawidłowy login lub hasło")
    if not user.active:
        raise HTTPException(403, "Konto zostało dezaktywowane")
    return {"token": create_token(user.id), "user": user_dict(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


# --- API: budowy ---------------------------------------------------------------------------------

class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    location: str = Field(default="", max_length=180)
    capacity_mw: float = Field(default=0, ge=0, le=100000)
    description: str = Field(default="", max_length=5000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    location: str | None = Field(default=None, max_length=180)
    capacity_mw: float | None = Field(default=None, ge=0, le=100000)
    description: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None


@app.get("/api/projects")
def list_projects(include_archived: bool = False, user: User = Depends(current_user), db: Session = Depends(registry_db)):
    if user.is_admin:
        projects = db.scalars(select(Project).order_by(Project.archived, Project.name)).all()
        roles = {project.id: "kierownik" for project in projects}
    else:
        memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
        roles = {item.project_id: item.role for item in memberships}
        projects = db.scalars(select(Project).where(Project.id.in_(list(roles) or [-1])).order_by(Project.archived, Project.name)).all()
    return [project_dict(project, roles[project.id], project_stats(project)) for project in projects if include_archived or not project.archived]


@app.post("/api/projects")
def create_project(data: ProjectIn, user: User = Depends(admin_only), db: Session = Depends(registry_db)):
    """Nowa budowa: wpis w rejestrze + własna, pusta przestrzeń danych + twórca jako kierownik."""
    name = data.name.strip()
    if db.scalar(select(Project).where(func.lower(Project.name) == name.lower(), Project.archived == False)):  # noqa: E712
        raise HTTPException(409, "Aktywna budowa o tej nazwie już istnieje")
    project = Project(name=name, location=data.location.strip(), capacity_mw=data.capacity_mw, description=data.description.strip(), created_by_id=user.id)
    db.add(project)
    db.flush()
    project.storage_key = tenancy.storage_key_for(project.id)
    try:
        tenancy.create_storage(project.storage_key)
        db.add(Membership(user_id=user.id, project_id=project.id, role="kierownik"))
        log(db, user, "create", f"project:{project.id}", {"name": name, "storage": project.storage_key})
        db.commit()
    except Exception:
        db.rollback()
        tenancy.drop_storage(project.storage_key)
        raise
    with tenancy.project_session(project.storage_key) as session:
        session.add(ProjectEvent(user_id=user.id, action="create", entity="project", entity_id=project.id, details=name))
        session.commit()
    db.refresh(project)
    return project_dict(project, "kierownik", project_stats(project))


@app.get("/api/projects/{project_id}")
def get_project(access: Access = Depends(project_access)):
    return project_dict(access.project, access.role, project_stats(access.project))


@app.patch("/api/projects/{project_id}")
def update_project(data: ProjectUpdate, access: Access = Depends(project_access)):
    access.require_manager()
    values = data.model_dump(exclude_unset=True)
    project = access.project
    for key, value in values.items():
        setattr(project, key, value.strip() if isinstance(value, str) else value)
    if "archived" in values:
        project.archived_at = now() if values["archived"] else None
    log(access.db, access.user, "update", f"project:{project.id}", values)
    access.db.commit()
    return project_dict(project, access.role, project_stats(project))


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, confirm_name: str = Query(...), user: User = Depends(admin_only), db: Session = Depends(registry_db)):
    """Trwałe usunięcie budowy razem z jej przestrzenią danych. Wymaga archiwizacji i przepisania nazwy."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Nie znaleziono budowy")
    if not project.archived:
        raise HTTPException(409, "Przed usunięciem zarchiwizuj budowę")
    if confirm_name.strip() != project.name:
        raise HTTPException(400, "Nazwa do potwierdzenia nie zgadza się z nazwą budowy")
    key = project.storage_key
    log(db, user, "delete", f"project:{project.id}", {"name": project.name, "storage": key})
    db.delete(project)
    db.commit()
    if key:
        tenancy.drop_storage(key)
    return {"ok": True}


# --- API: zespół budowy -------------------------------------------------------------------------

class MemberIn(BaseModel):
    user_id: int
    role: Literal["kierownik", "brygadzista"]


@app.get("/api/projects/{project_id}/members")
def list_members(access: Access = Depends(project_access)):
    items = access.db.scalars(select(Membership).where(Membership.project_id == access.project.id)).all()
    return [{"user": user_dict(item.user), "role": item.role, "since": item.created_at} for item in sorted(items, key=lambda m: (m.role != "kierownik", m.user.full_name))]


@app.put("/api/projects/{project_id}/members")
def set_member(data: MemberIn, access: Access = Depends(project_access)):
    """Dodaje osobę do budowy albo zmienia jej rolę."""
    access.require_manager()
    member = access.db.get(User, data.user_id)
    if not member or not member.active:
        raise HTTPException(404, "Nie znaleziono aktywnego konta")
    if member.id == access.user.id and data.role != "kierownik" and not access.user.is_admin:
        raise HTTPException(400, "Nie możesz odebrać sobie roli kierownika")
    item = access.db.scalar(select(Membership).where(Membership.user_id == member.id, Membership.project_id == access.project.id))
    if item:
        item.role = data.role
    else:
        access.db.add(Membership(user_id=member.id, project_id=access.project.id, role=data.role))
    log(access.db, access.user, "member", f"project:{access.project.id}", {"user": member.username, "role": data.role})
    access.db.commit()
    return {"ok": True}


@app.delete("/api/projects/{project_id}/members/{user_id}")
def remove_member(user_id: int, access: Access = Depends(project_access)):
    access.require_manager()
    if user_id == access.user.id and not access.user.is_admin:
        raise HTTPException(400, "Nie możesz usunąć siebie z budowy")
    item = access.db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.project_id == access.project.id))
    if not item:
        raise HTTPException(404, "Ta osoba nie należy do budowy")
    access.db.delete(item)
    log(access.db, access.user, "member-remove", f"project:{access.project.id}", {"user_id": user_id})
    access.db.commit()
    return {"ok": True}


# --- API: dane budowy (etap 1: strefy i dziennik) ------------------------------------------------

class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


def zone_dict(zone: Zone):
    return {"id": zone.id, "name": zone.name, "description": zone.description, "sort_order": zone.sort_order, "created_at": zone.created_at}


@app.get("/api/projects/{project_id}/zones")
def list_zones(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        return [zone_dict(zone) for zone in session.scalars(select(Zone).order_by(Zone.sort_order, Zone.id)).all()]


@app.post("/api/projects/{project_id}/zones")
def create_zone(data: ZoneIn, access: Access = Depends(project_access)):
    if access.project.archived:
        raise HTTPException(409, "Budowa jest zarchiwizowana")
    with tenancy.project_session(access.project.storage_key) as session:
        if session.scalar(select(Zone).where(func.lower(Zone.name) == data.name.strip().lower())):
            raise HTTPException(409, "Strefa o tej nazwie już istnieje")
        order = (session.scalar(select(func.max(Zone.sort_order))) or 0) + 1
        zone = Zone(name=data.name.strip(), description=data.description.strip(), sort_order=order, created_by=access.user.id)
        session.add(zone)
        session.flush()
        session.add(ProjectEvent(user_id=access.user.id, action="create", entity="zone", entity_id=zone.id, details=zone.name))
        session.commit()
        return zone_dict(zone)


@app.patch("/api/projects/{project_id}/zones/{zone_id}")
def update_zone(zone_id: int, data: ZoneIn, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        zone = session.get(Zone, zone_id)
        if not zone:
            raise HTTPException(404, "Nie znaleziono strefy")
        before = zone.name
        zone.name, zone.description = data.name.strip(), data.description.strip()
        session.add(ProjectEvent(user_id=access.user.id, action="update", entity="zone", entity_id=zone.id, details=json.dumps({"przed": before, "po": zone.name}, ensure_ascii=False)))
        session.commit()
        return zone_dict(zone)


@app.delete("/api/projects/{project_id}/zones/{zone_id}")
def delete_zone(zone_id: int, access: Access = Depends(project_access)):
    access.require_manager()
    with tenancy.project_session(access.project.storage_key) as session:
        zone = session.get(Zone, zone_id)
        if not zone:
            raise HTTPException(404, "Nie znaleziono strefy")
        session.add(ProjectEvent(user_id=access.user.id, action="delete", entity="zone", entity_id=zone.id, details=zone.name))
        session.delete(zone)
        session.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/events")
def list_events(limit: int = Query(50, ge=1, le=500), access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        events = session.scalars(select(ProjectEvent).order_by(ProjectEvent.id.desc()).limit(limit)).all()
    names = {user.id: user.full_name for user in access.db.scalars(select(User)).all()}
    return [{"id": e.id, "user": names.get(e.user_id, "—"), "action": e.action, "entity": e.entity, "entity_id": e.entity_id, "details": e.details, "created_at": e.created_at} for e in events]


# --- API: dokumenty PDF i propozycje (etap 2) -----------------------------------------------------

MAX_FILES_PER_UPLOAD = 20
MAX_FILE_BYTES = 60 * 1024 * 1024
CATEGORIES = ("auto", "bom", "rysunek", "instrukcja", "inne")


def writable(access: Access):
    access.require_manager()
    if access.project.archived:
        raise HTTPException(409, "Budowa jest zarchiwizowana")


@app.post("/api/projects/{project_id}/documents")
def upload_documents(background: BackgroundTasks, files: list[UploadFile] = File(...), category: str = Query("auto"),
                     access: Access = Depends(project_access)):
    """Wiele PDF naraz. Każdy plik jest zapisywany w przestrzeni tej budowy i analizowany w tle."""
    writable(access)
    if category not in CATEGORIES:
        raise HTTPException(400, "Nieznana kategoria dokumentu")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Jednorazowo można wgrać najwyżej {MAX_FILES_PER_UPLOAD} plików")
    key = access.project.storage_key
    accepted, duplicates, rejected = [], [], []
    with tenancy.project_session(key) as session:
        for upload in files:
            name = Path(upload.filename or "dokument.pdf").name[:255]
            content = upload.file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                rejected.append({"filename": name, "reason": f"Plik większy niż {MAX_FILE_BYTES // (1024 * 1024)} MB"})
                continue
            if not content.startswith(b"%PDF-"):
                rejected.append({"filename": name, "reason": "To nie jest plik PDF"})
                continue
            digest = hashlib.sha256(content).hexdigest()
            existing = session.scalar(select(Document).where(Document.sha256 == digest))
            if existing or any(item.sha256 == digest for item in accepted):
                duplicates.append({"filename": name, "existing": existing.filename if existing else name})
                continue
            document = Document(filename=name, sha256=digest, size=len(content), content=content, category=category, uploaded_by=access.user.id)
            session.add(document)
            accepted.append(document)
        session.flush()
        for document in accepted:
            session.add(ProjectEvent(user_id=access.user.id, action="upload", entity="document", entity_id=document.id, details=document.filename))
        session.commit()
        result = [document_dict(document) for document in accepted]
    for document in result:
        background.add_task(imports.analyze_document, key, document["id"])
    return {"accepted": result, "duplicates": duplicates, "rejected": rejected}


@app.get("/api/projects/{project_id}/documents")
def list_documents(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        return [document_dict(item) for item in session.scalars(select(Document).order_by(Document.uploaded_at.desc(), Document.id.desc())).all()]


@app.get("/api/projects/{project_id}/documents/{document_id}/file")
def document_file(document_id: int, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        document = session.get(Document, document_id)
        if not document:
            raise HTTPException(404, "Nie znaleziono dokumentu")
        return Response(document.content, media_type="application/pdf",
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(document.filename)}", "Cache-Control": "private, no-store"})


@app.post("/api/projects/{project_id}/documents/{document_id}/reanalyze")
def reanalyze_document(document_id: int, background: BackgroundTasks, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        document = session.get(Document, document_id)
        if not document:
            raise HTTPException(404, "Nie znaleziono dokumentu")
        if document.status == "analiza":
            raise HTTPException(409, "Analiza tego dokumentu jeszcze trwa")
        document.status = "oczekuje"
        session.commit()
        result = document_dict(document)
    background.add_task(imports.analyze_document, access.project.storage_key, document_id)
    return result


@app.delete("/api/projects/{project_id}/documents/{document_id}")
def delete_document(document_id: int, access: Access = Depends(project_access)):
    """Usuwa plik i jego nierozpatrzone propozycje. Zatwierdzone/odrzucone decyzje zostają."""
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        document = session.get(Document, document_id)
        if not document:
            raise HTTPException(404, "Nie znaleziono dokumentu")
        removed = imports.detach_document(session, document.id)
        imports.recompute_conflicts(session)
        session.add(ProjectEvent(user_id=access.user.id, action="delete", entity="document", entity_id=document.id, details=document.filename))
        session.delete(document)
        session.commit()
    return {"ok": True, "removed_suggestions": removed}


class SuggestionUpdate(BaseModel):
    status: Literal["nowa", "zatwierdzona", "odrzucona"] | None = None
    payload: dict | None = None


class BulkStatus(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=2000)
    status: Literal["nowa", "zatwierdzona", "odrzucona"]
    group: str | None = Field(default=None, max_length=60)  # typ konstrukcji dla pozycji BOM bez typu


def set_status(session, item: Suggestion, status: str, user_id: int, reapply: bool = False, confirm_only: bool = False):
    """Zmiana decyzji z jej skutkami w strukturze budowy. ApplyError = nic nie zostało zmienione."""
    if item.status == "zatwierdzona" and (status != "zatwierdzona" or reapply):
        structure.revert_suggestion(session, item)
        item.applied_ref = ""
    if status == "zatwierdzona" and (item.status != "zatwierdzona" or reapply):
        item.applied_ref = structure.apply_suggestion(session, item, user_id, confirm_only)
    item.status = status
    item.reviewed_by = user_id if status != "nowa" else None
    item.reviewed_at = now() if status != "nowa" else None
    item.updated_at = now()


@app.get("/api/projects/{project_id}/suggestions")
def list_suggestions(kind: str | None = None, status: str | None = None, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        query = select(Suggestion).order_by(Suggestion.kind, Suggestion.id)
        if kind:
            query = query.where(Suggestion.kind == kind)
        if status:
            query = query.where(Suggestion.status == status)
        return [suggestion_dict(item) for item in session.scalars(query).all()]


@app.patch("/api/projects/{project_id}/suggestions/{suggestion_id}")
def update_suggestion(suggestion_id: int, data: SuggestionUpdate, access: Access = Depends(project_access)):
    """Zatwierdź / odrzuć / popraw propozycję. Poprawione wartości nie zostaną nadpisane przy ponownej analizie."""
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = session.get(Suggestion, suggestion_id)
        if not item:
            raise HTTPException(404, "Nie znaleziono propozycji")
        details = {"klucz": item.key}
        changes = {}
        if data.payload:
            try:
                changes = imports.clean_payload(item.kind, data.payload)
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
            payload = imports.loads(item.payload_json, {})
            payload.update(changes)
            item.payload_json = imports.dumps(payload)
            item.edited = True
            details["poprawki"] = changes
        target = data.status or item.status
        try:
            # Poprawka zatwierdzonej propozycji = cofnięcie i ponowne zastosowanie z nowymi wartościami.
            set_status(session, item, target, access.user.id, reapply=bool(changes) and target == "zatwierdzona")
        except structure.ApplyError as error:
            session.rollback()
            raise HTTPException(409, str(error)) from None
        if data.status:
            details["status"] = data.status
        imports.recompute_conflicts(session)
        session.add(ProjectEvent(user_id=access.user.id, action="review", entity="suggestion", entity_id=item.id, details=imports.dumps(details)))
        session.commit()
        return suggestion_dict(item)


@app.post("/api/projects/{project_id}/suggestions/bulk")
def bulk_suggestions(data: BulkStatus, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        items = session.scalars(select(Suggestion).where(Suggestion.id.in_(data.ids)).order_by(Suggestion.id)).all()
        updated, failed = 0, []
        group = structure.normalize_type_code(data.group) if data.group else ""
        target = session.scalar(select(StructureType).where(StructureType.code == group)) if group else None
        confirm_only = target is not None and bool(session.scalar(select(func.count(BomItem.id)).where(BomItem.structure_type_id == target.id)))
        for item in items:
            try:
                # Każda pozycja w osobnym punkcie zapisu: odmowa jednej nie cofa pozostałych.
                with session.begin_nested():
                    if group and item.kind == "bom_line":
                        payload = imports.loads(item.payload_json, {})
                        if payload.get("group") != group:
                            payload["group"] = group
                            item.payload_json = imports.dumps(payload)
                            item.edited = True
                    set_status(session, item, data.status, access.user.id, reapply=bool(group) and item.kind == "bom_line",
                               confirm_only=confirm_only and item.kind == "bom_line")
                updated += 1
            except structure.ApplyError as error:
                failed.append({"id": item.id, "kind": item.kind, "reason": str(error)})
        imports.recompute_conflicts(session)
        session.add(ProjectEvent(user_id=access.user.id, action="review-bulk", entity="suggestion", entity_id=None,
                                 details=imports.dumps({"status": data.status, "liczba": updated, "odmowy": len(failed), **({"typ": group} if group else {})})))
        session.commit()
        return {"updated": updated, "failed": failed}


# --- API: struktura budowy (etap 3) ---------------------------------------------------------------

class TypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    modules: int = Field(default=0, ge=0, le=10000)
    posts_per_table: int | None = Field(default=None, ge=0, le=1000)
    description: str = Field(default="", max_length=2000)


class TypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=60)
    modules: int | None = Field(default=None, ge=0, le=10000)
    posts_per_table: int | None = Field(default=None, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=2000)


class BomIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(default="", max_length=120)
    spec: str = Field(default="", max_length=160)
    quantity: float = Field(ge=0, le=1_000_000)
    unit: str = Field(default="szt.", min_length=1, max_length=20)


class RowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    zone_id: int | None = None


class RangeIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z]{1,10}$")
    first: int = Field(ge=0, le=100000)
    last: int = Field(ge=0, le=100000)
    structure_type_id: int | None = None  # nowe stoły od razu z typem (np. liczba stołów z BOM)


class AssignIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    zone_id: int | None = None
    row_id: int | None = None
    structure_type_id: int | None = None


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)


def bom_dict(item: BomItem):
    return {"id": item.id, "structure_type_id": item.structure_type_id, "name": item.name, "code": item.code, "spec": item.spec,
            "quantity": item.quantity, "unit": item.unit, "from_pdf": item.source_suggestion_id is not None}


def table_dict(item: SiteTable, notes: int = 0, photos: int = 0):
    return {"id": item.id, "code": item.code, "prefix": item.prefix, "number": item.number, "zone_id": item.zone_id, "row_id": item.row_id,
            "structure_type_id": item.structure_type_id, "from_pdf": item.source_suggestion_id is not None,
            "built": bool(item.built), "built_at": item.built_at, "qc_checked": bool(item.qc_checked), "qc_at": item.qc_at,
            "last_changed_at": item.last_changed_at, "notes": notes, "photos": photos}


def project_event(session, access: Access, action: str, entity: str, entity_id, details):
    session.add(ProjectEvent(user_id=access.user.id, action=action, entity=entity, entity_id=entity_id,
                             details=details if isinstance(details, str) else imports.dumps(details)))


def get_or_404(session, model, item_id: int, message: str):
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(404, message)
    return item


@app.get("/api/projects/{project_id}/types")
def list_types(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        counts = dict(session.execute(select(SiteTable.structure_type_id, func.count(SiteTable.id)).group_by(SiteTable.structure_type_id)).all())
        boms = {}
        for item in session.scalars(select(BomItem).order_by(BomItem.id)).all():
            boms.setdefault(item.structure_type_id, []).append(bom_dict(item))
        return [{"id": t.id, "code": t.code, "modules": t.modules, "posts_per_table": t.posts_per_table, "planned_tables": t.planned_tables, "description": t.description,
                 "from_pdf": t.source_suggestion_id is not None, "tables": counts.get(t.id, 0), "bom": boms.get(t.id, [])}
                for t in session.scalars(select(StructureType).order_by(StructureType.code)).all()]


@app.post("/api/projects/{project_id}/types")
def create_type(data: TypeIn, access: Access = Depends(project_access)):
    writable(access)
    code = structure.normalize_type_code(data.code)
    with tenancy.project_session(access.project.storage_key) as session:
        if session.scalar(select(StructureType).where(StructureType.code == code)):
            raise HTTPException(409, f"Typ {code} już istnieje")
        item = StructureType(code=code, modules=data.modules or structure.modules_of(code), posts_per_table=data.posts_per_table, description=data.description.strip())
        session.add(item)
        session.flush()
        project_event(session, access, "create", "type", item.id, code)
        session.commit()
        return {"id": item.id}


@app.patch("/api/projects/{project_id}/types/{type_id}")
def update_type(type_id: int, data: TypeUpdate, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, StructureType, type_id, "Nie znaleziono typu konstrukcji")
        values = data.model_dump(exclude_unset=True)
        if "code" in values:
            code = structure.normalize_type_code(values["code"])
            if code != item.code and session.scalar(select(StructureType).where(StructureType.code == code)):
                raise HTTPException(409, f"Typ {code} już istnieje")
            values["code"] = code
        for field, value in values.items():
            if field == "modules" and value is None:
                continue
            setattr(item, field, value.strip() if isinstance(value, str) else value)
        project_event(session, access, "update", "type", item.id, values)
        session.commit()
        return {"ok": True}


@app.delete("/api/projects/{project_id}/types/{type_id}")
def delete_type(type_id: int, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, StructureType, type_id, "Nie znaleziono typu konstrukcji")
        used = session.scalar(select(func.count(SiteTable.id)).where(SiteTable.structure_type_id == item.id)) or 0
        if used:
            raise HTTPException(409, f"Typ {item.code} ma przypisane {used} stołów — najpierw zmień ich typ")
        for bom in session.scalars(select(BomItem).where(BomItem.structure_type_id == item.id)).all():
            session.delete(bom)
        project_event(session, access, "delete", "type", item.id, item.code)
        session.delete(item)
        session.commit()
    return {"ok": True}


@app.post("/api/projects/{project_id}/types/{type_id}/bom")
def create_bom(type_id: int, data: BomIn, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        parent = get_or_404(session, StructureType, type_id, "Nie znaleziono typu konstrukcji")
        identity, same_spec = structure.same_item(BomItem, data.code.strip(), data.name.strip(), data.spec.strip())
        if session.scalar(select(BomItem).where(BomItem.structure_type_id == parent.id, identity, same_spec)):
            raise HTTPException(409, f"Typ {parent.code} ma już tę pozycję — popraw jej ilość zamiast dodawać drugą")
        item = BomItem(structure_type_id=parent.id, name=data.name.strip(), code=data.code.strip(), spec=data.spec.strip(), quantity=data.quantity, unit=data.unit.strip())
        session.add(item)
        session.flush()
        project_event(session, access, "create", "bom", item.id, f"{parent.code}: {item.name} × {item.quantity:g}")
        session.commit()
        return bom_dict(item)


@app.patch("/api/projects/{project_id}/bom/{bom_id}")
def update_bom(bom_id: int, data: BomIn, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, BomItem, bom_id, "Nie znaleziono pozycji BOM")
        before = item.quantity
        item.name, item.code, item.spec, item.quantity, item.unit = data.name.strip(), data.code.strip(), data.spec.strip(), data.quantity, data.unit.strip()
        project_event(session, access, "update", "bom", item.id, {"pozycja": item.name, "ilość przed": before, "ilość po": item.quantity})
        session.commit()
        return bom_dict(item)


@app.delete("/api/projects/{project_id}/bom/{bom_id}")
def delete_bom(bom_id: int, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, BomItem, bom_id, "Nie znaleziono pozycji BOM")
        project_event(session, access, "delete", "bom", item.id, item.name)
        session.delete(item)
        session.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/rows")
def list_rows(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        counts = dict(session.execute(select(SiteTable.row_id, func.count(SiteTable.id)).group_by(SiteTable.row_id)).all())
        return [{"id": r.id, "name": r.name, "zone_id": r.zone_id, "tables": counts.get(r.id, 0)}
                for r in session.scalars(select(SiteRow).order_by(SiteRow.zone_id, SiteRow.sort_order, SiteRow.id)).all()]


def check_zone(session, zone_id):
    if zone_id is not None and session.get(Zone, zone_id) is None:
        raise HTTPException(404, "Nie znaleziono strefy")


@app.post("/api/projects/{project_id}/rows")
def create_row(data: RowIn, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        check_zone(session, data.zone_id)
        name = data.name.strip()
        duplicate = select(SiteRow).where(func.lower(SiteRow.name) == name.lower(), SiteRow.zone_id.is_(None) if data.zone_id is None else SiteRow.zone_id == data.zone_id)
        if session.scalar(duplicate):
            raise HTTPException(409, "Rząd o tej nazwie już istnieje w tej strefie")
        order = (session.scalar(select(func.max(SiteRow.sort_order))) or 0) + 1
        item = SiteRow(name=name, zone_id=data.zone_id, sort_order=order)
        session.add(item)
        session.flush()
        project_event(session, access, "create", "row", item.id, name)
        session.commit()
        return {"id": item.id, "name": item.name, "zone_id": item.zone_id, "tables": 0}


@app.patch("/api/projects/{project_id}/rows/{row_id}")
def update_row(row_id: int, data: RowIn, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, SiteRow, row_id, "Nie znaleziono rzędu")
        check_zone(session, data.zone_id)
        item.name, item.zone_id = data.name.strip(), data.zone_id
        # Stoły rzędu idą za rzędem do jego strefy — rząd nie może leżeć w dwóch strefach.
        for table in session.scalars(select(SiteTable).where(SiteTable.row_id == item.id)).all():
            table.zone_id = item.zone_id
        project_event(session, access, "update", "row", item.id, item.name)
        session.commit()
        return {"ok": True}


@app.delete("/api/projects/{project_id}/rows/{row_id}")
def delete_row(row_id: int, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, SiteRow, row_id, "Nie znaleziono rzędu")
        for table in session.scalars(select(SiteTable).where(SiteTable.row_id == item.id)).all():
            table.row_id = None
        project_event(session, access, "delete", "row", item.id, item.name)
        session.delete(item)
        session.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/tables")
def list_tables(zone_id: int | None = None, row_id: int | None = None, type_id: int | None = None, q: str = "", unassigned: bool = False,
                access: Access = Depends(project_access)):
    """Filtry: zone_id/row_id/type_id = 0 oznacza „bez przypisania”."""
    with tenancy.project_session(access.project.storage_key) as session:
        notes = dict(session.execute(select(TableNote.table_id, func.count(TableNote.id)).group_by(TableNote.table_id)).all())
        photos = dict(session.execute(select(Photo.table_id, func.count(Photo.id)).group_by(Photo.table_id)).all())
        return [table_dict(item, notes.get(item.id, 0), photos.get(item.id, 0)) for item in structure.find_tables(session, zone_id, row_id, type_id, q, unassigned)]


@app.post("/api/projects/{project_id}/tables/range")
def add_tables(data: RangeIn, access: Access = Depends(project_access)):
    """Ręczne dodanie stołów (np. gdy rysunek jest skanem): prefiks + zakres numerów. Istniejące są pomijane."""
    writable(access)
    if data.last < data.first:
        raise HTTPException(400, "Numer „do” musi być większy lub równy „od”")
    if data.last - data.first + 1 > structure.MAX_TABLES_FROM_NUMBERING:
        raise HTTPException(400, f"Najwyżej {structure.MAX_TABLES_FROM_NUMBERING} stołów naraz")
    prefix = data.prefix.upper()
    with tenancy.project_session(access.project.storage_key) as session:
        if data.structure_type_id is not None:
            get_or_404(session, StructureType, data.structure_type_id, "Nie znaleziono typu konstrukcji")
        codes = {structure.table_code(prefix, n): n for n in range(data.first, data.last + 1)}
        existing = set(session.scalars(select(SiteTable.code).where(SiteTable.code.in_(list(codes)))).all())
        for code, number in codes.items():
            if code not in existing:
                session.add(SiteTable(code=code, prefix=prefix, number=number, structure_type_id=data.structure_type_id))
        added = len(codes) - len(existing)
        project_event(session, access, "create", "tables", None, f"{prefix} {data.first}–{data.last} (+{added})")
        session.commit()
    return {"added": added, "skipped": len(existing)}


@app.post("/api/projects/{project_id}/tables/assign")
def assign_tables(data: AssignIn, access: Access = Depends(project_access)):
    """Przypisanie zaznaczonych stołów: tylko pola podane w żądaniu (null = usuń przypisanie)."""
    writable(access)
    fields = data.model_fields_set - {"ids"}
    if not fields:
        raise HTTPException(400, "Wybierz strefę, rząd lub typ do przypisania")
    with tenancy.project_session(access.project.storage_key) as session:
        if "zone_id" in fields:
            check_zone(session, data.zone_id)
        row = session.get(SiteRow, data.row_id) if data.row_id is not None else None
        if "row_id" in fields and data.row_id is not None and row is None:
            raise HTTPException(404, "Nie znaleziono rzędu")
        if "structure_type_id" in fields and data.structure_type_id is not None and session.get(StructureType, data.structure_type_id) is None:
            raise HTTPException(404, "Nie znaleziono typu konstrukcji")
        if row is not None and "zone_id" in fields and row.zone_id is not None and data.zone_id != row.zone_id:
            raise HTTPException(409, "Wybrany rząd należy do innej strefy")
        tables = session.scalars(select(SiteTable).where(SiteTable.id.in_(data.ids))).all()
        for table in tables:
            if "zone_id" in fields:
                table.zone_id = data.zone_id
                if table.row_id is not None and "row_id" not in fields:
                    current = session.get(SiteRow, table.row_id)
                    if current is not None and current.zone_id not in (None, data.zone_id):
                        table.row_id = None  # stół przeniesiony do innej strefy wychodzi z rzędu tamtej strefy
            if "row_id" in fields:
                table.row_id = data.row_id
                if row is not None and row.zone_id is not None:
                    table.zone_id = row.zone_id
            if "structure_type_id" in fields:
                table.structure_type_id = data.structure_type_id
        project_event(session, access, "assign", "tables", None, {"liczba": len(tables), **{f: getattr(data, f) for f in fields}})
        session.commit()
    return {"updated": len(tables)}


@app.post("/api/projects/{project_id}/tables/delete")
def delete_tables(data: IdsIn, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        tables = session.scalars(select(SiteTable).where(SiteTable.id.in_(data.ids))).all()
        with_work = structure.tables_with_field_data(session, [table.id for table in tables])
        if with_work:
            codes = ", ".join(sorted(table.code for table in tables if table.id in with_work)[:10])
            raise HTTPException(409, f"{len(with_work)} z zaznaczonych stołów ma zapisany postęp, notatki lub zdjęcia ({codes}) — odznacz je")
        for table in tables:
            session.delete(table)
        project_event(session, access, "delete", "tables", None, f"{len(tables)} stołów")
        session.commit()
    return {"deleted": len(tables)}


@app.get("/api/projects/{project_id}/catalog")
def list_catalog(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        items = session.scalars(select(CatalogItem).order_by(CatalogItem.kind, CatalogItem.name)).all()
        torques = session.scalars(select(TorqueSpec).order_by(TorqueSpec.bolt, TorqueSpec.min_nm)).all()
        return {"items": [{"id": i.id, "kind": i.kind, "name": i.name, "code": i.code, "spec": i.spec} for i in items],
                "torques": [{"id": t.id, "bolt": t.bolt, "min_nm": t.min_nm, "max_nm": t.max_nm, "context": t.context} for t in torques]}


@app.get("/api/projects/{project_id}/requirements")
def material_requirements(zone_id: int | None = None, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        return structure.requirements(session, zone_id)


# --- API: praca w terenie (etap 4a): postęp stołów, notatki, zdjęcia --------------------------------
#
# Zapisy z telefonu mogą przyjść z opóźnieniem (kolejka offline). client_time = moment wykonania
# czynności na telefonie; client_id = identyfikator nadany na telefonie (ponowna wysyłka nie dubluje).

MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_CLIENT_DELAY = timedelta(days=30)


def effective_time(client_time: datetime | None) -> datetime:
    """Czas z telefonu (UTC), ale nie z przyszłości i nie starszy niż 30 dni — wtedy czas serwera."""
    current = now()
    if client_time is None:
        return current
    value = client_time.astimezone(UTC).replace(tzinfo=None) if client_time.tzinfo else client_time
    return value if current - MAX_CLIENT_DELAY <= value <= current else current


def field_writable(access: Access):
    """Kierownik i brygadzista budowy zapisują postęp, notatki i zdjęcia."""
    if access.project.archived:
        raise HTTPException(409, "Budowa jest zarchiwizowana")


class ProgressIn(BaseModel):
    built: bool | None = None
    qc_checked: bool | None = None
    client_time: datetime | None = None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    client_id: str | None = Field(default=None, max_length=80)
    client_time: datetime | None = None


class NoteUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    client_time: datetime | None = None


def user_names(access: Access) -> dict[int, str]:
    return {user.id: user.full_name for user in access.db.scalars(select(User)).all()}


@app.patch("/api/projects/{project_id}/tables/{table_id}/progress")
def update_progress(table_id: int, data: ProgressIn, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        table = get_or_404(session, SiteTable, table_id, "Nie znaleziono stołu (mógł zostać usunięty)")
        when = effective_time(data.client_time)
        if data.built is not None:
            table.built, table.built_by, table.built_at = data.built, access.user.id if data.built else None, when if data.built else None
            if not data.built:  # cofnięcie montażu unieważnia odbiór
                table.qc_checked, table.qc_by, table.qc_at = False, None, None
        if data.qc_checked is not None:
            if not access.is_manager:
                raise HTTPException(403, "Odbiór QA/QC wykonuje kierownik budowy")
            if data.qc_checked and not table.built:
                raise HTTPException(400, "Najpierw oznacz stół jako zamontowany")
            table.qc_checked, table.qc_by, table.qc_at = data.qc_checked, access.user.id if data.qc_checked else None, when if data.qc_checked else None
        table.last_changed_by, table.last_changed_at = access.user.id, when
        project_event(session, access, "progress", "table", table.id, {"stół": table.code, **data.model_dump(exclude_unset=True, exclude={"client_time"})})
        session.commit()
        return table_dict(table)


@app.get("/api/projects/{project_id}/progress")
def progress_summary(zone_id: int | None = None, access: Access = Depends(project_access)):
    """Postęp: razem i w podziale na strefy, rzędy i typy (zamontowane / odebrane)."""
    with tenancy.project_session(access.project.storage_key) as session:
        query = select(SiteTable)
        if zone_id is not None:
            query = query.where(SiteTable.zone_id == zone_id) if zone_id else query.where(SiteTable.zone_id.is_(None))
        tables = session.scalars(query).all()
        zones = {z.id: z.name for z in session.scalars(select(Zone)).all()}
        rows = {r.id: r.name for r in session.scalars(select(SiteRow)).all()}
        types = {t.id: t.code for t in session.scalars(select(StructureType)).all()}

    def group(key, names):
        result = {}
        for table in tables:
            ident = getattr(table, key)
            entry = result.setdefault(ident, {"id": ident, "name": names.get(ident, "bez przypisania"), "total": 0, "built": 0, "qc": 0})
            entry["total"] += 1
            entry["built"] += bool(table.built)
            entry["qc"] += bool(table.qc_checked)
        return sorted(result.values(), key=lambda e: (e["id"] is None, e["name"]))

    return {"total": len(tables), "built": sum(bool(t.built) for t in tables), "qc": sum(bool(t.qc_checked) for t in tables),
            "zones": group("zone_id", zones), "rows": group("row_id", rows), "types": group("structure_type_id", types)}


@app.get("/api/projects/{project_id}/tables/{table_id}/notes")
def list_notes(table_id: int, access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        get_or_404(session, SiteTable, table_id, "Nie znaleziono stołu")
        notes = session.scalars(select(TableNote).where(TableNote.table_id == table_id).order_by(TableNote.created_at.desc(), TableNote.id.desc())).all()
        return [{"id": n.id, "text": n.text, "author_id": n.author_id, "author": names.get(n.author_id, "—"), "created_at": n.created_at,
                 "edited_at": n.edited_at, "edited_by": names.get(n.edited_by) if n.edited_by else None} for n in notes]


@app.post("/api/projects/{project_id}/tables/{table_id}/notes")
def create_note(table_id: int, data: NoteIn, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        if data.client_id:
            existing = session.scalar(select(TableNote).where(TableNote.client_id == data.client_id))
            if existing is not None:
                return {"id": existing.id, "duplicate": True}
        table = get_or_404(session, SiteTable, table_id, "Nie znaleziono stołu (mógł zostać usunięty)")
        text_value = data.text.strip()
        if not text_value:
            raise HTTPException(400, "Treść notatki jest wymagana")
        note = TableNote(client_id=data.client_id, table_id=table.id, text=text_value, author_id=access.user.id, created_at=effective_time(data.client_time))
        session.add(note)
        session.flush()
        project_event(session, access, "create", "note", note.id, f"{table.code}: {text_value[:120]}")
        session.commit()
        return {"id": note.id}


def editable_note(session, access: Access, table_id: int, note_id: int) -> TableNote:
    note = session.get(TableNote, note_id)
    if note is None or note.table_id != table_id:
        raise HTTPException(404, "Notatka nie istnieje (mogła zostać już usunięta)")
    if not access.is_manager and note.author_id != access.user.id:
        raise HTTPException(403, "Brygadzista może zmieniać tylko własne notatki")
    return note


@app.patch("/api/projects/{project_id}/tables/{table_id}/notes/{note_id}")
def update_note(table_id: int, note_id: int, data: NoteUpdate, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        note = editable_note(session, access, table_id, note_id)
        text_value = data.text.strip()
        if not text_value:
            raise HTTPException(400, "Treść notatki jest wymagana")
        if text_value != note.text:
            note.text, note.edited_at, note.edited_by = text_value, effective_time(data.client_time), access.user.id
            project_event(session, access, "update", "note", note.id, text_value[:120])
            session.commit()
        return {"ok": True}


@app.delete("/api/projects/{project_id}/tables/{table_id}/notes/{note_id}")
def delete_note(table_id: int, note_id: int, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        note = editable_note(session, access, table_id, note_id)
        project_event(session, access, "delete", "note", note.id, note.text[:120])
        session.delete(note)
        session.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/tables/{table_id}/photos")
def list_photos(table_id: int, access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        photos = session.scalars(select(Photo).where(Photo.table_id == table_id).order_by(Photo.created_at.desc(), Photo.id.desc())).all()
        return [{"id": p.id, "filename": p.filename, "size": p.size, "uploaded_by": p.uploaded_by, "author": names.get(p.uploaded_by, "—"), "created_at": p.created_at} for p in photos]


@app.post("/api/projects/{project_id}/tables/{table_id}/photos")
def upload_photo(table_id: int, file: UploadFile = File(...), client_id: str | None = Form(default=None, max_length=80),
                 client_time: datetime | None = Form(default=None), access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        if client_id:
            existing = session.scalar(select(Photo).where(Photo.client_id == client_id))
            if existing is not None:
                return {"id": existing.id, "duplicate": True}
        table = get_or_404(session, SiteTable, table_id, "Nie znaleziono stołu (mógł zostać usunięty)")
        mime = (file.content_type or "").lower()
        if mime not in PHOTO_TYPES:
            raise HTTPException(400, "Dozwolone są zdjęcia JPG, PNG, WEBP lub HEIC")
        content = file.file.read(MAX_PHOTO_BYTES + 1)
        if len(content) > MAX_PHOTO_BYTES:
            raise HTTPException(400, f"Zdjęcie większe niż {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
        photo = Photo(client_id=client_id, table_id=table.id, filename=Path(file.filename or "zdjecie.jpg").name[:255], mime_type=mime, size=len(content),
                      content=content, uploaded_by=access.user.id, created_at=effective_time(client_time))
        session.add(photo)
        session.flush()
        project_event(session, access, "create", "photo", photo.id, table.code)
        session.commit()
        return {"id": photo.id}


@app.get("/api/projects/{project_id}/photos/{photo_id}/file")
def photo_file(photo_id: int, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        photo = get_or_404(session, Photo, photo_id, "Nie znaleziono zdjęcia")
        return Response(photo.content, media_type=photo.mime_type, headers={"Cache-Control": "private, max-age=86400"})


@app.delete("/api/projects/{project_id}/photos/{photo_id}")
def delete_photo(photo_id: int, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        photo = get_or_404(session, Photo, photo_id, "Nie znaleziono zdjęcia (mogło zostać już usunięte)")
        if not access.is_manager and photo.uploaded_by != access.user.id:
            raise HTTPException(403, "Brygadzista może usuwać tylko własne zdjęcia")
        project_event(session, access, "delete", "photo", photo.id, photo.filename)
        session.delete(photo)
        session.commit()
    return {"ok": True}


# --- API: dostawy WZ, stan materiałów, meldunki (etap 4b) ------------------------------------------

class DeliveryItemIn(BaseModel):
    material_key: str = Field(min_length=1, max_length=400)
    quantity_received: float = Field(gt=0, le=10_000_000)
    quantity_damaged: float = Field(default=0, ge=0, le=10_000_000)


class DeliveryIn(BaseModel):
    delivery_date: date
    wz_number: str = Field(min_length=1, max_length=100)
    supplier: str = Field(default="", max_length=180)
    note: str = Field(default="", max_length=5000)
    client_id: str | None = Field(default=None, max_length=80)
    client_time: datetime | None = None
    items: list[DeliveryItemIn] = Field(min_length=1, max_length=500)


class WorkLogIn(BaseModel):
    work_date: date
    team: str = Field(min_length=1, max_length=120)
    stage: str = Field(min_length=1, max_length=5000)
    people: int = Field(ge=1, le=1000)
    hours: float = Field(gt=0, le=24)
    tables_completed: float = Field(default=0, ge=0, le=100000)
    table_id: int | None = None
    qc_notes: str = Field(default="", max_length=10000)
    note: str = Field(default="", max_length=10000)
    client_id: str | None = Field(default=None, max_length=80)
    client_time: datetime | None = None


def delivery_dict(item: Delivery, lines: list[DeliveryItem], names: dict):
    return {"id": item.id, "delivery_date": item.delivery_date, "wz_number": item.wz_number, "supplier": item.supplier, "note": item.note,
            "created_by": names.get(item.created_by, "—"), "created_at": item.created_at, "updated_by": names.get(item.updated_by) if item.updated_by else None,
            "updated_at": item.updated_at,
            "items": [{"material_key": l.material_key, "name": l.name, "code": l.code, "spec": l.spec, "unit": l.unit,
                       "quantity_received": l.quantity_received, "quantity_damaged": l.quantity_damaged} for l in lines]}


def delivery_lines(session, delivery: Delivery, items: list[DeliveryItemIn], known: dict):
    for line in items:
        info = known[line.material_key]
        session.add(DeliveryItem(delivery_id=delivery.id, material_key=line.material_key, name=info["name"], code=info.get("code", ""), spec=info.get("spec", ""),
                                 unit=info.get("unit", "szt."), quantity_received=line.quantity_received, quantity_damaged=line.quantity_damaged))


@app.get("/api/projects/{project_id}/materials")
def list_materials(access: Access = Depends(project_access)):
    """Katalog materiałów do wyboru w WZ (z zapotrzebowaniem, jeśli jest)."""
    with tenancy.project_session(access.project.storage_key) as session:
        needs = {line["key"]: line["total"] for line in structure.requirements(session)["totals"]}
        return [{**item, "required": needs.get(key, 0)} for key, item in logistics.catalogue(session).items()]


@app.get("/api/projects/{project_id}/stock")
def material_stock(zone_id: int | None = None, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        return logistics.stock(session, zone_id)


@app.get("/api/projects/{project_id}/deliveries")
def list_deliveries(access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        lines = defaultdict(list)
        for line in session.scalars(select(DeliveryItem).order_by(DeliveryItem.id)).all():
            lines[line.delivery_id].append(line)
        items = session.scalars(select(Delivery).order_by(Delivery.delivery_date.desc(), Delivery.id.desc())).all()
        return [delivery_dict(item, lines[item.id], names) for item in items]


@app.post("/api/projects/{project_id}/deliveries")
def create_delivery(data: DeliveryIn, access: Access = Depends(project_access)):
    """Przyjęcie WZ (kierownik lub brygadzista, także z kolejki offline — client_id bez duplikatów)."""
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        if data.client_id:
            existing = session.scalar(select(Delivery).where(Delivery.client_id == data.client_id))
            if existing is not None:
                return {"id": existing.id, "duplicate": True}
        try:
            known = logistics.validate_items(session, data.items)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        delivery = Delivery(client_id=data.client_id, delivery_date=data.delivery_date, wz_number=data.wz_number.strip(), supplier=data.supplier.strip(),
                            note=data.note.strip(), created_by=access.user.id, created_at=effective_time(data.client_time))
        session.add(delivery)
        session.flush()
        delivery_lines(session, delivery, data.items, known)
        project_event(session, access, "create", "delivery", delivery.id, f"WZ {delivery.wz_number} ({len(data.items)} poz.)")
        session.commit()
        return {"id": delivery.id}


@app.put("/api/projects/{project_id}/deliveries/{delivery_id}")
def update_delivery(delivery_id: int, data: DeliveryIn, access: Access = Depends(project_access)):
    """Edycja WZ (kierownik). Pozycje są zastępowane w całości; stan liczy się na bieżąco z pozycji."""
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        delivery = get_or_404(session, Delivery, delivery_id, "Nie znaleziono dostawy (mogła zostać usunięta)")
        old = session.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id == delivery.id)).all()
        previous = {l.material_key: {"name": l.name, "code": l.code, "spec": l.spec, "unit": l.unit} for l in old}
        try:
            known = logistics.validate_items(session, data.items, previous)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        before = {l.material_key: [l.quantity_received, l.quantity_damaged] for l in old}
        for line in old:
            session.delete(line)
        session.flush()
        delivery.delivery_date, delivery.wz_number, delivery.supplier, delivery.note = data.delivery_date, data.wz_number.strip(), data.supplier.strip(), data.note.strip()
        delivery.updated_by, delivery.updated_at = access.user.id, now()
        delivery_lines(session, delivery, data.items, known)
        project_event(session, access, "update", "delivery", delivery.id,
                      {"wz": delivery.wz_number, "przed": before, "po": {l.material_key: [l.quantity_received, l.quantity_damaged] for l in data.items}})
        session.commit()
        return {"id": delivery.id}


@app.delete("/api/projects/{project_id}/deliveries/{delivery_id}")
def delete_delivery(delivery_id: int, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        delivery = get_or_404(session, Delivery, delivery_id, "Nie znaleziono dostawy (mogła zostać już usunięta)")
        # Pozycje WZ i zdjęcia meldunków usuwa kaskada w bazie (ON DELETE CASCADE).
        project_event(session, access, "delete", "delivery", delivery.id, f"WZ {delivery.wz_number}")
        session.delete(delivery)
        session.commit()
    return {"ok": True}


def worklog_dict(item: WorkLog, names: dict, photos: int = 0):
    return {"id": item.id, "work_date": item.work_date, "team": item.team, "stage": item.stage, "people": item.people, "hours": item.hours,
            "manhours": round(item.people * item.hours, 2), "tables_completed": item.tables_completed, "table_id": item.table_id,
            "qc_notes": item.qc_notes, "note": item.note, "author_id": item.author_id, "author": names.get(item.author_id, "—"),
            "created_at": item.created_at, "updated_at": item.updated_at, "photos": photos}


def check_table(session, table_id):
    if table_id is not None and session.get(SiteTable, table_id) is None:
        raise HTTPException(404, "Nie znaleziono stołu wskazanego w meldunku")


@app.get("/api/projects/{project_id}/worklogs")
def list_worklogs(work_date: date | None = None, access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        query = select(WorkLog).order_by(WorkLog.work_date.desc(), WorkLog.id.desc())
        if work_date:
            query = query.where(WorkLog.work_date == work_date)
        photos = dict(session.execute(select(WorkLogPhoto.work_log_id, func.count(WorkLogPhoto.id)).group_by(WorkLogPhoto.work_log_id)).all())
        return [worklog_dict(item, names, photos.get(item.id, 0)) for item in session.scalars(query).all()]


@app.post("/api/projects/{project_id}/worklogs")
def create_worklog(data: WorkLogIn, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        if data.client_id:
            existing = session.scalar(select(WorkLog).where(WorkLog.client_id == data.client_id))
            if existing is not None:
                return {"id": existing.id, "duplicate": True}
        check_table(session, data.table_id)
        item = WorkLog(**data.model_dump(exclude={"client_time"}), author_id=access.user.id, created_at=effective_time(data.client_time))
        item.team, item.stage = item.team.strip(), item.stage.strip()
        session.add(item)
        session.flush()
        project_event(session, access, "create", "worklog", item.id, f"{item.work_date} · {item.team}")
        session.commit()
        return {"id": item.id}


@app.patch("/api/projects/{project_id}/worklogs/{worklog_id}")
def update_worklog(worklog_id: int, data: WorkLogIn, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, WorkLog, worklog_id, "Nie znaleziono meldunku (mógł zostać usunięty)")
        if not access.is_manager and item.author_id != access.user.id:
            raise HTTPException(403, "Brygadzista może zmieniać tylko własne meldunki")
        check_table(session, data.table_id)
        for field, value in data.model_dump(exclude={"client_id", "client_time"}).items():
            setattr(item, field, value.strip() if isinstance(value, str) else value)
        item.updated_at = effective_time(data.client_time)
        project_event(session, access, "update", "worklog", item.id, f"{item.work_date} · {item.team}")
        session.commit()
        return {"ok": True}


@app.delete("/api/projects/{project_id}/worklogs/{worklog_id}")
def delete_worklog(worklog_id: int, access: Access = Depends(project_access)):
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        item = get_or_404(session, WorkLog, worklog_id, "Nie znaleziono meldunku (mógł zostać już usunięty)")
        project_event(session, access, "delete", "worklog", item.id, f"{item.work_date} · {item.team}")
        session.delete(item)
        session.commit()
    return {"ok": True}


def save_worklog_photo(session, access: Access, worklog: WorkLog, file: UploadFile, client_id: str | None, client_time: datetime | None):
    if client_id:
        existing = session.scalar(select(WorkLogPhoto).where(WorkLogPhoto.client_id == client_id))
        if existing is not None:
            return {"id": existing.id, "duplicate": True}
    mime = (file.content_type or "").lower()
    if mime not in PHOTO_TYPES:
        raise HTTPException(400, "Dozwolone są zdjęcia JPG, PNG, WEBP lub HEIC")
    content = file.file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(400, f"Zdjęcie większe niż {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
    photo = WorkLogPhoto(client_id=client_id, work_log_id=worklog.id, filename=Path(file.filename or "zdjecie.jpg").name[:255], mime_type=mime,
                         size=len(content), content=content, uploaded_by=access.user.id, created_at=effective_time(client_time))
    session.add(photo)
    session.flush()
    project_event(session, access, "create", "worklog-photo", photo.id, f"meldunek {worklog.id}")
    session.commit()
    return {"id": photo.id}


@app.post("/api/projects/{project_id}/worklogs/{worklog_id}/photos")
def upload_worklog_photo(worklog_id: int, file: UploadFile = File(...), client_id: str | None = Form(default=None, max_length=80),
                         client_time: datetime | None = Form(default=None), access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        worklog = get_or_404(session, WorkLog, worklog_id, "Nie znaleziono meldunku (mógł zostać usunięty)")
        return save_worklog_photo(session, access, worklog, file, client_id, client_time)


@app.post("/api/projects/{project_id}/worklogs/by-client/{worklog_client_id}/photos")
def upload_worklog_photo_by_client(worklog_client_id: str, file: UploadFile = File(...), client_id: str | None = Form(default=None, max_length=80),
                                   client_time: datetime | None = Form(default=None), access: Access = Depends(project_access)):
    """Zdjęcie do meldunku utworzonego offline — telefon zna tylko client_id meldunku (kolejka wysyła meldunek wcześniej)."""
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        worklog = session.scalar(select(WorkLog).where(WorkLog.client_id == worklog_client_id))
        if worklog is None:
            raise HTTPException(404, "Meldunek tego zdjęcia nie dotarł jeszcze na serwer")
        return save_worklog_photo(session, access, worklog, file, client_id, client_time)


@app.get("/api/projects/{project_id}/worklogs/{worklog_id}/photos")
def list_worklog_photos(worklog_id: int, access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        photos = session.scalars(select(WorkLogPhoto).where(WorkLogPhoto.work_log_id == worklog_id).order_by(WorkLogPhoto.id)).all()
        return [{"id": p.id, "filename": p.filename, "size": p.size, "uploaded_by": p.uploaded_by, "author": names.get(p.uploaded_by, "—"), "created_at": p.created_at} for p in photos]


@app.get("/api/projects/{project_id}/worklog-photos/{photo_id}/file")
def worklog_photo_file(photo_id: int, access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        photo = get_or_404(session, WorkLogPhoto, photo_id, "Nie znaleziono zdjęcia")
        return Response(photo.content, media_type=photo.mime_type, headers={"Cache-Control": "private, max-age=86400"})


@app.delete("/api/projects/{project_id}/worklog-photos/{photo_id}")
def delete_worklog_photo(photo_id: int, access: Access = Depends(project_access)):
    field_writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        photo = get_or_404(session, WorkLogPhoto, photo_id, "Nie znaleziono zdjęcia (mogło zostać już usunięte)")
        if not access.is_manager and photo.uploaded_by != access.user.id:
            raise HTTPException(403, "Brygadzista może usuwać tylko własne zdjęcia")
        project_event(session, access, "delete", "worklog-photo", photo.id, photo.filename)
        session.delete(photo)
        session.commit()
    return {"ok": True}


# --- API: Planimetria, raport dzienny, pulpit (etap 4c) --------------------------------------------

class DocumentUpdate(BaseModel):
    category: Literal["auto", "bom", "rysunek", "instrukcja", "inne"]


def document_content(session, document_id: int) -> Document:
    document = get_or_404(session, Document, document_id, "Nie znaleziono dokumentu")
    _ = document.content  # kolumna odroczona — wczytaj, póki sesja jest otwarta
    return document


@app.patch("/api/projects/{project_id}/documents/{document_id}")
def update_document(document_id: int, data: DocumentUpdate, access: Access = Depends(project_access)):
    """Rodzaj dokumentu (np. „rysunek” — trafia na listę planów w Planimetrii)."""
    writable(access)
    with tenancy.project_session(access.project.storage_key) as session:
        document = get_or_404(session, Document, document_id, "Nie znaleziono dokumentu")
        document.category = data.category
        project_event(session, access, "update", "document", document.id, f"{document.filename}: {data.category}")
        session.commit()
        return document_dict(document)


@app.get("/api/projects/{project_id}/documents/{document_id}/plan")
def document_plan(document_id: int, page: int = Query(1, ge=1, le=10000), access: Access = Depends(project_access)):
    """Strona rysunku i znaczniki stołów w miejscach, gdzie ich oznaczenia są wydrukowane na rysunku."""
    with tenancy.project_session(access.project.storage_key) as session:
        document = document_content(session, document_id)
        tables = {t.code: {"id": t.id, "built": bool(t.built), "qc_checked": bool(t.qc_checked)} for t in session.scalars(select(SiteTable)).all()}
        try:
            info = plans.page_info(document.sha256, document.content, page)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except Exception as error:
            raise HTTPException(422, f"Nie udało się odczytać strony PDF ({type(error).__name__})") from None
    return {"document_id": document_id, "page": page, "pages": info["pages"], "width": info["width"], "height": info["height"],
            "has_text": info["has_text"], "codes_on_page": len(info["codes"]), **plans.markers(info, tables)}


@app.get("/api/projects/{project_id}/documents/{document_id}/pages/{page}.png")
def document_page_image(document_id: int, page: int, scale: float = Query(2.0, ge=0.5, le=plans.MAX_SCALE), access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        document = document_content(session, document_id)
        try:
            image = plans.render_png(document.sha256, document.content, page, scale)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except Exception as error:
            raise HTTPException(422, f"Nie udało się wyrenderować strony PDF ({type(error).__name__})") from None
    return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/projects/{project_id}/dashboard")
def project_dashboard(access: Access = Depends(project_access)):
    with tenancy.project_session(access.project.storage_key) as session:
        return report.dashboard(session)


@app.get("/api/projects/{project_id}/reports/daily")
def daily_report(report_date: date = Query(default_factory=date.today), access: Access = Depends(project_access)):
    names = user_names(access)
    with tenancy.project_session(access.project.storage_key) as session:
        content = report.daily_report(session, access.project, names, report_date)
    filename = f"ASOLAR-raport-{report_date.isoformat()}.pdf"
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --- API: konta (administrator)-----------------------------------------------------------------

class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8, max_length=200)
    is_admin: bool = False


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    active: bool | None = None
    is_admin: bool | None = None


@app.get("/api/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(registry_db)):
    """Administrator widzi wszystko; kierownik budowy — listę kont do dodania do zespołu."""
    manages = user.is_admin or db.scalar(select(Membership.id).where(Membership.user_id == user.id, Membership.role == "kierownik").limit(1))
    if not manages:
        raise HTTPException(403, "Brak uprawnień")
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return [user_dict(item) for item in users if user.is_admin or item.active]


@app.post("/api/users")
def create_user(data: UserIn, user: User = Depends(admin_only), db: Session = Depends(registry_db)):
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(409, "Login już istnieje")
    item = User(username=data.username, full_name=data.full_name.strip(), password_hash=hash_password(data.password), is_admin=data.is_admin)
    db.add(item)
    log(db, user, "user-create", data.username, {"admin": data.is_admin})
    db.commit()
    return user_dict(item)


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, user: User = Depends(admin_only), db: Session = Depends(registry_db)):
    item = db.get(User, user_id)
    if not item:
        raise HTTPException(404, "Brak konta")
    if item.id == user.id and (data.active is False or data.is_admin is False):
        raise HTTPException(400, "Nie możesz odebrać uprawnień własnemu kontu")
    if data.full_name is not None:
        item.full_name = data.full_name.strip()
    if data.password:
        item.password_hash = hash_password(data.password)
    if data.active is not None:
        item.active = data.active
    if data.is_admin is not None:
        item.is_admin = data.is_admin
    log(db, user, "user-update", item.username, data.model_dump(exclude_none=True, exclude={"password"}))
    db.commit()
    return user_dict(item)


# --- frontend -----------------------------------------------------------------------------------

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND.exists():
    if (FRONTEND / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Nie znaleziono")
        target = FRONTEND / full_path
        if full_path and target.is_file() and FRONTEND.resolve() in target.resolve().parents:
            return FileResponse(target, headers={"Cache-Control": "no-cache"} if full_path in ("sw.js", "manifest.json") else None)
        if Path(full_path).suffix:
            raise HTTPException(404, "Brak pliku")
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
