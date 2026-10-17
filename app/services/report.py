from io import BytesIO
from pathlib import Path
from datetime import date
from xml.sax.saxutils import escape
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
from ..models import ConstructionRow, Project, RFI, Section, User, WorkLog, Zone

# Czcionki z polskimi znakami: Linux/Docker (DejaVu) oraz Windows (Arial / Segoe UI).
FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]
_FONT = None


def report_font() -> str:
    global _FONT
    if _FONT:
        return _FONT
    _FONT = "Helvetica"
    for path in FONT_CANDIDATES:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("ASOLAR-PL", str(path)))
                _FONT = "ASOLAR-PL"
                break
            except Exception:
                continue
    return _FONT


def _table(data, widths, font, header=True):
    table = Table(data, repeatRows=1 if header else 0, colWidths=widths)
    style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#d5ddd9")), ("PADDING", (0, 0), (-1, -1), 5), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123e30")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    else:
        style += [("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf2ed"))]
    table.setStyle(TableStyle(style))
    return table


def daily_report(db: Session, project: Project, report_date: date, kpi: dict | None = None) -> BytesIO:
    font = report_font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("PL", parent=styles["BodyText"], fontName=font, fontSize=8.5, leading=12, textColor=colors.HexColor("#33443c"))
    small = ParagraphStyle("PLSmall", parent=normal, fontSize=7, leading=9.5)
    title = ParagraphStyle("PLTitle", parent=styles["Title"], fontName=font, fontSize=18, leading=22, textColor=colors.HexColor("#123e30"), alignment=TA_LEFT)
    heading = ParagraphStyle("PLHeading", parent=styles["Heading2"], fontName=font, fontSize=11, textColor=colors.HexColor("#123e30"), spaceBefore=10, spaceAfter=6)
    p = lambda text, style=normal: Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    if kpi is None:
        total, built, qc = db.execute(select(func.count(ConstructionRow.id), func.sum(func.cast(ConstructionRow.built, Integer)), func.sum(func.cast(ConstructionRow.qc_checked, Integer))).join(Section).join(Zone).where(Zone.project_id == project.id, ConstructionRow.active == True)).one()
        kpi = {"rows_total": total or 0, "rows_built": built or 0, "rows_qc": qc or 0, "completion_pct": round(100 * (built or 0) / total, 1) if total else 0, "qc_pct": round(100 * (qc or 0) / total, 1) if total else 0, "forecast_days": None, "forecast_date": None, "forecast_status": "brak danych", "forecast_assumptions": [], "productivity": 0}
    users = {item.id: item.full_name for item in db.scalars(select(User)).all()}
    logs = db.scalars(select(WorkLog).where(WorkLog.project_id == project.id, WorkLog.work_date == report_date).order_by(WorkLog.team, WorkLog.created_at)).all()
    rfis = db.scalars(select(RFI).where(RFI.project_id == project.id, RFI.status != "zamknięty").order_by(RFI.created_at)).all()
    priority_rank = {"krytyczny": 0, "wysoki": 1, "normalny": 2, "niski": 3}
    rfis = sorted(rfis, key=lambda item: (priority_rank.get(item.priority, 9), item.created_at))
    people_today = sum(log.people for log in logs)
    manhours_today = sum(log.people * log.hours for log in logs)
    rows_today = sum(log.rows_completed for log in logs)
    zones = db.execute(select(Zone.name, func.count(ConstructionRow.id), func.sum(func.cast(ConstructionRow.built, Integer)), func.sum(func.cast(ConstructionRow.qc_checked, Integer))).join(Section, Section.zone_id == Zone.id).join(ConstructionRow, ConstructionRow.section_id == Section.id).where(Zone.project_id == project.id, ConstructionRow.active == True).group_by(Zone.id, Zone.name).order_by(Zone.name)).all()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=f"Raport dzienny {project.name}")
    story = [p("ASOLAR — RAPORT DZIENNY BUDOWY", title), p(f"{project.name} · {project.location or 'brak lokalizacji'} · {report_date.isoformat()}"), Spacer(1, 6 * mm)]

    story.append(p("Dzień w liczbach", heading))
    story.append(_table([
        ["Meldunki z dnia", str(len(logs))],
        ["Liczba osób (suma z meldunków)", str(people_today)],
        ["Roboczogodziny", f"{manhours_today:.1f}"],
        ["Rzędy zgłoszone w meldunkach", f"{rows_today:g}"],
        ["Tempo dnia", f"{rows_today / manhours_today:.3f} rzędu/rbh" if manhours_today else "brak danych"],
    ], [70 * mm, 40 * mm], font, header=False))

    story.append(p("Postęp projektu", heading))
    forecast = f"{kpi['forecast_days']} dni (ok. {kpi['forecast_date']})" if kpi.get("forecast_days") is not None else kpi.get("forecast_status", "brak danych")
    story.append(_table([
        ["Rzędy zbudowane", f"{kpi['rows_built']}/{kpi['rows_total']} ({kpi['completion_pct']}%)"],
        ["Odebrane QA/QC", f"{kpi['rows_qc']}/{kpi['rows_total']} ({kpi['qc_pct']}%)"],
        ["Średnie tempo projektu", f"{kpi.get('productivity', 0):.3f} rzędu/rbh"],
        ["Prognoza zakończenia", forecast],
    ], [70 * mm, 70 * mm], font, header=False))
    if kpi.get("forecast_assumptions"):
        story.append(Spacer(1, 2 * mm))
        for line in kpi["forecast_assumptions"]:
            story.append(p(f"• {line}", small))
    if zones:
        story.append(Spacer(1, 3 * mm))
        story.append(_table([["Strefa", "Rzędy", "Zbudowane", "QA/QC"]] + [[p(name, small), str(total or 0), str(built or 0), str(qc or 0)] for name, total, built, qc in zones], [80 * mm, 25 * mm, 25 * mm, 25 * mm], font))

    story.append(p("Prace wykonane", heading))
    work = [["Brygada / autor", "Opis robót", "Osoby", "Godz.", "Rzędy", "Rbh"]]
    for log in logs:
        work.append([p(f"{log.team}\n{users.get(log.author_id, '—')}", small), p(log.stage + (f"\nUwagi: {log.note}" if log.note else ""), small), str(log.people), f"{log.hours:g}", f"{log.rows_completed:g}", f"{log.people * log.hours:g}"])
    if len(work) == 1:
        work.append(["Brak wpisów", "—", "—", "—", "—", "—"])
    story.append(_table(work, [32 * mm, 72 * mm, 13 * mm, 13 * mm, 14 * mm, 14 * mm], font))

    story.append(p("Dziennik jakości QA/QC", heading))
    quality = [["Brygada", "Notatka QA/QC"]] + [[p(log.team, small), p(log.qc_notes, small)] for log in logs if (log.qc_notes or "").strip()]
    if len(quality) == 1:
        quality.append(["—", "Brak wpisów QA/QC"])
    story.append(_table(quality, [35 * mm, 127 * mm], font))

    story.append(p("Otwarte RFI / problemy", heading))
    rfi = [["ID", "Priorytet", "Tytuł", "Status", "Odpowiedzialny"]] + [[str(x.id), x.priority, p(x.title, small), x.status, users.get(x.assigned_to_id, "—") if x.assigned_to_id else "—"] for x in rfis]
    if len(rfi) == 1:
        rfi.append(["—", "—", "Brak otwartych zgłoszeń", "—", "—"])
    story.append(_table(rfi, [12 * mm, 22 * mm, 78 * mm, 22 * mm, 28 * mm], font))

    story += [Spacer(1, 8 * mm), p("Raport wygenerowany przez ASOLAR ESET Tracker Manager. Zakres: montaż mechaniczny konstrukcji.", small)]
    doc.build(story)
    output.seek(0)
    return output
