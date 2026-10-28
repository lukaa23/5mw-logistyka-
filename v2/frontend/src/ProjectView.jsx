import React, { useState } from "react";
import { api, send } from "./api";
import { roleLabel } from "./Dashboard";
import Documents from "./Documents";
import { AsyncButton, Empty, fmt, Loader, PageHead, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

export const TABS = [["przeglad", "Przegląd"], ["dokumenty", "Dokumenty i import"], ["strefy", "Strefy"], ["zespol", "Zespół"], ["ustawienia", "Ustawienia"]];
const ACTIONS = { create: "utworzył(a)", update: "zmienił(a)", delete: "usunął(ęła)", upload: "wgrał(a)", review: "rozpatrzył(a)", "review-bulk": "zatwierdził(a) zbiorczo" };
const ENTITIES = { project: "budowę", zone: "strefę", document: "dokument", suggestion: "propozycję" };

function eventText(event) {
  if (event.action === "analyze") {
    try { const details = JSON.parse(event.details); return <>Analiza PDF zakończona: <strong>{details["plik"]}</strong> ({details["nowe"]} nowych propozycji)</>; } catch { return "Analiza PDF zakończona"; }
  }
  const detail = ["upload", "delete"].includes(event.action) && event.entity === "document" ? ` „${event.details}”` : event.entity === "zone" && event.action !== "update" ? ` „${event.details}”` : "";
  return <><strong>{event.user}</strong> {ACTIONS[event.action] || event.action} {ENTITIES[event.entity] || event.entity}{detail}</>;
}

function Overview({ project, navigate }) {
  const { data: events, loading } = useLoad(() => api(`/api/projects/${project.id}/events?limit=20`), [project.id]);
  return <div className="split">
    <section className="card"><div className="card-head"><h2>Dane budowy</h2></div>
      <dl className="facts"><dt>Lokalizacja</dt><dd>{project.location || "—"}</dd><dt>Moc</dt><dd>{project.capacity_mw ? `${project.capacity_mw} MW` : "—"}</dd><dt>Strefy</dt><dd>{project.stats.zones}</dd><dt>Dokumenty PDF</dt><dd>{project.stats.documents ?? 0}</dd><dt>Do przeglądu</dt><dd>{project.stats.pending_suggestions ?? 0} propozycji</dd><dt>Zespół</dt><dd>{project.stats.members} osób</dd><dt>Utworzono</dt><dd>{fmt(project.created_at)}</dd></dl>
      {project.description && <p>{project.description}</p>}
      <button type="button" className="secondary" onClick={() => navigate(`#/p/${project.id}/dokumenty`)}>{project.stats.pending_suggestions ? "Przejrzyj propozycje z PDF" : "Wgraj dokumenty PDF"}</button>
    </section>
    <section className="card"><div className="card-head"><h2>Ostatnie zmiany</h2></div>
      {loading && !events ? <Loader /> : (events || []).map(event => <div className="event-row" key={event.id}><span>{eventText(event)}</span><small>{fmt(event.created_at)}</small></div>)}
      {!loading && !events?.length && <Empty>Brak zmian.</Empty>}
    </section>
  </div>;
}

function ZoneRow({ zone, canDelete, onSave, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: zone.name, description: zone.description });
  const cancel = () => { setEditing(false); setForm({ name: zone.name, description: zone.description }); };
  useEscape(cancel, editing);
  async function submit(event) { event.preventDefault(); if (await onSave(zone, form)) setEditing(false); }
  if (editing) return <form className="zone-row editing" onSubmit={submit}><input aria-label="Nazwa strefy" autoFocus required value={form.name} onChange={e => setForm(c => ({ ...c, name: e.target.value }))} /><input aria-label="Opis strefy" placeholder="Opis (opcjonalnie)" value={form.description} onChange={e => setForm(c => ({ ...c, description: e.target.value }))} /><div className="card-actions"><button className="primary">Zapisz</button><button type="button" className="secondary" onClick={cancel}>Anuluj</button></div></form>;
  return <div className="zone-row" data-testid="zone-row"><div><strong>{zone.name}</strong>{zone.description && <small>{zone.description}</small>}</div><div className="card-actions"><button type="button" onClick={() => setEditing(true)}>Edytuj</button>{canDelete && <button type="button" className="danger-button" onClick={() => onDelete(zone)}>Usuń</button>}</div></div>;
}

function Zones({ project, access, notify }) {
  const confirm = useConfirm();
  const { data: zones, loading, error, reload } = useLoad(() => api(`/api/projects/${project.id}/zones`), [project.id]);
  const [form, setForm] = useState({ name: "", description: "" });
  const [busy, setBusy] = useState(false);
  async function create(event) {
    event.preventDefault(); setBusy(true);
    try { await send(`/api/projects/${project.id}/zones`, "POST", form); notify(`Dodano strefę „${form.name.trim()}”`); setForm({ name: "", description: "" }); await reload(); }
    catch (failure) { notify(failure.message, "error"); } finally { setBusy(false); }
  }
  async function save(zone, values) {
    try { await send(`/api/projects/${project.id}/zones/${zone.id}`, "PATCH", values); notify("Zapisano strefę"); await reload(); return true; }
    catch (failure) { notify(failure.message, "error"); return false; }
  }
  async function remove(zone) {
    if (!(await confirm({ title: "Usunąć strefę?", message: `Strefa „${zone.name}” zostanie usunięta z budowy „${project.name}”.`, danger: true, confirmLabel: "Usuń strefę" }))) return;
    try { await send(`/api/projects/${project.id}/zones/${zone.id}`, "DELETE"); notify("Strefa usunięta"); await reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <div className="split">
    <section className="card"><div className="card-head"><h2>Strefy budowy</h2><span className="badge neutral">{zones?.length || 0}</span></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {loading && !zones ? <Loader /> : (zones || []).map(zone => <ZoneRow key={zone.id} zone={zone} canDelete={access.isManager} onSave={save} onDelete={remove} />)}
      {!loading && !zones?.length && <Empty>Brak stref. Dodaj pierwszą strefę.</Empty>}
    </section>
    {!project.archived && <form id="zone-form" className="card" onSubmit={create}><h2>Nowa strefa</h2><label>Nazwa<input required value={form.name} onChange={e => setForm(c => ({ ...c, name: e.target.value }))} placeholder="np. Strefa A — północ" /></label><label>Opis (opcjonalnie)<input value={form.description} onChange={e => setForm(c => ({ ...c, description: e.target.value }))} /></label><button className="primary wide" disabled={busy || !form.name.trim()}>{busy ? "Dodawanie…" : "Dodaj strefę"}</button></form>}
  </div>;
}

function Team({ project, access, user, notify }) {
  const confirm = useConfirm();
  const { data: members, loading, reload } = useLoad(() => api(`/api/projects/${project.id}/members`), [project.id]);
  const directory = useLoad(() => (access.isManager ? api("/api/users") : Promise.resolve([])), [project.id, access.isManager]);
  const [pick, setPick] = useState({ user_id: "", role: "brygadzista" });
  const memberIds = new Set((members || []).map(item => item.user.id));
  const candidates = (directory.data || []).filter(item => !memberIds.has(item.id) && item.active);
  async function setRole(member, role) { try { await send(`/api/projects/${project.id}/members`, "PUT", { user_id: member.id, role }); notify(`${member.full_name}: ${roleLabel(role).toLowerCase()}`); await reload(); } catch (failure) { notify(failure.message, "error"); } }
  async function add(event) { event.preventDefault(); const person = candidates.find(item => String(item.id) === pick.user_id); if (!person) return; await setRole(person, pick.role); setPick({ user_id: "", role: "brygadzista" }); }
  async function remove(member) {
    if (!(await confirm({ title: "Usunąć z zespołu budowy?", message: `${member.full_name} straci dostęp do budowy „${project.name}”. Jego wpisy pozostaną.`, danger: true, confirmLabel: "Usuń z zespołu" }))) return;
    try { await send(`/api/projects/${project.id}/members/${member.id}`, "DELETE"); notify("Usunięto z zespołu"); await reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <div className="split">
    <section className="card"><div className="card-head"><h2>Zespół budowy</h2></div>
      {loading && !members ? <Loader /> : (members || []).map(item => <div className="user-row" key={item.user.id} data-testid="member-row"><div className="avatar">{item.user.full_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</div><div><strong>{item.user.full_name}</strong><small>@{item.user.username}{item.user.is_admin ? " · administrator" : ""}</small></div>
        {access.isManager && item.user.id !== user.id ? <div className="card-actions"><select aria-label={`Rola ${item.user.full_name}`} value={item.role} onChange={e => setRole(item.user, e.target.value)}><option value="kierownik">Kierownik</option><option value="brygadzista">Brygadzista</option></select><button type="button" className="danger-button" onClick={() => remove(item.user)}>Usuń</button></div> : <span className="badge neutral">{roleLabel(item.role)}</span>}
      </div>)}
      <p className="hint">Administrator ma dostęp do wszystkich budów, także jeśli nie jest na liście zespołu.</p>
    </section>
    {access.isManager && <form className="card" onSubmit={add}><h2>Dodaj osobę do budowy</h2>
      <label>Konto<select required value={pick.user_id} onChange={e => setPick(c => ({ ...c, user_id: e.target.value }))}><option value="">Wybierz osobę</option>{candidates.map(item => <option key={item.id} value={item.id}>{item.full_name} (@{item.username})</option>)}</select></label>
      <label>Rola na tej budowie<select value={pick.role} onChange={e => setPick(c => ({ ...c, role: e.target.value }))}><option value="brygadzista">Brygadzista</option><option value="kierownik">Kierownik</option></select></label>
      <button className="primary wide" disabled={!pick.user_id}>Dodaj do zespołu</button>
      <small className="hint">{user.is_admin ? "Nowe konta zakładasz w zakładce „Konta”." : "Nowe konta zakłada administrator."}</small>
    </form>}
  </div>;
}

function Settings({ project, access, user, notify, onChanged, onDeleted }) {
  const confirm = useConfirm();
  const [form, setForm] = useState({ name: project.name, location: project.location, capacity_mw: project.capacity_mw, description: project.description });
  const dirty = form.name !== project.name || form.location !== project.location || Number(form.capacity_mw) !== project.capacity_mw || form.description !== project.description;
  const reset = () => setForm({ name: project.name, location: project.location, capacity_mw: project.capacity_mw, description: project.description });
  useEscape(reset, dirty);
  async function save(event) { event.preventDefault(); try { await send(`/api/projects/${project.id}`, "PATCH", { ...form, capacity_mw: Number(form.capacity_mw || 0) }); notify("Zapisano dane budowy"); onChanged(); } catch (failure) { notify(failure.message, "error"); } }
  async function archive() { try { await send(`/api/projects/${project.id}`, "PATCH", { archived: !project.archived }); notify(project.archived ? "Budowa przywrócona" : "Budowa zarchiwizowana"); onChanged(); } catch (failure) { notify(failure.message, "error"); } }
  async function remove() {
    if (!(await confirm({ title: "Usunąć budowę na stałe?", message: `Zostanie usunięta cała przestrzeń danych budowy „${project.name}” (strefy, dziennik i wszystkie przyszłe dane). Inne budowy nie zostaną naruszone. Tej operacji nie można cofnąć.`, requireText: project.name, danger: true, confirmLabel: "Usuń budowę" }))) return;
    try { await send(`/api/projects/${project.id}?confirm_name=${encodeURIComponent(project.name)}`, "DELETE"); notify("Budowa usunięta"); onDeleted(); } catch (failure) { notify(failure.message, "error"); }
  }
  if (!access.isManager) return <Empty>Ustawienia budowy zmienia kierownik.</Empty>;
  const set = field => event => setForm(current => ({ ...current, [field]: event.target.value }));
  return <div className="split">
    <form className={`card ${dirty ? "editing" : ""}`} onSubmit={save}><h2>Dane budowy</h2>
      <label>Nazwa<input required minLength="2" value={form.name} onChange={set("name")} /></label>
      <div className="form-grid"><label>Lokalizacja<input value={form.location} onChange={set("location")} /></label><label>Moc [MW]<input type="number" min="0" step="0.01" value={form.capacity_mw} onChange={set("capacity_mw")} /></label></div>
      <label>Opis<textarea rows="3" value={form.description} onChange={set("description")} /></label>
      <div className="card-actions"><button className="primary" disabled={!dirty}>Zapisz</button>{dirty && <button type="button" className="secondary" onClick={reset}>Anuluj</button>}</div>
    </form>
    <section className="card"><h2>Archiwizacja i usuwanie</h2>
      <p className="hint">Zarchiwizowana budowa znika z listy aktywnych i nie przyjmuje nowych danych. Można ją przywrócić.</p>
      <AsyncButton onClick={archive} busyLabel="Zapisywanie…">{project.archived ? "Przywróć budowę" : "Archiwizuj budowę"}</AsyncButton>
      {user.is_admin && <><p className="hint">Usunięcie kasuje całą przestrzeń danych tej budowy. Wymaga wcześniejszej archiwizacji i przepisania nazwy.</p><button type="button" className="danger-button" disabled={!project.archived} onClick={remove}>Usuń budowę</button></>}
    </section>
  </div>;
}

export default function ProjectView({ projectId, tab, user, notify, navigate }) {
  const { data: project, error, loading, reload } = useLoad(() => api(`/api/projects/${projectId}`), [projectId]);
  if (error) return <Empty>{error === "Nie znaleziono budowy" ? "Nie znaleziono tej budowy albo nie masz do niej dostępu." : error}</Empty>;
  if (loading && !project) return <Loader />;
  if (!project) return null;
  const access = { role: project.role, isManager: project.role === "kierownik" };
  const common = { project, access, user, notify };
  return <>
    <PageHead eyebrow={project.archived ? "BUDOWA ZARCHIWIZOWANA" : "BUDOWA"} title={project.name}><span className="badge neutral">{roleLabel(project.role)}</span></PageHead>
    <nav className="view-switch project-tabs" aria-label="Sekcje budowy">{TABS.map(([id, label]) => <button type="button" key={id} className={tab === id ? "active" : ""} aria-current={tab === id ? "page" : undefined} onClick={() => navigate(`#/p/${project.id}/${id}`)}>{label}</button>)}</nav>
    {tab === "dokumenty" ? <Documents {...common} onChanged={reload} /> : tab === "strefy" ? <Zones {...common} /> : tab === "zespol" ? <Team {...common} /> : tab === "ustawienia" ? <Settings key={`${project.name}|${project.location}|${project.capacity_mw}|${project.description}|${project.archived}`} {...common} onChanged={reload} onDeleted={() => navigate("#/")} /> : <Overview {...common} navigate={navigate} />}
  </>;
}
