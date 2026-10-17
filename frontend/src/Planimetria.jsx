import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, cachedGet, download, upload } from "./api";
import { canRenderPdf, createLatestGuard, createPdfLoader, findPlan, formatPlanDate, formatSize, nextZoom, normalizePlans, pdfViewerHash, resolveSelection } from "./planimetria";

function Notice({ children, tone = "neutral" }) {
  return <div className={`plan-notice ${tone}`}>{children}</div>;
}

export default function Planimetria({ project, sync, notify, user }) {
  const projectId = project?.id ?? null;
  const [plans, setPlans] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [listError, setListError] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [pdf, setPdf] = useState({ status: "idle", key: null, url: null, error: null });
  const [zoom, setZoom] = useState(100);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const listGuard = useRef(createLatestGuard());
  const loaderRef = useRef(null);
  const isManager = user?.role === "kierownik";

  if (!loaderRef.current) {
    loaderRef.current = createPdfLoader({
      fetchBlob: path => api(path),
      createObjectURL: blob => URL.createObjectURL(blob),
      revokeObjectURL: url => URL.revokeObjectURL(url),
      onChange: setPdf,
    });
  }
  useEffect(() => () => loaderRef.current.dispose(), []);

  // Lista planów: nieaktualne odpowiedzi (inny projekt, nowsze odświeżenie) są odrzucane.
  const loadPlans = useCallback(async () => {
    const token = listGuard.current.begin();
    if (projectId === null) { setPlans([]); setSelectedId(null); setLoadingList(false); return; }
    try {
      const raw = await cachedGet(`/api/plans?project_id=${projectId}`);
      if (!listGuard.current.isCurrent(token)) return;
      const next = normalizePlans(raw);
      setPlans(next);
      setSelectedId(current => resolveSelection(next, current));
      setListError("");
    } catch (error) {
      if (!listGuard.current.isCurrent(token)) return;
      setListError(error?.message || "Nie udało się pobrać listy planów");
    } finally {
      if (listGuard.current.isCurrent(token)) setLoadingList(false);
    }
  }, [projectId]);

  useEffect(() => { setSelectedId(null); setPlans([]); setLoadingList(true); setZoom(100); }, [projectId]);
  useEffect(() => { loadPlans(); }, [loadPlans, sync]);
  useEffect(() => { const timer = setInterval(loadPlans, 15000); return () => clearInterval(timer); }, [loadPlans]);
  useEffect(() => () => listGuard.current.invalidate(), []);

  const selected = findPlan(plans, selectedId);
  // Zależność od adresu pliku, a nie od obiektu planu: odświeżenie listy nie przeładowuje PDF-a.
  const selectedFileUrl = selected?.file_url ?? null;
  const selectedKeyId = selected?.id ?? null;
  useEffect(() => {
    const current = findPlan(plans, selectedKeyId);
    loaderRef.current.load(projectId, current);
    setZoom(100);
  }, [projectId, selectedKeyId, selectedFileUrl]);

  const renderable = canRenderPdf(pdf, projectId, selected);
  const viewerSrc = useMemo(() => (renderable ? `${pdf.url}${pdfViewerHash(zoom)}` : null), [renderable, pdf.url, zoom]);

  async function submit(event) {
    event.preventDefault();
    if (!file || !isManager) return;
    setBusy(true);
    const form = new FormData();
    form.append("project_id", projectId);
    form.append("file", file);
    if (title.trim()) form.append("title", title.trim());
    try {
      const result = await upload("/api/plans", form);
      notify("Plan dodany");
      setFile(null); setTitle(""); event.target.reset();
      await loadPlans();
      if (result?.id !== undefined) setSelectedId(result.id);
    } catch (error) { notify(error.message, "error"); } finally { setBusy(false); }
  }

  async function remove(plan) {
    if (!window.confirm(`Usunąć plan „${plan.title}”?`)) return;
    try {
      await api(`/api/plans/${plan.id}`, { method: "DELETE" });
      notify("Plan usunięty");
      await loadPlans();
    } catch (error) { notify(error.message, "error"); }
  }

  if (!project) return <div className="empty"><span>◇</span><p>Wybierz aktywny projekt.</p></div>;

  return <>
    <div className="page-head"><div><p className="eyebrow">MAPA / PLANIMETRIA</p><h1>Planimetria PDF</h1></div><div className="head-actions"><span className="badge neutral">{plans.length} planów</span></div></div>
    <div className="plan-layout">
      <section className="card plan-list">
        <div className="card-head"><div><p className="eyebrow">ZATWIERDZONE PLANY ŹRÓDŁOWE</p><h2>Dokumenty</h2></div></div>
        {loadingList && !plans.length && <div className="loading"><i /><span>Ładowanie planów…</span></div>}
        {listError && <Notice tone="error">{listError}</Notice>}
        {!loadingList && !plans.length && !listError && <div className="empty"><span>◇</span><p>Brak planów w tym projekcie.{isManager ? " Wgraj pierwszy plan poniżej." : ""}</p></div>}
        {plans.map(plan => <div className={`plan-item ${String(plan.id) === String(selectedId) ? "active" : ""}`} key={plan.id}>
          <button type="button" className="plan-select" onClick={() => setSelectedId(plan.id)}>
            <strong>{plan.title}</strong>
            <small>{plan.approved_source ? "zatwierdzone źródło" : "plan dodatkowy"} · {formatSize(plan.size)}</small>
            <small>{plan.uploaded_by} · {formatPlanDate(plan.uploaded_at)}</small>
          </button>
          <div className="plan-actions">
            <button type="button" className="icon-button" title="Pobierz PDF" onClick={() => download(plan.file_url, plan.filename).catch(error => notify(error.message, "error"))}>↓</button>
            {isManager && plan.deletable && <button type="button" className="icon-button danger-button" title="Usuń plan dodatkowy" onClick={() => remove(plan)}>×</button>}
            {isManager && plan.approved_source && <span className="badge neutral" title="Zatwierdzone źródła są chronione przed usunięciem">chroniony</span>}
          </div>
        </div>)}
        {isManager && <form className="plan-upload" onSubmit={submit}>
          <h3>Wgraj oficjalny plan</h3>
          <label>Nazwa dokumentu<input value={title} placeholder="np. Planimetria — wersja 3" onChange={event => setTitle(event.target.value)} /></label>
          <label className="file-drop"><input type="file" accept="application/pdf,.pdf" onChange={event => setFile(event.target.files?.[0] || null)} /><span>{file?.name || "Wybierz plik PDF"}</span></label>
          <button className="primary" disabled={busy || !file}>{busy ? "Wgrywanie…" : "Dodaj plan"}</button>
          <small className="hint">Wgrywanie plików wymaga połączenia z serwerem.</small>
        </form>}
      </section>
      <section className="card plan-viewer">
        {!selected && <div className="empty"><span>◇</span><p>{plans.length ? "Wybierz plan z listy." : "Brak dokumentu do wyświetlenia."}</p></div>}
        {selected && <>
          <div className="plan-toolbar">
            <div><p className="eyebrow">PODGLĄD</p><h2>{selected.title}</h2></div>
            <div className="zoom-controls">
              <button type="button" onClick={() => setZoom(value => nextZoom(typeof value === "number" ? value : 100, -1))} disabled={!renderable} aria-label="Oddal">−</button>
              <span>{zoom === "fit" ? "Dopasuj" : `${zoom}%`}</span>
              <button type="button" onClick={() => setZoom(value => nextZoom(typeof value === "number" ? value : 100, 1))} disabled={!renderable} aria-label="Przybliż">+</button>
              <button type="button" onClick={() => setZoom("fit")} disabled={!renderable}>Dopasuj</button>
              <button type="button" onClick={() => download(selected.file_url, selected.filename).catch(error => notify(error.message, "error"))}>Pobierz</button>
              {renderable && <a className="open-tab" href={pdf.url} target="_blank" rel="noreferrer">Otwórz w nowej karcie</a>}
            </div>
          </div>
          {pdf.status === "loading" && <div className="loading"><i /><span>Pobieranie dokumentu…</span></div>}
          {pdf.status === "error" && <Notice tone="error">Nie udało się wyświetlić planu: {pdf.error}. Spróbuj ponownie lub pobierz plik.</Notice>}
          {viewerSrc && <iframe key={`${pdf.key}|${zoom}`} className="plan-frame" title={selected.title} src={viewerSrc} />}
          {renderable && <p className="hint">Przybliżanie korzysta z wbudowanej przeglądarki PDF. Jeśli telefon nie pokazuje dokumentu, użyj „Otwórz w nowej karcie” lub „Pobierz”.</p>}
        </>}
      </section>
    </div>
  </>;
}
