import React, { useState } from "react";
import { api, send } from "./api";
import { AsyncButton, Empty, fmt, Loader, PageHead, useEscape } from "./ui";
import { useLoad } from "./useLoad";

export const roleLabel = role => ({ kierownik: "Kierownik", brygadzista: "Brygadzista" }[role] || role);

function NewProjectForm({ onCreated, onCancel, notify }) {
  const [form, setForm] = useState({ name: "", location: "", capacity_mw: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEscape(onCancel);
  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const project = await send("/api/projects", "POST", { name: form.name.trim(), location: form.location.trim(), capacity_mw: Number(form.capacity_mw || 0), description: form.description.trim() });
      notify(`Utworzono budowę „${project.name}” z własną przestrzenią danych`);
      onCreated(project);
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }
  const set = field => event => setForm(current => ({ ...current, [field]: event.target.value }));
  return <div className="dialog-overlay form-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onCancel(); }}>
    <form className="card dialog new-project" role="dialog" aria-modal="true" aria-labelledby="new-project-title" onSubmit={submit}>
      <h2 id="new-project-title">Nowa budowa</h2>
      <p className="dialog-message">Budowa dostanie własną, odizolowaną przestrzeń danych. Strefy, konstrukcje i BOM dodasz w niej lub zaimportujesz z plików PDF (kolejny etap).</p>
      <label>Nazwa budowy<input required minLength="2" autoFocus value={form.name} onChange={set("name")} placeholder="np. Farma PV Kalisz 12 MW" /></label>
      <div className="form-grid"><label>Lokalizacja<input value={form.location} onChange={set("location")} /></label><label>Moc [MW]<input type="number" min="0" step="0.01" value={form.capacity_mw} onChange={set("capacity_mw")} /></label></div>
      <label>Opis (opcjonalnie)<textarea rows="2" value={form.description} onChange={set("description")} /></label>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="card-actions dialog-actions"><button type="button" className="secondary" onClick={onCancel}>Anuluj</button><button className="primary" disabled={busy || form.name.trim().length < 2}>{busy ? "Tworzenie…" : "Utwórz budowę"}</button></div>
    </form>
  </div>;
}

export default function Dashboard({ user, notify, openProject }) {
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data: projects, error, loading, reload } = useLoad(() => api(`/api/projects?include_archived=${showArchived}`), [showArchived]);
  return <>
    <PageHead eyebrow="WSZYSTKIE BUDOWY" title="Moje budowy">
      <label className="check-line"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} /> Pokaż archiwalne</label>
      {user.is_admin && <button type="button" className="primary add-new" onClick={() => setCreating(true)}>+ Nowa budowa</button>}
    </PageHead>
    {error && <div className="alert error" role="alert">{error} <AsyncButton onClick={reload}>Spróbuj ponownie</AsyncButton></div>}
    {loading && !projects ? <Loader /> : <div className="project-grid">
      {(projects || []).map(project => <article key={project.id} className={`card project-card ${project.archived ? "archived" : ""}`} data-testid="project-card">
        <div className="card-head"><span className={`badge ${project.archived ? "neutral" : "success"}`}>{project.archived ? "archiwum" : "aktywna"}</span><span className="badge neutral">{roleLabel(project.role)}</span></div>
        <h2>{project.name}</h2>
        <p>{project.location || "Brak lokalizacji"}{project.capacity_mw ? ` · ${project.capacity_mw} MW` : ""}</p>
        <div className="project-stats"><span><b>{project.stats.zones}</b> stref</span><span><b>{project.stats.members}</b> osób</span><span>ostatnia zmiana: {fmt(project.stats.last_activity)}</span></div>
        <div className="card-actions"><button type="button" className="primary" onClick={() => openProject(project.id)}>Otwórz</button></div>
      </article>)}
    </div>}
    {!loading && !error && !projects?.length && <Empty>{user.is_admin ? "Nie ma jeszcze budów. Utwórz pierwszą przyciskiem „+ Nowa budowa”." : "Nie masz jeszcze dostępu do żadnej budowy. Poproś kierownika o dodanie do zespołu."}</Empty>}
    {creating && <NewProjectForm notify={notify} onCancel={() => setCreating(false)} onCreated={project => { setCreating(false); openProject(project.id); }} />}
  </>;
}
