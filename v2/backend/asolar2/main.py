"""ASOLAR v2 — serwer wielu budów (etap 1: rejestr, izolowane przestrzenie budów, konta i role)."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import APP_VERSION, IS_POSTGRES, SERVER_MODE
from .registry import Membership, Project, RegistryEvent, RegistrySession, User, init_registry, now
from .security import create_token, decode_token, hash_password, verify_password
from . import tenancy
from .tenancy import ProjectEvent, Zone

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
        for project in db.scalars(select(Project)).all():
            if project.storage_key:
                tenancy.create_storage(project.storage_key)


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
        last = session.scalar(select(func.max(ProjectEvent.created_at)))
    return {"zones": zones, "members": len(project.memberships), "last_activity": last}


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


# --- API: konta (administrator) -----------------------------------------------------------------

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
