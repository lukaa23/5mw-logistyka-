import React, { useCallback, useMemo, useState } from "react";
import { api, send } from "./api";
import Fieldwork, { TablePanel, usePending, useSynced } from "./Fieldwork";
import { applyPendingTables, cachedGet } from "./offline";
import { AsyncButton, Empty, fmt, Loader, pct, Progress, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* „Strefy i rzędy” jak w v1 — ale dla każdej budowy osobno i bez wariantów wpisanych w kod:
 * 1) strefa (nazwa, opis), 2) rzędy z zakresu numerów, 3) warianty stołów tej budowy przypisane do rzędów.
 * Widok „Rzędy operacyjne” to praca w terenie: montaż, odbiór QA/QC, notatki, zdjęcia, offline. */

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function Guide() {
  return <section className="card zone-guide">
    <div><strong>1. Utwórz strefę</strong><small>Nazwa i opis, np. „Strefa A — północ”.</small></div><i>→</i>
    <div><strong>2. Dodaj rzędy</strong><small>Zakres numerów, np. od 1 do 50.</small></div><i>→</i>
    <div><strong>3. Przypisz warianty</strong><small>Warianty stołów tej budowy (np. 1x28, 1x56+1x42).</small></div>
  </section>;
}

function Variants({ project, types, tables, canEdit, notify, reload }) {
  const confirm = useConfirm();
  const [form, setForm] = useState({ code: "", modules: "" });
  const used = id => tables.filter(table => table.structure_type_id === id).length;
  async function add(event) {
    event.preventDefault();
    try {
      await send(`/api/projects/${project.id}/types`, "POST", { code: form.code, modules: Number(form.modules || 0) });
      notify(`Dodano wariant ${form.code}`); setForm({ code: "", modules: "" }); reload();
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function remove(type) {
    if (!(await confirm({ title: `Usunąć wariant ${type.code}?`, message: "Wariant zniknie z listy tej budowy (razem z jego BOM).", danger: true, confirmLabel: "Usuń wariant" }))) return;
    try { await send(`/api/projects/${project.id}/types/${type.id}`, "DELETE"); notify(`Usunięto wariant ${type.code}`); reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <section className="card variants-card" data-testid="variants">
    <div className="card-head"><h2>Warianty stołów na tej budowie</h2><span className="badge neutral">{types.length}</span></div>
    {!types.length && <p className="needs">Brak wariantów — dodaj warianty występujące na budowie (np. 1x28, 1x42, 1x56+1x42).</p>}
    <div className="variant-chips">{types.map(type => <span className="variant-chip" key={type.id} data-testid="variant-chip">
      <strong>{type.code}</strong><small>{type.modules ? `${type.modules} mod.` : "moduły ?"} · {used(type.id)} rz.</small>
      {canEdit && <button type="button" aria-label={`Usuń wariant ${type.code}`} disabled={used(type.id) > 0} title={used(type.id) ? "Wariant jest przypisany do rzędów" : "Usuń"} onClick={() => remove(type)}>×</button>}
    </span>)}</div>
    {canEdit && <form className="inline-form" onSubmit={add} aria-label="Nowy wariant">
      <input aria-label="Oznaczenie wariantu" required placeholder="np. 1x56+1x42" value={form.code} onChange={event => setForm(c => ({ ...c, code: event.target.value }))} />
      <input aria-label="Moduły na stół" type="number" min="0" placeholder="moduły (z oznaczenia)" value={form.modules} onChange={event => setForm(c => ({ ...c, modules: event.target.value }))} />
      <button className="primary" disabled={!form.code.trim()}>+ Dodaj wariant</button>
    </form>}
  </section>;
}

function ZoneList({ zones, selectedId, onSelect, canEdit, project, notify, reload }) {
  const [form, setForm] = useState({ name: "", description: "" });
  async function create(event) {
    event.preventDefault();
    try {
      const zone = await send(`/api/projects/${project.id}/zones`, "POST", { name: form.name, description: form.description });
      notify(`Utworzono strefę „${zone.name}”`); setForm({ name: "", description: "" }); await reload(); onSelect(zone.id);
    } catch (failure) { notify(failure.message, "error"); }
  }
  return <aside className="zone-list-panel">
    <div className="zone-list" role="list" aria-label="Strefy">{zones.map(zone => <button type="button" role="listitem" key={zone.id} className={`zone-item ${zone.id === selectedId ? "active" : ""}`} onClick={() => onSelect(zone.id)}>
      <strong>{zone.name}</strong>{zone.description && <small>{zone.description}</small>}
      <span className="zone-item-stats"><b>{zone.stats.built}/{zone.stats.total}</b> zbudowanych · {zone.stats.qc} QA/QC</span>
      <Progress value={pct(zone.stats.built, zone.stats.total)} />
    </button>)}</div>
    {!zones.length && <p className="hint">Nie ma jeszcze stref.</p>}
    {canEdit && <form className="card zone-create-form" onSubmit={create} aria-label="Nowa strefa">
      <strong>+ Nowa strefa</strong>
      <input aria-label="Nazwa nowej strefy" required placeholder="Nazwa, np. Strefa A — północ" value={form.name} onChange={event => setForm(c => ({ ...c, name: event.target.value }))} />
      <input aria-label="Opis nowej strefy" placeholder="Opis (opcjonalnie)" value={form.description} onChange={event => setForm(c => ({ ...c, description: event.target.value }))} />
      <button className="primary" disabled={!form.name.trim()}>Utwórz strefę</button>
    </form>}
  </aside>;
}

function ZoneHeader({ zone, project, canEdit, isManager, notify, reload, onDeleted }) {
  const confirm = useConfirm();
  const [form, setForm] = useState(null);
  const cancel = useCallback(() => setForm(null), []);
  useEscape(cancel, !!form);
  async function save(event) {
    event.preventDefault();
    try { await send(`/api/projects/${project.id}/zones/${zone.id}`, "PATCH", form); notify("Zapisano strefę"); cancel(); reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  async function remove() {
    const withRows = zone.stats.total > 0;
    if (!(await confirm({ title: `Usunąć strefę „${zone.name}”?`, message: withRows ? `Zostanie usunięta razem z ${zone.stats.total} rzędami. Rzędów z montażem, notatkami lub zdjęciami aplikacja nie usunie.` : "Strefa nie ma rzędów.", danger: true, confirmLabel: "Usuń strefę" }))) return;
    try { await send(`/api/projects/${project.id}/zones/${zone.id}?with_tables=true`, "DELETE"); notify("Strefa usunięta"); onDeleted(); } catch (failure) { notify(failure.message, "error"); }
  }
  async function protocol() {
    try {
      const blob = await api(`/api/projects/${project.id}/zones/${zone.id}/protocol`);
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url; link.download = `Protokol-${zone.name}.pdf`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (failure) { notify(failure.message, "error"); }
  }
  if (form) {
    return <form className="card zone-header editing" onSubmit={save} aria-label="Edycja strefy">
      <label>Nazwa<input required autoFocus value={form.name} onChange={event => setForm(c => ({ ...c, name: event.target.value }))} /></label>
      <label>Opis<input value={form.description} onChange={event => setForm(c => ({ ...c, description: event.target.value }))} /></label>
      <div className="card-actions"><button className="primary">Zapisz</button><button type="button" className="secondary" onClick={cancel}>Anuluj</button></div>
    </form>;
  }
  return <section className="card zone-header">
    <div className="zone-name"><span>STREFA</span><h2>{zone.name}</h2>{zone.description && <small>{zone.description}</small>}</div>
    <div className="zone-progress"><strong>{zone.stats.built}/{zone.stats.total}</strong><span>zbudowane · {zone.stats.qc} QA/QC</span><Progress value={pct(zone.stats.built, zone.stats.total)} /></div>
    <div className="card-actions">
      <AsyncButton onClick={protocol} busyLabel="Generowanie…">Protokół PDF</AsyncButton>
      {canEdit && <button type="button" onClick={() => setForm({ name: zone.name, description: zone.description || "" })}>Edytuj</button>}
      {isManager && <button type="button" className="danger-button" onClick={remove}>Usuń strefę</button>}
    </div>
  </section>;
}

function RangeForms({ zone, zoneIndex, zoneTables, types, project, notify, reload }) {
  const prefixes = [...new Set(zoneTables.map(table => table.prefix))];
  const defaultPrefix = prefixes[0] || LETTERS[zoneIndex % LETTERS.length];
  const nextNumber = 1 + Math.max(0, ...zoneTables.filter(table => table.prefix === defaultPrefix).map(table => table.number));
  const [add, setAdd] = useState({ prefix: "", first: "", last: "", type: "" });
  const [assign, setAssign] = useState({ first: "", last: "", type: "" });
  const prefix = (add.prefix || defaultPrefix).toUpperCase();
  const first = add.first === "" ? nextNumber : Number(add.first);
  async function create(event) {
    event.preventDefault();
    try {
      const result = await send(`/api/projects/${project.id}/tables/range`, "POST", { prefix, first, last: Number(add.last), zone_id: zone.id, ...(add.type ? { structure_type_id: Number(add.type) } : {}) });
      notify(`Dodano ${result.added} rzędów ${prefix}-${first}…${prefix}-${add.last}${result.skipped ? ` (pominięto ${result.skipped} istniejących oznaczeń)` : ""}`);
      setAdd({ prefix: "", first: "", last: "", type: add.type }); reload();
    } catch (failure) { notify(failure.message, "error"); }
  }
  async function apply(event) {
    event.preventDefault();
    const from = Number(assign.first), to = Number(assign.last);
    const ids = zoneTables.filter(table => table.prefix === defaultPrefix && table.number >= from && table.number <= to).map(table => table.id);
    if (!ids.length) { notify(`W strefie nie ma rzędów ${defaultPrefix}-${from}…${defaultPrefix}-${to}`, "error"); return; }
    try {
      await send(`/api/projects/${project.id}/tables/assign`, "POST", { ids, structure_type_id: assign.type ? Number(assign.type) : null });
      notify(`Wariant ${types.find(type => String(type.id) === assign.type)?.code || "—"} przypisany do ${ids.length} rzędów`); reload();
    } catch (failure) { notify(failure.message, "error"); }
  }
  const typeOptions = types.map(type => <option key={type.id} value={type.id}>{type.code}</option>);
  return <div className="range-forms">
    <form className="card" onSubmit={create} aria-label="Dodaj rzędy">
      <h3>2. Dodaj rzędy do strefy</h3>
      <div className="form-grid four">
        <label>Prefiks<input value={add.prefix} placeholder={defaultPrefix} onChange={event => setAdd(c => ({ ...c, prefix: event.target.value }))} pattern="[A-Za-z]{1,10}" /></label>
        <label>Od<input type="number" min="0" value={add.first} placeholder={String(nextNumber)} onChange={event => setAdd(c => ({ ...c, first: event.target.value }))} /></label>
        <label>Do<input type="number" min="0" required value={add.last} onChange={event => setAdd(c => ({ ...c, last: event.target.value }))} /></label>
        <label>Wariant<select value={add.type} onChange={event => setAdd(c => ({ ...c, type: event.target.value }))}><option value="">— później —</option>{typeOptions}</select></label>
      </div>
      <button className="primary" disabled={!add.last}>Dodaj rzędy {add.last ? `${prefix}-${first}…${prefix}-${add.last}` : ""}</button>
    </form>
    <form className="card" onSubmit={apply} aria-label="Przypisz wariant">
      <h3>3. Przypisz wariant do rzędów</h3>
      <div className="form-grid three">
        <label>Od rzędu<input type="number" min="0" required value={assign.first} onChange={event => setAssign(c => ({ ...c, first: event.target.value }))} /></label>
        <label>Do rzędu<input type="number" min="0" required value={assign.last} onChange={event => setAssign(c => ({ ...c, last: event.target.value }))} /></label>
        <label>Wariant<select required value={assign.type} onChange={event => setAssign(c => ({ ...c, type: event.target.value }))}><option value="">Wybierz…</option>{typeOptions}</select></label>
      </div>
      <button className="primary" disabled={!types.length}>Przypisz {assign.first && assign.last ? `${defaultPrefix}-${assign.first}…${defaultPrefix}-${assign.last}` : ""}</button>
      {!types.length && <small className="needs">Najpierw dodaj warianty budowy (u góry).</small>}
    </form>
  </div>;
}

function RowsTable({ zone, zoneTables, types, project, canEdit, notify, reload, onOpen }) {
  const confirm = useConfirm();
  const typeCode = id => types.find(type => type.id === id)?.code;
  const summary = useMemo(() => {
    const counts = new Map();
    for (const table of zoneTables) counts.set(table.structure_type_id ?? 0, (counts.get(table.structure_type_id ?? 0) || 0) + 1);
    return [...counts.entries()];
  }, [zoneTables]);
  async function setVariant(table, value) {
    try { await send(`/api/projects/${project.id}/tables/assign`, "POST", { ids: [table.id], structure_type_id: value ? Number(value) : null }); reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  async function remove(table) {
    if (!(await confirm({ title: `Usunąć rząd ${table.code}?`, message: "Rząd zniknie ze strefy i z zapotrzebowania.", danger: true, confirmLabel: "Usuń rząd" }))) return;
    try { await send(`/api/projects/${project.id}/tables/delete`, "POST", { ids: [table.id] }); notify(`Usunięto ${table.code}`); reload(); } catch (failure) { notify(failure.message, "error"); }
  }
  return <section className="card rows-card">
    <div className="card-head"><h2>Rzędy strefy</h2><span className="badge neutral">{zoneTables.length}</span>
      <div className="variant-summary">{summary.map(([id, count]) => <span key={id} className={id ? "variant-chip small" : "variant-chip small missing"}><strong>{id ? typeCode(id) : "bez wariantu"}</strong><small>{count}</small></span>)}</div>
    </div>
    {!zoneTables.length ? <Empty>Strefa nie ma rzędów. Dodaj zakres, np. od 1 do 50.</Empty>
      : <div className="table-scroll rows-scroll"><table className="grid-table rows-table" data-testid="zone-rows">
        <thead><tr><th>Rząd</th><th>Wariant</th><th>Montaż</th><th>QA/QC</th><th>Pamięć rzędu</th><th>Ostatnia zmiana</th>{canEdit && <th />}</tr></thead>
        <tbody>{zoneTables.map(table => <tr key={table.id} className={table.qc_checked ? "row-qc" : table.built ? "row-built" : ""}>
          <td><button type="button" className="text-button row-open" onClick={() => onOpen(table.id)}>{table.code}</button>{table.pending && <span className="badge warning">offline</span>}</td>
          <td>{canEdit ? <select aria-label={`Wariant ${table.code}`} value={table.structure_type_id || ""} onChange={event => setVariant(table, event.target.value)}><option value="">—</option>{types.map(type => <option key={type.id} value={type.id}>{type.code}</option>)}</select> : typeCode(table.structure_type_id) || "—"}</td>
          <td>{table.built ? <span className="badge success">✓ zbudowany</span> : <span className="badge neutral">do zrobienia</span>}</td>
          <td>{table.qc_checked ? <span className="badge success">✓ odebrany</span> : "—"}</td>
          <td><button type="button" className="text-button" onClick={() => onOpen(table.id)}>{table.notes || table.photos ? `📝 ${table.notes} · 📷 ${table.photos}` : "dodaj notatkę / zdjęcie"}</button></td>
          <td><small>{table.last_changed_at ? fmt(table.last_changed_at) : "—"}</small></td>
          {canEdit && <td><button type="button" className="danger-button small" aria-label={`Usuń rząd ${table.code}`} onClick={() => remove(table)}>×</button></td>}
        </tr>)}</tbody>
      </table></div>}
  </section>;
}

function Configuration({ project, access, user, notify }) {
  const base = `/api/projects/${project.id}`;
  const zones = useLoad(() => cachedGet(`${base}/zones`), [project.id]);
  const types = useLoad(() => cachedGet(`${base}/types`), [project.id]);
  const tables = useLoad(() => cachedGet(`${base}/tables`), [project.id]);
  const [pending, reloadPending] = usePending();
  const [selected, setSelected] = useState(null);
  const [openId, setOpenId] = useState(null);
  const canEdit = access.isManager && !project.archived;
  const reloadZones = zones.reload, reloadTypes = types.reload, reloadTables = tables.reload;
  const reload = useCallback(async () => { await Promise.all([reloadZones(), reloadTypes(), reloadTables()]); }, [reloadZones, reloadTypes, reloadTables]);
  useSynced(useCallback(() => { reloadTables(); reloadZones(); }, [reloadTables, reloadZones]));
  const zoneList = (Array.isArray(zones.data) ? zones.data : []).map(item => ({ ...item, stats: item.stats || { total: 0, built: 0, qc: 0 } }));
  const typeList = Array.isArray(types.data) ? types.data : [];
  const all = applyPendingTables(base, Array.isArray(tables.data) ? tables.data : [], pending);
  const zone = zoneList.find(item => item.id === selected) || zoneList[0];
  const zoneTables = zone ? all.filter(table => table.zone_id === zone.id).sort((a, b) => a.prefix.localeCompare(b.prefix) || a.number - b.number) : [];
  const open = all.find(table => table.id === openId);
  if (zones.loading && !zones.data) return <Loader />;
  return <>
    <Guide />
    <Variants project={project} types={typeList} tables={all} canEdit={canEdit} notify={notify} reload={reload} />
    <div className="zones-layout">
      <ZoneList zones={zoneList} selectedId={zone?.id} onSelect={setSelected} canEdit={canEdit} project={project} notify={notify} reload={reload} />
      <section className="zone-work">
        {!zone ? <Empty>Utwórz pierwszą strefę (po lewej), a potem dodaj rzędy i przypisz warianty.</Empty> : <>
          <ZoneHeader key={`${zone.id}-${zone.name}-${zone.description}`} zone={zone} project={project} canEdit={canEdit} isManager={access.isManager && !project.archived} notify={notify} reload={reload} onDeleted={() => { setSelected(null); reload(); }} />
          {canEdit && <RangeForms key={zone.id} zone={zone} zoneIndex={zoneList.indexOf(zone)} zoneTables={zoneTables} types={typeList} project={project} notify={notify} reload={reload} />}
          <RowsTable zone={zone} zoneTables={zoneTables} types={typeList} project={project} canEdit={canEdit} notify={notify} reload={reload} onOpen={setOpenId} />
        </>}
      </section>
    </div>
    {open && <TablePanel project={project} table={open} user={user} access={access} notify={notify} onClose={() => setOpenId(null)} onChanged={() => { reloadPending(); reloadTables(); }} />}
  </>;
}

export default function ZonesAndRows({ project, access, user, notify, navigate, tab }) {
  const operational = tab === "postep";
  return <>
    <div className="view-switch zones-switch" role="tablist" aria-label="Widok">
      <button type="button" role="tab" aria-selected={!operational} className={!operational ? "active" : ""} onClick={() => navigate(`#/p/${project.id}/strefy`)}>Konfiguracja stref</button>
      <button type="button" role="tab" aria-selected={operational} className={operational ? "active" : ""} onClick={() => navigate(`#/p/${project.id}/postep`)}>Rzędy operacyjne</button>
    </div>
    {operational ? <Fieldwork project={project} access={access} user={user} notify={notify} />
      : <Configuration project={project} access={access} user={user} notify={notify} />}
  </>;
}
