import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, send, uploadFile } from "./api";
import { Empty, fmt, Loader, qty, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* Dokumenty budowy: 1) wybierz rodzaj i upuść pliki, 2) sprawdź pozycje obok podglądu, 3) zatwierdź.
 * Rodzaj dokumentu decyduje, co serwer z niego odczytuje. Gdy nic nie da się odczytać (skan, nietypowy
 * układ), dokument nie jest „błędem” — obok podglądu jest prosty formularz ręcznego uzupełnienia. */

export const DOC_TYPES = [
  ["bom", "BOM / lista materiałowa", "Zestawienia materiałów z ilościami (PDF)", "≣"],
  ["rysunek", "Rysunki i schematy", "Planimetrie, layouty — PDF, DWG, DXF", "▦"],
  ["instrukcja", "Instrukcje i manuale", "Montaż, momenty dokręcania, narzędzia (PDF)", "☰"],
];
const TYPE_LABEL = { bom: "BOM", rysunek: "Rysunek / schemat", instrukcja: "Instrukcja", auto: "Inny", inne: "Inny" };
const ACCEPTED = /\.(pdf|dwg|dxf)$/i;
const MAX_MB = 60;
const isCad = document => document?.format === "dwg" || document?.format === "dxf";

export const KINDS = [
  ["bom_line", "Pozycje BOM"],
  ["structure_type", "Typy konstrukcji"],
  ["numbering", "Numeracja stołów"],
  ["zone", "Strefy"],
  ["drawing_block", "Bloki z rysunku"],
  ["torque", "Momenty dokręcania"],
  ["tool", "Narzędzia"],
  ["component", "Komponenty"],
];
const FIELDS = {
  bom_line: [["name", "Nazwa"], ["code", "Kod"], ["spec", "Specyfikacja"], ["quantity", "Ilość / stół", "number"], ["unit", "J.m."], ["group", "Typ stołu"]],
  component: [["name", "Nazwa"], ["code", "Kod"], ["spec", "Specyfikacja"]],
  tool: [["name", "Nazwa"], ["spec", "Specyfikacja"]],
  structure_type: [["code", "Oznaczenie (np. 2x26)"], ["modules", "Moduły na stół", "number"], ["tables", "Liczba stołów", "number"]],
  zone: [["name", "Nazwa strefy"]],
  numbering: [["prefix", "Prefiks"], ["first", "Od", "number"], ["last", "Do", "number"]],
  torque: [["bolt", "Śruba (np. M12)"], ["min_nm", "Min N·m", "number"], ["max_nm", "Max N·m", "number"]],
  drawing_block: [["name", "Nazwa bloku"], ["count", "Liczba w rysunku", "number"]],
};
const MANUAL_KINDS = { bom: ["bom_line", "structure_type"], rysunek: ["numbering", "zone", "structure_type"], instrukcja: ["torque", "tool", "structure_type"] };
const STATUS = { nowa: ["Wymaga potwierdzenia", "warning"], zatwierdzona: ["Zatwierdzone", "success"], odrzucona: ["Odrzucone", "neutral"] };

export function describe(item) {
  const p = item.payload;
  switch (item.kind) {
    case "bom_line": return { title: p.name, detail: [p.code, p.spec, p.material].filter(Boolean).join(" · ") + (p.check ? ` · ⚠ ${p.check}` : ""), value: `${qty(p.quantity)} ${p.unit || "szt."}${p.group ? " / stół" : ""}` };
    case "component": return { title: p.name, detail: [p.code, p.spec].filter(Boolean).join(" · ") };
    case "tool": return { title: p.name, detail: p.spec };
    case "structure_type": return { title: p.code, detail: `moduły na stół: ${p.modules}${p.tables ? ` · stołów: ${p.tables}` : ""}` };
    case "zone": return { title: p.name, detail: "" };
    case "numbering": return { title: `${p.prefix} ${p.first}–${p.last}`, detail: `${p.count} oznaczeń${p.missing?.length ? ` · brakujące: ${p.missing.slice(0, 10).join(", ")}${p.missing.length > 10 ? "…" : ""}` : ""}${p.layers?.length ? ` · warstwa: ${p.layers.join(", ")}` : ""}` };
    case "torque": return { title: p.bolt, detail: p.context || "", value: p.min_nm === p.max_nm ? `${qty(p.min_nm)} N·m` : `${qty(p.min_nm)}–${qty(p.max_nm)} N·m` };
    case "drawing_block": return { title: p.name, detail: p.layers?.length ? `warstwa: ${p.layers.join(", ")}` : "", value: `${qty(p.count)} szt. w rysunku` };
    default: return { title: item.key, detail: "" };
  }
}

const sourcePage = (item, documentId) => item.sources.find(source => source.document_id === documentId)?.page || 1;

/* ---------- 1. Wgrywanie ---------- */

function TypeTile({ type, label, hint, icon, onFiles }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  return <div className={`type-tile ${over ? "over" : ""}`} data-testid={`tile-${type}`}
    onDragOver={event => { event.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
    onDrop={event => { event.preventDefault(); setOver(false); onFiles(type, event.dataTransfer.files); }}>
    <span className="type-icon" aria-hidden="true">{icon}</span>
    <strong>{label}</strong>
    <small>{hint}</small>
    <small className="drop-hint">Przeciągnij pliki tutaj</small>
    <button type="button" className="secondary" onClick={() => input.current?.click()}>Wybierz pliki z dysku</button>
    <input ref={input} type="file" multiple hidden accept={type === "rysunek" ? ".pdf,.dwg,.dxf,application/pdf" : ".pdf,application/pdf"} aria-label={`Pliki: ${label}`}
      onChange={event => { onFiles(type, event.target.files); event.target.value = ""; }} />
  </div>;
}

function QueueRow({ entry, document, onOpen }) {
  const phase = entry.phase === "wysłany" ? (document?.status === "gotowy" ? "gotowy" : document?.status === "ręcznie" || document?.status === "błąd" ? "ręcznie" : "analiza") : entry.phase;
  const text = { wysyłanie: `Wysyłanie… ${entry.progress}%`, analiza: "Odczytywanie danych…", gotowy: "Gotowe do sprawdzenia", ręcznie: "Do uzupełnienia ręcznie" }[phase] || entry.message;
  const percent = phase === "wysyłanie" ? entry.progress : 100;
  return <li className={`queue-row phase-${phase}`} data-testid="queue-row">
    <div className="queue-name"><strong>{entry.name}</strong><small>{TYPE_LABEL[entry.type]}</small></div>
    <div className="queue-progress" role="progressbar" aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100" aria-label={`Postęp: ${entry.name}`}><i style={{ width: `${percent}%` }} className={phase === "analiza" ? "pulse" : ""} /></div>
    <span className="queue-status">{text}</span>
    {(phase === "gotowy" || phase === "ręcznie") && <button type="button" className="primary" onClick={() => onOpen(entry.documentId)}>Sprawdź</button>}
  </li>;
}

function Upload({ project, documents, notify, onUploaded, onOpen }) {
  const [queue, setQueue] = useState([]);
  const update = (id, change) => setQueue(current => current.map(entry => (entry.id === id ? { ...entry, ...change } : entry)));
  async function addFiles(type, list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    const entries = files.map((file, index) => ({ id: `${Date.now()}-${index}-${file.name}`, file, name: file.name, type, progress: 0, phase: "wysyłanie" }));
    setQueue(current => [...entries, ...current]);
    let sent = 0;
    for (const entry of entries) {
      if (!ACCEPTED.test(entry.name)) { update(entry.id, { phase: "odrzucony", message: "Obsługiwane są pliki PDF, DWG i DXF" }); continue; }
      if (entry.file.size > MAX_MB * 1048576) { update(entry.id, { phase: "odrzucony", message: `Plik większy niż ${MAX_MB} MB` }); continue; }
      try {
        const result = await uploadFile(`/api/projects/${project.id}/documents?category=${type}`, entry.file, progress => update(entry.id, { progress }));
        if (result?.accepted?.length) { update(entry.id, { phase: "wysłany", documentId: result.accepted[0].id, progress: 100 }); sent += 1; }
        else if (result?.duplicates?.length) update(entry.id, { phase: "duplikat", message: `Już wgrany jako „${result.duplicates[0].existing}”` });
        else update(entry.id, { phase: "odrzucony", message: result?.rejected?.[0]?.reason || "Plik odrzucony" });
      } catch (failure) { update(entry.id, { phase: "błąd", message: failure.message }); }
      onUploaded();
    }
    if (sent) notify(`Wysłano ${sent} plik(ów) — odczytuję dane`);
  }
  const byId = new Map((documents || []).map(item => [item.id, item]));
  return <section className="card upload-card-v2">
    <h2>Dodaj dokumenty</h2>
    <p className="hint">Upuść pliki na kafelek z właściwym rodzajem dokumentu (można wiele naraz). Rodzaj podpowiada aplikacji, co odczytać.</p>
    <div className="type-tiles">{DOC_TYPES.map(([type, label, hint, icon]) => <TypeTile key={type} type={type} label={label} hint={hint} icon={icon} onFiles={addFiles} />)}</div>
    {queue.length > 0 && <ul className="upload-queue" aria-label="Wgrywane pliki">{queue.map(entry => <QueueRow key={entry.id} entry={entry} document={byId.get(entry.documentId)} onOpen={onOpen} />)}</ul>}
  </section>;
}

/* ---------- Lista dokumentów ---------- */

function docState(document, pending) {
  if (document.status === "oczekuje" || document.status === "analiza") return ["Odczytywanie…", "neutral"];
  if (document.status === "ręcznie" || document.status === "błąd") return ["Uzupełnij ręcznie", "warning"];
  return pending ? [`Do sprawdzenia: ${pending}`, "warning"] : ["Sprawdzony", "success"];
}

function DocumentList({ project, documents, suggestions, canEdit, notify, onOpen, onChanged }) {
  const confirm = useConfirm();
  if (!documents?.length) return <Empty>Brak dokumentów. Dodaj pierwszy plik powyżej.</Empty>;
  const pendingFor = id => suggestions.filter(item => item.status === "nowa" && item.sources.some(source => source.document_id === id)).length;
  async function remove(document) {
    if (!(await confirm({ title: "Usunąć dokument?", message: `„${document.filename}” i jego niesprawdzone pozycje zostaną usunięte. Zatwierdzone dane zostają w projekcie.`, danger: true, confirmLabel: "Usuń dokument" }))) return;
    try { await send(`/api/projects/${project.id}/documents/${document.id}`, "DELETE"); notify("Dokument usunięty"); onChanged(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <section className="card"><div className="card-head"><h2>Dokumenty budowy</h2><span className="badge neutral">{documents.length}</span></div>
    <ul className="doc-list">{documents.map(document => {
      const [label, tone] = docState(document, pendingFor(document.id));
      return <li key={document.id} className="doc-item" data-testid="document-row">
        <button type="button" className="doc-open" onClick={() => onOpen(document.id)}>
          <strong>{document.filename}</strong>
          <small>{TYPE_LABEL[document.category] || "Inny"}{isCad(document) ? ` · ${document.format.toUpperCase()}` : document.pages ? ` · ${document.pages} str.` : ""} · {fmt(document.uploaded_at)}</small>
        </button>
        <span className={`badge ${tone}`}>{label}</span>
        <div className="card-actions"><button type="button" className="primary" onClick={() => onOpen(document.id)}>Sprawdź</button>{canEdit && <button type="button" className="danger-button" onClick={() => remove(document)}>Usuń</button>}</div>
      </li>;
    })}</ul>
  </section>;
}

/* ---------- 2. Weryfikacja: podgląd po lewej, pozycje po prawej ---------- */

function usePreview(path) {
  const [state, setState] = useState({ url: "", error: "" });
  useEffect(() => {
    if (!path) { setState({ url: "", error: "" }); return undefined; }
    let active = true, objectUrl = "";
    setState({ url: "", error: "" });
    api(path).then(blob => { if (!active) return; objectUrl = URL.createObjectURL(blob); setState({ url: objectUrl, error: "" }); })
      .catch(error => { if (active) setState({ url: "", error: error.message || "Podgląd niedostępny" }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  return state;
}

function Preview({ project, document, page, setPage }) {
  const base = `/api/projects/${project.id}/documents/${document.id}`;
  const pages = Math.max(1, document.pages || 1);
  const path = isCad(document) ? `${base}/pages/1.svg` : document.pages ? `${base}/pages/${page}.png?scale=1.5` : "";
  const preview = usePreview(path);
  const [zoomed, setZoomed] = useState(false);
  async function openOriginal() {
    try {
      const blob = await api(`${base}/file`);
      const url = URL.createObjectURL(blob);
      if (isCad(document)) { const link = window.document.createElement("a"); link.href = url; link.download = document.filename; link.click(); }
      else window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { /* brak pliku — podgląd i tak pokazuje komunikat */ }
  }
  return <section className="card review-preview" data-testid="preview">
    <div className="preview-bar">
      {!isCad(document) && pages > 1 ? <div className="pager"><button type="button" aria-label="Poprzednia strona" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button><span>Strona {page} / {pages}</span><button type="button" aria-label="Następna strona" disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button></div> : <span />}
      <div className="card-actions">
        {preview.url && <button type="button" className="secondary small" aria-pressed={zoomed} onClick={() => setZoomed(value => !value)}>{zoomed ? "Dopasuj" : "Powiększ"}</button>}
        <button type="button" className="secondary small" onClick={openOriginal}>{isCad(document) ? "Pobierz oryginał" : "Otwórz oryginał"}</button>
      </div>
    </div>
    <div className="preview-frame">
      {preview.url ? <img src={preview.url} alt={`${document.filename}${isCad(document) ? "" : `, strona ${page}`}`} style={zoomed ? { width: "250%", maxWidth: "none" } : undefined} onDoubleClick={() => setZoomed(value => !value)} />
        : preview.error || !path ? <Empty>Podgląd niedostępny{preview.error ? ` — ${preview.error}` : ""}. Użyj przycisku „{isCad(document) ? "Pobierz" : "Otwórz"} oryginał”.</Empty> : <Loader />}
    </div>
  </section>;
}

function EditFields({ kind, values, onChange, typeOptions, listId }) {
  return <>
    {(FIELDS[kind] || []).map(([field, label, type]) => <label key={field}>{label}
      <input type={type || "text"} step="any" min={type === "number" ? 0 : undefined} value={values[field] ?? ""} list={field === "group" ? listId : undefined}
        onChange={event => onChange({ ...values, [field]: event.target.value })} /></label>)}
    {kind === "bom_line" && <datalist id={listId}>{typeOptions.map(option => <option key={option} value={option} />)}</datalist>}
  </>;
}

function ItemRow({ item, documentId, canEdit, error, typeOptions, onSave, onStatus, onFocus }) {
  const [form, setForm] = useState(null);
  const cancel = useCallback(() => setForm(null), []);
  useEscape(cancel, !!form);
  const info = describe(item);
  const [label, tone] = STATUS[item.status];
  const missingType = item.kind === "bom_line" && !item.payload.group;
  const conflict = item.payload.conflict;
  async function save(event) {
    event.preventDefault();
    const changes = {};
    for (const [field, , type] of FIELDS[item.kind] || []) {
      const raw = form[field];
      if (type === "number" && (raw === "" || raw === null)) continue;
      const value = type === "number" ? Number(raw) : String(raw ?? "").trim();
      if (value !== (item.payload[field] ?? "")) changes[field] = value;
    }
    if (await onSave(item, changes)) cancel();
  }
  if (form) {
    return <li className="item-row editing" data-testid="item-row">
      <form onSubmit={save} className="item-edit" aria-label={`Edycja: ${info.title}`}>
        <EditFields kind={item.kind} values={form} onChange={setForm} typeOptions={typeOptions} listId={`types-${item.id}`} />
        <div className="card-actions"><button className="primary">Zapisz</button><button type="button" className="secondary" onClick={cancel}>Anuluj</button></div>
      </form>
    </li>;
  }
  const startEdit = () => { onFocus(sourcePage(item, documentId)); if (canEdit) setForm(Object.fromEntries((FIELDS[item.kind] || []).map(([field]) => [field, item.payload[field] ?? ""]))); };
  return <li className={`item-row status-${item.status}`} data-testid="item-row">
    <button type="button" className="item-main" onClick={startEdit} title={canEdit ? "Kliknij, aby poprawić" : "Pokaż w podglądzie"}>
      <span className="item-title"><strong>{info.title}</strong>{info.value && <span className="item-value">{info.value}</span>}</span>
      {info.detail && <small>{info.detail}</small>}
      {item.kind === "bom_line" && item.payload.group && <small>Typ stołu: {item.payload.group}</small>}
      {missingType && <small className="needs">Brak typu stołu — kliknij, aby wpisać</small>}
      {conflict && <small className="needs">Różne ilości w dokumentach: {conflict.map(value => qty(value)).join(" / ")}</small>}
      {error && <small className="item-error" role="alert">{error}</small>}
    </button>
    <span className={`badge ${tone}`}>{label}</span>
    {canEdit && <div className="item-actions">
      {item.status === "nowa"
        ? <><button type="button" className="approve" aria-label={`Zatwierdź: ${info.title}`} onClick={() => onStatus(item, "zatwierdzona")}>✓</button><button type="button" className="reject" aria-label={`Odrzuć: ${info.title}`} onClick={() => onStatus(item, "odrzucona")}>✕</button></>
        : <button type="button" className="secondary small" onClick={() => onStatus(item, "nowa")}>Cofnij</button>}
    </div>}
  </li>;
}

function ManualForm({ project, document, page, typeOptions, notify, onAdded }) {
  const kinds = MANUAL_KINDS[document.category] || ["bom_line", "structure_type", "numbering", "zone", "torque"];
  const [kind, setKind] = useState(kinds[0]);
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState(false);
  async function add(approve) {
    setBusy(true);
    const payload = {};
    for (const [field, , type] of FIELDS[kind]) {
      const raw = values[field];
      if (raw === undefined || raw === "") continue;
      payload[field] = type === "number" ? Number(raw) : String(raw).trim();
    }
    try {
      await send(`/api/projects/${project.id}/suggestions`, "POST", { kind, payload, document_id: document.id, page, approve });
      notify(approve ? "Dodano i zatwierdzono" : "Dodano pozycję do sprawdzenia");
      setValues({}); onAdded();
    } catch (failure) { notify(failure.message, "error"); } finally { setBusy(false); }
  }
  return <form className="card manual-form" onSubmit={event => { event.preventDefault(); add(false); }} aria-label="Dodaj pozycję ręcznie">
    <h3>Dodaj pozycję ręcznie</h3>
    <p className="hint">Przepisz dane z podglądu po lewej (strona {page}).</p>
    <label>Rodzaj<select value={kind} onChange={event => { setKind(event.target.value); setValues({}); }}>{kinds.map(option => <option key={option} value={option}>{KINDS.find(([id]) => id === option)?.[1]}</option>)}</select></label>
    <div className="manual-fields"><EditFields kind={kind} values={values} onChange={setValues} typeOptions={typeOptions} listId="types-manual" /></div>
    <div className="card-actions"><button type="button" className="primary" disabled={busy} onClick={() => add(true)}>Dodaj i zatwierdź</button><button className="secondary" disabled={busy}>Dodaj</button></div>
  </form>;
}

function Review({ project, document, suggestions, canEdit, notify, reload, onBack, onChanged }) {
  const confirm = useConfirm();
  const [page, setPage] = useState(1);
  const [errors, setErrors] = useState({});
  const [showRejected, setShowRejected] = useState(false);
  const [bulkType, setBulkType] = useState("");
  // Esc wraca do listy — ale nie wtedy, gdy poprawiana jest pozycja (wtedy Esc anuluje tylko edycję).
  const backUnlessEditing = useCallback(() => { if (!window.document.querySelector(".item-row.editing")) onBack(); }, [onBack]);
  useEscape(backUnlessEditing, true);
  const items = suggestions.filter(item => item.sources.some(source => source.document_id === document.id));
  const visible = items.filter(item => showRejected || item.status !== "odrzucona");
  const pending = items.filter(item => item.status === "nowa");
  const untyped = pending.filter(item => item.kind === "bom_line" && !item.payload.group);
  const ready = pending.filter(item => !untyped.includes(item));
  const counts = { zatwierdzona: items.filter(item => item.status === "zatwierdzona").length, odrzucona: items.filter(item => item.status === "odrzucona").length };
  const types = useLoad(() => api(`/api/projects/${project.id}/types`), [project.id, counts.zatwierdzona]);
  const typeOptions = [...new Set([...(Array.isArray(types.data) ? types.data : []).map(type => type.code), ...suggestions.filter(item => item.kind === "structure_type" && item.status !== "odrzucona").map(item => item.payload.code)])].sort();
  const done = () => { reload(); onChanged?.(); };

  async function patch(item, body) {
    try { await send(`/api/projects/${project.id}/suggestions/${item.id}`, "PATCH", body); setErrors(current => ({ ...current, [item.id]: "" })); done(); return true; }
    catch (failure) { setErrors(current => ({ ...current, [item.id]: failure.message })); return false; }
  }
  const save = (item, changes) => (Object.keys(changes).length ? patch(item, { payload: changes }) : Promise.resolve(true));
  const setStatus = (item, status) => patch(item, { status });
  async function approveAll(group) {
    const target = group ? untyped : ready;
    if (!target.length) return;
    if (!(await confirm({ title: group ? `Ustawić typ ${group}?` : "Zatwierdzić wszystkie?", message: group ? `${target.length} pozycji bez typu dostanie typ ${group} i zostanie zatwierdzonych.` : `Zostanie zatwierdzonych ${target.length} pozycji z tego dokumentu.`, confirmLabel: `Zatwierdź ${target.length}` }))) return;
    try {
      const result = await send(`/api/projects/${project.id}/suggestions/bulk`, "POST", { ids: target.map(item => item.id), status: "zatwierdzona", ...(group ? { group } : {}) });
      setErrors(Object.fromEntries((result.failed || []).map(failure => [failure.id, failure.reason])));
      notify(result.failed?.length ? `Zatwierdzono ${result.updated}; ${result.failed.length} wymaga poprawki (opis przy pozycji)` : `Zatwierdzono ${result.updated} pozycji`, result.failed?.length ? "error" : "success");
      done();
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function changeType(category) {
    try { await send(`/api/projects/${project.id}/documents/${document.id}`, "PATCH", { category }); notify(`Rodzaj: „${TYPE_LABEL[category]}” — odczytuję ponownie`); done(); } catch (failure) { notify(failure.message, "error"); }
  }
  const reading = document.status === "oczekuje" || document.status === "analiza";
  return <div className="review-v2" data-testid="review">
    <div className="review-head">
      <button type="button" className="secondary" onClick={onBack}>← Dokumenty</button>
      <div className="review-title"><h2>{document.filename}</h2>
        <small>{pending.length} wymaga potwierdzenia · {counts.zatwierdzona} zatwierdzonych{counts.odrzucona ? ` · ${counts.odrzucona} odrzuconych` : ""}</small></div>
      {canEdit && <label className="inline-label">Rodzaj<select aria-label="Rodzaj dokumentu" value={DOC_TYPES.some(([type]) => type === document.category) ? document.category : ""} onChange={event => changeType(event.target.value)}>
        {!DOC_TYPES.some(([type]) => type === document.category) && <option value="">Inny</option>}
        {DOC_TYPES.map(([type, label]) => <option key={type} value={type}>{label}</option>)}</select></label>}
    </div>
    <div className="review-grid">
      <Preview project={project} document={document} page={page} setPage={setPage} />
      <div className="review-items">
        {reading && <div className="alert info">Odczytuję dane z pliku…</div>}
        {!reading && document.error && <div className="alert info">{document.error}</div>}
        {canEdit && pending.length > 0 && <div className="review-actions">
          {ready.length > 0 && <button type="button" className="primary" onClick={() => approveAll()}>Zatwierdź wszystkie ({ready.length})</button>}
          {untyped.length > 0 && <span className="untyped">{untyped.length} bez typu stołu:
            <input aria-label="Typ dla pozycji bez typu" list="types-bulk" placeholder="np. 2x26" value={bulkType} onChange={event => setBulkType(event.target.value)} />
            <datalist id="types-bulk">{typeOptions.map(option => <option key={option} value={option} />)}</datalist>
            <button type="button" className="secondary" disabled={!bulkType.trim()} onClick={() => approveAll(bulkType.trim())}>Ustaw i zatwierdź</button></span>}
        </div>}
        {!items.length && !reading && <Empty>Nic nie odczytano automatycznie. Dodaj pozycje ręcznie poniżej.</Empty>}
        {KINDS.map(([kind, title]) => {
          const list = visible.filter(item => item.kind === kind);
          return list.length ? <section key={kind} className="item-group" data-testid={`group-${kind}`}><h3>{title} <small>({list.length})</small></h3>
            <ul>{list.map(item => <ItemRow key={item.id} item={item} documentId={document.id} canEdit={canEdit} error={errors[item.id]} typeOptions={typeOptions} onSave={save} onStatus={setStatus} onFocus={setPage} />)}</ul>
          </section> : null;
        })}
        {counts.odrzucona > 0 && <label className="check"><input type="checkbox" checked={showRejected} onChange={event => setShowRejected(event.target.checked)} /> Pokaż odrzucone</label>}
        {canEdit && <ManualForm project={project} document={document} page={page} typeOptions={typeOptions} notify={notify} onAdded={done} />}
      </div>
    </div>
  </div>;
}

/* ---------- Zakładka ---------- */

export default function Documents({ project, access, notify, onChanged }) {
  const documents = useLoad(() => api(`/api/projects/${project.id}/documents`), [project.id]);
  const suggestions = useLoad(() => api(`/api/projects/${project.id}/suggestions`), [project.id]);
  const [openId, setOpenId] = useState(null);
  const canEdit = access.isManager && !project.archived;
  const reloadDocs = documents.reload, reloadSuggestions = suggestions.reload;
  const reload = useCallback(() => { reloadDocs(); reloadSuggestions(); }, [reloadDocs, reloadSuggestions]);
  const working = (documents.data || []).some(item => item.status === "oczekuje" || item.status === "analiza");
  useEffect(() => {
    if (!working) return undefined;
    const timer = setInterval(reload, 2000);
    return () => clearInterval(timer);
  }, [working, reload]);
  const all = useMemo(() => (Array.isArray(suggestions.data) ? suggestions.data : []), [suggestions.data]);
  const open = (documents.data || []).find(item => item.id === openId);
  if (documents.loading && !documents.data) return <Loader />;
  if (open) return <Review project={project} document={open} suggestions={all} canEdit={canEdit} notify={notify} reload={reload} onBack={() => setOpenId(null)} onChanged={onChanged} />;
  return <>
    {documents.error && <div className="alert error" role="alert">{documents.error}</div>}
    {canEdit ? <Upload project={project} documents={documents.data} notify={notify} onUploaded={reload} onOpen={setOpenId} />
      : <p className="hint">{project.archived ? "Budowa jest zarchiwizowana — nie przyjmuje nowych dokumentów." : "Dokumenty dodaje i zatwierdza kierownik budowy. Masz podgląd."}</p>}
    <DocumentList project={project} documents={documents.data} suggestions={all} canEdit={canEdit} notify={notify} onOpen={setOpenId} onChanged={() => { reload(); onChanged?.(); }} />
  </>;
}
