import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, cachedGet, download, upload } from "./api";

/** Zamienia odpowiedź listy planów na bezpieczną tablicę rekordów. */
export function normalizePlans(list) {
  if (!Array.isArray(list)) return [];
  const seen = new Set();
  const result = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const validId = (typeof item.id === "number" && Number.isFinite(item.id)) || (typeof item.id === "string" && item.id !== "");
    if (!validId || typeof item.file_url !== "string" || !item.file_url) continue;
    const key = String(item.id);
    if (seen.has(key)) continue;
    seen.add(key);
    const filename = typeof item.filename === "string" && item.filename.trim() ? item.filename.trim() : "planimetria.pdf";
    const title = typeof item.title === "string" && item.title.trim() ? item.title.trim() : filename !== "planimetria.pdf" ? filename : `Plan #${key}`;
    result.push({
      ...item,
      title,
      filename,
      uploaded_by: typeof item.uploaded_by === "string" && item.uploaded_by.trim() ? item.uploaded_by : "—",
      deletable: item.deletable === true,
      approved_source: item.approved_source === true,
    });
  }
  return result;
}

/** Data dodania planu; nieprawidłowa wartość nie wywraca widoku. */
export function formatPlanDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  try {
    return new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: "short" }).format(date);
  } catch {
    return "—";
  }
}

/** Zasób PDF jest związany jednocześnie z projektem, dokumentem i adresem pliku. */
export const planResourceKey = (projectId, plan) => plan ? `${projectId}|${plan.id}|${plan.file_url}` : null;

export default function PlanMap({ project, sync, notify, user }) {
  const projectId = project?.id ?? null;
  const [plans, setPlans] = useState({ projectId: null, list: [] });
  const [listState, setListState] = useState({ loading: true, error: "" });
  const [selectedId, setSelectedId] = useState(null);
  const [pdf, setPdf] = useState(null); // { key, url }
  const [pdfError, setPdfError] = useState(null); // { key, message }
  const [zoom, setZoom] = useState(1);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const requestSeq = useRef(0);
  const currentProject = useRef(projectId);
  const mounted = useRef(true);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const load = useCallback(async () => {
    if (projectId == null) return;
    const seq = ++requestSeq.current;
    const forProject = projectId;
    try {
      const list = normalizePlans(await cachedGet(`/api/planimetry?project_id=${forProject}`));
      // Odrzuć spóźnione odpowiedzi: nowsze żądanie, inny projekt lub odmontowany komponent.
      if (!mounted.current || seq !== requestSeq.current || currentProject.current !== forProject) return;
      setPlans({ projectId: forProject, list });
      setListState({ loading: false, error: "" });
      setSelectedId(current => list.some(item => String(item.id) === String(current)) ? current : (list[0]?.id ?? null));
    } catch (error) {
      if (!mounted.current || seq !== requestSeq.current || currentProject.current !== forProject) return;
      setListState({ loading: false, error: error?.message || "Nie udało się pobrać listy planów" });
    }
  }, [projectId]);

  // Zmiana projektu: jedyny moment, w którym wybór jest czyszczony.
  useEffect(() => {
    currentProject.current = projectId;
    setPlans({ projectId, list: [] });
    setSelectedId(null);
    setZoom(1);
    setListState({ loading: true, error: "" });
  }, [projectId]);

  // Odświeżenie synchronizacji (WebSocket lub co 15 s) zachowuje bieżący wybór.
  useEffect(() => { load(); }, [load, sync]);

  // Lista z innego projektu nigdy nie jest używana — nawet przez jeden render.
  const items = plans.projectId === projectId ? plans.list : [];
  const selected = items.find(item => String(item.id) === String(selectedId)) || null;
  const expectedKey = planResourceKey(projectId, selected);
  const fileUrl = selected?.file_url;

  useEffect(() => {
    if (!expectedKey) { setPdf(null); return undefined; }
    let cancelled = false;
    let objectUrl = "";
    setPdfError(null);
    api(fileUrl).then(blob => {
      if (cancelled) return;
      if (!blob || typeof blob !== "object" || typeof blob.size !== "number") throw new Error("Serwer nie zwrócił pliku PDF");
      objectUrl = URL.createObjectURL(blob);
      setPdf({ key: expectedKey, url: objectUrl });
    }).catch(error => {
      if (cancelled) return;
      setPdfError({ key: expectedKey, message: error?.message || "Nie udało się pobrać dokumentu" });
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [expectedKey, fileUrl]);

  async function submit(event) {
    event.preventDefault();
    if (!file || projectId == null) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("title", title);
      form.append("file", file);
      const created = await upload("/api/planimetry", form);
      notify("Planimetria PDF została zapisana");
      setTitle(""); setFile(null);
      if (created?.id != null) setSelectedId(created.id);
      await load();
    } catch (error) { notify(error.message, "error"); } finally { setBusy(false); }
  }

  async function remove(item) {
    if (!window.confirm(`Usunąć plan „${item.title}”? Tej operacji nie można cofnąć.`)) return;
    try { await api(`/api/planimetry/${item.id}`, { method: "DELETE" }); notify("Planimetria usunięta"); await load(); } catch (error) { notify(error.message, "error"); }
  }

  function choose(item) { setSelectedId(item.id); setZoom(1); }

  if (!project) return <div className="empty"><span>◇</span><p>Wybierz aktywny projekt.</p></div>;
  const showPdf = !!selected && !!pdf && pdf.key === expectedKey;
  const currentError = selected && pdfError && pdfError.key === expectedKey ? pdfError.message : "";
  const isManager = user?.role === "kierownik";

  return <>
    <div className="page-head"><div><p className="eyebrow">PLAN BUDOWY W TERENIE</p><h1>Mapa / Planimetria</h1></div><div className="head-actions"><span className="badge success">PDF · telefon i komputer</span></div></div>
    {isManager && <form className="card plan-upload" onSubmit={submit}><div><p className="eyebrow">OFICJALNY PLAN</p><h2>Dodaj planimetrię projektu</h2><small>Plik zostanie trwale zapisany w bazie projektu i udostępniony całemu zespołowi. Wgrywanie wymaga połączenia z serwerem.</small></div><label>Nazwa planu<input value={title} onChange={e => setTitle(e.target.value)} placeholder="np. Planimetria wykonawcza — rewizja 03" /></label><label className="file-drop"><input required type="file" accept="application/pdf,.pdf" onChange={e => setFile(e.target.files?.[0] || null)} /><span>{file?.name || "Wybierz PDF"}</span></label><button className="primary" disabled={busy}>{busy ? "Wgrywanie…" : "Wgraj planimetrię"}</button></form>}
    <div className="plan-layout">
      <aside className="card plan-list">
        <div className="card-head"><h2>Dostępne plany</h2><span className="badge neutral">{items.length}</span></div>
        {listState.error && <div className="alert error" role="alert">Lista planów: {listState.error}</div>}
        {items.map(item => <button type="button" className={String(selectedId) === String(item.id) ? "active" : ""} key={item.id} onClick={() => choose(item)}><span>PDF</span><div><strong>{item.title}</strong><small>{item.approved_source ? "zatwierdzone źródło · " : ""}{item.uploaded_by} · {formatPlanDate(item.uploaded_at)}</small></div></button>)}
        {!items.length && !listState.loading && !listState.error && <div className="empty"><span>◇</span><p>Brak planimetrii w tym projekcie.</p></div>}
      </aside>
      <section className="card plan-viewer">
        <div className="plan-toolbar">
          <div><strong data-testid="plan-title">{selected ? selected.title : "Brak wybranego planu"}</strong>{selected && <small>{selected.filename}</small>}</div>
          {selected && <>
            <div className="zoom-controls"><button type="button" onClick={() => setZoom(value => Math.max(0.6, +(value - 0.2).toFixed(2)))} aria-label="Oddal">−</button><b>{Math.round(zoom * 100)}%</b><button type="button" onClick={() => setZoom(value => Math.min(3, +(value + 0.2).toFixed(2)))} aria-label="Przybliż">+</button><button type="button" onClick={() => setZoom(1)}>Dopasuj</button></div>
            <button type="button" className="secondary" onClick={() => download(selected.file_url, selected.filename).catch(error => notify(error.message, "error"))}>↓ Pobierz PDF</button>
            {showPdf && <a className="secondary plan-open-tab" href={pdf.url} target="_blank" rel="noreferrer">Otwórz w nowej karcie</a>}
            {isManager && selected.deletable && <button type="button" className="danger-button" onClick={() => remove(selected)}>Usuń</button>}
          </>}
        </div>
        {currentError && <div className="alert error" role="alert">Nie udało się otworzyć planu: {currentError}</div>}
        {selected && !showPdf && !currentError && <div className="loading"><i /><span>Pobieranie PDF…</span></div>}
        {showPdf && <div className="plan-pdf-viewport"><iframe title={selected.title} src={`${pdf.url}#toolbar=1&navpanes=0&view=FitH`} style={{ transform: `scale(${zoom})` }} /></div>}
        {!selected && <div className="empty"><span>◇</span><p>Wybierz lub wgraj planimetrię, aby otworzyć plan budowy.</p></div>}
      </section>
    </div>
  </>;
}
