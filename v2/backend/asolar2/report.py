"""Etap 4c: raport dzienny budowy (PDF) i pulpit postępu — przeniesione z v1, liczone ze stołów.

Prognoza jest liczona tylko z rzeczywistych dat montażu (built_at) i zawsze zwraca swoje założenia.
"""
import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from . import logistics
from .tenancy import Delivery, DeliveryItem, SiteTable, StructureType, TableNote, WorkLog, Zone

FORECAST_WINDOW_DAYS = 14
FORECAST_MIN_DAYS = 2
FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]
_font = None


def dashboard(session, today: date | None = None) -> dict:
    today = today or date.today()
    tables = session.scalars(select(SiteTable)).all()
    total = len(tables)
    built = sum(bool(t.built) for t in tables)
    qc = sum(bool(t.qc_checked) for t in tables)
    remaining = total - built
    window_start = today - timedelta(days=FORECAST_WINDOW_DAYS - 1)
    per_day = Counter(t.built_at.date() for t in tables if t.built and t.built_at and t.built_at.date() >= window_start)
    history = [{"date": (window_start + timedelta(days=i)).isoformat(), "built": per_day.get(window_start + timedelta(days=i), 0)} for i in range(FORECAST_WINDOW_DAYS)]
    active_days = [day for day, count in per_day.items() if count]
    daily = sum(per_day.values()) / len(active_days) if active_days else 0
    forecast_days = forecast_date = None
    if total and not remaining:
        status = "montaż zakończony"
    elif len(active_days) >= FORECAST_MIN_DAYS and daily > 0:
        forecast_days = math.ceil(remaining / daily)
        forecast_date = (today + timedelta(days=forecast_days)).isoformat()
        status = "szacunek"
    else:
        status = f"za mało danych — potrzeba montażu z co najmniej {FORECAST_MIN_DAYS} różnych dni w ostatnich {FORECAST_WINDOW_DAYS} dniach"
    assumptions = [
        "Postęp i odbiór QA/QC liczone są ze statusów stołów oznaczonych w aplikacji.",
        f"Tempo = średnia liczba stołów zamontowanych w dniach, w których był montaż (ostatnie {FORECAST_WINDOW_DAYS} dni: {len(active_days)} dni, {daily:.1f} stołu/dzień).",
        "Prognoza zakłada kolejne dni robocze z takim samym tempem — nie uwzględnia przerw, pogody, braków materiałów ani zmian liczby brygad.",
    ]
    stock = logistics.stock(session)
    worklogs_today = session.scalars(select(WorkLog).where(WorkLog.work_date == today)).all()
    return {"tables_total": total, "tables_built": built, "tables_qc": qc, "tables_remaining": remaining,
            "built_pct": round(100 * built / total, 1) if total else 0, "qc_pct": round(100 * qc / total, 1) if total else 0,
            "built_today": per_day.get(today, 0), "history": history, "daily_rate": round(daily, 2),
            "forecast_days": forecast_days, "forecast_date": forecast_date, "forecast_status": status, "forecast_assumptions": assumptions,
            "materials_missing": stock["summary"]["missing_items"], "materials_required": stock["summary"]["required_items"],
            "deliveries": stock["summary"]["deliveries"], "worklogs_today": len(worklogs_today),
            "manhours_today": round(sum(w.people * w.hours for w in worklogs_today), 1)}


def report_font() -> str:
    global _font
    if _font:
        return _font
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    _font = "Helvetica"
    for path in FONT_CANDIDATES:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("ASOLAR-PL", str(path)))
                _font = "ASOLAR-PL"
                break
            except Exception:
                continue
    return _font


def _pdf_kit():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    font = report_font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("PL", parent=styles["BodyText"], fontName=font, fontSize=8.5, leading=12, textColor=colors.HexColor("#33443c"))
    small = ParagraphStyle("PLSmall", parent=normal, fontSize=7, leading=9.5)
    title = ParagraphStyle("PLTitle", parent=styles["Title"], fontName=font, fontSize=17, leading=21, textColor=colors.HexColor("#123e30"), alignment=TA_LEFT)
    heading = ParagraphStyle("PLHeading", parent=styles["Heading2"], fontName=font, fontSize=11, textColor=colors.HexColor("#123e30"), spaceBefore=10, spaceAfter=6)
    return font, normal, small, title, heading


def zone_protocol(session, project, zone, users: dict[int, str]) -> bytes:
    """Protokół montażu i odbioru QA/QC strefy: każdy rząd z wariantem, kto i kiedy zamontował i odebrał."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, normal, small, title, heading = _pdf_kit()
    p = lambda text, style=normal: Paragraph(escape(str(text or "")), style)
    tables = session.scalars(select(SiteTable).where(SiteTable.zone_id == zone.id).order_by(SiteTable.prefix, SiteTable.number, SiteTable.code)).all()
    types = {t.id: t.code for t in session.scalars(select(StructureType)).all()}
    notes = dict(session.execute(select(TableNote.table_id, func.count(TableNote.id)).where(TableNote.table_id.in_([t.id for t in tables] or [-1])).group_by(TableNote.table_id)).all())
    built = sum(bool(t.built) for t in tables)
    qc = sum(bool(t.qc_checked) for t in tables)
    stamp = lambda who, when: f"{users.get(who, '—')} · {when:%Y-%m-%d %H:%M}" if when else "—"
    data = [["Rząd", "Wariant", "Montaż", "Odbiór QA/QC", "Notatki"]]
    for t in tables:
        data.append([t.code, types.get(t.structure_type_id, "—"), p(stamp(t.built_by, t.built_at) if t.built else "nie", small),
                     p(stamp(t.qc_by, t.qc_at) if t.qc_checked else "nie", small), str(notes.get(t.id, 0) or "")])
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=f"Protokół {zone.name}")
    table = Table(data, repeatRows=1, colWidths=[28 * mm, 30 * mm, 46 * mm, 46 * mm, 18 * mm])
    table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#d5ddd9")),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123e30")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [p("ASOLAR — PROTOKÓŁ MONTAŻU I ODBIORU STREFY", title), p(f"{project.name} · strefa: {zone.name}{f' — {zone.description}' if zone.description else ''}"),
             p(f"Rzędów: {len(tables)} · zamontowanych: {built} · odebranych QA/QC: {qc} · wygenerowano: {datetime.now():%Y-%m-%d %H:%M}"), Spacer(1, 5 * mm), table,
             Spacer(1, 12 * mm), p("Podpis kierownika budowy: ..............................................    Podpis odbierającego: ..............................................", small)]
    doc.build(story)
    return output.getvalue()


def daily_report(session, project, users: dict[int, str], report_date: date) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = report_font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("PL", parent=styles["BodyText"], fontName=font, fontSize=8.5, leading=12, textColor=colors.HexColor("#33443c"))
    small = ParagraphStyle("PLSmall", parent=normal, fontSize=7, leading=9.5)
    title = ParagraphStyle("PLTitle", parent=styles["Title"], fontName=font, fontSize=18, leading=22, textColor=colors.HexColor("#123e30"), alignment=TA_LEFT)
    heading = ParagraphStyle("PLHeading", parent=styles["Heading2"], fontName=font, fontSize=11, textColor=colors.HexColor("#123e30"), spaceBefore=10, spaceAfter=6)

    def p(text, style=normal):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    def table(data, widths, header=True):
        result = Table(data, repeatRows=1 if header else 0, colWidths=widths)
        style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#d5ddd9")),
                 ("PADDING", (0, 0), (-1, -1), 5), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123e30")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)] if header else [("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf2ed"))]
        result.setStyle(TableStyle(style))
        return result

    start, end = datetime.combine(report_date, time.min), datetime.combine(report_date + timedelta(days=1), time.min)
    kpi = dashboard(session, report_date)
    tables = session.scalars(select(SiteTable)).all()
    built_day = sorted((t for t in tables if t.built and t.built_at and start <= t.built_at < end), key=lambda t: (t.prefix, t.number))
    qc_day = sorted((t for t in tables if t.qc_checked and t.qc_at and start <= t.qc_at < end), key=lambda t: (t.prefix, t.number))
    logs = session.scalars(select(WorkLog).where(WorkLog.work_date == report_date).order_by(WorkLog.team, WorkLog.id)).all()
    deliveries = session.scalars(select(Delivery).where(Delivery.delivery_date == report_date).order_by(Delivery.id)).all()
    lines = {}
    for line in session.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id.in_([d.id for d in deliveries] or [-1]))).all():
        lines.setdefault(line.delivery_id, []).append(line)
    notes = session.scalars(select(TableNote).where(TableNote.created_at >= start, TableNote.created_at < end).order_by(TableNote.created_at)).all()
    codes = {t.id: t.code for t in tables}
    zones = session.execute(select(Zone.name, func.count(SiteTable.id)).join(SiteTable, SiteTable.zone_id == Zone.id).group_by(Zone.id, Zone.name).order_by(Zone.name)).all()
    zone_progress = {name: [0, 0, 0] for name, _ in zones}
    zone_names = {z.id: z.name for z in session.scalars(select(Zone)).all()}
    for t in tables:
        if t.zone_id in zone_names:
            entry = zone_progress.setdefault(zone_names[t.zone_id], [0, 0, 0])
            entry[0] += 1; entry[1] += bool(t.built); entry[2] += bool(t.qc_checked)

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=f"Raport dzienny {project.name}")
    story = [p("ASOLAR — RAPORT DZIENNY BUDOWY", title), p(f"{project.name} · {project.location or 'brak lokalizacji'} · {report_date.isoformat()}"), Spacer(1, 6 * mm)]
    manhours = sum(log.people * log.hours for log in logs)
    story += [p("Dzień w liczbach", heading), table([
        ["Stoły zamontowane tego dnia", str(len(built_day))],
        ["Stoły odebrane (QA/QC) tego dnia", str(len(qc_day))],
        ["Meldunki", str(len(logs))],
        ["Osoby (suma z meldunków)", str(sum(log.people for log in logs))],
        ["Roboczogodziny", f"{manhours:.1f}"],
        ["Dostawy (WZ)", str(len(deliveries))],
    ], [75 * mm, 40 * mm], header=False)]
    forecast = f"{kpi['forecast_days']} dni (ok. {kpi['forecast_date']})" if kpi["forecast_days"] is not None else kpi["forecast_status"]
    story += [p("Postęp budowy (stan na koniec dnia raportu)", heading), table([
        ["Zamontowane", f"{kpi['tables_built']}/{kpi['tables_total']} ({kpi['built_pct']}%)"],
        ["Odebrane QA/QC", f"{kpi['tables_qc']}/{kpi['tables_total']} ({kpi['qc_pct']}%)"],
        ["Prognoza zakończenia montażu", forecast],
    ], [75 * mm, 85 * mm], header=False), Spacer(1, 2 * mm)]
    story += [p(f"• {line}", small) for line in kpi["forecast_assumptions"]]
    if zone_progress:
        story += [Spacer(1, 3 * mm), table([["Strefa", "Stoły", "Zamontowane", "QA/QC"]] + [[p(name, small), str(v[0]), str(v[1]), str(v[2])] for name, v in sorted(zone_progress.items())],
                                            [80 * mm, 25 * mm, 28 * mm, 25 * mm])]
    if built_day:
        story += [p("Stoły zamontowane tego dnia", heading), p(", ".join(t.code for t in built_day), small)]
    work = [["Brygada / autor", "Wykonane prace", "Osoby", "Godz.", "Stoły", "Rbh"]]
    for log in logs:
        work.append([p(f"{log.team}\n{users.get(log.author_id, '—')}", small), p(log.stage + (f"\nUwagi: {log.note}" if log.note else ""), small),
                     str(log.people), f"{log.hours:g}", f"{log.tables_completed:g}", f"{log.people * log.hours:g}"])
    if len(work) == 1:
        work.append(["Brak meldunków", "—", "—", "—", "—", "—"])
    story += [p("Prace wykonane (meldunki)", heading), table(work, [32 * mm, 72 * mm, 13 * mm, 13 * mm, 14 * mm, 14 * mm])]
    quality = [["Brygada", "Dziennik QA/QC"]] + [[p(log.team, small), p(log.qc_notes, small)] for log in logs if (log.qc_notes or "").strip()]
    if len(quality) == 1:
        quality.append(["—", "Brak wpisów QA/QC"])
    story += [p("Dziennik jakości QA/QC", heading), table(quality, [35 * mm, 127 * mm])]
    note_rows = [["Stół", "Notatka", "Autor"]] + [[codes.get(n.table_id, "—"), p(n.text, small), users.get(n.author_id, "—")] for n in notes]
    if len(note_rows) == 1:
        note_rows.append(["—", "Brak notatek z tego dnia", "—"])
    story += [p("Notatki do stołów", heading), table(note_rows, [20 * mm, 110 * mm, 32 * mm])]
    wz = [["WZ", "Dostawca", "Pozycje"]] + [[d.wz_number, p(d.supplier, small), p("\n".join(f"{l.name}: {l.quantity_received:g} {l.unit}" + (f" (uszk. {l.quantity_damaged:g})" if l.quantity_damaged else "") for l in lines.get(d.id, [])), small)] for d in deliveries]
    if len(wz) == 1:
        wz.append(["—", "—", "Brak dostaw"])
    story += [p("Dostawy", heading), table(wz, [30 * mm, 40 * mm, 92 * mm])]
    story += [Spacer(1, 8 * mm), p("Raport wygenerowany przez ASOLAR v2 z danych zapisanych w aplikacji.", small)]
    doc.build(story)
    return output.getvalue()
