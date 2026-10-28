import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, send } from "./api";
import { AsyncButton, Empty, fmt, Loader, qty, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* Etap 2: wiele PDF naraz → lokalny parser → propozycje, które kierownik zatwierdza, poprawia lub odrzuca. */

export const KINDS = [
  ["zone", "Strefy", "Zatwierdzona strefa trafia do zakładki „Strefy”."],
  ["structure_type", "Typy konstrukcji", "Zatwierdzony typ trafia do zakładki „Konstrukcje i BOM”."],
  ["numbering", "Numeracja stołów / trackerów", "Zatwierdzenie tworzy stoły o numerach odczytanych z rysunku (luki nie są dopisywane). Oznaczenia elektryczne (INV, MPPT…) są pomijane."],
  ["bom_line", "BOM — ilości na typ konstrukcji", "Ilości na jeden stół danego typu. Zatwierdzona pozycja trafia do BOM typu — pozycja bez typu konstrukcji wymaga uzupełnienia (Popraw)."],
  ["component", "Komponenty (bez ilości)", "Elementy z tabel bez kolumny ilości."],
  ["tool", "Narzędzia", "Tabele narzędzi montażowych."],
  ["torque", "Momenty dokręcania", "Wartości odczytane z tekstu — sprawdź z instrukcją producenta."],
];
const FIELDS = {
  bom_line: [["name", "Nazwa"], ["code", "Kod"], ["spec", "Specyfikacja"], ["quantity", "Ilość", "number"], ["unit", "J.m."], ["group", "Typ konstrukcji"]],
  component: [["name", "Nazwa"], ["code", "Kod"], ["spec", "Specyfikacja"]],
  tool: [["name", "Nazwa"], ["spec", "Specyfikacja"]],
  structure_type: [["code", "Oznaczenie"], ["modules", "Moduły na stół", "number"]],
  zone: [["name", "Nazwa strefy"]],
  numbering: [["prefix", "Prefiks"], ["first", "Od", "number"], ["last", "Do", "number"]],
  torque: [["bolt", "Śruba"], ["min_nm", "Min [N·m]", "number"], ["max_nm", "Max [N·m]", "number"]],
};
const REQUIRED = { bom_line: ["name"], component: ["name"], tool: ["name"], structure_type: ["code"], zone: ["name"], numbering: ["prefix"], torque: ["bolt"] };
const STATUS_LABEL ={ nowa: "Do przeglądu", zatwierdzona: "Zatwierdzona", odrzucona: "Odrzucona" };
const DOC_STATUS = { oczekuje: ["W kolejce", "neutral"], analiza: ["Analiza…", "warning"], gotowy: ["Przeanalizowany", "success"], "błąd": ["Błąd odczytu", "danger"] };
const CATEGORIES = [["auto", "Rozpoznaj automatycznie"], ["bom", "BOM / zestawienie materiałów"], ["rysunek", "Rysunek / planimetria"], ["instrukcja", "Instrukcja montażu"], ["inne", "Inne"]];
const MAX_FILES = 20;
const MAX_MB = 60;

const size = bytes => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} kB`;
const confidence = value => value >= 0.8 ? ["wysoka", "success"] : value >= 0.6 ? ["średnia", "neutral"] : ["niska", "warning"];

export function describe(item) {
  const p = item.payload;
  switch (item.kind) {
    case "bom_line": return { title: p.name, detail: [p.code, p.spec].filter(Boolean).join(" · "), value: `${qty(p.quantity)} ${p.unit || "szt."}` };
    case "component": return { title: p.name, detail: [p.code, p.spec].filter(Boolean).join(" · ") };
    case "tool": return { title: p.name, detail: p.spec };
    case "structure_type": return { title: p.code, detail: `moduły na stół: ${p.modules} · ${p.occurrences}× w dokumentach` };
    case "zone": return { title: p.name, detail: `${p.occurrences}× w dokumentach` };
    case "numbering": return { title: `${p.prefix} ${p.first}–${p.last}`, detail: `${p.count} oznaczeń, np. ${p.example}${p.missing?.length ? ` · brak w zakresie: ${p.missing.slice(0, 12).join(", ")}${p.missing.length > 12 ? "…" : ""}` : ""}` };
    case "torque": return { title: p.bolt, detail: p.context, value: p.min_nm === p.max_nm ? `${qty(p.min_nm)} N·m` : `${qty(p.min_nm)}–${qty(p.max_nm)} N·m` };
    default: return { title: item.key, detail: "" };
  }
}

function Upload({ project, notify, onUploaded }) {
  const input = useRef(null);
  const [category, setCategory] = useState("auto");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  async function upload(list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    const pdfs = files.filter(file => /\.pdf$/i.test(file.name) || file.type === "application/pdf");
    const skipped = files.length - pdfs.length;
    const tooBig = pdfs.filter(file => file.size > MAX_MB * 1048576);
    const ready = pdfs.filter(file => file.size <= MAX_MB * 1048576);
    if (skipped) notify(`Pominięto ${skipped} plik(ów) innych niż PDF`, "error");
    if (tooBig.length) notify(`Za duże (powyżej ${MAX_MB} MB): ${tooBig.map(file => file.name).join(", ")}`, "error");
    if (!ready.length) return;
    setBusy(true);
    try {
      let accepted = 0; const duplicates = []; const rejected = [];
      for (let start = 0; start < ready.length; start += MAX_FILES) {
        const form = new FormData();
        ready.slice(start, start + MAX_FILES).forEach(file => form.append("files", file, file.name));
        const result = await api(`/api/projects/${project.id}/documents?category=${category}`, { method: "POST", body: form });
        accepted += result.accepted.length; duplicates.push(...result.duplicates); rejected.push(...result.rejected);
      }
      if (accepted) notify(`Wgrano ${accepted} plik(ów) — analiza trwa w tle`);
      if (duplicates.length) notify(`Już wgrane wcześniej: ${duplicates.map(item => item.filename).join(", ")}`, "error");
      if (rejected.length) notify(`Odrzucone: ${rejected.map(item => `${item.filename} (${item.reason})`).join(", ")}`, "error");
      onUploaded();
    } catch (failure) { notify(failure.message, "error"); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  }
  return <section className="card"><h2>Wgraj dokumenty budowy</h2>
    <div className={`drop-zone ${over ? "over" : ""}`} data-testid="drop-zone"
      onDragOver={event => { event.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={event => { event.preventDefault(); setOver(false); if (!busy) upload(event.dataTransfer.files); }}>
      <strong>{busy ? "Wysyłanie…" : "Przeciągnij tutaj pliki PDF"}</strong>
      <small>BOM, rysunki, planimetrie, instrukcje — wiele plików naraz (do {MAX_MB} MB każdy)</small>
      <button type="button" className="secondary" disabled={busy} onClick={() => input.current?.click()}>Wybierz pliki…</button>
      <input ref={input} type="file" accept="application/pdf,.pdf" multiple hidden aria-label="Pliki PDF" onChange={event => upload(event.target.files)} />
    </div>
    <label>Rodzaj dokumentów (opcjonalnie)<select value={category} onChange={event => setCategory(event.target.value)}>{CATEGORIES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
    <p className="hint">Analiza działa lokalnie na serwerze aplikacji — pliki nie są wysyłane do usług zewnętrznych. Strony zapisane jako obraz (skany) wymagają OCR, którego ta wersja jeszcze nie wykonuje.</p>
  </section>;
}

function DocumentRow({ document, project, canEdit, notify, onChanged }) {
  const confirm = useConfirm();
  const [label, tone] = DOC_STATUS[document.status] || [document.status, "neutral"];
  const counts = Object.entries(document.summary?.suggestions || {}).reduce((sum, [, value]) => sum + value, 0);
  async function open() {
    try {
      const blob = await api(`/api/projects/${project.id}/documents/${document.id}/file`);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function reanalyze() {
    try { await send(`/api/projects/${project.id}/documents/${document.id}/reanalyze`, "POST"); notify(`Ponowna analiza: ${document.filename}`); onChanged(); } catch (failure) { notify(failure.message, "error"); }
  }
  async function remove() {
    if (!(await confirm({ title: "Usunąć dokument?", message: `Plik „${document.filename}” i jego nierozpatrzone propozycje zostaną usunięte. Zatwierdzone i odrzucone decyzje pozostaną.`, danger: true, confirmLabel: "Usuń dokument" }))) return;
    try { await send(`/api/projects/${project.id}/documents/${document.id}`, "DELETE"); notify("Dokument usunięty"); onChanged(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <div className="doc-row" data-testid="document-row">
    <div className="doc-main">
      <strong>{document.filename}</strong>
      <small>{size(document.size)}{document.pages ? ` · ${document.pages} str.` : ""} · {fmt(document.uploaded_at)}{document.status === "gotowy" ? ` · ${counts} propozycji` : ""}</small>
      {document.error && <small className="doc-warning">{document.error}</small>}
      {(document.warnings || []).map(warning => <small className="doc-warning" key={warning}>⚠ {warning}</small>)}
    </div>
    <span className={`badge ${tone}`}>{label}</span>
    <div className="card-actions">
      <button type="button" onClick={open}>Otwórz</button>
      {canEdit && <AsyncButton onClick={reanalyze} busyLabel="…" disabled={document.status === "analiza" || document.status === "oczekuje"}>Analizuj ponownie</AsyncButton>}
      {canEdit && <button type="button" className="danger-button" onClick={remove}>Usuń</button>}
    </div>
  </div>;
}

function EditForm({ item, onSave, onCancel }) {
  const fields = FIELDS[item.kind] || [];
  const [form, setForm] = useState(() => Object.fromEntries(fields.map(([field]) => [field, item.payload[field] ?? ""])));
  useEscape(onCancel, true);
  async function submit(event) {
    event.preventDefault();
    const changes = {};
    for (const [field, , type] of fields) {
      const value = type === "number" ? Number(form[field]) : String(form[field]).trim();
      if (value !== item.payload[field]) changes[field] = value;
    }
    await onSave(changes);
  }
  return <form className="suggestion-edit" onSubmit={submit} aria-label={`Popraw: ${describe(item).title}`}>
    {fields.map(([field, label, type], index) => <label key={field}>{label}<input autoFocus={index === 0} type={type || "text"} step="any" min={type === "number" ? 0 : undefined} required={(REQUIRED[item.kind] || []).includes(field)} value={form[field]} onChange={event => setForm(current => ({ ...current, [field]: event.target.value }))} /></label>)}
    <div className="card-actions"><button className="primary">Zapisz i zatwierdź</button><button type="button" className="secondary" onClick={onCancel}>Anuluj</button></div>
  </form>;
}

function SuggestionRow({ item, canEdit, onUpdate }) {
  const [editing, setEditing] = useState(false);
  const info = describe(item);
  const [level, tone] = confidence(item.confidence);
  const conflict = item.payload.conflict;
  const pages = item.sources.slice(0, 4).map(source => `${source.filename} s. ${source.page}`).join("; ");
  async function save(changes) { if (await onUpdate(item, { status: "zatwierdzona", ...(Object.keys(changes).length ? { payload: changes } : {}) })) setEditing(false); }
  return <div className={`suggestion-row status-${item.status}`} data-testid="suggestion-row">
    <div className="suggestion-main">
      <div className="suggestion-title"><strong>{info.title}</strong>{info.value && <span className="suggestion-value">{info.value}</span>}</div>
      {info.detail && <small>{info.detail}</small>}
      <small className="suggestion-source" title={item.sources.map(source => `${source.filename}, str. ${source.page}: ${source.excerpt}`).join("\n")}>
        Źródło: {pages || "plik usunięty"}{item.sources.length > 4 ? ` i ${item.sources.length - 4} więcej` : ""}
      </small>
      {conflict && <small className="doc-warning">⚠ Rozbieżność ilości między źródłami: {conflict.map(value => qty(value)).join(" / ")} — wymaga potwierdzenia</small>}
      {item.edited && <small className="hint">Poprawione ręcznie (parser odczytał: {describe({ ...item, payload: item.original }).value || describe({ ...item, payload: item.original }).title})</small>}
      {item.applied_ref?.startsWith("zone:") && <small className="hint">Dodano do stref budowy.</small>}
    </div>
    <div className="suggestion-side">
      <span className={`badge ${tone}`} title={`Pewność odczytu ${Math.round(item.confidence * 100)}%`}>pewność {level}</span>
      {item.status !== "nowa" && <span className={`badge ${item.status === "zatwierdzona" ? "success" : "danger"}`}>{STATUS_LABEL[item.status]}</span>}
    </div>
    {canEdit && !editing && <div className="card-actions suggestion-actions">
      {item.status === "nowa" ? <>
        <AsyncButton className="primary" busyLabel="…" onClick={() => onUpdate(item, { status: "zatwierdzona" })}>Zatwierdź</AsyncButton>
        <button type="button" onClick={() => setEditing(true)}>Popraw</button>
        <AsyncButton busyLabel="…" onClick={() => onUpdate(item, { status: "odrzucona" })}>Odrzuć</AsyncButton>
      </> : <AsyncButton busyLabel="…" onClick={() => onUpdate(item, { status: "nowa" })}>Cofnij decyzję</AsyncButton>}
    </div>}
    {editing && <EditForm item={item} onSave={save} onCancel={() => setEditing(false)} />}
  </div>;
}

function KindSection({ kind, title, hint, items, canEdit, onUpdate, onBulk }) {
  const [open, setOpen] = useState(items.length <= 40);
  const groups = useMemo(() => {
    if (kind !== "bom_line") return [["", items]];
    const map = new Map();
    for (const item of items) { const key = item.payload.group || "bez przypisanego typu"; map.set(key, [...(map.get(key) || []), item]); }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b, "pl", { numeric: true }));
  }, [kind, items]);
  const bulkable = items.filter(item => item.status === "nowa" && !item.payload.conflict);
  return <section className="card suggestion-section" data-testid={`section-${kind}`}>
    <div className="card-head"><h2>{title}</h2><span className="badge neutral">{items.length}</span>
      <div className="card-actions">
        {canEdit && bulkable.length > 0 && <button type="button" className="secondary" onClick={() => onBulk(bulkable, title)}>Zatwierdź wszystkie ({bulkable.length})</button>}
        <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}>{open ? "Zwiń" : "Rozwiń"}</button>
      </div>
    </div>
    <p className="hint">{hint}</p>
    {open && groups.map(([group, list]) => <div key={group || "all"}>
      {group && <h3 className="suggestion-group">Typ konstrukcji: {group} <small>({list.length})</small></h3>}
      {list.map(item => <SuggestionRow key={item.id} item={item} canEdit={canEdit} onUpdate={onUpdate} />)}
    </div>)}
  </section>;
}

function Review({ project, canEdit, notify, suggestions, reload, onChanged }) {
  const confirm = useConfirm();
  const [status, setStatus] = useState("nowa");
  const [query, setQuery] = useState("");
  const all = suggestions || [];
  const counts = all.reduce((sum, item) => ({ ...sum, [item.status]: (sum[item.status] || 0) + 1 }), {});
  const needle = query.trim().toLowerCase();
  const visible = all.filter(item => (status === "wszystkie" || item.status === status) && (!needle || JSON.stringify(item.payload).toLowerCase().includes(needle) || item.sources.some(source => source.filename.toLowerCase().includes(needle))));
  async function update(item, body) {
    try {
      await send(`/api/projects/${project.id}/suggestions/${item.id}`, "PATCH", body);
      const name = describe(item).title;
      notify(body.status === "zatwierdzona" ? `Zatwierdzono: ${name}` : body.status === "odrzucona" ? `Odrzucono: ${name}` : `Przywrócono do przeglądu: ${name}`);
      await reload(); onChanged?.();
      return true;
    } catch (failure) { notify(failure.message, "error"); return false; }
  }
  async function bulk(items, title) {
    if (!(await confirm({ title: "Zatwierdzić wszystkie?", message: `Zostanie zatwierdzonych ${items.length} propozycji z sekcji „${title}”. Pozycje z rozbieżnością ilości trzeba rozpatrzyć pojedynczo.`, confirmLabel: `Zatwierdź ${items.length}` }))) return;
    try {
      const result = await send(`/api/projects/${project.id}/suggestions/bulk`, "POST", { ids: items.map(item => item.id), status: "zatwierdzona" });
      notify(`Zatwierdzono ${result.updated} propozycji`);
      if (result.failed?.length) notify(`Pominięto ${result.failed.length}: ${result.failed.slice(0, 3).map(item => item.reason).join(" · ")}${result.failed.length > 3 ? " …" : ""}`, "error");
      await reload(); onChanged?.();
    }
    catch (failure) { notify(failure.message, "error"); }
  }
  return <>
    <div className="toolbar review-toolbar">
      <nav className="view-switch" aria-label="Filtr propozycji">{[["nowa", "Do przeglądu"], ["zatwierdzona", "Zatwierdzone"], ["odrzucona", "Odrzucone"], ["wszystkie", "Wszystkie"]].map(([id, label]) => <button type="button" key={id} className={status === id ? "active" : ""} onClick={() => setStatus(id)}>{label} ({id === "wszystkie" ? all.length : counts[id] || 0})</button>)}</nav>
      <input type="search" aria-label="Szukaj w propozycjach" placeholder="Szukaj (nazwa, kod, plik)…" value={query} onChange={event => setQuery(event.target.value)} />
    </div>
    {!canEdit && <p className="hint">Propozycje zatwierdza kierownik budowy. Masz podgląd.</p>}
    {!all.length && <Empty>Brak propozycji. Wgraj dokumenty PDF — po analizie pojawią się tutaj.</Empty>}
    {all.length > 0 && !visible.length && <Empty>Brak propozycji w tym widoku.</Empty>}
    {KINDS.map(([kind, title, hint]) => {
      const items = visible.filter(item => item.kind === kind);
      return items.length ? <KindSection key={`${kind}-${status}`} kind={kind} title={title} hint={hint} items={items} canEdit={canEdit} onUpdate={update} onBulk={bulk} /> : null;
    })}
    {all.length > 0 && <p className="hint">Nic nie trafia do danych budowy bez zatwierdzenia. Cofnięcie decyzji usuwa utworzone dane, o ile nie są już używane.</p>}
  </>;
}

export default function Documents({ project, access, notify, onChanged }) {
  const documents = useLoad(() => api(`/api/projects/${project.id}/documents`), [project.id]);
  const suggestions = useLoad(() => api(`/api/projects/${project.id}/suggestions`), [project.id]);
  const canEdit = access.isManager && !project.archived;
  const working = (documents.data || []).some(item => item.status === "oczekuje" || item.status === "analiza");
  const reloadDocs = documents.reload;
  const reloadSuggestions = suggestions.reload;
  useEffect(() => {
    if (!working) return undefined;
    const timer = setInterval(() => { reloadDocs(); reloadSuggestions(); }, 2500);
    return () => clearInterval(timer);
  }, [working, reloadDocs, reloadSuggestions]);
  const refresh = () => { reloadDocs(); reloadSuggestions(); onChanged?.(); };
  return <>
    <div className="split">
      {canEdit ? <Upload project={project} notify={notify} onUploaded={refresh} /> : <section className="card"><h2>Dokumenty budowy</h2><p className="hint">{project.archived ? "Budowa jest zarchiwizowana — nie przyjmuje nowych dokumentów." : "Dokumenty wgrywa kierownik budowy."}</p></section>}
      <section className="card"><div className="card-head"><h2>Wgrane pliki</h2><span className="badge neutral">{documents.data?.length || 0}</span>{working && <span className="badge warning">analiza w toku</span>}</div>
        {documents.error && <div className="alert error" role="alert">{documents.error}</div>}
        {documents.loading && !documents.data ? <Loader /> : (documents.data || []).map(item => <DocumentRow key={item.id} document={item} project={project} canEdit={canEdit} notify={notify} onChanged={refresh} />)}
        {!documents.loading && !documents.data?.length && <Empty>Brak dokumentów.</Empty>}
      </section>
    </div>
    <h2 className="section-title">Propozycje z dokumentów</h2>
    {suggestions.error && <div className="alert error" role="alert">{suggestions.error}</div>}
    {suggestions.loading && !suggestions.data ? <Loader /> : <Review project={project} canEdit={canEdit} notify={notify} suggestions={suggestions.data} reload={reloadSuggestions} onChanged={onChanged} />}
  </>;
}
