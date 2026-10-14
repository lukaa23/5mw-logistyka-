import json, math, mimetypes, os, shutil, uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session, selectinload
from .auth import create_token, current_user, decode_token, hash_password, roles, verify_password
from .database import Base, SessionLocal, UPLOAD_DIR, engine, get_db
from .models import Attachment, AuditEvent, Component, ConstructionRow, Delivery, DeliveryItem, Document, Project, RFI, RowType, RowTypeComponent, Section, User, WorkLog, Zone
from .services.parser import analyze
from .services.report import daily_report

app=FastAPI(title="ASOLAR Enterprise Construction & Logistics Manager",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
MAX_DOCUMENT_SIZE=int(os.getenv("ASOLAR_MAX_DOCUMENT_MB","100"))*1024*1024
MAX_PHOTO_SIZE=25*1024*1024

def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)

class LoginIn(BaseModel): username:str; password:str
class UserIn(BaseModel): username:str; full_name:str; role:str; password:str=Field(min_length=8)
class ProjectIn(BaseModel): name:str; location:str=""; capacity_mw:float=0
class ZoneIn(BaseModel): project_id:int; name:str
class SectionIn(BaseModel): zone_id:int; name:str
class RowsIn(BaseModel): section_id:int; prefix:str="R"; start_number:int=1; count:int=Field(ge=1,le=2000); row_type_id:int|None=None; length_m:float=0
class RowStatusIn(BaseModel): built:bool|None=None; qc_checked:bool|None=None; note:str|None=None
class RFIIn(BaseModel): project_id:int; row_id:int|None=None; title:str; description:str; priority:str="normalny"; client_id:str|None=None
class RFIUpdate(BaseModel): status:str|None=None; assigned_to_id:int|None=None; priority:str|None=None
class WorkLogIn(BaseModel): project_id:int; work_date:date=Field(default_factory=date.today); team:str; stage:str; people:int=Field(ge=1,le=1000); hours:float=Field(gt=0,le=24); rows_completed:float=Field(ge=0); note:str=""; client_id:str|None=None
class DeliveryItemIn(BaseModel): component_id:int; quantity_received:float=Field(gt=0); quantity_damaged:float=Field(ge=0,default=0)
class DeliveryIn(BaseModel): project_id:int; delivery_date:date=Field(default_factory=date.today); wz_number:str; supplier:str=""; note:str=""; client_id:str|None=None; items:list[DeliveryItemIn]
class CalculatorIn(BaseModel): row_type_id:int; length_m:float=Field(gt=0,le=500); row_count:int=Field(ge=1,le=5000)

def audit(db,user,action,entity_type,entity_id=None,details=""):
    db.add(AuditEvent(user_id=user.id if user else None,action=action,entity_type=entity_type,entity_id=entity_id,details=details))

def user_dict(user): return {"id":user.id,"username":user.username,"full_name":user.full_name,"role":user.role,"active":user.active}
def row_dict(row):
    return {"id":row.id,"code":row.code,"section_id":row.section_id,"row_type_id":row.row_type_id,"row_type":row.row_type.name if row.row_type else None,"length_m":row.length_m,"built":row.built,"built_by":row.built_by.full_name if row.built_by else None,"built_at":row.built_at,"qc_checked":row.qc_checked,"qc_by":row.qc_by.full_name if row.qc_by else None,"qc_at":row.qc_at,"note":row.note}

class Realtime:
    def __init__(self): self.clients=[]
    async def connect(self,ws): await ws.accept(); self.clients.append(ws)
    def disconnect(self,ws):
        if ws in self.clients:self.clients.remove(ws)
    async def send(self,event,payload=None):
        for ws in list(self.clients):
            try: await ws.send_json({"event":event,"payload":payload or {},"at":utc_now().isoformat()})
            except Exception:self.disconnect(ws)
realtime=Realtime()

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.scalar(select(func.count(User.id))):
            db.add_all([
                User(username="kierownik",full_name="Kierownik Budowy",role="kierownik",password_hash=hash_password("Asolar2026!")),
                User(username="brygadzista",full_name="Brygadzista",role="brygadzista",password_hash=hash_password("Brygada2026!")),
                User(username="magazynier",full_name="Magazynier",role="magazynier",password_hash=hash_password("Magazyn2026!"))])
        project=db.scalar(select(Project).limit(1))
        if not project:
            project=Project(name="Farma PV 6,5 MW",location="Projekt budowy",capacity_mw=6.5); db.add(project); db.flush()
            zone=Zone(project_id=project.id,name="Strefa A"); db.add(zone); db.flush(); db.add(Section(zone_id=zone.id,name="Sekcja A1"))
        presets=[("1P×28",38.459,30),("1P×42",57.946,44),("1P×56",77.080,58),("1P×70",95.481,73)]
        for name,length,purlins in presets:
            row_type=db.scalar(select(RowType).where(RowType.name==name))
            if not row_type:
                row_type=RowType(name=name,structure_kind="tracker 1-noga",reference_length_m=length,description="Wariant referencyjny z manual v.2"); db.add(row_type); db.flush()
            seed_components=[(f"PURLIN-{name}","Płatew","Konstrukcja",purlins),(f"UBOLT-{name}","Śruba U M10","Śruby",purlins),(f"NUT-M10-{name}","Nakrętka kołnierzowa M10","Śruby",purlins*2)]
            for sku,cname,cat,qty in seed_components:
                comp=db.scalar(select(Component).where(Component.sku==sku))
                if not comp:
                    comp=Component(sku=sku,name=cname,category=cat,unit="szt.",torque_min_nm=25 if "NUT" in sku else None,torque_max_nm=32 if "NUT" in sku else None); db.add(comp); db.flush()
                if not db.scalar(select(RowTypeComponent).where(RowTypeComponent.row_type_id==row_type.id,RowTypeComponent.component_id==comp.id)):
                    db.add(RowTypeComponent(row_type_id=row_type.id,component_id=comp.id,quantity=qty))
        db.commit()
seed()

@app.get("/api/health")
def health(): return {"status":"ok","version":"2.0.0","time":utc_now()}

@app.post("/api/auth/login")
def login(data:LoginIn,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.username==data.username))
    if not user or not verify_password(data.password,user.password_hash): raise HTTPException(401,"Nieprawidłowy login lub hasło")
    return {"token":create_token(user),"user":user_dict(user)}

@app.get("/api/auth/me")
def me(user=Depends(current_user)): return user_dict(user)

@app.get("/api/users")
def users(db:Session=Depends(get_db),user=Depends(roles("kierownik"))): return [user_dict(x) for x in db.scalars(select(User).order_by(User.full_name))]

@app.post("/api/users")
def create_user(data:UserIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    if data.role not in ("kierownik","brygadzista","magazynier"): raise HTTPException(400,"Nieznana rola")
    if db.scalar(select(User).where(User.username==data.username)): raise HTTPException(409,"Login już istnieje")
    item=User(username=data.username,full_name=data.full_name,role=data.role,password_hash=hash_password(data.password));db.add(item);db.commit();return user_dict(item)

@app.get("/api/projects")
def projects(db:Session=Depends(get_db),user=Depends(current_user)):
    return [{"id":x.id,"name":x.name,"location":x.location,"capacity_mw":x.capacity_mw} for x in db.scalars(select(Project).order_by(Project.name))]

@app.post("/api/projects")
async def create_project(data:ProjectIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Project(**data.model_dump());db.add(item);db.flush();audit(db,user,"create","project",item.id,item.name);db.commit();await realtime.send("project.changed",{"id":item.id});return {"id":item.id}

@app.get("/api/projects/{project_id}/tree")
def project_tree(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    project=db.scalar(select(Project).where(Project.id==project_id).options(selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.row_type),selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.built_by),selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.qc_by)))
    if not project: raise HTTPException(404,"Brak projektu")
    return {"id":project.id,"name":project.name,"location":project.location,"capacity_mw":project.capacity_mw,"zones":[{"id":z.id,"name":z.name,"sections":[{"id":s.id,"name":s.name,"archived":s.archived,"rows":[row_dict(r) for r in s.rows]} for s in z.sections]} for z in project.zones]}

@app.post("/api/zones")
async def create_zone(data:ZoneIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Zone(**data.model_dump());db.add(item);db.flush();audit(db,user,"create","zone",item.id,item.name);db.commit();await realtime.send("structure.changed",{"project_id":data.project_id});return {"id":item.id}

@app.post("/api/sections")
async def create_section(data:SectionIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Section(**data.model_dump());db.add(item);db.flush();audit(db,user,"create","section",item.id,item.name);db.commit();await realtime.send("structure.changed");return {"id":item.id}

@app.post("/api/rows/bulk")
async def create_rows(data:RowsIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    section=db.get(Section,data.section_id)
    if not section: raise HTTPException(404,"Brak sekcji")
    created=[]
    for i in range(data.start_number,data.start_number+data.count):
        code=f"{data.prefix}{i:03d}"
        if db.scalar(select(ConstructionRow).where(ConstructionRow.section_id==data.section_id,ConstructionRow.code==code)): continue
        row=ConstructionRow(section_id=data.section_id,row_type_id=data.row_type_id,code=code,length_m=data.length_m);db.add(row);db.flush();created.append(row.id)
    audit(db,user,"bulk_create","row",details=f"{len(created)} rzędów");db.commit();await realtime.send("structure.changed");return {"created":len(created),"ids":created}

@app.patch("/api/rows/{row_id}")
async def update_row(row_id:int,data:RowStatusIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    row=db.get(ConstructionRow,row_id)
    if not row: raise HTTPException(404,"Brak rzędu")
    now=utc_now()
    if data.built is not None:
        row.built=data.built;row.built_by_id=user.id if data.built else None;row.built_at=now if data.built else None
        if not data.built: row.qc_checked=False;row.qc_by_id=None;row.qc_at=None
    if data.qc_checked is not None:
        if user.role!="kierownik": raise HTTPException(403,"Odbiór QA/QC wykonuje Kierownik Budowy")
        if data.qc_checked and not row.built: raise HTTPException(400,"Najpierw oznacz rząd jako zbudowany")
        row.qc_checked=data.qc_checked;row.qc_by_id=user.id if data.qc_checked else None;row.qc_at=now if data.qc_checked else None
    if data.note is not None: row.note=data.note
    audit(db,user,"update_status","row",row.id,json.dumps(data.model_dump(exclude_none=True),ensure_ascii=False));db.commit();await realtime.send("row.changed",{"id":row.id});db.refresh(row);return row_dict(row)

@app.post("/api/sections/{section_id}/archive")
async def archive_section(section_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    section=db.get(Section,section_id)
    if not section: raise HTTPException(404,"Brak sekcji")
    unfinished=db.scalar(select(func.count(ConstructionRow.id)).where(ConstructionRow.section_id==section_id,ConstructionRow.qc_checked==False))
    if unfinished: raise HTTPException(409,f"Pozostało {unfinished} rzędów bez odbioru QA/QC")
    section.archived=True;section.archived_at=utc_now();audit(db,user,"archive","section",section.id);db.commit();await realtime.send("structure.changed");return {"ok":True}

@app.get("/api/row-types")
def row_types(db:Session=Depends(get_db),user=Depends(current_user)):
    return [{"id":x.id,"name":x.name,"structure_kind":x.structure_kind,"reference_length_m":x.reference_length_m,"description":x.description} for x in db.scalars(select(RowType).order_by(RowType.name))]

def requirements_query(db,project_id=None,section_id=None):
    statement=select(Component,func.sum(RowTypeComponent.quantity).label("required"),func.count(ConstructionRow.id).label("rows")).join(RowTypeComponent,RowTypeComponent.component_id==Component.id).join(ConstructionRow,ConstructionRow.row_type_id==RowTypeComponent.row_type_id).join(Section,Section.id==ConstructionRow.section_id).join(Zone,Zone.id==Section.zone_id).group_by(Component.id)
    if project_id: statement=statement.where(Zone.project_id==project_id)
    if section_id: statement=statement.where(Section.id==section_id)
    return statement

@app.get("/api/requirements")
def requirements(project_id:int|None=None,section_id:int|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    return [{"component_id":c.id,"sku":c.sku,"name":c.name,"category":c.category,"unit":c.unit,"torque_min_nm":c.torque_min_nm,"torque_max_nm":c.torque_max_nm,"required":float(req or 0),"rows":rows} for c,req,rows in db.execute(requirements_query(db,project_id,section_id))]

@app.get("/api/components")
def components(db:Session=Depends(get_db),user=Depends(current_user)):
    return [{"id":x.id,"sku":x.sku,"name":x.name,"category":x.category,"unit":x.unit,"torque_min_nm":x.torque_min_nm,"torque_max_nm":x.torque_max_nm} for x in db.scalars(select(Component).order_by(Component.category,Component.name))]

@app.post("/api/calculator")
def calculate_equipment(data:CalculatorIn,db:Session=Depends(get_db),user=Depends(current_user)):
    row_type=db.scalar(select(RowType).where(RowType.id==data.row_type_id).options(selectinload(RowType.components).selectinload(RowTypeComponent.component)))
    if not row_type: raise HTTPException(404,"Brak typu konstrukcji")
    reference=row_type.reference_length_m or data.length_m
    factor=data.length_m/reference
    materials=[]
    torque_values=[]
    for relation in row_type.components:
        per_row=math.ceil(relation.quantity*factor)
        component=relation.component
        materials.append({"component_id":component.id,"sku":component.sku,"name":component.name,"category":component.category,"unit":component.unit,"per_row":per_row,"total":per_row*data.row_count,"torque_min_nm":component.torque_min_nm,"torque_max_nm":component.torque_max_nm})
        if component.torque_min_nm is not None:
            torque_values.append((component.torque_min_nm,component.torque_max_nm or component.torque_min_nm))
    torque_min=min((x[0] for x in torque_values),default=20)
    torque_max=max((x[1] for x in torque_values),default=100)
    tools=[
        {"name":"Klucz dynamometryczny","quantity":max(1,math.ceil(data.row_count/8)),"specification":f"zakres obejmujący {torque_min:g}–{torque_max:g} Nm"},
        {"name":"Klucz udarowy akumulatorowy","quantity":max(1,math.ceil(data.row_count/10)),"specification":"z kompletem nasadek zgodnych z BOM"},
        {"name":"Klucz płasko-oczkowy / nasadki","quantity":max(2,math.ceil(data.row_count/5)),"specification":"rozmiary według śrub z BOM"},
        {"name":"Poziomica i taśma miernicza","quantity":max(1,math.ceil(data.row_count/12)),"specification":"kontrola osi i położenia konstrukcji"},
        {"name":"Marker, kreda traserska, zestaw kontroli QC","quantity":1,"specification":"na brygadę"},
    ]
    return {"row_type":{"id":row_type.id,"name":row_type.name,"structure_kind":row_type.structure_kind,"reference_length_m":reference},"input":{"length_m":data.length_m,"row_count":data.row_count,"scale_factor":round(factor,4)},"materials":materials,"tools":tools,"assumption":"Ilości elementów liniowych są zaokrąglane w górę względem długości referencyjnej BOM. Wynik należy porównać z zatwierdzoną dokumentacją projektu."}

@app.get("/api/documents")
def documents(project_id:int|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    q=select(Document).order_by(Document.uploaded_at.desc())
    if project_id:q=q.where(Document.project_id==project_id)
    return [{"id":x.id,"filename":x.filename,"kind":x.kind,"size":x.size,"status":x.status,"analysis":json.loads(x.analysis_json or "{}"),"uploaded_at":x.uploaded_at} for x in db.scalars(q)]

@app.post("/api/documents")
async def upload_document(project_id:int=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista","magazynier"))):
    if not db.get(Project,project_id): raise HTTPException(404,"Brak projektu")
    if file.size is not None and file.size>MAX_DOCUMENT_SIZE: raise HTTPException(413,"Plik przekracza limit rozmiaru")
    extension=Path(file.filename or "").suffix.lower()
    if extension not in (".pdf",".dwg",".dxf",".xlsx",".xlsm"): raise HTTPException(400,"Dozwolone: PDF, DWG, DXF, XLSX")
    stored=f"{uuid.uuid4().hex}{extension}";path=UPLOAD_DIR/stored
    with path.open("wb") as target: shutil.copyfileobj(file.file,target)
    if path.stat().st_size>MAX_DOCUMENT_SIZE:
        path.unlink(missing_ok=True);raise HTTPException(413,"Plik przekracza limit rozmiaru")
    try: result=analyze(path,extension,db);status="przeanalizowany"
    except Exception as exc: result={"error":str(exc)};status="wymaga sprawdzenia"
    extracted=result.pop("text","")
    item=Document(project_id=project_id,filename=Path(file.filename or "dokument").name,stored_name=stored,kind=extension[1:].upper(),size=path.stat().st_size,status=status,extracted_text=extracted,analysis_json=json.dumps(result,ensure_ascii=False),uploaded_by_id=user.id)
    db.add(item);db.flush();audit(db,user,"upload","document",item.id,item.filename);db.commit();await realtime.send("document.changed",{"id":item.id});return {"id":item.id,"status":status,"analysis":result}

@app.get("/api/documents/{document_id}/file")
def document_file(document_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    item=db.get(Document,document_id)
    if not item: raise HTTPException(404,"Brak dokumentu")
    return FileResponse(UPLOAD_DIR/item.stored_name,filename=item.filename)

@app.get("/api/instructions")
def instructions(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    docs=db.scalars(select(Document).where(Document.project_id==project_id).order_by(Document.uploaded_at.desc())).all();result=[]
    for doc in docs:
        analysis=json.loads(doc.analysis_json or "{}")
        for value in analysis.get("instructions",[]): result.append({**value,"document_id":doc.id,"source":doc.filename})
    return result

@app.post("/api/worklogs")
async def create_worklog(data:WorkLogIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if data.client_id:
        existing=db.scalar(select(WorkLog).where(WorkLog.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    item=WorkLog(**data.model_dump(),author_id=user.id);db.add(item);db.flush();audit(db,user,"create","worklog",item.id);db.commit();await realtime.send("worklog.changed",{"project_id":data.project_id});return {"id":item.id}

@app.get("/api/worklogs")
def worklogs(project_id:int,work_date:date|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    q=select(WorkLog).where(WorkLog.project_id==project_id).order_by(WorkLog.work_date.desc(),WorkLog.created_at.desc())
    if work_date:q=q.where(WorkLog.work_date==work_date)
    return [{"id":x.id,"work_date":x.work_date,"team":x.team,"stage":x.stage,"people":x.people,"hours":x.hours,"rows_completed":x.rows_completed,"manhours":x.people*x.hours,"note":x.note} for x in db.scalars(q).all()]

@app.post("/api/rfis")
async def create_rfi(data:RFIIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if data.client_id:
        existing=db.scalar(select(RFI).where(RFI.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    item=RFI(**data.model_dump(),created_by_id=user.id);db.add(item);db.flush();audit(db,user,"create","rfi",item.id,item.title);db.commit();await realtime.send("rfi.changed",{"id":item.id});return {"id":item.id}

@app.get("/api/rfis")
def rfis(project_id:int,status:str|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    q=select(RFI).where(RFI.project_id==project_id).order_by(RFI.created_at.desc())
    if status:q=q.where(RFI.status==status)
    result=[]
    for x in db.scalars(q):
        photos=db.scalar(select(func.count(Attachment.id)).where(Attachment.entity_type=="rfi",Attachment.entity_id==x.id))
        result.append({"id":x.id,"row_id":x.row_id,"title":x.title,"description":x.description,"priority":x.priority,"status":x.status,"created_at":x.created_at,"photos":photos})
    return result

@app.patch("/api/rfis/{rfi_id}")
async def update_rfi(rfi_id:int,data:RFIUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(RFI,rfi_id)
    if not item:raise HTTPException(404,"Brak RFI")
    for key,value in data.model_dump(exclude_none=True).items():setattr(item,key,value)
    if item.status=="zamknięty":item.resolved_at=utc_now()
    audit(db,user,"update","rfi",item.id,item.status);db.commit();await realtime.send("rfi.changed",{"id":item.id});return {"ok":True}

@app.post("/api/{entity_type}/{entity_id}/photos")
async def upload_photo(entity_type:str,entity_id:int,file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if entity_type not in ("row","rfi"):raise HTTPException(400,"Zdjęcie można przypisać do rzędu lub RFI")
    entity=db.get(ConstructionRow if entity_type=="row" else RFI,entity_id)
    if not entity:raise HTTPException(404,"Nie znaleziono wskazanego rzędu lub RFI")
    if file.size is not None and file.size>MAX_PHOTO_SIZE:raise HTTPException(413,"Zdjęcie przekracza limit 25 MB")
    mime=file.content_type or "application/octet-stream"
    if not mime.startswith("image/"):raise HTTPException(400,"Wymagany plik zdjęcia")
    extension=Path(file.filename or ".jpg").suffix.lower() or ".jpg";stored=f"{uuid.uuid4().hex}{extension}"
    with (UPLOAD_DIR/stored).open("wb") as target:shutil.copyfileobj(file.file,target)
    if (UPLOAD_DIR/stored).stat().st_size>MAX_PHOTO_SIZE:
        (UPLOAD_DIR/stored).unlink(missing_ok=True);raise HTTPException(413,"Zdjęcie przekracza limit 25 MB")
    item=Attachment(entity_type=entity_type,entity_id=entity_id,filename=Path(file.filename or "zdjecie.jpg").name,stored_name=stored,mime_type=mime,uploaded_by_id=user.id);db.add(item);db.commit();await realtime.send(f"{entity_type}.photo",{"id":entity_id});return {"id":item.id}

@app.get("/api/{entity_type}/{entity_id}/photos")
def photos(entity_type:str,entity_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if entity_type not in ("row","rfi"):raise HTTPException(400,"Nieznany typ obiektu")
    items=db.scalars(select(Attachment).where(Attachment.entity_type==entity_type,Attachment.entity_id==entity_id).order_by(Attachment.created_at.desc())).all()
    return [{"id":item.id,"filename":item.filename,"mime_type":item.mime_type,"created_at":item.created_at,"url":f"/api/attachments/{item.id}"} for item in items]

@app.get("/api/attachments/{attachment_id}")
def attachment(attachment_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    item=db.get(Attachment,attachment_id)
    if not item:raise HTTPException(404,"Brak załącznika")
    return FileResponse(UPLOAD_DIR/item.stored_name,media_type=item.mime_type,filename=item.filename)

@app.post("/api/deliveries")
async def create_delivery(data:DeliveryIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","magazynier"))):
    if data.client_id:
        existing=db.scalar(select(Delivery).where(Delivery.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    payload=data.model_dump(exclude={"items"});item=Delivery(**payload,created_by_id=user.id);db.add(item);db.flush()
    for value in data.items:db.add(DeliveryItem(delivery_id=item.id,**value.model_dump()))
    audit(db,user,"create","delivery",item.id,item.wz_number);db.commit();await realtime.send("delivery.changed",{"project_id":data.project_id});return {"id":item.id}

@app.get("/api/deliveries")
def deliveries(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    items=db.scalars(select(Delivery).where(Delivery.project_id==project_id).options(selectinload(Delivery.items).selectinload(DeliveryItem.component)).order_by(Delivery.delivery_date.desc())).all()
    return [{"id":x.id,"delivery_date":x.delivery_date,"wz_number":x.wz_number,"supplier":x.supplier,"note":x.note,"items":[{"component_id":i.component_id,"name":i.component.name,"sku":i.component.sku,"quantity_received":i.quantity_received,"quantity_damaged":i.quantity_damaged,"unit":i.component.unit} for i in x.items]} for x in items]

@app.get("/api/logistics/stock")
def stock(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    required={c.id:(c,req) for c,req,_ in db.execute(requirements_query(db,project_id=project_id))}
    received=dict(db.execute(select(DeliveryItem.component_id,func.sum(DeliveryItem.quantity_received-DeliveryItem.quantity_damaged)).join(Delivery).where(Delivery.project_id==project_id).group_by(DeliveryItem.component_id)).all())
    ids=set(required)|set(received);result=[]
    for cid in ids:
        comp=required.get(cid,(db.get(Component,cid),0))[0];req=float(required.get(cid,(None,0))[1] or 0);got=float(received.get(cid,0) or 0)
        result.append({"component_id":cid,"sku":comp.sku,"name":comp.name,"unit":comp.unit,"required":req,"available":got,"balance":got-req,"status":"komplet" if got>=req else "brak"})
    return sorted(result,key=lambda x:(x["status"],x["name"]))

@app.get("/api/dashboard")
def dashboard(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    total,built,qc=db.execute(select(func.count(ConstructionRow.id),func.sum(func.cast(ConstructionRow.built,Integer)),func.sum(func.cast(ConstructionRow.qc_checked,Integer))).join(Section).join(Zone).where(Zone.project_id==project_id)).one();total=total or 0;built=built or 0;qc=qc or 0
    open_rfi=db.scalar(select(func.count(RFI.id)).where(RFI.project_id==project_id,RFI.status!="zamknięty")) or 0
    rows_done,manhours,days=db.execute(select(func.sum(WorkLog.rows_completed),func.sum(WorkLog.people*WorkLog.hours),func.count(func.distinct(WorkLog.work_date))).where(WorkLog.project_id==project_id)).one();rows_done=rows_done or 0;manhours=manhours or 0;days=days or 0
    productivity=rows_done/manhours if manhours else 0;daily=rows_done/days if days else 0;forecast=(total-built)/daily if daily else None
    return {"rows_total":total,"rows_built":built,"rows_remaining":total-built,"rows_qc":qc,"completion_pct":round(100*built/total,1) if total else 0,"qc_pct":round(100*qc/total,1) if total else 0,"open_rfi":open_rfi,"manhours":round(manhours,1),"productivity":round(productivity,4),"forecast_days":round(forecast,1) if forecast is not None else None,"offline_supported":True}

@app.get("/api/reports/daily")
def report(project_id:int,report_date:date|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    report_date=report_date or date.today()
    project=db.get(Project,project_id)
    if not project:raise HTTPException(404,"Brak projektu")
    content=daily_report(db,project,report_date)
    return StreamingResponse(content,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="raport-{report_date.isoformat()}.pdf"'})

@app.websocket("/ws")
async def websocket(ws:WebSocket,token:str):
    try:decode_token(token)
    except HTTPException:await ws.close(code=4401);return
    await realtime.connect(ws)
    try:
        while True:await ws.receive_text()
    except WebSocketDisconnect:realtime.disconnect(ws)

FRONTEND=Path(__file__).resolve().parent.parent/"frontend"/"dist"
if FRONTEND.exists():
    app.mount("/assets",StaticFiles(directory=FRONTEND/"assets"),name="assets")
    @app.get("/{full_path:path}",include_in_schema=False)
    def spa(full_path:str):
        target=FRONTEND/full_path
        if full_path and target.is_file():return FileResponse(target)
        return FileResponse(FRONTEND/"index.html")
