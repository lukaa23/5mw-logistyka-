import React, { useCallback, useEffect, useState } from "react";
import { api, send } from "./api";
import { TablePanel, usePending, useSynced } from "./Fieldwork";
import { applyPendingTables, cachedGet } from "./offline";
import { Empty, fmt, Loader, Progress, qty, today } from "./ui";
import { useLoad } from "./useLoad";

/* Etap 4c: Planimetria (rysunek + stoły w miejscach odczytanych z PDF) i pulpit postępu. */

const ZOOMS = [0.5, 0.75, 1, 1.5, 2, 3];
const STATUS = [["", "Wszystkie"], ["todo", "Do montażu"], ["built", "Zamontowane"], ["qc", "Odebrane"]];
const hasNumbering = doc => (doc.summary?.suggestions?.numbering ? 1 : 0);
const statusOf = table => (table.qc_checked ? "qc" : table.built ? "built" : "todo");

/** Obraz strony pobrany z nagłówkiem autoryzacji; spóźniona odpowiedź (inna strona) jest ignorowana. */
function usePageImage(path) {
  const [state, setState] = useState({ url: "", error: "" });
  useEffect(() => {
    if (!path) { setState({ url: "", error: "" }); return undefined; }
    let active = true, objectUrl = "";
    setState({ url: "", error: "" });
    api(path).then(blob => { if (!active) return; objectUrl = URL.createObjectURL(blob); setState({ url: objectUrl, error: "" }); })
      .catch(error => { if (active) setState({ url: "", error: error.message || "Nie udało się pobrać rysunku" }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  return state;
}

export function PlanView({ project, access, user, notify }) {
  const base = `/api/projects/${project.id}`;
  const documents = useLoad(() => cachedGet(`${base}/documents`), [project.id]);
  const tables = useLoad(() => cachedGet(`${base}/tables`), [project.id]);
  const [pending, reloadPending] = usePending();
  const lastKey = `asolar2_plan_${project.id}`;
  const [docId, setDocIdState] = useState(() => { try { return localStorage.getItem(lastKey) || ""; } catch { return ""; } });
  const setDocId = value => { setDocIdState(value); try { localStorage.setItem(lastKey, value); } catch { /* brak dostępu */ } };
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [filter, setFilter] = useState("");
  const [openId, setOpenId] = useState(null);
  const ready = (documents.data || []).filter(d => d.status === "gotowy" && d.pages > 0)
    // Najpierw rysunki, potem dokumenty, w których parser znalazł numerację stołów.
    .sort((a, b) => (b.category === "rysunek") - (a.category === "rysunek") || hasNumbering(b) - hasNumbering(a) || a.filename.localeCompare(b.filename, "pl"));
  const selected = ready.find(d => String(d.id) === String(docId)) || ready[0];
  const plan = useLoad(() => (selected ? api(`${base}/documents/${selected.id}/plan?page=${page}`) : Promise.resolve(null)), [base, selected?.id, page]);
  const image = usePageImage(selected ? `${base}/documents/${selected.id}/pages/${page}.png?scale=2` : "");
  const reloadTables = tables.reload;
  useSynced(useCallback(() => reloadTables(), [reloadTables]));
  // Stan znacznika z bieżącej listy stołów (z niewysłanymi zmianami tego urządzenia), nie z chwili odczytu rysunku.
  const all = applyPendingTables(base, tables.data || [], pending);
  const byId = new Map(all.map(t => [t.id, t]));
  const markers = (plan.data?.markers || []).map(m => ({ ...m, table: byId.get(m.table_id) })).filter(m => m.table && (!filter || statusOf(m.table) === filter));
  const open = openId ? byId.get(openId) : null;

  async function markAsDrawing() {
    try { await send(`${base}/documents/${selected.id}`, "PATCH", { category: "rysunek" }); notify(`„${selected.filename}” oznaczony jako rysunek`); documents.reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  if (documents.loading && !documents.data) return <Loader />;
  if (!ready.length) return <Empty>Brak przeanalizowanych dokumentów PDF. Wgraj rysunek (planimetrię) w zakładce „Dokumenty i import”.</Empty>;
  const counts = { todo: 0, built: 0, qc: 0 };
  (plan.data?.markers || []).forEach(m => { const t = byId.get(m.table_id); if (t) counts[statusOf(t)] += 1; });
  return <>
    <section className="card plan-toolbar">
      <div className="filters">
        <select aria-label="Rysunek" value={selected?.id || ""} onChange={e => { setDocId(e.target.value); setPage(1); }}>{ready.map(d => <option key={d.id} value={d.id}>{d.category === "rysunek" ? "▣ " : ""}{d.filename} ({d.pages} str.)</option>)}</select>
        <label className="inline-label">Strona<input type="number" min="1" max={selected?.pages || 1} value={page} onChange={e => setPage(Math.min(selected.pages, Math.max(1, Number(e.target.value) || 1)))} /></label>
        <select aria-label="Pokaż stoły" value={filter} onChange={e => setFilter(e.target.value)}>{STATUS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
        <div className="zoom-buttons" role="group" aria-label="Powiększenie">
          <button type="button" className="secondary" aria-label="Pomniejsz" disabled={zoom <= ZOOMS[0]} onClick={() => setZoom(ZOOMS[Math.max(0, ZOOMS.indexOf(zoom) - 1)])}>−</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" className="secondary" aria-label="Powiększ" disabled={zoom >= ZOOMS[ZOOMS.length - 1]} onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(zoom) + 1)])}>+</button>
        </div>
      </div>
      <div className="plan-legend"><span className="dot todo" /> do montażu {counts.todo}<span className="dot built" /> zamontowane {counts.built}<span className="dot qc" /> odebrane {counts.qc}
        {access.isManager && selected && selected.category !== "rysunek" && !project.archived && <button type="button" className="secondary small" onClick={markAsDrawing}>Oznacz jako rysunek</button>}</div>
      {plan.data && !plan.data.markers.length && <p className="needs">{plan.data.codes_on_page ? "Na tej stronie są oznaczenia, ale żadne nie pasuje do stołów budowy — dodaj stoły (zakładka „Stoły i rzędy”) albo zatwierdź numerację z PDF." : "Na tej stronie nie znaleziono oznaczeń stołów w warstwie tekstowej (np. skan) — znaczników nie da się umieścić automatycznie."}</p>}
      {plan.data?.markers.length > 0 && plan.data.tables_not_on_page > 0 && <p className="hint">{plan.data.tables_not_on_page} stołów budowy nie występuje na tej stronie.</p>}
      {plan.loading && !plan.data && <p className="hint">Odczytywanie położenia stołów z rysunku… (duży arkusz może potrwać kilka sekund)</p>}
      {plan.error && <div className="alert error" role="alert">{plan.error}</div>}
    </section>
    <div className="plan-scroll" data-testid="plan">
      {image.error ? <Empty>{image.error}</Empty> : !image.url ? <Loader /> :
        <div className="plan-canvas" style={{ width: `${zoom * 100}%` }}>
          <img src={image.url} alt={`${selected.filename}, strona ${page}`} draggable="false" />
          {markers.map(m => <button type="button" key={m.table_id} className={`plan-marker ${statusOf(m.table)} ${m.table.pending ? "pending" : ""}`} data-testid="plan-marker"
            style={{ left: `${m.x * 100}%`, top: `${m.y * 100}%`, width: `${Math.max(m.w * 100, 0.6)}%`, height: `${Math.max(m.h * 100, 0.6)}%` }}
            title={`${m.code}: ${statusOf(m.table) === "qc" ? "odebrany" : statusOf(m.table) === "built" ? "zamontowany" : "do montażu"}`} aria-label={`Stół ${m.code}`} onClick={() => setOpenId(m.table_id)} />)}
        </div>}
    </div>
    {open && <TablePanel project={project} table={open} user={user} access={access} notify={notify} onClose={() => setOpenId(null)} onChanged={() => { reloadPending(); reloadTables(); }} />}
  </>;
}

export function DashboardCard({ project }) {
  const base = `/api/projects/${project.id}`;
  const data = useLoad(() => cachedGet(`${base}/dashboard`), [project.id]);
  const [day, setDay] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function downloadReport() {
    setBusy(true); setError("");
    try {
      const blob = await api(`${base}/reports/daily?report_date=${day}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `ASOLAR-raport-${day}.pdf`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }
  const d = data.data;
  if (data.loading && !d) return <section className="card"><Loader /></section>;
  if (!d?.history) return data.error ? <section className="card"><div className="alert error">{data.error}</div></section> : null;
  const peak = Math.max(1, ...d.history.map(h => h.built));
  return <section className="card dashboard-card" data-testid="dashboard">
    <div className="card-head"><h2>Postęp budowy</h2></div>
    <div className="kpis">
      <div><strong>{d.tables_built}</strong><small>z {d.tables_total} zamontowanych ({d.built_pct}%)</small><Progress value={d.built_pct} /></div>
      <div><strong>{d.tables_qc}</strong><small>odebranych QA/QC ({d.qc_pct}%)</small><Progress value={d.qc_pct} /></div>
      <div><strong>{d.built_today}</strong><small>zamontowanych dziś</small></div>
      <div><strong className={d.materials_missing ? "negative" : ""}>{d.materials_missing}</strong><small>braków materiałów (z {d.materials_required})</small></div>
    </div>
    <div className="history" aria-label="Montaż w ostatnich 14 dniach">{d.history.map(h => <div key={h.date} className="history-bar" title={`${fmt(h.date)}: ${h.built}`}><i style={{ height: `${(h.built / peak) * 100}%` }} /><small>{h.date.slice(8)}</small></div>)}</div>
    <p className="forecast"><strong>Prognoza zakończenia montażu:</strong> {d.forecast_days != null ? `${d.forecast_days} dni (ok. ${fmt(d.forecast_date)})` : d.forecast_status}</p>
    <details><summary>Założenia prognozy</summary><ul>{d.forecast_assumptions.map(line => <li key={line}>{line}</li>)}</ul></details>
    <div className="report-download"><label>Raport dzienny PDF<input type="date" value={day} onChange={e => setDay(e.target.value)} /></label><button type="button" className="secondary" disabled={busy} onClick={downloadReport}>{busy ? "Generowanie…" : "↓ Pobierz raport"}</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    <small className="hint">Dziś: {d.worklogs_today} meldunków, {qty(d.manhours_today)} rbh.</small>
  </section>;
}
