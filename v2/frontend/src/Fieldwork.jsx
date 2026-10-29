import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { applyPendingNoteChanges, applyPendingTables, cachedGet, discardQueued, editQueuedNote, mutate, noteClientId, pendingItems, pendingNotes, pendingPhotos, savePhotos } from "./offline";
import { AsyncButton, Empty, fmt, Loader, pct, Progress, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* Etap 4a: praca w terenie — montaż i odbiór stołów, notatki, zdjęcia. Działa także bez zasięgu. */

// Odpowiedź serwera lub kopia offline, która nie jest listą, nie może wywrócić widoku.
const asList = value => (Array.isArray(value) ? value : []);
const STATUSES = [["", "Wszystkie"], ["todo", "Do montażu"], ["built", "Zamontowane, bez odbioru"], ["qc", "Odebrane"]];

/** Niewysłane zmiany z kolejki tego urządzenia — odświeżane po każdej zmianie kolejki. */
export function usePending() {
  const [items, setItems] = useState([]);
  const reload = useCallback(() => pendingItems().then(setItems), []);
  useEffect(() => {
    reload();
    const listener = () => reload();
    window.addEventListener("asolar2:queue", listener);
    return () => window.removeEventListener("asolar2:queue", listener);
  }, [reload]);
  return [items, reload];
}

export function useSynced(handler) {
  useEffect(() => {
    window.addEventListener("asolar2:synced", handler);
    return () => window.removeEventListener("asolar2:synced", handler);
  }, [handler]);
}

export function PhotoThumb({ url: fileUrl, photo, canDelete, onDelete }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true, objectUrl = "";
    api(fileUrl).then(blob => { if (!active) return; objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }).catch(() => {});
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [fileUrl]);
  return <figure className="photo-thumb" data-testid="photo">
    {url ? <a href={url} target="_blank" rel="noopener noreferrer"><img src={url} alt={photo.filename} /></a> : <div className="photo-placeholder">…</div>}
    <figcaption>{photo.author} · {fmt(photo.created_at)}</figcaption>
    {canDelete && <button type="button" className="danger-button small" onClick={() => onDelete(photo)}>Usuń</button>}
  </figure>;
}

function NoteItem({ note, canEdit, onSave, onDelete }) {
  const [text, setText] = useState(null);
  const cancel = useCallback(() => setText(null), []);
  useEscape(cancel, text !== null);
  if (text !== null) {
    return <form className="note-item editing" onSubmit={async event => { event.preventDefault(); if (text.trim() && await onSave(note, text.trim())) cancel(); }}>
      <textarea aria-label="Treść notatki" rows="3" autoFocus value={text} onChange={event => setText(event.target.value)} />
      <div className="card-actions"><button className="primary" disabled={!text.trim()}>Zapisz</button><button type="button" className="secondary" onClick={cancel}>Anuluj</button></div>
    </form>;
  }
  return <div className={`note-item ${note.pending || note.pending_edit ? "pending" : ""}`} data-testid="note">
    <p>{note.text}</p>
    <small>{note.pending ? "czeka na wysłanie" : `${note.author} · ${fmt(note.created_at)}`}{note.edited_at && !note.pending ? ` · edytowano${note.edited_by ? ` (${note.edited_by})` : ""}` : ""}{note.pending_edit ? " · zmiana czeka na wysłanie" : ""}</small>
    {canEdit && <div className="card-actions"><button type="button" onClick={() => setText(note.text)}>Edytuj</button><button type="button" className="danger-button" onClick={() => onDelete(note)}>Usuń</button></div>}
  </div>;
}

export function TablePanel({ project, table, user, access, notify, onClose, onChanged }) {
  const confirm = useConfirm();
  const base = `/api/projects/${project.id}`;
  const notesPath = `${base}/tables/${table.id}/notes`;
  const photosPath = `${base}/tables/${table.id}/photos`;
  const notes = useLoad(() => cachedGet(notesPath), [notesPath]);
  const photos = useLoad(() => cachedGet(photosPath), [photosPath]);
  const [pending, reloadPending] = usePending();
  const [text, setText] = useState("");
  const fileInput = useRef(null);
  const canWrite = !project.archived;
  useEscape(onClose, true);
  useSynced(useCallback(() => { notes.reload(); photos.reload(); }, [notes.reload, photos.reload])); // eslint-disable-line react-hooks/exhaustive-deps

  const shownNotes = [...pendingNotes(notesPath, pending), ...applyPendingNoteChanges(notesPath, notes.data || [], pending)];
  const queuedPhotos = pendingPhotos(photosPath, pending);
  const mayEdit = note => canWrite && (note.pending || access.isManager || note.author_id === user.id);

  async function addNote(event) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    try {
      const result = await mutate(notesPath, "POST", { text: value, client_id: noteClientId() });
      setText("");
      notify(result?.queued ? "Brak zasięgu — notatka zapisana na urządzeniu, wyślemy ją automatycznie" : "Dodano notatkę");
      reloadPending(); notes.reload(); onChanged();
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function saveNote(note, value) {
    try {
      if (note.pending) await editQueuedNote(note.seq, value);
      else { const result = await mutate(`${notesPath}/${note.id}`, "PATCH", { text: value }); if (result?.queued) notify("Zmiana zapisana na urządzeniu — wyślemy ją po powrocie zasięgu"); }
      reloadPending(); notes.reload();
      return true;
    } catch (failure) { notify(failure.message, "error"); return false; }
  }
  async function deleteNote(note) {
    if (!(await confirm({ title: "Czy na pewno chcesz usunąć tę notatkę?", message: note.text.slice(0, 200), danger: true, confirmLabel: "Usuń notatkę" }))) return;
    try {
      if (note.pending) await discardQueued(note.seq);
      else await mutate(`${notesPath}/${note.id}`, "DELETE");
      notify("Notatka usunięta"); reloadPending(); notes.reload(); onChanged();
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function addPhotos(files) {
    if (!files?.length) return;
    try {
      const result = await savePhotos(photosPath, files, `Zdjęcie ${table.code}`);
      notify(result.queued ? `Zapisano ${result.queued} zdjęć na urządzeniu — wyślemy je po powrocie zasięgu` : `Dodano ${result.sent} zdjęć`);
      reloadPending(); photos.reload(); onChanged();
    } catch (failure) { notify(failure.message, "error"); }
    finally { if (fileInput.current) fileInput.current.value = ""; }
  }
  async function deletePhoto(photo) {
    if (!(await confirm({ title: "Usunąć zdjęcie?", message: `Zdjęcie stołu ${table.code} (${photo.filename}).`, danger: true, confirmLabel: "Usuń zdjęcie" }))) return;
    try { await mutate(`${base}/photos/${photo.id}`, "DELETE"); notify("Zdjęcie usunięte"); photos.reload(); onChanged(); } catch (failure) { notify(failure.message, "error"); }
  }
  async function discardPhoto(item) {
    if (!(await confirm({ title: "Odrzucić niewysłane zdjęcie?", message: item.name, danger: true, confirmLabel: "Odrzuć" }))) return;
    await discardQueued(item.seq); reloadPending(); onChanged();
  }

  return <div className="dialog-overlay form-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="card table-panel" role="dialog" aria-modal="true" aria-label={`Stół ${table.code}`}>
      <div className="card-head"><h2>Stół {table.code}</h2><button type="button" className="secondary" onClick={onClose}>Zamknij</button></div>
      <p className="hint">{table.built ? `Zamontowany ${fmt(table.built_at)}` : "Nie zamontowany"}{table.qc_checked ? ` · odebrany ${fmt(table.qc_at)}` : ""}</p>
      <h3>Notatki</h3>
      {canWrite && <form onSubmit={addNote} className="note-form">
        <textarea aria-label="Nowa notatka" rows="2" placeholder="Np. brak śruby, uszkodzony element, uwagi do odbioru…" value={text} onChange={event => setText(event.target.value)} />
        <button className="primary" disabled={!text.trim()}>Dodaj notatkę</button>
      </form>}
      {shownNotes.map(note => <NoteItem key={note.id} note={note} canEdit={mayEdit(note)} onSave={saveNote} onDelete={deleteNote} />)}
      {notes.loading && !notes.data ? <Loader /> : notes.error && !notes.data ? <p className="hint">{notes.error} — notatki z serwera pokażą się po powrocie zasięgu.</p>
        : !shownNotes.length && <p className="hint">Brak notatek.</p>}
      <h3>Zdjęcia</h3>
      {canWrite && <div className="card-actions"><button type="button" className="secondary" onClick={() => fileInput.current?.click()}>Dodaj zdjęcie</button>
        <input ref={fileInput} hidden type="file" accept="image/*" capture="environment" multiple aria-label="Zdjęcia stołu" onChange={event => addPhotos(event.target.files)} /></div>}
      <div className="photo-grid">
        {queuedPhotos.map(item => <figure className="photo-thumb pending" key={`q-${item.seq}`}><div className="photo-placeholder">{item.failed ? "błąd wysyłki" : "czeka na wysłanie"}</div><figcaption>{item.name}</figcaption><button type="button" className="danger-button small" onClick={() => discardPhoto(item)}>Odrzuć</button></figure>)}
        {(photos.data || []).map(photo => <PhotoThumb key={photo.id} url={`${base}/photos/${photo.id}/file`} photo={photo} canDelete={canWrite && (access.isManager || photo.uploaded_by === user.id)} onDelete={deletePhoto} />)}
      </div>
      {!queuedPhotos.length && !photos.data?.length && !photos.loading && <p className="hint">Brak zdjęć.</p>}
    </section>
  </div>;
}

export default function Fieldwork({ project, access, user, notify }) {
  const confirm = useConfirm();
  const base = `/api/projects/${project.id}`;
  const tables = useLoad(() => cachedGet(`${base}/tables`), [project.id]);
  const zones = useLoad(() => cachedGet(`${base}/zones`), [project.id]);
  const rows = useLoad(() => cachedGet(`${base}/rows`), [project.id]);
  const types = useLoad(() => cachedGet(`${base}/types`), [project.id]);
  const [pending, reloadPending] = usePending();
  const [filter, setFilter] = useState({ zone_id: "", row_id: "", status: "", q: "" });
  const [openId, setOpenId] = useState(null);
  const reloadTables = tables.reload;
  useSynced(useCallback(() => reloadTables(), [reloadTables]));
  const canWrite = !project.archived;

  const all = useMemo(() => applyPendingTables(base, asList(tables.data), pending), [base, tables.data, pending]);
  const name = (list, id) => asList(list.data).find(item => item.id === id);
  const visible = all.filter(t => (filter.zone_id === "" || (filter.zone_id === "0" ? t.zone_id == null : t.zone_id === Number(filter.zone_id)))
    && (filter.row_id === "" || (filter.row_id === "0" ? t.row_id == null : t.row_id === Number(filter.row_id)))
    && (filter.status === "" || (filter.status === "todo" && !t.built) || (filter.status === "built" && t.built && !t.qc_checked) || (filter.status === "qc" && t.qc_checked))
    && (!filter.q || t.code.toLowerCase().includes(filter.q.trim().toLowerCase())));
  const built = visible.filter(t => t.built).length, qc = visible.filter(t => t.qc_checked).length;

  async function setProgress(table, change) {
    if (change.built === false && table.qc_checked && !(await confirm({ title: `Cofnąć montaż stołu ${table.code}?`, message: "Stół ma odbiór QA/QC — cofnięcie montażu usunie również odbiór.", danger: true, confirmLabel: "Cofnij montaż" }))) return;
    try {
      const result = await mutate(`${base}/tables/${table.id}/progress`, "PATCH", change);
      if (result?.queued) notify(`Brak zasięgu — ${table.code} zapisany na urządzeniu`);
      reloadPending();
      if (!result?.queued) reloadTables();
    } catch (failure) { notify(failure.message, "error"); }
  }
  const set = field => event => setFilter(current => ({ ...current, [field]: event.target.value }));
  const open = all.find(t => t.id === openId);
  return <>
    <section className="card progress-card">
      <div className="progress-head"><div><strong>{built}</strong> / {visible.length} zamontowanych <small>({pct(built, visible.length)}%)</small></div><div><strong>{qc}</strong> odebranych <small>({pct(qc, visible.length)}%)</small></div></div>
      <Progress value={pct(built, visible.length)} />
      <div className="filters">
        <select aria-label="Strefa" value={filter.zone_id} onChange={set("zone_id")}><option value="">Wszystkie strefy</option><option value="0">— bez strefy —</option>{asList(zones.data).map(z => <option key={z.id} value={z.id}>{z.name}</option>)}</select>
        <select aria-label="Rząd" value={filter.row_id} onChange={set("row_id")}><option value="">Wszystkie rzędy</option><option value="0">— bez rzędu —</option>{asList(rows.data).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
        <select aria-label="Stan" value={filter.status} onChange={set("status")}>{STATUSES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
        <input type="search" aria-label="Szukaj stołu" placeholder="Szukaj, np. T-12" value={filter.q} onChange={set("q")} />
      </div>
    </section>
    {tables.error && <div className="alert error" role="alert">{tables.error}</div>}
    {tables.loading && !tables.data ? <Loader /> : !all.length ? <Empty>Brak stołów. Kierownik tworzy je w zakładce „Stoły i rzędy” (z numeracji PDF albo ręcznie).</Empty>
      : <div className="field-list">{visible.map(t => <div key={t.id} className={`field-row ${t.qc_checked ? "qc" : t.built ? "built" : ""}`} data-testid="field-row">
        <button type="button" className="field-code" onClick={() => setOpenId(t.id)} aria-label={`Szczegóły stołu ${t.code}`}>
          <strong>{t.code}</strong>
          <small>{name(types, t.structure_type_id)?.code || "typ ?"} · {name(zones, t.zone_id)?.name || "strefa ?"}{t.row_id ? ` · ${name(rows, t.row_id)?.name || ""}` : ""}</small>
          <small>{t.notes ? `📝 ${t.notes}` : ""} {t.photos ? `📷 ${t.photos}` : ""} {t.pending ? <span className="badge warning">czeka na wysłanie</span> : null}</small>
        </button>
        <div className="field-actions">
          <AsyncButton className={t.built ? "primary" : "secondary"} aria-pressed={t.built} disabled={!canWrite} onClick={() => setProgress(t, { built: !t.built })}>{t.built ? "✓ Zamontowany" : "Zamontowany"}</AsyncButton>
          {access.isManager && <AsyncButton className={t.qc_checked ? "primary" : "secondary"} aria-pressed={t.qc_checked} disabled={!canWrite || !t.built} title={t.built ? undefined : "Najpierw montaż"} onClick={() => setProgress(t, { qc_checked: !t.qc_checked })}>{t.qc_checked ? "✓ Odebrany" : "Odbiór QC"}</AsyncButton>}
          {!access.isManager && t.qc_checked && <span className="badge success">odebrany</span>}
        </div>
      </div>)}</div>}
    {!access.isManager && <p className="hint">Odbiór QA/QC wykonuje kierownik budowy.</p>}
    {open && <TablePanel project={project} table={open} user={user} access={access} notify={notify} onClose={() => setOpenId(null)} onChanged={() => { reloadPending(); reloadTables(); }} />}
  </>;
}
