import React, { useCallback, useMemo, useRef, useState } from "react";
import { PhotoThumb, usePending, useSynced } from "./Fieldwork";
import { cachedGet, clientId, mutate, savePhotos } from "./offline";
import { Empty, fmt, Loader, Progress, qty, today, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

/* Etap 4b: dostawy WZ wobec zapotrzebowania, stan materiałów, meldunki dzienne (także offline). */

const STATUS_TONE = { komplet: "success", brak: "danger", "poza zapotrzebowaniem": "neutral" };
const queuedMessage = what => `Brak zasięgu — ${what} zapisany na urządzeniu, wyślemy go automatycznie`;

/* ---------- Dostawy WZ i stan materiałów ---------- */

const blankDelivery = () => ({ delivery_date: today(), wz_number: "", supplier: "", note: "", items: [{ material_key: "", quantity_received: "", quantity_damaged: "" }] });

function DeliveryForm({ materials, initial, onSubmit, onCancel }) {
  const [form, setForm] = useState(initial || blankDelivery());
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  useEscape(onCancel || (() => {}), !!onCancel);
  const needle = filter.trim().toLowerCase();
  const options = materials.filter(m => !needle || `${m.name} ${m.code} ${m.spec}`.toLowerCase().includes(needle));
  const setLine = (index, field, value) => setForm(current => ({ ...current, items: current.items.map((line, i) => (i === index ? { ...line, [field]: value } : line)) }));
  const used = new Set(form.items.map(line => line.material_key));
  async function submit(event) {
    event.preventDefault();
    const items = form.items.filter(line => line.material_key).map(line => ({ material_key: line.material_key, quantity_received: Number(line.quantity_received), quantity_damaged: Number(line.quantity_damaged || 0) }));
    if (!items.length) return;
    setBusy(true);
    try { if (await onSubmit({ ...form, wz_number: form.wz_number.trim(), items })) setForm(blankDelivery()); } finally { setBusy(false); }
  }
  return <form id="wz-form" className={`card ${initial ? "editing" : ""}`} onSubmit={submit} aria-label={initial ? "Edycja WZ" : "Nowa dostawa WZ"}>
    <h2>{initial ? `Edycja WZ ${initial.wz_number}` : "Przyjęcie dostawy (WZ)"}</h2>
    <div className="form-grid"><label>Data<input type="date" required value={form.delivery_date} onChange={e => setForm(c => ({ ...c, delivery_date: e.target.value }))} /></label>
      <label>Numer WZ<input required value={form.wz_number} onChange={e => setForm(c => ({ ...c, wz_number: e.target.value }))} /></label></div>
    <label>Dostawca<input value={form.supplier} onChange={e => setForm(c => ({ ...c, supplier: e.target.value }))} /></label>
    <input type="search" aria-label="Szukaj materiału" placeholder="Szukaj materiału (nazwa, kod, specyfikacja)…" value={filter} onChange={e => setFilter(e.target.value)} />
    {form.items.map((line, index) => {
      const chosen = materials.find(m => m.key === line.material_key);
      return <div className="wz-line" key={index} data-testid="wz-line">
        <select aria-label={`Materiał ${index + 1}`} required={index === 0} value={line.material_key} onChange={e => setLine(index, "material_key", e.target.value)}>
          <option value="">Wybierz materiał…</option>
          {chosen && !options.includes(chosen) && <option value={chosen.key}>{chosen.name}</option>}
          {options.map(m => <option key={m.key} value={m.key} disabled={used.has(m.key) && m.key !== line.material_key}>{m.name}{m.spec ? ` · ${m.spec}` : ""}{m.code ? ` (${m.code})` : ""}</option>)}
        </select>
        <input aria-label={`Dostarczono ${index + 1}`} type="number" min="0.001" step="any" required={!!line.material_key} placeholder={`Dostarczono${chosen ? ` [${chosen.unit}]` : ""}`} value={line.quantity_received} onChange={e => setLine(index, "quantity_received", e.target.value)} />
        <input aria-label={`Uszkodzone ${index + 1}`} type="number" min="0" step="any" placeholder="Uszkodzone" value={line.quantity_damaged} onChange={e => setLine(index, "quantity_damaged", e.target.value)} />
        {form.items.length > 1 && <button type="button" className="danger-button small" aria-label={`Usuń pozycję ${index + 1}`} onClick={() => setForm(c => ({ ...c, items: c.items.filter((_, i) => i !== index) }))}>×</button>}
      </div>;
    })}
    <button type="button" className="secondary" onClick={() => setForm(c => ({ ...c, items: [...c.items, { material_key: "", quantity_received: "", quantity_damaged: "" }] }))}>+ Pozycja</button>
    <label>Uwagi<textarea rows="2" value={form.note} onChange={e => setForm(c => ({ ...c, note: e.target.value }))} /></label>
    {!materials.length && <p className="needs">Katalog materiałów jest pusty — najpierw zatwierdź BOM lub komponenty (zakładka „Dokumenty i import”).</p>}
    <div className="card-actions"><button className="primary" disabled={busy || !materials.length}>{busy ? "Zapisywanie…" : initial ? "Zapisz WZ" : "Przyjmij dostawę"}</button>{onCancel && <button type="button" className="secondary" onClick={onCancel}>Anuluj</button>}</div>
  </form>;
}

export function Deliveries({ project, access, notify }) {
  const confirm = useConfirm();
  const base = `/api/projects/${project.id}`;
  const materials = useLoad(() => cachedGet(`${base}/materials`), [project.id]);
  const stock = useLoad(() => cachedGet(`${base}/stock`), [project.id]);
  const deliveries = useLoad(() => cachedGet(`${base}/deliveries`), [project.id]);
  const [pending] = usePending();
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [editing, setEditing] = useState(null);
  const refresh = useCallback(() => { stock.reload(); deliveries.reload(); }, [stock.reload, deliveries.reload]); // eslint-disable-line react-hooks/exhaustive-deps
  useSynced(refresh);
  const canWrite = !project.archived;
  const queuedWz = pending.filter(item => item.kind === "json" && item.method === "POST" && item.path === `${base}/deliveries`);

  async function create(body) {
    try {
      const result = await mutate(`${base}/deliveries`, "POST", { ...body, client_id: clientId("wz") });
      notify(result?.queued ? queuedMessage(`WZ ${body.wz_number}`) : `Przyjęto WZ ${body.wz_number}`);
      refresh(); return true;
    } catch (failure) { notify(failure.message, "error"); return false; }
  }
  async function update(body) {
    try { const result = await mutate(`${base}/deliveries/${editing.id}`, "PUT", body); notify(result?.queued ? queuedMessage("zmiana WZ") : `Zapisano WZ ${body.wz_number}`); setEditing(null); refresh(); return true; }
    catch (failure) { notify(failure.message, "error"); return false; }
  }
  async function remove(item) {
    if (!(await confirm({ title: `Usunąć WZ ${item.wz_number}?`, message: `Dostawa z ${fmt(item.delivery_date)} (${item.items.length} poz.) zniknie ze stanu materiałów.`, danger: true, confirmLabel: "Usuń WZ" }))) return;
    try { await mutate(`${base}/deliveries/${item.id}`, "DELETE"); notify("WZ usunięty"); refresh(); } catch (failure) { notify(failure.message, "error"); }
  }
  const items = (stock.data?.items || []).filter(item => !onlyMissing || item.status === "brak");
  const summary = stock.data?.summary;
  return <>
    <section className="card">
      <div className="card-head"><h2>Stan materiałów</h2>{summary && <><span className="badge success">{summary.complete_items} komplet</span><span className={`badge ${summary.missing_items ? "danger" : "neutral"}`}>{summary.missing_items} braków</span></>}
        <label className="check"><input type="checkbox" checked={onlyMissing} onChange={e => setOnlyMissing(e.target.checked)} /> tylko braki</label></div>
      <p className="hint">Zapotrzebowanie = zatwierdzony BOM × stoły danego typu. Dostępne = dostarczone − uszkodzone.</p>
      {stock.error && <div className="alert error" role="alert">{stock.error}</div>}
      {stock.loading && !stock.data ? <Loader /> : !items.length ? <Empty>{onlyMissing ? "Brak braków." : "Brak danych — przypisz stołom typy z BOM albo przyjmij pierwszą dostawę."}</Empty>
        : <div className="table-scroll"><table className="grid-table" data-testid="stock-table"><thead><tr><th>Materiał</th><th className="num">Potrzeba</th><th className="num">Dostarczono</th><th className="num">Uszkodzone</th><th className="num">Bilans</th><th>Stan</th></tr></thead>
          <tbody>{items.map(item => <tr key={item.key}><td><strong>{item.name}</strong><small className="cell-sub">{[item.code, item.spec].filter(Boolean).join(" · ")}</small>{item.completion_pct != null && <Progress value={item.completion_pct} />}</td>
            <td className="num">{qty(item.required)} {item.unit}</td><td className="num">{qty(item.delivered)}</td><td className="num">{qty(item.damaged)}</td>
            <td className={`num ${item.balance < 0 ? "negative" : ""}`}>{item.balance > 0 ? "+" : ""}{qty(item.balance)}</td><td><span className={`badge ${STATUS_TONE[item.status]}`}>{item.status}</span></td></tr>)}</tbody></table></div>}
    </section>
    <div className="split">
      {canWrite && (editing
        ? <DeliveryForm key={`edit-${editing.id}`} materials={materials.data || []} initial={{ ...editing, items: editing.items.map(line => ({ material_key: line.material_key, quantity_received: line.quantity_received, quantity_damaged: line.quantity_damaged })) }} onSubmit={update} onCancel={() => setEditing(null)} />
        : <DeliveryForm key="new" materials={materials.data || []} onSubmit={create} />)}
      <section className="card"><div className="card-head"><h2>Przyjęte dostawy</h2><span className="badge neutral">{deliveries.data?.length || 0}</span></div>
        {queuedWz.map(item => <article className="wz-entry pending" key={`q-${item.seq}`}><strong>WZ {item.body?.wz_number}</strong> <span className="badge warning">czeka na wysłanie</span><small>{item.body?.items?.length} poz. · {fmt(item.body?.delivery_date)}</small></article>)}
        {deliveries.loading && !deliveries.data ? <Loader /> : !deliveries.data?.length && !queuedWz.length ? <Empty>Brak dostaw.</Empty>
          : (deliveries.data || []).map(item => <article className="wz-entry" key={item.id} data-testid="wz-entry">
            <div className="card-head"><div><strong>WZ {item.wz_number}</strong><small>{fmt(item.delivery_date)}{item.supplier ? ` · ${item.supplier}` : ""} · {item.created_by}{item.updated_by ? ` · poprawił(a) ${item.updated_by}` : ""}</small></div>
              {access.isManager && canWrite && <div className="card-actions"><button type="button" onClick={() => setEditing(item)}>Edytuj</button><button type="button" className="danger-button" onClick={() => remove(item)}>Usuń</button></div>}</div>
            <ul className="plain-list">{item.items.map(line => <li key={line.material_key}><span>{line.name}{line.spec ? ` · ${line.spec}` : ""}</span><small>{qty(line.quantity_received)} {line.unit}{line.quantity_damaged ? `, uszkodzone ${qty(line.quantity_damaged)}` : ""}</small></li>)}</ul>
            {item.note && <p className="hint">{item.note}</p>}
          </article>)}
        {!access.isManager && <p className="hint">Poprawki i usuwanie WZ wykonuje kierownik.</p>}
      </section>
    </div>
  </>;
}

/* ---------- Meldunki dzienne ---------- */

const blankLog = () => ({ work_date: today(), team: "", stage: "", people: 1, hours: 8, tables_completed: 0, table_id: "", qc_notes: "", note: "" });

function WorklogPhotos({ base, log, user, access, canWrite, notify, onChanged }) {
  const confirm = useConfirm();
  const photos = useLoad(() => (log.photos ? cachedGet(`${base}/worklogs/${log.id}/photos`) : Promise.resolve([])), [base, log.id, log.photos]);
  async function remove(photo) {
    if (!(await confirm({ title: "Usunąć zdjęcie meldunku?", message: photo.filename, danger: true, confirmLabel: "Usuń zdjęcie" }))) return;
    try { await mutate(`${base}/worklog-photos/${photo.id}`, "DELETE"); notify("Zdjęcie usunięte"); onChanged(); } catch (failure) { notify(failure.message, "error"); }
  }
  if (!photos.data?.length) return null;
  return <div className="photo-grid">{photos.data.map(photo => <PhotoThumb key={photo.id} url={`${base}/worklog-photos/${photo.id}/file`} photo={photo} canDelete={canWrite && (access.isManager || photo.uploaded_by === user.id)} onDelete={remove} />)}</div>;
}

export function Worklogs({ project, access, user, notify }) {
  const confirm = useConfirm();
  const base = `/api/projects/${project.id}`;
  const logs = useLoad(() => cachedGet(`${base}/worklogs`), [project.id]);
  const tables = useLoad(() => cachedGet(`${base}/tables`), [project.id]);
  const [pending] = usePending();
  const [form, setForm] = useState(blankLog);
  const [photos, setPhotos] = useState([]);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef(null);
  const reloadLogs = logs.reload;
  useSynced(useCallback(() => reloadLogs(), [reloadLogs]));
  const cancelEdit = useCallback(() => { setEditing(null); setForm(blankLog()); }, []);
  useEscape(cancelEdit, !!editing);
  const canWrite = !project.archived;
  const tableName = id => (tables.data || []).find(t => t.id === id)?.code;
  const queuedLogs = useMemo(() => pending.filter(item => item.kind === "json" && item.method === "POST" && item.path === `${base}/worklogs`), [pending, base]);
  const set = field => event => setForm(current => ({ ...current, [field]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const body = { ...form, team: form.team.trim(), stage: form.stage.trim(), people: Number(form.people), hours: Number(form.hours), tables_completed: Number(form.tables_completed || 0), table_id: form.table_id ? Number(form.table_id) : null };
    try {
      if (editing) {
        const result = await mutate(`${base}/worklogs/${editing.id}`, "PATCH", body);
        if (photos.length) await savePhotos(`${base}/worklogs/${editing.id}/photos`, photos, "Zdjęcie meldunku");
        notify(result?.queued ? queuedMessage("meldunek") : "Meldunek zaktualizowany");
      } else {
        const id = clientId("log");
        const result = await mutate(`${base}/worklogs`, "POST", { ...body, client_id: id });
        if (photos.length) {
          // Meldunek w kolejce nie ma jeszcze numeru na serwerze — zdjęcia idą po client_id, zaraz po nim.
          const path = result?.queued ? `${base}/worklogs/by-client/${id}/photos` : `${base}/worklogs/${result.id}/photos`;
          await savePhotos(path, photos, "Zdjęcie meldunku", { queue: !!result?.queued });
        }
        notify(result?.queued ? queuedMessage(`meldunek${photos.length ? ` (z ${photos.length} zdjęciami)` : ""}`) : "Meldunek wysłany");
      }
      setEditing(null); setForm(blankLog()); setPhotos([]); if (fileInput.current) fileInput.current.value = "";
      reloadLogs();
    } catch (failure) { notify(failure.message, "error"); }
    finally { setBusy(false); }
  }
  function edit(log) {
    setEditing(log);
    setForm({ work_date: log.work_date, team: log.team, stage: log.stage, people: log.people, hours: log.hours, tables_completed: log.tables_completed, table_id: log.table_id ? String(log.table_id) : "", qc_notes: log.qc_notes, note: log.note });
    document.getElementById("worklog-form")?.scrollIntoView?.({ behavior: "smooth" });
  }
  async function remove(log) {
    if (!(await confirm({ title: "Usunąć meldunek?", message: `Meldunek z ${fmt(log.work_date)} (${log.team}, ${log.author}) zostanie usunięty razem ze zdjęciami.`, danger: true, confirmLabel: "Usuń meldunek" }))) return;
    try { await mutate(`${base}/worklogs/${log.id}`, "DELETE"); notify("Meldunek usunięty"); reloadLogs(); } catch (failure) { notify(failure.message, "error"); }
  }
  const manhours = Number(form.people || 0) * Number(form.hours || 0);
  return <div className="split report-layout">
    {canWrite && <form id="worklog-form" className={`card ${editing ? "editing" : ""}`} onSubmit={submit}>
      <h2>{editing ? "Edycja meldunku" : "Nowy meldunek dzienny"}</h2>
      <div className="form-grid"><label>Data<input type="date" required value={form.work_date} onChange={set("work_date")} /></label><label>Brygada<input required value={form.team} onChange={set("team")} /></label></div>
      <label>Wykonane prace<textarea required rows="3" placeholder="Etap, zakres, nietypowe zadania…" value={form.stage} onChange={set("stage")} /></label>
      <div className="form-grid three"><label>Stoły wykonane<input type="number" min="0" step="0.1" value={form.tables_completed} onChange={set("tables_completed")} /></label>
        <label>Osoby<input type="number" min="1" required value={form.people} onChange={set("people")} /></label>
        <label>Godziny / osoba<input type="number" min="0.5" max="24" step="0.5" required value={form.hours} onChange={set("hours")} /></label></div>
      <small className="hint">Roboczogodziny: {qty(manhours)} rbh</small>
      <label>Stół (opcjonalnie)<select value={form.table_id} onChange={set("table_id")}><option value="">Meldunek ogólny</option>{(tables.data || []).map(t => <option key={t.id} value={t.id}>{t.code}</option>)}</select></label>
      <label>Dziennik QA/QC<textarea rows="3" placeholder="Kontrole, pomiary, niezgodności…" value={form.qc_notes} onChange={set("qc_notes")} /></label>
      <label>Notatki<textarea rows="2" value={form.note} onChange={set("note")} /></label>
      <label className="camera-button"><input ref={fileInput} type="file" accept="image/*" capture="environment" multiple aria-label="Zdjęcia meldunku" onChange={e => setPhotos(Array.from(e.target.files || []))} /><span>▧</span>{photos.length ? `${photos.length} zdjęć do wysłania` : "Zrób lub dodaj zdjęcia"}</label>
      <small className="hint">Bez zasięgu meldunek i zdjęcia zapiszą się na urządzeniu i wyślą automatycznie.</small>
      <div className="card-actions"><button className="primary" disabled={busy}>{busy ? "Zapisywanie…" : editing ? "Zapisz meldunek" : "Wyślij meldunek"}</button>{editing && <button type="button" className="secondary" onClick={cancelEdit}>Anuluj</button>}</div>
    </form>}
    <section className="report-history">
      {queuedLogs.map(item => <article className="card report-entry pending" key={`q-${item.seq}`}><p className="eyebrow">{fmt(item.body?.work_date)} · {item.body?.team}</p><h3>{item.body?.stage}</h3><span className="badge warning">czeka na wysłanie</span></article>)}
      {logs.error && !logs.data && <div className="alert error" role="alert">{logs.error}</div>}
      {logs.loading && !logs.data ? <Loader /> : !logs.data?.length && !queuedLogs.length ? <Empty>Brak meldunków.</Empty>
        : (logs.data || []).map(log => <article className="card report-entry" key={log.id} data-testid="worklog">
          <p className="eyebrow">{fmt(log.work_date)} · {log.team} · {log.author}</p>
          <h3>{qty(log.tables_completed)} stołów · {log.people} os. · {qty(log.manhours)} rbh</h3>
          <p className="pre">{log.stage}</p>
          {log.table_id && <small>Stół: {tableName(log.table_id) || `#${log.table_id}`}</small>}
          {log.qc_notes && <div className="qc-journal"><strong>QA/QC</strong><p className="pre">{log.qc_notes}</p></div>}
          {log.note && <p className="hint pre">{log.note}</p>}
          <WorklogPhotos base={base} log={log} user={user} access={access} canWrite={canWrite} notify={notify} onChanged={reloadLogs} />
          {canWrite && (access.isManager || log.author_id === user.id) && <div className="card-actions"><button type="button" onClick={() => edit(log)}>Edytuj</button>{access.isManager && <button type="button" className="danger-button" onClick={() => remove(log)}>Usuń</button>}</div>}
        </article>)}
    </section>
  </div>;
}
