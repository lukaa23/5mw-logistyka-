import hashlib, json, math, mimetypes, os, shutil, uuid
from urllib.parse import quote
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.orm import Session, selectinload
from .auth import STARTER_ACCOUNTS, create_token, current_user, decode_token, hash_password, initial_password, roles, verify_password
from .database import Base, SessionLocal, UPLOAD_DIR, engine, get_db
from .lan import lan_urls
from .migrations import ensure_schema_columns
from .models import Attachment, AuditEvent, Component, ConstructionRow, Delivery, DeliveryItem, Document, MaterialTemplate, Project, ProjectMaterial, ProjectVariantConfig, RFI, RowType, RowTypeComponent, Section, SiteDelivery, SiteDeliveryItem, User, WorkLog, Zone, ZoneVariantConfig
from .services.report import daily_report
from .services.source_basis import SOURCE_DIR, build_eset_demand, load_eset_bom, load_source_manifest, sha256_file, source_analysis, source_entry_by_hash

APP_VERSION="4.4.0"
app=FastAPI(title="ASOLAR ESET Tracker Manager",version=APP_VERSION)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
MAX_DOCUMENT_SIZE=int(os.getenv("ASOLAR_MAX_DOCUMENT_MB","100"))*1024*1024
MAX_PHOTO_SIZE=25*1024*1024

def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)

ALLOWED_PHOTO_MIME={"image/jpeg","image/jpg","image/png","image/webp","image/gif","image/heic","image/heif"}
DOCUMENT_MIME={".pdf":"application/pdf",".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",".xlsm":"application/vnd.ms-excel.sheet.macroEnabled.12",".dwg":"application/octet-stream",".dxf":"application/octet-stream"}

def read_upload_limited(file,limit,message):
    """Czyta przesłany plik do pamięci i odrzuca go po przekroczeniu limitu."""
    data=file.file.read(limit+1)
    if len(data)>limit:raise HTTPException(413,message)
    return data

def content_disposition(filename,kind="attachment"):
    return f"{kind}; filename*=utf-8''{quote(filename or 'plik')}"

def binary_response(data,media_type,filename,kind="attachment"):
    return Response(content=data,media_type=media_type,headers={"Content-Disposition":content_disposition(filename,kind),"X-Content-Type-Options":"nosniff"})

class LoginIn(BaseModel): username:str; password:str
class UserIn(BaseModel): username:str; full_name:str; role:str; password:str=Field(min_length=8)
class ProjectIn(BaseModel): name:str; location:str=""; capacity_mw:float=0; structure_type:str="tracker"
class ProjectUpdate(BaseModel): name:str|None=None; location:str|None=None; capacity_mw:float|None=None; structure_type:str|None=None; archived:bool|None=None
class ZoneIn(BaseModel): project_id:int; name:str
class SectionIn(BaseModel): zone_id:int; name:str
class NameUpdate(BaseModel): name:str=Field(min_length=1,max_length=180)
class RowsIn(BaseModel): section_id:int; prefix:str="R"; start_number:int=1; count:int=Field(ge=1,le=2000); template_id:int|None=None; variant_name:str=""; length_m:float=0; specification:str=""; material_quantities:dict[str,float]=Field(default_factory=dict)
class RowIn(BaseModel): section_id:int; code:str; template_id:int|None=None; variant_name:str=""; length_m:float=0; specification:str=""; material_quantities:dict[str,float]=Field(default_factory=dict)
class RowUpdate(BaseModel): code:str|None=None; template_id:int|None=None; variant_name:str|None=None; length_m:float|None=None; specification:str|None=None; material_quantities:dict[str,float]|None=None; built:bool|None=None; qc_checked:bool|None=None; note:str|None=None
class RowMoveIn(BaseModel): direction:str
class RFIIn(BaseModel): project_id:int; row_id:int|None=None; title:str; description:str; priority:str="normalny"; client_id:str|None=None
class RFIUpdate(BaseModel): status:str|None=None; assigned_to_id:int|None=None; priority:str|None=None
class WorkLogIn(BaseModel): project_id:int; work_date:date=Field(default_factory=date.today); team:str; stage:str; people:int=Field(ge=1,le=1000); hours:float=Field(gt=0,le=24,default=8); rows_completed:float=Field(ge=0); qc_notes:str=""; note:str=""; row_id:int|None=None; client_id:str|None=None
class WorkLogUpdate(BaseModel): work_date:date|None=None; team:str|None=None; stage:str|None=None; people:int|None=Field(default=None,ge=1,le=1000); hours:float|None=Field(default=None,gt=0,le=24); rows_completed:float|None=Field(default=None,ge=0); qc_notes:str|None=None; note:str|None=None; row_id:int|None=None
class DeliveryItemIn(BaseModel): material_id:int; quantity_received:float=Field(gt=0); quantity_damaged:float=Field(ge=0,default=0)
class DeliveryIn(BaseModel): project_id:int; delivery_date:date=Field(default_factory=date.today); wz_number:str; supplier:str=""; note:str=""; client_id:str|None=None; items:list[DeliveryItemIn]
class BomDeliveryItemIn(BaseModel): component_id:int; quantity_received:float=Field(gt=0); quantity_damaged:float=Field(ge=0,default=0)
class BomDeliveryIn(BaseModel): project_id:int; delivery_date:date=Field(default_factory=date.today); wz_number:str=Field(min_length=1,max_length=100); supplier:str=""; note:str=""; client_id:str|None=None; items:list[BomDeliveryItemIn]=Field(min_length=1)
class MaterialIn(BaseModel): slot_number:int=Field(ge=1,le=3); name:str=Field(min_length=1,max_length=180); unit:str="szt."; required_quantity:float=Field(ge=0)
class MaterialListIn(BaseModel): items:list[MaterialIn]=Field(min_length=3,max_length=3)
class TemplateIn(BaseModel): project_id:int; name:str=Field(min_length=1,max_length=120); structure_type:str=""; default_length_m:float=Field(ge=0,le=1000); specification:str=""; materials:dict[str,float]=Field(default_factory=dict)
class TemplateUpdate(BaseModel): name:str|None=None; structure_type:str|None=None; default_length_m:float|None=None; specification:str|None=None; materials:dict[str,float]|None=None
class CalculatorIn(BaseModel): project_id:int; template_id:int|None=None; variant_name:str=""; length_m:float=Field(ge=0,le=1000); row_count:int=Field(ge=1,le=5000); materials:dict[str,float]|None=None
class VariantCountIn(BaseModel): variant_code:str; row_count:int=Field(ge=0,le=5000)
class VariantConfigurationIn(BaseModel): items:list[VariantCountIn]=Field(min_length=7,max_length=7)

def audit(db,user,action,entity_type,entity_id=None,details=""):
    db.add(AuditEvent(user_id=user.id if user else None,action=action,entity_type=entity_type,entity_id=entity_id,details=details))

def user_dict(user): return {"id":user.id,"username":user.username,"full_name":user.full_name,"role":user.role,"active":user.active}
def project_dict(project): return {"id":project.id,"name":project.name,"location":project.location,"capacity_mw":project.capacity_mw,"structure_type":project.structure_type,"archived":project.archived,"archived_at":project.archived_at}
def row_dict(row):
    return {"id":row.id,"code":row.code,"section_id":row.section_id,"template_id":row.template_id,"variant_name":row.variant_name,"variant_ordinal":row.variant_ordinal,"sort_order":row.sort_order,"auto_generated":row.auto_generated,"active":row.active,"length_m":row.length_m,"specification":row.specification,"material_quantities":json.loads(row.material_quantities_json or "{}"),"built":row.built,"built_by":row.built_by.full_name if row.built_by else None,"built_at":row.built_at,"qc_checked":row.qc_checked,"qc_by":row.qc_by.full_name if row.qc_by else None,"qc_at":row.qc_at,"note":row.note}

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

SOURCE_MANIFEST=load_source_manifest()
ESET_VARIANT_CODES=tuple(item["code"] for item in load_eset_bom()["variants"])
DEFAULT_MATERIALS=tuple((item["slot_number"],item["name"],item["unit"]) for item in SOURCE_MANIFEST["materials"])
AUTO_SECTION_NAME="Rzędy ESET — automatyczne"
MODULE_COMPONENT_SKU="MODULE-JINKO-JKM710-735"

def ensure_bom_components(db):
    """Synchronize the approved ESET/Jinko delivery catalogue with stable database ids."""
    catalogue=load_eset_bom()["components"]
    for sku,definition in catalogue.items():
        item=db.scalar(select(Component).where(Component.sku==sku))
        values={"name":definition["name"],"category":definition["category"],"unit":definition["unit"],"torque_min_nm":definition.get("torque_min_nm"),"torque_max_nm":definition.get("torque_max_nm")}
        if item:
            for key,value in values.items():setattr(item,key,value)
        else:db.add(Component(sku=sku,**values))
    module=SOURCE_MANIFEST["module"]
    item=db.scalar(select(Component).where(Component.sku==MODULE_COMPONENT_SKU))
    values={"name":f'Moduł PV {module["model"]}',"category":"Moduły PV","unit":"szt.","torque_min_nm":None,"torque_max_nm":None}
    if item:
        for key,value in values.items():setattr(item,key,value)
    else:db.add(Component(sku=MODULE_COMPONENT_SKU,**values))

def bom_catalogue():
    catalogue={key:{"key":key,**value} for key,value in load_eset_bom()["components"].items()}
    module=SOURCE_MANIFEST["module"]
    catalogue[MODULE_COMPONENT_SKU]={"key":MODULE_COMPONENT_SKU,"name":f'Moduł PV {module["model"]}',"category":"Moduły PV","unit":"szt.","spec":f'{module["dimensions_mm"]}; {module["power_min_w"]}–{module["power_max_w"]} W; {module["weight_kg"]} kg',"source":module["source"],"torque_min_nm":None,"torque_max_nm":None}
    return catalogue

def ensure_variant_config(db,project_id):
    current={item.variant_code for item in db.scalars(select(ProjectVariantConfig).where(ProjectVariantConfig.project_id==project_id))}
    for code in ESET_VARIANT_CODES:
        if code not in current:db.add(ProjectVariantConfig(project_id=project_id,variant_code=code,row_count=0))

def ensure_zone_variant_config(db,zone_id):
    current={item.variant_code for item in db.scalars(select(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zone_id))}
    for code in ESET_VARIANT_CODES:
        if code not in current:db.add(ZoneVariantConfig(zone_id=zone_id,variant_code=code,row_count=0))

def zone_variant_values(db,zone_id):
    ensure_zone_variant_config(db,zone_id);db.flush()
    return {item.variant_code:item.row_count for item in db.scalars(select(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zone_id))}

def reconcile_zone_rows(db,zone):
    counts=zone_variant_values(db,zone.id)
    desired_total=sum(counts.values())
    section=db.scalar(select(Section).where(Section.zone_id==zone.id,Section.name==AUTO_SECTION_NAME))
    if not section and not desired_total:return
    if not section:
        section=Section(zone_id=zone.id,name=AUTO_SECTION_NAME);db.add(section);db.flush()
    existing=db.scalars(select(ConstructionRow).where(ConstructionRow.section_id==section.id,ConstructionRow.auto_generated==True)).all()
    was_active={row.id:row.active for row in existing}
    previous_order={row.id:(row.sort_order or (int(row.code) if row.code.isdigit() else 1_000_000+row.id)) for row in existing}
    for row in existing:row.code=f"tmp-{uuid.uuid4().hex[:24]}"
    db.flush()
    selected=[]
    by_key={(row.variant_name,row.variant_ordinal):row for row in existing}
    for code in ESET_VARIANT_CODES:
        for ordinal in range(1,counts.get(code,0)+1):
            row=by_key.get((code,ordinal))
            if not row:
                row=ConstructionRow(section_id=section.id,code=f"tmp-{uuid.uuid4().hex[:24]}",variant_name=code,variant_ordinal=ordinal,sort_order=0,auto_generated=True,active=True,specification=f"Tracker ESET {code}",material_quantities_json="{}")
                db.add(row)
            row.active=True;selected.append(row)
    selected_ids={id(row) for row in selected}
    for row in existing:
        if id(row) not in selected_ids:row.active=False;row.sort_order=0
    db.flush()
    variant_rank={code:index for index,code in enumerate(ESET_VARIANT_CODES)}
    selected.sort(key=lambda row:(0,previous_order[row.id]) if row.id in was_active and was_active[row.id] else (1,variant_rank.get(row.variant_name,999),row.variant_ordinal,row.id or 0))
    for index,row in enumerate(selected,1):row.code=str(index);row.sort_order=index
    for row in existing:
        if not row.active:row.code=f"archiwalny-{row.id}"
    db.flush()

def sync_project_variant_totals(db,project_id):
    ensure_variant_config(db,project_id);db.flush()
    totals={code:0 for code in ESET_VARIANT_CODES}
    for code,count in db.execute(select(ZoneVariantConfig.variant_code,func.sum(ZoneVariantConfig.row_count)).join(Zone).where(Zone.project_id==project_id).group_by(ZoneVariantConfig.variant_code)):
        totals[code]=int(count or 0)
    current={item.variant_code:item for item in db.scalars(select(ProjectVariantConfig).where(ProjectVariantConfig.project_id==project_id))}
    for code,value in totals.items():current[code].row_count=value

def ensure_project_zone_configs(db,project_id):
    zones=db.scalars(select(Zone).where(Zone.project_id==project_id).order_by(Zone.id)).all()
    had_zone_config=bool(db.scalar(select(func.count(ZoneVariantConfig.id)).join(Zone).where(Zone.project_id==project_id)))
    legacy={item.variant_code:item.row_count for item in db.scalars(select(ProjectVariantConfig).where(ProjectVariantConfig.project_id==project_id))}
    for zone in zones:ensure_zone_variant_config(db,zone.id)
    db.flush()
    if zones and not had_zone_config and any(legacy.values()):
        first={item.variant_code:item for item in db.scalars(select(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zones[0].id))}
        for code,value in legacy.items():
            if code in first:first[code].row_count=value
    for zone in zones:reconcile_zone_rows(db,zone)
    if zones:sync_project_variant_totals(db,project_id)
    return zones

def project_demand(db,project_id):
    zones=ensure_project_zone_configs(db,project_id)
    if zones:
        values={code:0 for code in ESET_VARIANT_CODES}
        for code,count in db.execute(select(ZoneVariantConfig.variant_code,func.sum(ZoneVariantConfig.row_count)).join(Zone).where(Zone.project_id==project_id).group_by(ZoneVariantConfig.variant_code)):values[code]=int(count or 0)
    else:
        ensure_variant_config(db,project_id);db.flush();values={item.variant_code:item.row_count for item in db.scalars(select(ProjectVariantConfig).where(ProjectVariantConfig.project_id==project_id))}
    return build_eset_demand(values)

def validate_variant_configuration(items):
    codes=[item.variant_code for item in items]
    if len(set(codes))!=len(ESET_VARIANT_CODES) or set(codes)!=set(ESET_VARIANT_CODES):
        raise HTTPException(400,"Konfiguracja musi zawierać dokładnie siedem zatwierdzonych wariantów ESET")

def zone_demand_payload(db,zone):
    demand=build_eset_demand(zone_variant_values(db,zone.id))
    total,built,qc=db.execute(select(func.count(ConstructionRow.id),func.sum(func.cast(ConstructionRow.built,Integer)),func.sum(func.cast(ConstructionRow.qc_checked,Integer))).join(Section).where(Section.zone_id==zone.id,ConstructionRow.auto_generated==True,ConstructionRow.active==True)).one()
    return {"id":zone.id,"project_id":zone.project_id,"name":zone.name,"stats":{"total":int(total or 0),"built":int(built or 0),"qc":int(qc or 0)},"demand":demand}

def ensure_materials(db,project_id):
    rows=db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==project_id)).all()
    existing={item.slot_number for item in rows}
    previous_defaults={"Rury / profile konstrukcyjne","Płatwie","Śruby i łączenia"}
    configured={slot:(name,unit) for slot,name,unit in DEFAULT_MATERIALS}
    for item in rows:
        if item.name in previous_defaults:
            item.name,item.unit=configured[item.slot_number]
    for slot,name,unit in DEFAULT_MATERIALS:
        if slot not in existing:db.add(ProjectMaterial(project_id=project_id,slot_number=slot,name=name,unit=unit,required_quantity=0))

def seed_source_templates(db,project_id):
    for source in SOURCE_MANIFEST["templates"]:
        item=db.scalar(select(MaterialTemplate).where(MaterialTemplate.project_id==project_id,MaterialTemplate.name==source["name"]))
        if item:continue
        specification=f'{source["specification"]}\nŹródło: {source["source"]}'
        db.add(MaterialTemplate(project_id=project_id,name=source["name"],structure_type=source["structure_type"],default_length_m=source["default_length_m"],specification=specification,materials_json=json.dumps(source["materials"],ensure_ascii=False)))

def seed_source_documents(db,project_id,user_id):
    current=db.scalars(select(Document).where(Document.project_id==project_id)).all()
    approved={json.loads(item.analysis_json or "{}").get("sha256"):item for item in current}
    for entry in SOURCE_MANIFEST["documents"]:
        source_path=SOURCE_DIR/entry["filename"]
        if not source_path.exists() or sha256_file(source_path)!=entry["sha256"]:continue
        stored=f'source-{entry["sha256"][:20]}.pdf';target=UPLOAD_DIR/stored
        if not target.exists():shutil.copy2(source_path,target)
        analysis=source_analysis(entry)
        item=approved.get(entry["sha256"])
        if item:
            item.status="zatwierdzone źródło";item.analysis_json=json.dumps(analysis,ensure_ascii=False);item.stored_name=stored;item.size=target.stat().st_size
        else:
            db.add(Document(project_id=project_id,filename=entry["filename"],stored_name=stored,kind="PDF",size=target.stat().st_size,status="zatwierdzone źródło",extracted_text="",analysis_json=json.dumps(analysis,ensure_ascii=False),uploaded_by_id=user_id))

def ensure_starter_users(db):
    """Tworzy brakujące konta startowe. Istniejące konta i ich hasła nigdy nie są zmieniane."""
    generated={}
    for username,env_name,full_name,role in STARTER_ACCOUNTS:
        if db.scalar(select(User).where(User.username==username)):continue
        password,was_generated=initial_password(env_name)
        db.add(User(username=username,full_name=full_name,role=role,password_hash=hash_password(password)))
        if was_generated:generated[username]=password
    db.flush()
    if generated:store_generated_passwords(generated)

def store_generated_passwords(passwords):
    """Hasła wylosowane przy braku zmiennych ASOLAR_*_PASSWORD trafiają do lokalnego pliku (nie do logów)."""
    path=UPLOAD_DIR.parent/"initial-passwords.txt"
    with path.open("a",encoding="utf8") as target:
        for username,password in passwords.items():target.write(f"{username}: {password}\n")
    try:path.chmod(0o600)
    except OSError:pass
    print(f"[ASOLAR] Brak ustawionych haseł startowych — wylosowano je i zapisano w {path}. Na serwerze ustaw ASOLAR_MANAGER_PASSWORD, ASOLAR_FOREMAN1_PASSWORD i ASOLAR_FOREMAN2_PASSWORD.",flush=True)

def seed():
    Base.metadata.create_all(engine)
    ensure_schema_columns(engine)
    with SessionLocal() as db:
        ensure_starter_users(db)
        manager=db.scalar(select(User).where(User.username=="kierownik")) or db.scalar(select(User).where(User.role=="kierownik"))
        project=db.scalar(select(Project).limit(1))
        if not project:
            details=SOURCE_MANIFEST["project"]
            project=Project(name=details["name"],location=details["location"],capacity_mw=details["capacity_mw"],structure_type=details["structure_type"]); db.add(project); db.flush()
            zone=Zone(project_id=project.id,name="Strefa A"); db.add(zone); db.flush()
        elif project.name=="Farma PV 6,5 MW" and project.location=="Projekt budowy":
            details=SOURCE_MANIFEST["project"];project.name=details["name"];project.location=details["location"];project.capacity_mw=details["capacity_mw"];project.structure_type=details["structure_type"]
        placeholder=db.scalar(select(Zone).where(Zone.name=="Strefa do uzupełnienia"))
        if placeholder:placeholder.name="Strefa A"
        for item in db.scalars(select(Project)).all():ensure_materials(db,item.id);ensure_variant_config(db,item.id);ensure_project_zone_configs(db,item.id)
        ensure_bom_components(db)
        seed_source_templates(db,project.id)
        seed_source_documents(db,project.id,manager.id)
        db.commit()
seed()

LAN_MODE=os.getenv("ASOLAR_LAN")=="1"

@app.get("/api/server-info")
def server_info(user=Depends(roles("kierownik"))):
    """Adresy, pod którymi telefony w tej samej sieci Wi-Fi otworzą aplikację (tryb sieciowy)."""
    port=int(os.getenv("PORT","8765"))
    return {"version":APP_VERSION,"lan_enabled":LAN_MODE,"urls":lan_urls(port) if LAN_MODE else []}

@app.get("/api/health")
def health(): return {"status":"ok","version":APP_VERSION,"time":utc_now()}

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
def projects(include_archived:bool=False,db:Session=Depends(get_db),user=Depends(current_user)):
    query=select(Project).order_by(Project.archived,Project.name)
    if not include_archived:query=query.where(Project.archived==False)
    return [project_dict(x) for x in db.scalars(query)]

@app.post("/api/projects")
async def create_project(data:ProjectIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Project(**data.model_dump());db.add(item);db.flush();ensure_materials(db,item.id);ensure_variant_config(db,item.id);audit(db,user,"create","project",item.id,item.name);db.commit();await realtime.send("project.changed",{"id":item.id});return project_dict(item)

@app.patch("/api/projects/{project_id}")
async def update_project(project_id:int,data:ProjectUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Project,project_id)
    if not item:raise HTTPException(404,"Brak projektu")
    values=data.model_dump(exclude_none=True)
    if "archived" in values:item.archived_at=utc_now() if values["archived"] else None
    for key,value in values.items():setattr(item,key,value)
    audit(db,user,"update","project",item.id,json.dumps(values,ensure_ascii=False));db.commit();await realtime.send("project.changed",{"id":item.id});return project_dict(item)

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Project,project_id)
    if not item:raise HTTPException(404,"Brak projektu")
    row_ids=list(db.scalars(select(ConstructionRow.id).join(Section).join(Zone).where(Zone.project_id==project_id)))
    rfi_ids=list(db.scalars(select(RFI.id).where(RFI.project_id==project_id)))
    log_ids=list(db.scalars(select(WorkLog.id).where(WorkLog.project_id==project_id)))
    attachments=db.scalars(select(Attachment).where((Attachment.entity_type=="row") & (Attachment.entity_id.in_(row_ids or [-1])) | (Attachment.entity_type=="rfi") & (Attachment.entity_id.in_(rfi_ids or [-1])) | (Attachment.entity_type=="worklog") & (Attachment.entity_id.in_(log_ids or [-1])))).all()
    for photo in attachments:(UPLOAD_DIR/photo.stored_name).unlink(missing_ok=True);db.delete(photo)
    for document in db.scalars(select(Document).where(Document.project_id==project_id)).all():(UPLOAD_DIR/document.stored_name).unlink(missing_ok=True);db.delete(document)
    db.execute(delete(RFI).where(RFI.project_id==project_id));db.execute(delete(WorkLog).where(WorkLog.project_id==project_id));db.execute(delete(Delivery).where(Delivery.project_id==project_id));db.execute(delete(SiteDelivery).where(SiteDelivery.project_id==project_id));db.execute(delete(ProjectVariantConfig).where(ProjectVariantConfig.project_id==project_id))
    db.delete(item);db.commit();await realtime.send("project.deleted",{"id":project_id});return {"ok":True}

@app.get("/api/projects/{project_id}/tree")
def project_tree(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    project=db.scalar(select(Project).where(Project.id==project_id).options(selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.row_type),selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.built_by),selectinload(Project.zones).selectinload(Zone.sections).selectinload(Section.rows).selectinload(ConstructionRow.qc_by)))
    if not project: raise HTTPException(404,"Brak projektu")
    return {**project_dict(project),"zones":[{"id":z.id,"name":z.name,"sections":[{"id":s.id,"name":s.name,"archived":s.archived,"rows":[row_dict(r) for r in s.rows if r.active]} for s in z.sections]} for z in project.zones]}

@app.post("/api/zones")
async def create_zone(data:ZoneIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Zone(**data.model_dump());db.add(item);db.flush();audit(db,user,"create","zone",item.id,item.name);db.commit();await realtime.send("structure.changed",{"project_id":data.project_id});return {"id":item.id}

@app.patch("/api/zones/{zone_id}")
async def update_zone(zone_id:int,data:NameUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Zone,zone_id)
    if not item:raise HTTPException(404,"Brak strefy")
    item.name=data.name;db.commit();await realtime.send("structure.changed",{"project_id":item.project_id});return {"ok":True}

@app.post("/api/sections")
async def create_section(data:SectionIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=Section(**data.model_dump());db.add(item);db.flush();audit(db,user,"create","section",item.id,item.name);db.commit();await realtime.send("structure.changed");return {"id":item.id}

@app.patch("/api/sections/{section_id}")
async def update_section(section_id:int,data:NameUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Section,section_id)
    if not item:raise HTTPException(404,"Brak sekcji")
    item.name=data.name;db.commit();await realtime.send("structure.changed");return {"ok":True}

@app.delete("/api/sections/{section_id}")
async def delete_section(section_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Section,section_id)
    if not item:raise HTTPException(404,"Brak sekcji")
    row_ids=list(db.scalars(select(ConstructionRow.id).where(ConstructionRow.section_id==section_id)))
    for rfi in db.scalars(select(RFI).where(RFI.row_id.in_(row_ids or [-1]))):rfi.row_id=None
    for photo in db.scalars(select(Attachment).where(Attachment.entity_type=="row",Attachment.entity_id.in_(row_ids or [-1]))).all():(UPLOAD_DIR/photo.stored_name).unlink(missing_ok=True);db.delete(photo)
    db.delete(item);db.commit();await realtime.send("structure.changed");return {"ok":True}

@app.post("/api/rows")
async def create_row(data:RowIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if not db.get(Section,data.section_id):raise HTTPException(404,"Brak sekcji")
    if db.scalar(select(ConstructionRow).where(ConstructionRow.section_id==data.section_id,ConstructionRow.code==data.code)):raise HTTPException(409,"Rząd o tym oznaczeniu już istnieje w sekcji")
    values=data.model_dump(exclude={"material_quantities"});item=ConstructionRow(**values,material_quantities_json=json.dumps(data.material_quantities,ensure_ascii=False));db.add(item);db.flush();audit(db,user,"create","row",item.id,item.code);db.commit();await realtime.send("structure.changed");return row_dict(item)

@app.post("/api/rows/bulk")
async def create_rows(data:RowsIn,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    section=db.get(Section,data.section_id)
    if not section: raise HTTPException(404,"Brak sekcji")
    created=[]
    for i in range(data.start_number,data.start_number+data.count):
        code=f"{data.prefix}{i:03d}"
        if db.scalar(select(ConstructionRow).where(ConstructionRow.section_id==data.section_id,ConstructionRow.code==code)): continue
        row=ConstructionRow(section_id=data.section_id,template_id=data.template_id,code=code,variant_name=data.variant_name,length_m=data.length_m,specification=data.specification,material_quantities_json=json.dumps(data.material_quantities,ensure_ascii=False));db.add(row);db.flush();created.append(row.id)
    audit(db,user,"bulk_create","row",details=f"{len(created)} rzędów");db.commit();await realtime.send("structure.changed");return {"created":len(created),"ids":created}

@app.patch("/api/rows/{row_id}")
async def update_row(row_id:int,data:RowUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
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
    values=data.model_dump(exclude_unset=True,exclude={"built","qc_checked","note","material_quantities"})
    for key,value in values.items():setattr(row,key,value)
    if "material_quantities" in data.model_fields_set:row.material_quantities_json=json.dumps(data.material_quantities or {},ensure_ascii=False)
    audit(db,user,"update","row",row.id,json.dumps(data.model_dump(exclude_unset=True),ensure_ascii=False));db.commit();await realtime.send("row.changed",{"id":row.id});db.refresh(row);return row_dict(row)

@app.delete("/api/rows/{row_id}")
async def delete_row(row_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    row=db.get(ConstructionRow,row_id)
    if not row:raise HTTPException(404,"Brak rzędu")
    for rfi in db.scalars(select(RFI).where(RFI.row_id==row_id)):rfi.row_id=None
    for log in db.scalars(select(WorkLog).where(WorkLog.row_id==row_id)):log.row_id=None
    for photo in db.scalars(select(Attachment).where(Attachment.entity_type=="row",Attachment.entity_id==row_id)).all():(UPLOAD_DIR/photo.stored_name).unlink(missing_ok=True);db.delete(photo)
    db.delete(row);db.commit();await realtime.send("structure.changed");return {"ok":True}

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

def template_dict(item):
    return {"id":item.id,"project_id":item.project_id,"name":item.name,"structure_type":item.structure_type,"default_length_m":item.default_length_m,"specification":item.specification,"materials":json.loads(item.materials_json or "{}"),"source_based":"Źródło:" in (item.specification or ""),"updated_at":item.updated_at}

def clean_three_materials(values):
    return {str(slot):max(0,float((values or {}).get(str(slot),(values or {}).get(slot,0)) or 0)) for slot in range(1,4)}

@app.get("/api/material-templates")
def material_templates(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    return [template_dict(item) for item in db.scalars(select(MaterialTemplate).where(MaterialTemplate.project_id==project_id).order_by(MaterialTemplate.name))]

@app.post("/api/material-templates")
async def create_template(data:TemplateIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if not db.get(Project,data.project_id):raise HTTPException(404,"Brak projektu")
    if db.scalar(select(MaterialTemplate).where(MaterialTemplate.project_id==data.project_id,MaterialTemplate.name==data.name)):raise HTTPException(409,"Szablon o tej nazwie już istnieje")
    values=data.model_dump(exclude={"materials"});item=MaterialTemplate(**values,materials_json=json.dumps(clean_three_materials(data.materials),ensure_ascii=False));db.add(item);db.flush();audit(db,user,"create","material_template",item.id,item.name);db.commit();await realtime.send("template.changed",{"id":item.id});return template_dict(item)

@app.patch("/api/material-templates/{template_id}")
async def update_template(template_id:int,data:TemplateUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    item=db.get(MaterialTemplate,template_id)
    if not item:raise HTTPException(404,"Brak szablonu")
    values=data.model_dump(exclude_unset=True,exclude={"materials"})
    for key,value in values.items():setattr(item,key,value)
    if "materials" in data.model_fields_set:item.materials_json=json.dumps(clean_three_materials(data.materials),ensure_ascii=False)
    item.updated_at=utc_now();db.commit();await realtime.send("template.changed",{"id":item.id});return template_dict(item)

@app.delete("/api/material-templates/{template_id}")
async def delete_template(template_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(MaterialTemplate,template_id)
    if not item:raise HTTPException(404,"Brak szablonu")
    for row in db.scalars(select(ConstructionRow).where(ConstructionRow.template_id==template_id)):row.template_id=None
    db.delete(item);db.commit();await realtime.send("template.changed");return {"ok":True}

@app.post("/api/calculator")
def calculate_equipment(data:CalculatorIn,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,data.project_id):raise HTTPException(404,"Brak projektu")
    template=db.get(MaterialTemplate,data.template_id) if data.template_id else None
    if template and template.project_id!=data.project_id:raise HTTPException(400,"Szablon należy do innego projektu")
    source=data.materials if data.materials is not None else (json.loads(template.materials_json or "{}") if template else {})
    quantities=clean_three_materials(source)
    slots=db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==data.project_id).order_by(ProjectMaterial.slot_number)).all()
    ensure_materials(db,data.project_id)
    if len(slots)!=3:db.flush();slots=db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==data.project_id).order_by(ProjectMaterial.slot_number)).all()
    materials=[{"material_id":slot.id,"slot_number":slot.slot_number,"name":slot.name,"unit":slot.unit,"per_row":quantities[str(slot.slot_number)],"total":quantities[str(slot.slot_number)]*data.row_count} for slot in slots]
    return {"template":template_dict(template) if template else None,"variant_name":data.variant_name or (template.name if template else "Konfiguracja własna"),"input":{"length_m":data.length_m,"row_count":data.row_count},"materials":materials,"assumption":"Ilości nie są automatycznie skalowane długością. Użytkownik może ręcznie zmienić każdą z trzech pozycji przed obliczeniem lub zapisaniem szablonu."}

@app.get("/api/source-basis")
def source_basis(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    payload=json.loads(json.dumps(SOURCE_MANIFEST,ensure_ascii=False))
    rows=db.scalars(select(Document).where(Document.project_id==project_id)).all()
    registered={json.loads(item.analysis_json or "{}").get("sha256") for item in rows}
    payload["registered_sources"]=sum(item["sha256"] in registered for item in payload["documents"])
    payload["expected_sources"]=len(payload["documents"])
    return payload

@app.get("/api/projects/{project_id}/tracker-config")
def tracker_config(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    result=project_demand(db,project_id);db.commit();return result

@app.put("/api/projects/{project_id}/tracker-config")
async def update_tracker_config(project_id:int,data:VariantConfigurationIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    validate_variant_configuration(data.items)
    zones=ensure_project_zone_configs(db,project_id)
    if not zones:
        zone=Zone(project_id=project_id,name="Strefa A");db.add(zone);db.flush();ensure_zone_variant_config(db,zone.id);db.flush();zones=[zone]
    for zone in zones:
        current={item.variant_code:item for item in db.scalars(select(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zone.id))}
        for value in data.items:current[value.variant_code].row_count=value.row_count if zone.id==zones[0].id else 0
        reconcile_zone_rows(db,zone)
    sync_project_variant_totals(db,project_id)
    audit(db,user,"update","tracker_config",project_id,json.dumps({x.variant_code:x.row_count for x in data.items},ensure_ascii=False))
    result=project_demand(db,project_id);db.commit();await realtime.send("tracker-config.changed",{"project_id":project_id});return result

@app.get("/api/projects/{project_id}/tracker-zones")
def tracker_zones(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    zones=ensure_project_zone_configs(db,project_id)
    result=[zone_demand_payload(db,zone) for zone in zones]
    db.commit();return result

@app.post("/api/tracker-zones")
async def create_tracker_zone(data:ZoneIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if not db.get(Project,data.project_id):raise HTTPException(404,"Brak projektu")
    name=data.name.strip()
    if not name:raise HTTPException(400,"Nazwa strefy jest wymagana")
    item=Zone(project_id=data.project_id,name=name);db.add(item);db.flush();ensure_zone_variant_config(db,item.id);db.flush()
    audit(db,user,"create","tracker_zone",item.id,item.name);result=zone_demand_payload(db,item);db.commit();await realtime.send("tracker-zone.changed",{"project_id":data.project_id});return result

@app.patch("/api/tracker-zones/{zone_id}")
async def update_tracker_zone(zone_id:int,data:NameUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    item=db.get(Zone,zone_id)
    if not item:raise HTTPException(404,"Brak strefy")
    item.name=data.name.strip();audit(db,user,"update","tracker_zone",item.id,item.name);result=zone_demand_payload(db,item);db.commit();await realtime.send("tracker-zone.changed",{"project_id":item.project_id});return result

@app.put("/api/tracker-zones/{zone_id}/config")
async def update_tracker_zone_config(zone_id:int,data:VariantConfigurationIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    zone=db.get(Zone,zone_id)
    if not zone:raise HTTPException(404,"Brak strefy")
    validate_variant_configuration(data.items);ensure_zone_variant_config(db,zone_id);db.flush()
    current={item.variant_code:item for item in db.scalars(select(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zone_id))}
    for value in data.items:current[value.variant_code].row_count=value.row_count
    reconcile_zone_rows(db,zone);sync_project_variant_totals(db,zone.project_id)
    audit(db,user,"update","tracker_zone_config",zone.id,json.dumps({x.variant_code:x.row_count for x in data.items},ensure_ascii=False));result=zone_demand_payload(db,zone);db.commit();await realtime.send("tracker-zone.changed",{"project_id":zone.project_id,"zone_id":zone.id});return result

@app.delete("/api/tracker-zones/{zone_id}")
async def delete_tracker_zone(zone_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    zone=db.get(Zone,zone_id)
    if not zone:raise HTTPException(404,"Brak strefy")
    project_id=zone.project_id
    row_ids=list(db.scalars(select(ConstructionRow.id).join(Section).where(Section.zone_id==zone_id)))
    for rfi in db.scalars(select(RFI).where(RFI.row_id.in_(row_ids or [-1]))):rfi.row_id=None
    for log in db.scalars(select(WorkLog).where(WorkLog.row_id.in_(row_ids or [-1]))):log.row_id=None
    for photo in db.scalars(select(Attachment).where(Attachment.entity_type=="row",Attachment.entity_id.in_(row_ids or [-1]))).all():(UPLOAD_DIR/photo.stored_name).unlink(missing_ok=True);db.delete(photo)
    db.execute(delete(ZoneVariantConfig).where(ZoneVariantConfig.zone_id==zone_id));db.delete(zone);db.flush();sync_project_variant_totals(db,project_id)
    audit(db,user,"delete","tracker_zone",zone_id,zone.name);db.commit();await realtime.send("tracker-zone.changed",{"project_id":project_id});return {"ok":True}

@app.get("/api/projects/{project_id}/operational-rows")
def operational_rows(project_id:int,zone_id:int|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    ensure_project_zone_configs(db,project_id)
    statement=select(ConstructionRow,Zone).join(Section,Section.id==ConstructionRow.section_id).join(Zone,Zone.id==Section.zone_id).where(Zone.project_id==project_id,ConstructionRow.auto_generated==True,ConstructionRow.active==True).options(selectinload(ConstructionRow.built_by),selectinload(ConstructionRow.qc_by))
    if zone_id is not None:statement=statement.where(Zone.id==zone_id)
    pairs=db.execute(statement).all();row_ids=[row.id for row,_ in pairs]
    photo_counts=dict(db.execute(select(Attachment.entity_id,func.count(Attachment.id)).where(Attachment.entity_type=="row",Attachment.entity_id.in_(row_ids or [-1])).group_by(Attachment.entity_id)).all())
    result=[]
    for row,zone in pairs:result.append({**row_dict(row),"zone_id":zone.id,"zone_name":zone.name,"photos":int(photo_counts.get(row.id,0))})
    result.sort(key=lambda item:(item["zone_id"],item["sort_order"],item["id"]))
    db.commit();return result

@app.post("/api/rows/{row_id}/move")
async def move_operational_row(row_id:int,data:RowMoveIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if data.direction not in ("up","down"):raise HTTPException(400,"Dozwolony kierunek: up lub down")
    row=db.get(ConstructionRow,row_id)
    if not row or not row.auto_generated or not row.active:raise HTTPException(404,"Brak aktywnego rzędu operacyjnego")
    section=db.get(Section,row.section_id);zone=db.get(Zone,section.zone_id)
    rows=db.scalars(select(ConstructionRow).join(Section).where(Section.zone_id==zone.id,ConstructionRow.auto_generated==True,ConstructionRow.active==True).order_by(ConstructionRow.sort_order,ConstructionRow.id)).all()
    index=next((position for position,item in enumerate(rows) if item.id==row_id),None)
    if index is None:raise HTTPException(404,"Brak rzędu na liście strefy")
    target=index-1 if data.direction=="up" else index+1
    if target<0 or target>=len(rows):return {"ok":True,"moved":False}
    rows[index],rows[target]=rows[target],rows[index]
    for item in rows:item.code=f"tmp-{uuid.uuid4().hex[:24]}"
    db.flush()
    for position,item in enumerate(rows,1):item.sort_order=position;item.code=str(position)
    audit(db,user,"move","row",row_id,data.direction);db.commit();await realtime.send("row-order.changed",{"project_id":zone.project_id,"zone_id":zone.id});return {"ok":True,"moved":True}

def document_dict(item):
    analysis=json.loads(item.analysis_json or "{}")
    return {"id":item.id,"filename":item.filename,"kind":item.kind,"size":item.size,"status":item.status,"approved_source":bool(analysis.get("approved_source")),"sha256":analysis.get("sha256"),"role":analysis.get("role"),"analysis":analysis,"uploaded_at":item.uploaded_at}

@app.get("/api/documents")
def documents(project_id:int|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    q=select(Document).order_by(Document.uploaded_at.desc())
    if project_id:q=q.where(Document.project_id==project_id)
    return [document_dict(x) for x in db.scalars(q)]

@app.post("/api/documents")
async def upload_document(project_id:int=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista","magazynier"))):
    if not db.get(Project,project_id): raise HTTPException(404,"Brak projektu")
    extension=Path(file.filename or "").suffix.lower()
    if extension not in (".pdf",".dwg",".dxf",".xlsx",".xlsm"): raise HTTPException(400,"Dozwolone: PDF, DWG, DXF, XLSX")
    data=read_upload_limited(file,MAX_DOCUMENT_SIZE,"Plik przekracza limit rozmiaru")
    if not data: raise HTTPException(400,"Plik jest pusty")
    digest=hashlib.sha256(data).hexdigest();source=source_entry_by_hash(digest)
    if source:
        existing=next((item for item in db.scalars(select(Document).where(Document.project_id==project_id)).all() if json.loads(item.analysis_json or "{}").get("sha256")==digest),None)
        if existing:return {"id":existing.id,"status":existing.status,"analysis":json.loads(existing.analysis_json or "{}"),"deduplicated":True}
        result=source_analysis(source);status="zatwierdzone źródło";filename=source["filename"]
    else:
        result={"approved_source":False,"sha256":digest,"summary":{"source_policy":"plik pomocniczy"},"warnings":["Plik zapisano, ale nie należy do dziesięciu zatwierdzonych źródeł. Nie zmienia instrukcji ani bazy BOM."]};status="pomocniczy — poza bazą źródłową";filename=Path(file.filename or "dokument").name
    item=Document(project_id=project_id,filename=filename,stored_name=f"db-{uuid.uuid4().hex}{extension}",kind=extension[1:].upper(),size=len(data),data=data,status=status,extracted_text="",analysis_json=json.dumps(result,ensure_ascii=False),uploaded_by_id=user.id)
    db.add(item);db.flush();audit(db,user,"upload","document",item.id,item.filename);db.commit();await realtime.send("document.changed",{"id":item.id});return {"id":item.id,"status":status,"analysis":result}

@app.get("/api/documents/{document_id}/file")
def document_file(document_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    item=db.get(Document,document_id)
    if not item: raise HTTPException(404,"Brak dokumentu")
    media_type=DOCUMENT_MIME.get(Path(item.filename).suffix.lower(),"application/octet-stream")
    if item.data is not None:return binary_response(item.data,media_type,item.filename)
    path=UPLOAD_DIR/item.stored_name
    if not path.is_file():raise HTTPException(404,"Plik dokumentu nie jest dostępny na serwerze")
    return FileResponse(path,filename=item.filename,media_type=media_type)

def document_is_plan(item):
    analysis=json.loads(item.analysis_json or "{}")
    if analysis.get("plan"):return True
    return bool(analysis.get("approved_source")) and item.kind=="PDF" and "planimetria" in item.filename.lower()

def plan_dict(item,users):
    analysis=json.loads(item.analysis_json or "{}");approved=bool(analysis.get("approved_source"))
    return {"id":item.id,"title":analysis.get("title") or item.filename,"filename":item.filename,"size":item.size,"approved_source":approved,"deletable":bool(analysis.get("plan")) and not approved,"uploaded_by":users.get(item.uploaded_by_id,"—"),"uploaded_at":item.uploaded_at,"file_url":f"/api/documents/{item.id}/file"}

@app.get("/api/plans")
def plans(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    users={person.id:person.full_name for person in db.scalars(select(User)).all()}
    items=[item for item in db.scalars(select(Document).where(Document.project_id==project_id)).all() if document_is_plan(item)]
    result=[plan_dict(item,users) for item in items]
    result.sort(key=lambda plan:(0,plan["filename"].lower()) if plan["approved_source"] else (1,"",-(plan["uploaded_at"].timestamp() if plan["uploaded_at"] else 0)))
    return result

@app.post("/api/plans")
async def upload_plan(project_id:int=Form(...),title:str=Form(""),file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    filename=Path(file.filename or "plan.pdf").name
    if Path(filename).suffix.lower()!=".pdf":raise HTTPException(400,"Plan musi być plikiem PDF")
    data=read_upload_limited(file,MAX_DOCUMENT_SIZE,"Plik przekracza limit rozmiaru")
    if not data.startswith(b"%PDF-"):raise HTTPException(400,"Plik nie jest poprawnym dokumentem PDF")
    digest=hashlib.sha256(data).hexdigest()
    if any(json.loads(item.analysis_json or "{}").get("sha256")==digest for item in db.scalars(select(Document).where(Document.project_id==project_id)).all()):
        raise HTTPException(409,"Ten plik jest już dodany w projekcie")
    source=source_entry_by_hash(digest)
    if source:
        if "planimetria" not in source["filename"].lower():raise HTTPException(400,"To zatwierdzone źródło techniczne, a nie plan. Dodaj je w zakładce Dokumenty.")
        analysis=source_analysis(source);status="zatwierdzone źródło";filename=source["filename"]
    else:
        clean_title=(title or "").strip()[:180] or Path(filename).stem
        analysis={"approved_source":False,"plan":True,"title":clean_title,"sha256":digest,"summary":{"source_policy":"plan dodatkowy"},"warnings":[]};status="plan dodatkowy"
    item=Document(project_id=project_id,filename=filename,stored_name=f"db-{uuid.uuid4().hex}.pdf",kind="PDF",size=len(data),data=data,status=status,extracted_text="",analysis_json=json.dumps(analysis,ensure_ascii=False),uploaded_by_id=user.id)
    db.add(item);db.flush();audit(db,user,"upload","plan",item.id,item.filename);result={"id":item.id}
    db.commit();await realtime.send("plan.changed",{"project_id":project_id});return result

@app.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Document,plan_id)
    if not item or not document_is_plan(item):raise HTTPException(404,"Brak planu")
    analysis=json.loads(item.analysis_json or "{}")
    if analysis.get("approved_source") or not analysis.get("plan"):raise HTTPException(403,"Zatwierdzone źródła są chronione przed usunięciem")
    project_id=item.project_id;(UPLOAD_DIR/item.stored_name).unlink(missing_ok=True)
    audit(db,user,"delete","plan",item.id,item.filename);db.delete(item);db.commit();await realtime.send("plan.changed",{"project_id":project_id});return {"ok":True}

@app.get("/api/instructions")
def instructions(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    docs=db.scalars(select(Document).where(Document.project_id==project_id).order_by(Document.uploaded_at.desc())).all();result=[]
    for doc in docs:
        analysis=json.loads(doc.analysis_json or "{}")
        if not analysis.get("approved_source"):continue
        for value in analysis.get("instructions",[]): result.append({**value,"document_id":doc.id,"source":doc.filename})
    return result

@app.post("/api/worklogs")
async def create_worklog(data:WorkLogIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    if data.client_id:
        existing=db.scalar(select(WorkLog).where(WorkLog.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    if data.row_id:
        row=db.scalar(select(ConstructionRow).join(Section).join(Zone).where(ConstructionRow.id==data.row_id,Zone.project_id==data.project_id))
        if not row:raise HTTPException(400,"Rząd nie należy do wybranego projektu")
    item=WorkLog(**data.model_dump(),author_id=user.id);db.add(item);db.flush();audit(db,user,"create","worklog",item.id);db.commit();await realtime.send("worklog.changed",{"project_id":data.project_id});return {"id":item.id}

@app.get("/api/worklogs")
def worklogs(project_id:int,work_date:date|None=None,db:Session=Depends(get_db),user=Depends(current_user)):
    q=select(WorkLog).where(WorkLog.project_id==project_id).order_by(WorkLog.work_date.desc(),WorkLog.created_at.desc())
    if work_date:q=q.where(WorkLog.work_date==work_date)
    result=[]
    for x in db.scalars(q).all():
        photos=db.scalar(select(func.count(Attachment.id)).where(Attachment.entity_type=="worklog",Attachment.entity_id==x.id)) or 0
        result.append({"id":x.id,"work_date":x.work_date,"team":x.team,"stage":x.stage,"people":x.people,"hours":x.hours,"rows_completed":x.rows_completed,"manhours":x.people*x.hours,"qc_notes":x.qc_notes,"note":x.note,"row_id":x.row_id,"photos":photos})
    return result

@app.patch("/api/worklogs/{worklog_id}")
async def update_worklog(worklog_id:int,data:WorkLogUpdate,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista"))):
    item=db.get(WorkLog,worklog_id)
    if not item:raise HTTPException(404,"Brak meldunku")
    for key,value in data.model_dump(exclude_unset=True).items():setattr(item,key,value)
    db.commit();await realtime.send("worklog.changed",{"project_id":item.project_id});return {"ok":True}

@app.delete("/api/worklogs/{worklog_id}")
async def delete_worklog(worklog_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(WorkLog,worklog_id)
    if not item:raise HTTPException(404,"Brak meldunku")
    for photo in db.scalars(select(Attachment).where(Attachment.entity_type=="worklog",Attachment.entity_id==worklog_id)).all():(UPLOAD_DIR/photo.stored_name).unlink(missing_ok=True);db.delete(photo)
    project_id=item.project_id;db.delete(item);db.commit();await realtime.send("worklog.changed",{"project_id":project_id});return {"ok":True}

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
    entity_models={"row":ConstructionRow,"rfi":RFI,"worklog":WorkLog}
    if entity_type not in entity_models:raise HTTPException(400,"Zdjęcie można przypisać do rzędu, RFI lub meldunku")
    entity=db.get(entity_models[entity_type],entity_id)
    if not entity:raise HTTPException(404,"Nie znaleziono wskazanego obiektu")
    mime=(file.content_type or "").lower()
    if mime not in ALLOWED_PHOTO_MIME:raise HTTPException(400,"Wymagane zdjęcie w formacie JPEG, PNG, WebP, GIF lub HEIC")
    data=read_upload_limited(file,MAX_PHOTO_SIZE,"Zdjęcie przekracza limit 25 MB")
    if not data:raise HTTPException(400,"Plik zdjęcia jest pusty")
    extension=Path(file.filename or ".jpg").suffix.lower() or ".jpg"
    item=Attachment(entity_type=entity_type,entity_id=entity_id,filename=Path(file.filename or "zdjecie.jpg").name,stored_name=f"db-{uuid.uuid4().hex}{extension}",mime_type=mime,data=data,size=len(data),uploaded_by_id=user.id);db.add(item);db.commit();await realtime.send(f"{entity_type}.photo",{"id":entity_id});return {"id":item.id}

@app.get("/api/{entity_type}/{entity_id}/photos")
def photos(entity_type:str,entity_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if entity_type not in ("row","rfi","worklog"):raise HTTPException(400,"Nieznany typ obiektu")
    items=db.scalars(select(Attachment).where(Attachment.entity_type==entity_type,Attachment.entity_id==entity_id).order_by(Attachment.created_at.desc())).all()
    authors={person.id:person.full_name for person in db.scalars(select(User)).all()}
    return [{"id":item.id,"filename":item.filename,"mime_type":item.mime_type,"created_at":item.created_at,"author":authors.get(item.uploaded_by_id,"—"),"url":f"/api/attachments/{item.id}"} for item in items]

@app.get("/api/attachments/{attachment_id}")
def attachment(attachment_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    item=db.get(Attachment,attachment_id)
    if not item:raise HTTPException(404,"Brak załącznika")
    if item.data is not None:return binary_response(item.data,item.mime_type,item.filename,"inline")
    path=UPLOAD_DIR/item.stored_name
    if not path.is_file():raise HTTPException(404,"Plik zdjęcia nie jest dostępny na serwerze")
    return FileResponse(path,media_type=item.mime_type,filename=item.filename)

@app.post("/api/deliveries")
async def create_delivery(data:DeliveryIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista","magazynier"))):
    if data.client_id:
        existing=db.scalar(select(SiteDelivery).where(SiteDelivery.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    material_ids={item.id for item in db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==data.project_id))}
    if any(value.material_id not in material_ids for value in data.items):raise HTTPException(400,"Pozycja dostawy nie należy do trzech materiałów projektu")
    payload=data.model_dump(exclude={"items"});item=SiteDelivery(**payload,created_by_id=user.id);db.add(item);db.flush()
    for value in data.items:db.add(SiteDeliveryItem(delivery_id=item.id,**value.model_dump()))
    audit(db,user,"create","delivery",item.id,item.wz_number);db.commit();await realtime.send("delivery.changed",{"project_id":data.project_id});return {"id":item.id}

@app.get("/api/deliveries")
def deliveries(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    items=db.scalars(select(SiteDelivery).where(SiteDelivery.project_id==project_id).options(selectinload(SiteDelivery.items).selectinload(SiteDeliveryItem.material)).order_by(SiteDelivery.delivery_date.desc(),SiteDelivery.created_at.desc())).all()
    return [{"id":x.id,"delivery_date":x.delivery_date,"wz_number":x.wz_number,"supplier":x.supplier,"note":x.note,"items":[{"material_id":i.material_id,"name":i.material.name,"quantity_received":i.quantity_received,"quantity_damaged":i.quantity_damaged,"unit":i.material.unit} for i in x.items]} for x in items]

@app.get("/api/projects/{project_id}/materials")
def project_materials(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    ensure_materials(db,project_id);db.commit()
    return [{"id":item.id,"slot_number":item.slot_number,"name":item.name,"unit":item.unit,"required_quantity":item.required_quantity} for item in db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==project_id).order_by(ProjectMaterial.slot_number))]

@app.put("/api/projects/{project_id}/materials")
async def update_project_materials(project_id:int,data:MaterialListIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","magazynier"))):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    if {item.slot_number for item in data.items}!={1,2,3}:raise HTTPException(400,"Lista musi zawierać dokładnie pozycje 1, 2 i 3")
    ensure_materials(db,project_id);db.flush();by_slot={item.slot_number:item for item in db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==project_id))}
    for value in data.items:
        item=by_slot[value.slot_number];item.name=value.name;item.unit=value.unit;item.required_quantity=value.required_quantity
    audit(db,user,"update","project_materials",project_id);db.commit();await realtime.send("materials.changed",{"project_id":project_id});return {"ok":True}

@app.get("/api/logistics/stock")
def stock(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    ensure_materials(db,project_id);db.commit();slots=db.scalars(select(ProjectMaterial).where(ProjectMaterial.project_id==project_id).order_by(ProjectMaterial.slot_number)).all()
    received=dict(db.execute(select(SiteDeliveryItem.material_id,func.sum(SiteDeliveryItem.quantity_received-SiteDeliveryItem.quantity_damaged)).join(SiteDelivery).where(SiteDelivery.project_id==project_id).group_by(SiteDeliveryItem.material_id)).all())
    return [{"material_id":item.id,"slot_number":item.slot_number,"name":item.name,"unit":item.unit,"required":float(item.required_quantity or 0),"available":float(received.get(item.id,0) or 0),"balance":float(received.get(item.id,0) or 0)-float(item.required_quantity or 0),"status":"komplet" if float(received.get(item.id,0) or 0)>=float(item.required_quantity or 0) else "brak"} for item in slots]

def bom_delivery_status_payload(db,project_id):
    demand=project_demand(db,project_id)
    ensure_bom_components(db);db.flush()
    definitions=bom_catalogue()
    required={item["key"]:float(item["quantity_total"]) for item in demand["grand_total"]}
    required[MODULE_COMPONENT_SKU]=float(demand["total_modules"])
    components=db.scalars(select(Component).where(Component.sku.in_(list(definitions)))).all()
    totals={component_id:(float(received or 0),float(damaged or 0)) for component_id,received,damaged in db.execute(select(DeliveryItem.component_id,func.sum(DeliveryItem.quantity_received),func.sum(DeliveryItem.quantity_damaged)).join(Delivery).where(Delivery.project_id==project_id).group_by(DeliveryItem.component_id)).all()}
    category_order={name:index for index,name in enumerate(["Moduły PV","Słupy","Napęd i łożyska","Rury torsyjne","Płatwie","Amortyzatory","Sterowanie","Śruby i zestawy"])}
    items=[]
    for component in components:
        definition=definitions[component.sku];received,damaged=totals.get(component.id,(0.0,0.0));available=received-damaged;needed=required.get(component.sku,0.0)
        items.append({**definition,"component_id":component.id,"required":needed,"delivered":received,"damaged":damaged,"available":available,"balance":available-needed,"completion_pct":round(min(100,available/needed*100),1) if needed>0 else (100 if available>0 else 0),"status":"komplet" if needed>0 and available>=needed else "brak" if needed>0 else "poza zapotrzebowaniem"})
    items.sort(key=lambda item:(category_order.get(item["category"],99),item["name"],item["key"]))
    required_items=[item for item in items if item["required"]>0]
    deliveries_count=db.scalar(select(func.count(Delivery.id)).where(Delivery.project_id==project_id)) or 0
    return {"project_id":project_id,"demand":{"total_rows":demand["total_rows"],"total_modules":demand["total_modules"]},"summary":{"catalogue_items":len(items),"required_items":len(required_items),"complete_items":sum(item["available"]>=item["required"] for item in required_items),"missing_items":sum(item["available"]<item["required"] for item in required_items),"deliveries_count":int(deliveries_count)},"items":items}

@app.get("/api/projects/{project_id}/bom-delivery-status")
def bom_delivery_status(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    result=bom_delivery_status_payload(db,project_id);db.commit();return result

@app.post("/api/bom-deliveries")
async def create_bom_delivery(data:BomDeliveryIn,db:Session=Depends(get_db),user=Depends(roles("kierownik","brygadzista","magazynier"))):
    if not db.get(Project,data.project_id):raise HTTPException(404,"Brak projektu")
    if not data.wz_number.strip():raise HTTPException(400,"Numer WZ jest wymagany")
    if data.client_id:
        existing=db.scalar(select(Delivery).where(Delivery.client_id==data.client_id))
        if existing:return {"id":existing.id,"deduplicated":True}
    if len({line.component_id for line in data.items})!=len(data.items):raise HTTPException(400,"Każdy element BOM może wystąpić tylko raz w jednym WZ")
    if any(line.quantity_damaged>line.quantity_received for line in data.items):raise HTTPException(400,"Ilość uszkodzona nie może przekraczać ilości dostarczonej")
    ensure_bom_components(db);db.flush();approved={item.id for item in db.scalars(select(Component).where(Component.sku.in_(list(bom_catalogue()))))}
    if any(line.component_id not in approved for line in data.items):raise HTTPException(400,"Pozycja nie należy do zatwierdzonej listy BOM")
    payload=data.model_dump(exclude={"items"});payload["wz_number"]=payload["wz_number"].strip()
    item=Delivery(**payload,created_by_id=user.id);db.add(item);db.flush()
    for line in data.items:db.add(DeliveryItem(delivery_id=item.id,**line.model_dump()))
    audit(db,user,"create","bom_delivery",item.id,item.wz_number);db.commit();await realtime.send("bom-delivery.changed",{"project_id":data.project_id});return {"id":item.id}

@app.get("/api/bom-deliveries")
def bom_deliveries(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if not db.get(Project,project_id):raise HTTPException(404,"Brak projektu")
    items=db.scalars(select(Delivery).where(Delivery.project_id==project_id).options(selectinload(Delivery.items).selectinload(DeliveryItem.component)).order_by(Delivery.delivery_date.desc(),Delivery.created_at.desc())).all()
    users={item.id:item.full_name for item in db.scalars(select(User)).all()}
    return [{"id":item.id,"delivery_date":item.delivery_date,"wz_number":item.wz_number,"supplier":item.supplier,"note":item.note,"created_at":item.created_at,"created_by":users.get(item.created_by_id,"—"),"items":[{"component_id":line.component_id,"key":line.component.sku,"name":line.component.name,"unit":line.component.unit,"quantity_received":line.quantity_received,"quantity_damaged":line.quantity_damaged} for line in item.items]} for item in items]

@app.delete("/api/bom-deliveries/{delivery_id}")
async def delete_bom_delivery(delivery_id:int,db:Session=Depends(get_db),user=Depends(roles("kierownik"))):
    item=db.get(Delivery,delivery_id)
    if not item:raise HTTPException(404,"Brak dostawy")
    project_id=item.project_id;audit(db,user,"delete","bom_delivery",item.id,item.wz_number);db.delete(item);db.commit();await realtime.send("bom-delivery.changed",{"project_id":project_id});return {"ok":True}

@app.get("/api/dashboard")
def dashboard(project_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    legacy_total,built,qc=db.execute(select(func.count(ConstructionRow.id),func.sum(func.cast(ConstructionRow.built,Integer)),func.sum(func.cast(ConstructionRow.qc_checked,Integer))).join(Section).join(Zone).where(Zone.project_id==project_id,ConstructionRow.active==True)).one();legacy_total=legacy_total or 0;built=built or 0;qc=qc or 0
    open_rfi=db.scalar(select(func.count(RFI.id)).where(RFI.project_id==project_id,RFI.status!="zamknięty")) or 0
    rows_done,manhours,days=db.execute(select(func.sum(WorkLog.rows_completed),func.sum(WorkLog.people*WorkLog.hours),func.count(func.distinct(WorkLog.work_date))).where(WorkLog.project_id==project_id)).one();rows_done=rows_done or 0;manhours=manhours or 0;days=days or 0
    configured_total=project_demand(db,project_id)["total_rows"];total=configured_total or legacy_total;built=min(total,max(float(built),float(rows_done))) if total else float(built)
    productivity=rows_done/manhours if manhours else 0;daily=rows_done/days if days else 0;forecast=max(0,total-built)/daily if daily else None
    db.commit();return {"rows_total":total,"rows_built":built,"rows_remaining":total-built,"rows_qc":qc,"completion_pct":round(100*built/total,1) if total else 0,"qc_pct":round(100*qc/total,1) if total else 0,"open_rfi":open_rfi,"manhours":round(manhours,1),"productivity":round(productivity,4),"forecast_days":round(forecast,1) if forecast is not None else None,"offline_supported":True}

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
        target=(FRONTEND/full_path).resolve()
        if full_path and target.is_file() and target.is_relative_to(FRONTEND.resolve()):return FileResponse(target)
        if Path(full_path).suffix:raise HTTPException(404,"Nie znaleziono pliku")
        return FileResponse(FRONTEND/"index.html")

if LAN_MODE:
    for _url in lan_urls(int(os.getenv("PORT","8765"))) or ["(nie wykryto adresu sieci lokalnej)"]:
        print(f"[ASOLAR] Adres dla telefonów w tej samej sieci Wi-Fi: {_url}",flush=True)
