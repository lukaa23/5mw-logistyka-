from io import BytesIO
from pathlib import Path
from datetime import date
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session
from ..models import ConstructionRow, Project, RFI, Section, WorkLog, Zone

FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

def daily_report(db: Session, project: Project, report_date: date) -> BytesIO:
    font="Helvetica"
    if FONT_PATH.exists():
        try: pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_PATH))); font="DejaVu"
        except Exception: pass
    styles=getSampleStyleSheet()
    normal=ParagraphStyle("PL",parent=styles["BodyText"],fontName=font,fontSize=8.5,leading=12,textColor=colors.HexColor("#33443c"))
    title=ParagraphStyle("PLTitle",parent=styles["Title"],fontName=font,fontSize=18,leading=22,textColor=colors.HexColor("#123e30"),alignment=TA_LEFT)
    heading=ParagraphStyle("PLHeading",parent=styles["Heading2"],fontName=font,fontSize=11,textColor=colors.HexColor("#123e30"),spaceBefore=10,spaceAfter=6)
    total,built,qc=db.execute(select(func.count(ConstructionRow.id),func.sum(func.cast(ConstructionRow.built,Integer)),func.sum(func.cast(ConstructionRow.qc_checked,Integer))).join(Section).join(Zone).where(Zone.project_id==project.id)).one()
    total=total or 0; built=built or 0; qc=qc or 0
    logs=db.scalars(select(WorkLog).where(WorkLog.project_id==project.id,WorkLog.work_date==report_date).order_by(WorkLog.team)).all()
    rfis=db.scalars(select(RFI).where(RFI.project_id==project.id,RFI.status!="zamknięty").order_by(RFI.priority.desc())).all()
    manhours=sum(log.people*log.hours for log in logs); rows_today=sum(log.rows_completed for log in logs)
    productivity=rows_today/manhours if manhours else 0
    historical=db.execute(select(func.sum(WorkLog.rows_completed),func.count(func.distinct(WorkLog.work_date))).where(WorkLog.project_id==project.id)).one()
    daily_rate=(historical[0] or 0)/(historical[1] or 1); forecast=(total-built)/daily_rate if daily_rate else None
    output=BytesIO(); doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=15*mm,leftMargin=15*mm,topMargin=14*mm,bottomMargin=14*mm,title=f"Raport dzienny {project.name}")
    story=[Paragraph("ASOLAR — RAPORT DZIENNY BUDOWY",title),Paragraph(f"{project.name} · {project.location} · {report_date.isoformat()}",normal),Spacer(1,7*mm)]
    kpi=[["Rzędy wykonane",f"{built}/{total}"],["Odebrane QA/QC",f"{qc}/{total}"],["Roboczogodziny",f"{manhours:.1f}"],["Tempo",f"{productivity:.3f} rzędu/rbh"],["Prognoza",f"{forecast:.1f} dni" if forecast is not None else "brak danych"]]
    table=Table(kpi,colWidths=[55*mm,35*mm]); table.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),8),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eaf2ed")),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#cbd8d1")),("PADDING",(0,0),(-1,-1),6)])); story.append(table)
    story.append(Paragraph("Prace wykonane",heading))
    work_data=[["Brygada","Etap","Osoby","Godz.","Rzędy","Rbh"]]+[[x.team,x.stage,str(x.people),f"{x.hours:g}",f"{x.rows_completed:g}",f"{x.people*x.hours:g}"] for x in logs]
    if len(work_data)==1: work_data.append(["Brak wpisów","—","—","—","—","—"])
    work=Table(work_data,repeatRows=1,colWidths=[30*mm,55*mm,15*mm,15*mm,17*mm,17*mm]); work.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),7),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#123e30")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#d5ddd9")),("PADDING",(0,0),(-1,-1),5)])); story.append(work)
    story.append(Paragraph("Otwarte RFI / problemy",heading))
    rfi_data=[["ID","Priorytet","Tytuł","Status"]]+[[str(x.id),x.priority,x.title,x.status] for x in rfis]
    if len(rfi_data)==1:rfi_data.append(["—","—","Brak otwartych zgłoszeń","—"])
    rfi=Table(rfi_data,repeatRows=1,colWidths=[12*mm,25*mm,100*mm,25*mm]); rfi.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),font),("FONTSIZE",(0,0),(-1,-1),7),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#123e30")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#d5ddd9")),("PADDING",(0,0),(-1,-1),5)])); story.append(rfi)
    story += [Spacer(1,8*mm),Paragraph("Raport wygenerowany przez ASOLAR Enterprise Construction & Logistics Manager.",normal)]
    doc.build(story); output.seek(0); return output
