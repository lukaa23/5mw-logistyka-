import React, { useMemo, useState } from "react";
import { api, send } from "./api";
import { AsyncButton, Empty, Loader, qty, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* Etap 3: struktura budowy — typy konstrukcji z BOM, stoły i rzędy, zapotrzebowanie materiałów. */

const NEEDS = "wymaga potwierdzenia";

function useAction(notify) {
  return async (fn, success) => {
    try { const result = await fn(); if (success) notify(typeof success === "function" ? success(result) : success); return result ?? true; }
    catch (failure) { notify(failure.message, "error"); return false; }
  };
}

/* ---------- Konstrukcje i BOM ---------- */

function BomRow({ line, canEdit, onSave, onDelete }) {
  const [form, setForm] = useState(null);
  const cancel = () => setForm(null);
  useEscape(cancel, !!form);
  const set = field => event => setForm(current => ({ ...current, [field]: event.target.value }));
  if (form) {
    return <tr className="editing"><td colSpan="6">
      <form className="inline-form" onSubmit={async event => { event.preventDefault(); if (await onSave(line, { ...form, quantity: Number(form.quantity) })) cancel(); }}>
        <input aria-label="Nazwa" required autoFocus value={form.name} onChange={set("name")} />
        <input aria-label="Kod" placeholder="Kod" value={form.code} onChange={set("code")} />
        <input aria-label="Specyfikacja" placeholder="Specyfikacja" value={form.spec} onChange={set("spec")} />
        <input aria-label="Ilość na stół" type="number" min="0" step="any" required value={form.quantity} onChange={set("quantity")} />
        <input aria-label="Jednostka" required value={form.unit} onChange={set("unit")} />
        <button className="primary">Zapisz</button><button type="button" className="secondary" onClick={cancel}>Anuluj</button>
      </form>
    </td></tr>;
  }
  return <tr data-testid="bom-row"><td>{line.name}{line.from_pdf && <small className="tag">PDF</small>}</td><td>{line.code || "—"}</td><td>{line.spec || "—"}</td><td className="num">{qty(line.quantity)}</td><td>{line.unit}</td>
    <td className="row-actions">{canEdit && <><button type="button" onClick={() => setForm({ name: line.name, code: line.code, spec: line.spec, quantity: line.quantity, unit: line.unit })}>Edytuj</button><button type="button" className="danger-button" onClick={() => onDelete(line)}>Usuń</button></>}</td></tr>;
}

/** Brakujące stoły typu wg BOM: liczba z dokumentu, oznaczenia (prefiks, numeracja) wybiera kierownik. */
function CreateTables({ type, project, notify, reload, nextNumber }) {
  const missing = Math.max(0, (type.planned_tables || 0) - type.tables);
  const [prefix, setPrefix] = useState("T");
  const [chosenFirst, setFirst] = useState("");  // puste = następny wolny numer (liczony z aktualnej listy stołów)
  const first = chosenFirst === "" ? nextNumber(prefix) : chosenFirst;
  const [busy, setBusy] = useState(false);
  if (!missing) return null;
  const last = Number(first) + missing - 1;
  async function create(event) {
    event.preventDefault(); setBusy(true);
    try {
      const result = await send(`/api/projects/${project.id}/tables/range`, "POST", { prefix, first: Number(first), last, structure_type_id: type.id });
      notify(`Utworzono ${result.added} stołów typu ${type.code}${result.skipped ? ` (pominięto ${result.skipped} istniejących oznaczeń — sprawdź numerację)` : ""}`);
      reload();
    } catch (failure) { notify(failure.message, "error"); } finally { setBusy(false); }
  }
  return <form className="inline-form create-tables" onSubmit={create} aria-label={`Utwórz stoły typu ${type.code}`}>
    <span>Brakuje <b>{missing}</b> stołów tego typu (wg BOM {type.planned_tables}). Utwórz je jako</span>
    <input aria-label="Prefiks oznaczeń" required pattern="[A-Za-z]{1,10}" value={prefix} onChange={event => { setPrefix(event.target.value); setFirst(""); }} />
    <input aria-label="Pierwszy numer" type="number" min="0" required value={first} onChange={event => setFirst(event.target.value)} />
    <span>… {prefix.toUpperCase()}-{last}</span>
    <button className="primary" disabled={busy}>{busy ? "Tworzenie…" : `Utwórz ${missing} stołów`}</button>
  </form>;
}

function TypeCard({ type, canEdit, project, notify, reload, nextNumber }) {
  const confirm = useConfirm();
  const run = useAction(notify);
  const [posts, setPosts] = useState(type.posts_per_table ?? "");
  const [line, setLine] = useState({ name: "", code: "", spec: "", quantity: "", unit: "szt." });
  const base = `/api/projects/${project.id}`;
  async function savePosts() {
    const value = posts === "" ? null : Number(posts);
    if (value === type.posts_per_table) return;
    if (await run(() => send(`${base}/types/${type.id}`, "PATCH", { posts_per_table: value }), `Typ ${type.code}: słupy na stół zapisane`)) reload();
  }
  async function remove() {
    if (!(await confirm({ title: `Usunąć typ ${type.code}?`, message: `Zostanie usunięty typ razem z ${type.bom.length} pozycjami BOM.`, danger: true, confirmLabel: "Usuń typ" }))) return;
    if (await run(() => send(`${base}/types/${type.id}`, "DELETE"), `Usunięto typ ${type.code}`)) reload();
  }
  async function addLine(event) {
    event.preventDefault();
    if (await run(() => send(`${base}/types/${type.id}/bom`, "POST", { ...line, quantity: Number(line.quantity) }), `Dodano do ${type.code}: ${line.name}`)) { setLine({ name: "", code: "", spec: "", quantity: "", unit: "szt." }); reload(); }
  }
  const saveLine = async (item, values) => { const ok = await run(() => send(`${base}/bom/${item.id}`, "PATCH", values), "Zapisano pozycję BOM"); if (ok) reload(); return ok; };
  async function deleteLine(item) {
    if (!(await confirm({ title: "Usunąć pozycję BOM?", message: `${type.code}: „${item.name}”`, danger: true, confirmLabel: "Usuń pozycję" }))) return;
    if (await run(() => send(`${base}/bom/${item.id}`, "DELETE"), "Usunięto pozycję BOM")) reload();
  }
  const set = field => event => setLine(current => ({ ...current, [field]: event.target.value }));
  return <section className="card type-card" data-testid={`type-${type.code}`}>
    <div className="card-head"><h2>{type.code}</h2>{type.from_pdf && <span className="badge neutral">z PDF</span>}<span className="badge neutral">{type.tables} stołów</span>
      {canEdit && <div className="card-actions"><button type="button" className="danger-button" onClick={remove} disabled={type.tables > 0} title={type.tables ? "Typ ma przypisane stoły" : undefined}>Usuń typ</button></div>}</div>
    <dl className="facts"><dt>Moduły na stół</dt><dd>{type.modules || <span className="needs">{NEEDS}</span>}</dd>
      {type.planned_tables != null && <><dt>Stoły wg BOM</dt><dd>{type.planned_tables}{type.tables !== type.planned_tables && <span className="needs"> (w budowie: {type.tables})</span>}</dd></>}
      <dt>Słupy na stół</dt><dd>{canEdit
        ? <span className="inline-field"><input aria-label={`Słupy na stół ${type.code}`} type="number" min="0" value={posts} placeholder={NEEDS} onChange={event => setPosts(event.target.value)} onBlur={savePosts} onKeyDown={event => { if (event.key === "Enter") event.currentTarget.blur(); }} /></span>
        : type.posts_per_table ?? <span className="needs">{NEEDS}</span>}</dd></dl>
    {canEdit && <CreateTables type={type} project={project} notify={notify} reload={reload} nextNumber={nextNumber} />}
    {type.bom.length ? <div className="table-scroll"><table className="grid-table"><thead><tr><th>Pozycja</th><th>Kod</th><th>Specyfikacja</th><th className="num">Ilość / stół</th><th>J.m.</th><th /></tr></thead>
      <tbody>{type.bom.map(item => <BomRow key={item.id} line={item} canEdit={canEdit} onSave={saveLine} onDelete={deleteLine} />)}</tbody></table></div>
      : <p className="needs">Brak BOM dla tego typu — {NEEDS} (zatwierdź pozycje z PDF albo dodaj ręcznie).</p>}
    {canEdit && <form className="inline-form add-line" onSubmit={addLine} aria-label={`Dodaj pozycję BOM do ${type.code}`}>
      <input aria-label="Nowa pozycja — nazwa" placeholder="Nazwa pozycji" required value={line.name} onChange={set("name")} />
      <input aria-label="Nowa pozycja — kod" placeholder="Kod" value={line.code} onChange={set("code")} />
      <input aria-label="Nowa pozycja — specyfikacja" placeholder="Specyfikacja" value={line.spec} onChange={set("spec")} />
      <input aria-label="Nowa pozycja — ilość na stół" placeholder="Ilość / stół" type="number" min="0" step="any" required value={line.quantity} onChange={set("quantity")} />
      <input aria-label="Nowa pozycja — jednostka" required value={line.unit} onChange={set("unit")} />
      <button className="secondary">Dodaj pozycję</button>
    </form>}
  </section>;
}

export function Constructions({ project, access, notify }) {
  const types = useLoad(() => api(`/api/projects/${project.id}/types`), [project.id]);
  const tables = useLoad(() => api(`/api/projects/${project.id}/tables`), [project.id]);
  const nextNumber = prefix => 1 + Math.max(0, ...(tables.data || []).filter(t => t.prefix === prefix.trim().toUpperCase()).map(t => t.number));
  const reloadAll = () => { types.reload(); tables.reload(); };
  const catalog = useLoad(() => api(`/api/projects/${project.id}/catalog`), [project.id]);
  const run = useAction(notify);
  const [form, setForm] = useState({ code: "", modules: "" });
  const canEdit = access.isManager && !project.archived;
  async function create(event) {
    event.preventDefault();
    if (await run(() => send(`/api/projects/${project.id}/types`, "POST", { code: form.code, modules: Number(form.modules || 0) }), `Dodano typ ${form.code}`)) { setForm({ code: "", modules: "" }); types.reload(); }
  }
  const items = catalog.data?.items || [];
  return <>
    <div className="split">
      <section className="card"><h2>Typy konstrukcji</h2>
        <p className="hint">Typy i ilości BOM na jeden stół pochodzą z zatwierdzonych propozycji PDF albo z ręcznego wpisu. Puste pola to dane do potwierdzenia — aplikacja niczego nie dopowiada.</p>
        {types.error && <div className="alert error" role="alert">{types.error}</div>}
        {!types.loading && !types.data?.length && <Empty>Brak typów. Zatwierdź typy z zakładki „Dokumenty” albo dodaj typ ręcznie.</Empty>}
      </section>
      {canEdit && <form className="card" onSubmit={create}><h2>Nowy typ konstrukcji</h2>
        <div className="form-grid"><label>Oznaczenie<input required placeholder="np. 1x28" value={form.code} onChange={event => setForm(c => ({ ...c, code: event.target.value }))} /></label>
          <label>Moduły na stół<input type="number" min="0" placeholder="z oznaczenia" value={form.modules} onChange={event => setForm(c => ({ ...c, modules: event.target.value }))} /></label></div>
        <button className="primary wide" disabled={!form.code.trim()}>Dodaj typ</button></form>}
    </div>
    {types.loading && !types.data ? <Loader /> : (types.data || []).map(type => <TypeCard key={`${type.id}-${type.posts_per_table}`} type={type} canEdit={canEdit} project={project} notify={notify} reload={reloadAll} nextNumber={nextNumber} />)}
    <div className="split">
      <section className="card"><div className="card-head"><h2>Komponenty, narzędzia, bloki z rysunków</h2><span className="badge neutral">{items.length}</span></div>
        {!items.length ? <Empty>Brak — pojawią się po zatwierdzeniu propozycji „Komponenty” i „Narzędzia”.</Empty>
          : <ul className="plain-list">{items.map(item => <li key={item.id}><span className="badge neutral">{item.kind === "tool" ? "narzędzie" : item.kind === "block" ? "blok z rysunku" : "komponent"}</span> <strong>{item.name}</strong>{item.quantity != null && <span className="suggestion-value">{qty(item.quantity)} szt. w rysunku</span>} <small>{[item.code, item.spec].filter(Boolean).join(" · ")}</small></li>)}</ul>}
      </section>
      <section className="card"><div className="card-head"><h2>Momenty dokręcania</h2></div>
        {!catalog.data?.torques?.length ? <Empty>Brak zatwierdzonych momentów.</Empty>
          : <ul className="plain-list">{catalog.data.torques.map(item => <li key={item.id}><strong>{item.bolt}</strong> {item.min_nm === item.max_nm ? qty(item.min_nm) : `${qty(item.min_nm)}–${qty(item.max_nm)}`} N·m <small>{item.context}</small></li>)}</ul>}
        <p className="hint">Wartości z dokumentów producenta — przed montażem porównaj z aktualną instrukcją.</p>
      </section>
    </div>
  </>;
}

/* ---------- Stoły i rzędy ---------- */

function Rows({ project, zones, rows, canEdit, notify, reload }) {
  const confirm = useConfirm();
  const run = useAction(notify);
  const [form, setForm] = useState({ name: "", zone_id: "" });
  const zoneName = id => zones.find(zone => zone.id === id)?.name || "bez strefy";
  async function create(event) {
    event.preventDefault();
    if (await run(() => send(`/api/projects/${project.id}/rows`, "POST", { name: form.name, zone_id: form.zone_id ? Number(form.zone_id) : null }), `Dodano rząd ${form.name}`)) { setForm(c => ({ ...c, name: "" })); reload(); }
  }
  async function remove(row) {
    if (!(await confirm({ title: `Usunąć rząd ${row.name}?`, message: `${row.tables} stołów zostanie bez rzędu (stoły nie są usuwane).`, danger: true, confirmLabel: "Usuń rząd" }))) return;
    if (await run(() => send(`/api/projects/${project.id}/rows/${row.id}`, "DELETE"), "Rząd usunięty")) reload();
  }
  return <section className="card"><div className="card-head"><h2>Rzędy</h2><span className="badge neutral">{rows.length}</span></div>
    {!rows.length && <p className="hint">Brak rzędów. Rzędy grupują stoły w strefie (np. do raportowania postępu w kolejnym etapie).</p>}
    <ul className="plain-list">{rows.map(row => <li key={row.id} data-testid="row-item"><strong>{row.name}</strong> <small>{zoneName(row.zone_id)} · {row.tables} stołów</small>{canEdit && <button type="button" className="danger-button small" onClick={() => remove(row)}>Usuń</button>}</li>)}</ul>
    {canEdit && <form className="inline-form" onSubmit={create}>
      <input aria-label="Nazwa rzędu" required placeholder="Nazwa rzędu, np. R1" value={form.name} onChange={event => setForm(c => ({ ...c, name: event.target.value }))} />
      <select aria-label="Strefa rzędu" value={form.zone_id} onChange={event => setForm(c => ({ ...c, zone_id: event.target.value }))}><option value="">bez strefy</option>{zones.map(zone => <option key={zone.id} value={zone.id}>{zone.name}</option>)}</select>
      <button className="secondary">Dodaj rząd</button>
    </form>}
  </section>;
}

export function Tables({ project, access, notify }) {
  const base = `/api/projects/${project.id}`;
  const confirm = useConfirm();
  const run = useAction(notify);
  const canEdit = access.isManager && !project.archived;
  const [filter, setFilter] = useState({ zone_id: "", row_id: "", type_id: "", q: "" });
  const [selected, setSelected] = useState(() => new Set());
  const [target, setTarget] = useState({ zone_id: "", row_id: "", structure_type_id: "" });
  const [range, setRange] = useState({ prefix: "T", first: "", last: "" });
  const tables = useLoad(() => api(`${base}/tables`), [project.id]);
  const zones = useLoad(() => api(`${base}/zones`), [project.id]);
  const rows = useLoad(() => api(`${base}/rows`), [project.id]);
  const types = useLoad(() => api(`${base}/types`), [project.id]);
  const all = tables.data || [];
  const zoneList = zones.data || [], rowList = rows.data || [], typeList = types.data || [];
  const matches = (value, wanted) => wanted === "" || (wanted === "0" ? value == null : value === Number(wanted));
  const visible = useMemo(() => all.filter(t => matches(t.zone_id, filter.zone_id) && matches(t.row_id, filter.row_id) && matches(t.structure_type_id, filter.type_id) && (!filter.q || t.code.toLowerCase().includes(filter.q.trim().toLowerCase()))), [all, filter]);
  const names = { zone: id => zoneList.find(z => z.id === id)?.name, row: id => rowList.find(r => r.id === id)?.name, type: id => typeList.find(t => t.id === id)?.code };
  const refresh = () => { tables.reload(); rows.reload(); types.reload(); };
  const toggle = id => setSelected(current => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const allVisibleSelected = visible.length > 0 && visible.every(t => selected.has(t.id));
  const selectVisible = () => setSelected(current => { const next = new Set(current); visible.forEach(t => (allVisibleSelected ? next.delete(t.id) : next.add(t.id))); return next; });
  useEscape(() => setSelected(new Set()), selected.size > 0);

  async function assign() {
    const body = { ids: [...selected] };
    for (const field of ["zone_id", "row_id", "structure_type_id"]) {
      if (target[field] === "") continue;
      body[field] = target[field] === "0" ? null : Number(target[field]);
    }
    if (Object.keys(body).length === 1) { notify("Wybierz strefę, rząd lub typ do przypisania", "error"); return; }
    if (await run(() => send(`${base}/tables/assign`, "POST", body), result => `Zaktualizowano ${result.updated} stołów`)) { setSelected(new Set()); setTarget({ zone_id: "", row_id: "", structure_type_id: "" }); refresh(); }
  }
  async function removeSelected() {
    if (!(await confirm({ title: `Usunąć ${selected.size} stołów?`, message: "Stoły znikną ze struktury budowy i z zapotrzebowania materiałów.", danger: true, confirmLabel: `Usuń ${selected.size}` }))) return;
    if (await run(() => send(`${base}/tables/delete`, "POST", { ids: [...selected] }), result => `Usunięto ${result.deleted} stołów`)) { setSelected(new Set()); refresh(); }
  }
  async function addRange(event) {
    event.preventDefault();
    if (await run(() => send(`${base}/tables/range`, "POST", { prefix: range.prefix, first: Number(range.first), last: Number(range.last) }), result => `Dodano ${result.added} stołów${result.skipped ? `, pominięto ${result.skipped} istniejących` : ""}`)) { setRange(c => ({ ...c, first: "", last: "" })); refresh(); }
  }
  const setF = field => event => setFilter(current => ({ ...current, [field]: event.target.value }));
  const setT = field => event => setTarget(current => ({ ...current, [field]: event.target.value }));
  const options = (list, label) => [<option key="any" value="">{label}</option>, <option key="none" value="0">— bez przypisania —</option>, ...list];
  return <div className="split wide-left">
    <section className="card">
      <div className="card-head"><h2>Stoły / trackery</h2><span className="badge neutral">{visible.length}{visible.length !== all.length ? ` z ${all.length}` : ""}</span></div>
      <div className="filters">
        <select aria-label="Filtr strefy" value={filter.zone_id} onChange={setF("zone_id")}>{options(zoneList.map(z => <option key={z.id} value={z.id}>{z.name}</option>), "Wszystkie strefy")}</select>
        <select aria-label="Filtr rzędu" value={filter.row_id} onChange={setF("row_id")}>{options(rowList.map(r => <option key={r.id} value={r.id}>{r.name}</option>), "Wszystkie rzędy")}</select>
        <select aria-label="Filtr typu" value={filter.type_id} onChange={setF("type_id")}>{options(typeList.map(t => <option key={t.id} value={t.id}>{t.code}</option>), "Wszystkie typy")}</select>
        <input type="search" aria-label="Szukaj stołu" placeholder="Szukaj, np. T-12" value={filter.q} onChange={setF("q")} />
      </div>
      {canEdit && all.length > 0 && <div className="selection-bar">
        <label className="check"><input type="checkbox" checked={allVisibleSelected} onChange={selectVisible} /> Zaznacz widoczne</label>
        <span>{selected.size ? `Zaznaczono: ${selected.size}` : "Zaznacz stoły, aby przypisać strefę, rząd lub typ"}</span>
        {selected.size > 0 && <>
          <select aria-label="Przypisz strefę" value={target.zone_id} onChange={setT("zone_id")}><option value="">strefa: bez zmian</option><option value="0">strefa: usuń</option>{zoneList.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}</select>
          <select aria-label="Przypisz rząd" value={target.row_id} onChange={setT("row_id")}><option value="">rząd: bez zmian</option><option value="0">rząd: usuń</option>{rowList.map(r => <option key={r.id} value={r.id}>{r.name}{r.zone_id ? ` (${names.zone(r.zone_id) || ""})` : ""}</option>)}</select>
          <select aria-label="Przypisz typ" value={target.structure_type_id} onChange={setT("structure_type_id")}><option value="">typ: bez zmian</option><option value="0">typ: usuń</option>{typeList.map(t => <option key={t.id} value={t.id}>{t.code}</option>)}</select>
          <AsyncButton className="primary" busyLabel="Zapisywanie…" onClick={assign}>Przypisz</AsyncButton>
          <button type="button" className="danger-button" onClick={removeSelected}>Usuń zaznaczone</button>
        </>}
      </div>}
      {tables.error && <div className="alert error" role="alert">{tables.error}</div>}
      {tables.loading && !tables.data ? <Loader /> : !all.length ? <Empty>Brak stołów. Zatwierdź numerację z PDF (zakładka „Dokumenty”) albo dodaj zakres ręcznie.</Empty>
        : <div className="table-chips">{visible.map(t => {
          const missing = !t.structure_type_id || !t.zone_id;
          return <button type="button" key={t.id} data-testid="table-chip" className={`table-chip ${selected.has(t.id) ? "selected" : ""} ${missing ? "incomplete" : ""}`} aria-pressed={selected.has(t.id)} disabled={!canEdit}
            title={`${t.code}\nstrefa: ${names.zone(t.zone_id) || NEEDS}\nrząd: ${names.row(t.row_id) || "—"}\ntyp: ${names.type(t.structure_type_id) || NEEDS}`} onClick={() => toggle(t.id)}>
            <strong>{t.code}</strong><small>{names.type(t.structure_type_id) || "typ ?"}</small><small>{names.zone(t.zone_id) || "strefa ?"}{t.row_id ? ` · ${names.row(t.row_id)}` : ""}</small>
          </button>;
        })}</div>}
      <p className="hint">Stół oznaczony przerywaną ramką nie ma typu albo strefy — jego materiały nie są liczone w zapotrzebowaniu.</p>
    </section>
    <div className="stack">
      {canEdit && <form className="card" onSubmit={addRange}><h2>Dodaj stoły ręcznie</h2>
        <p className="hint">Gdy rysunek jest skanem i parser nie odczytał numeracji. Istniejące numery są pomijane.</p>
        <div className="form-grid three"><label>Prefiks<input required pattern="[A-Za-z]{1,10}" value={range.prefix} onChange={event => setRange(c => ({ ...c, prefix: event.target.value }))} /></label>
          <label>Od<input required type="number" min="0" value={range.first} onChange={event => setRange(c => ({ ...c, first: event.target.value }))} /></label>
          <label>Do<input required type="number" min="0" value={range.last} onChange={event => setRange(c => ({ ...c, last: event.target.value }))} /></label></div>
        <button className="secondary wide">Dodaj zakres</button></form>}
      <Rows project={project} zones={zoneList} rows={rowList} canEdit={canEdit} notify={notify} reload={() => { rows.reload(); tables.reload(); }} />
    </div>
  </div>;
}

/* ---------- Zapotrzebowanie materiałów ---------- */

function csv(rows) {
  return rows.map(row => row.map(value => { const text = String(value ?? ""); return /[;"\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text; }).join(";")).join("\n");
}

export function Requirements({ project }) {
  const [zone, setZone] = useState("");
  const zones = useLoad(() => api(`/api/projects/${project.id}/zones`), [project.id]);
  const data = useLoad(() => api(`/api/projects/${project.id}/requirements${zone ? `?zone_id=${zone}` : ""}`), [project.id, zone]);
  const result = data.data;
  function exportCsv() {
    const rows = [["Pozycja", "Kod", "Specyfikacja", "Ilość", "J.m.", "Typy konstrukcji"], ...result.totals.map(line => [line.name, line.code, line.spec, String(line.total).replace(".", ","), line.unit, line.types.join(", ")])];
    const url = URL.createObjectURL(new Blob(["﻿" + csv(rows)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = `zapotrzebowanie-${project.name.replace(/[^\w-]+/g, "_")}${zone ? `-strefa-${zone}` : ""}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  return <>
    <div className="toolbar review-toolbar">
      <select aria-label="Zakres zapotrzebowania" value={zone} onChange={event => setZone(event.target.value)}><option value="">Cała budowa</option>{(zones.data || []).map(z => <option key={z.id} value={z.id}>{z.name}</option>)}</select>
      {result?.totals?.length > 0 && <button type="button" className="secondary" onClick={exportCsv}>Eksport CSV</button>}
    </div>
    {data.error && <div className="alert error" role="alert">{data.error}</div>}
    {data.loading && !result ? <Loader /> : result && <>
      {result.warnings.map(warning => <div className="alert warning" key={warning}>⚠ {warning}</div>)}
      <div className="split">
        <section className="card"><h2>Podsumowanie</h2>
          <dl className="facts"><dt>Stoły</dt><dd>{result.tables_total}</dd><dt>bez typu</dt><dd>{result.tables_without_type}</dd><dt>Moduły</dt><dd>{qty(result.modules_total)}</dd>
            <dt>Słupy</dt><dd>{result.posts_complete ? qty(result.posts_total) : <span className="needs">{qty(result.posts_total)} + {NEEDS}</span>}</dd></dl>
        </section>
        <section className="card"><h2>Stoły wg typu</h2>
          <div className="table-scroll"><table className="grid-table"><thead><tr><th>Typ</th><th className="num">Stoły</th><th className="num">Moduły</th><th className="num">Słupy/stół</th><th>BOM</th></tr></thead>
            <tbody>{result.types.map(t => <tr key={t.type_id}><td><strong>{t.code}</strong></td><td className="num">{t.tables}</td><td className="num">{qty(t.modules_total)}</td><td className="num">{t.posts_per_table ?? <span className="needs">?</span>}</td><td>{t.bom_missing ? <span className="needs">brak</span> : `${t.lines.length} poz.`}</td></tr>)}</tbody></table></div>
        </section>
      </div>
      <section className="card"><div className="card-head"><h2>Zapotrzebowanie materiałów</h2><span className="badge neutral">{result.totals.length}</span></div>
        <p className="hint">Ilość = ilość z BOM na jeden stół × liczba stołów danego typu{zone ? " w wybranej strefie" : ""}. Liczone wyłącznie z zatwierdzonych danych.</p>
        {!result.totals.length ? <Empty>Brak danych do policzenia — przypisz stołom typy konstrukcji z BOM.</Empty>
          : <div className="table-scroll"><table className="grid-table" data-testid="requirements-table"><thead><tr><th>Pozycja</th><th>Kod</th><th>Specyfikacja</th><th className="num">Ilość</th><th>J.m.</th><th>Typy</th></tr></thead>
            <tbody>{result.totals.map(line => <tr key={`${line.code}|${line.name}|${line.spec}|${line.unit}`}><td>{line.name}</td><td>{line.code || "—"}</td><td>{line.spec || "—"}</td><td className="num"><strong>{qty(line.total)}</strong></td><td>{line.unit}</td><td>{line.types.join(", ")}</td></tr>)}</tbody></table></div>}
      </section>
    </>}
  </>;
}
