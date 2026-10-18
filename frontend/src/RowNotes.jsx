import React, { useCallback, useEffect, useState } from "react";
import { applyPendingNoteChanges, cachedGet, discardQueued, editQueuedNote, mutate, pendingItems, pendingNotes } from "./api";
import { canWrite, fmt, useConfirm } from "./ui";

const preview = text => (text.length > 120 ? `${text.slice(0, 117)}…` : text);

/**
 * Historia notatek rzędu z edycją i usuwaniem (autor notatki lub kierownik).
 * Bez zasięgu zmiany trafiają do kolejki IndexedDB; notatkę jeszcze niewysłaną zmienia się
 * bezpośrednio w kolejce. Lista odświeża się przy każdej synchronizacji (refreshKey).
 */
export default function RowNotes({ row, user, notify, onChanged, refreshKey }) {
  const [notes, setNotes] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();

  const load = useCallback(async () => {
    const items = await pendingItems();
    const local = pendingNotes(row.id, items).map(item => ({ ...item, author: user.full_name, author_id: user.id }));
    try {
      const remote = applyPendingNoteChanges(row.id, await cachedGet(`/api/rows/${row.id}/notes`), items);
      setNotes([...local, ...remote]);
    } catch (error) {
      setNotes(local);
      if (!local.length) notify(error.message, "error");
    }
  }, [row.id, user.id]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const canModify = note => canWrite(user) && (note.pending || user.role === "kierownik" || note.author_id === user.id);
  function startEdit(note) { setEditingId(note.id); setDraft(note.text); }
  function cancelEdit() { setEditingId(null); setDraft(""); }

  async function saveEdit(note) {
    const text = draft.trim();
    if (!text) return notify("Notatka nie może być pusta", "error");
    if (text === note.text) return cancelEdit();
    setBusy(true);
    try {
      if (note.pending) {
        await editQueuedNote(note.seq, text);
        notify("Zmieniono notatkę czekającą na wysłanie");
      } else {
        const result = await mutate(`/api/rows/${row.id}/notes/${note.id}`, "PATCH", { text });
        notify(result?.queued ? "Zmiana notatki zapisana w telefonie — zostanie wysłana po odzyskaniu sieci" : "Zapisano zmianę notatki");
      }
      cancelEdit();
      await load();
      onChanged?.();
    } catch (error) { notify(error.message, "error"); } finally { setBusy(false); }
  }

  async function remove(note) {
    const ok = await confirm({ title: "Czy na pewno chcesz usunąć tę notatkę?", message: `„${preview(note.text)}”\n${note.author || "—"} · ${fmt(note.created_at)}`, danger: true, confirmLabel: "Usuń notatkę" });
    if (!ok) return;
    try {
      if (note.pending) {
        await discardQueued(note.seq);
        notify("Notatka usunięta z pamięci urządzenia (nie była jeszcze wysłana)");
      } else {
        const result = await mutate(`/api/rows/${row.id}/notes/${note.id}`, "DELETE");
        notify(result?.queued ? "Usunięcie notatki zapisane w telefonie — zostanie wysłane po odzyskaniu sieci" : "Notatka usunięta");
      }
      if (editingId === note.id) cancelEdit();
      await load();
      onChanged?.();
    } catch (error) { notify(error.message, "error"); }
  }

  return <section className="row-notes">
    <h3>Historia notatek</h3>
    {notes.map(note => <article className={`row-note ${note.pending || note.pending_edit ? "pending" : ""} ${editingId === note.id ? "is-editing" : ""}`} key={note.id} data-testid="row-note">
      {editingId === note.id
        ? <div className="note-edit">
            <textarea aria-label="Treść notatki" rows="3" autoFocus value={draft} onChange={event => setDraft(event.target.value)}
              onKeyDown={event => {
                if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancelEdit(); }
                else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); saveEdit(note); }
              }} />
            <div className="card-actions"><button type="button" className="primary" disabled={busy || !draft.trim()} onClick={() => saveEdit(note)}>{busy ? "Zapisywanie…" : "Zapisz"}</button><button type="button" className="secondary" onClick={cancelEdit}>Anuluj</button><small className="hint">Ctrl+Enter — zapisz · Esc — anuluj</small></div>
          </div>
        : <p>{note.text}</p>}
      <div className="row-note-meta">
        <small>{note.author || "—"} · {fmt(note.created_at)}{note.edited_at ? ` · edytowano${note.edited_by ? ` (${note.edited_by})` : ""} ${fmt(note.edited_at)}` : ""}{note.pending || note.pending_edit ? " · czeka na wysłanie" : ""}</small>
        {canModify(note) && editingId !== note.id && <span className="row-note-actions">
          <button type="button" className="text-button" onClick={() => startEdit(note)}>Edytuj</button>
          <button type="button" className="note-delete" aria-label="Usuń notatkę" title="Usuń notatkę" onClick={() => remove(note)}>
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2zm-3 6h12l-1 12H7L6 9zm4 2v8h2v-8h-2zm4 0v8h2v-8h-2z" /></svg>
          </button>
        </span>}
      </div>
    </article>)}
    {!notes.length && <small>Brak notatek dla tego rzędu.</small>}
  </section>;
}
