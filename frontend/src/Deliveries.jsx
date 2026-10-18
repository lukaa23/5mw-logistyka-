import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { cachedGet, mutate } from "./api";
import { AddButton, canWrite, Empty, fmt, Loader, PageHead, Progress, qty, today, uid, useConfirm, useEscape } from "./ui";

/* ---------- wyszukiwanie w katalogu BOM ---------- */

/** Małe litery, bez polskich znaków i akcentów: „Płatew 1×M16” → „platew 1xm16”. */
export function normalize(value) {
  return String(value ?? "").toLowerCase().replace(/ł/g, "l").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/×/g, "x");
}

/** true, gdy słowa różnią się co najwyżej jednym znakiem (literówka). */
function withinOneEdit(a, b) {
  if (a === b) return true;
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0; let j = 0; let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { i += 1; j += 1; continue; }
    if (++edits > 1) return false;
    if (a.length > b.length) i += 1; else if (b.length > a.length) j += 1; else { i += 1; j += 1; }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

function tokenScore(token, entry) {
  if (entry.key.startsWith(token)) return 100;
  if (entry.name.startsWith(token)) return 70;
  if (entry.words.some(word => word.startsWith(token))) return 45;
  if (entry.text.includes(token)) return 25;
  if (token.length >= 4 && entry.words.some(word => withinOneEdit(word, token) || (word.length > token.length && withinOneEdit(word.slice(0, token.length), token)))) return 8;
  return 0;
}

/** Filtruje katalog po fragmencie nazwy, kodu, specyfikacji lub kategorii; każde słowo zapytania musi pasować. */
export function searchBom(items, query, limit = 40) {
  const tokens = normalize(query).split(/\s+/).filter(Boolean);
  const scored = [];
  for (const item of items || []) {
    const text = normalize(`${item.key} ${item.name} ${item.spec || ""} ${item.category} ${item.unit || ""}`);
    const entry = { key: normalize(item.key), name: normalize(item.name), text, words: text.split(/[^a-z0-9]+/).filter(Boolean) };
    let score = 0;
    let matched = true;
    for (const token of tokens) {
      const value = tokenScore(token, entry);
      if (!value) { matched = false; break; }
      score += value;
    }
    if (matched) scored.push({ item, score: score + (item.required > 0 ? 3 : 0) });
  }
  scored.sort((a, b) => b.score - a.score || String(a.item.category).localeCompare(String(b.item.category), "pl") || String(a.item.name).localeCompare(String(b.item.name), "pl"));
  return scored.slice(0, limit).map(entry => entry.item);
}

const itemLabel = item => `${item.name} [${item.key}]`;

/** 1 pozycja, 2–4 pozycje, 5+ pozycji (z wyjątkiem 12–14). */
export function positionsLabel(count) {
  const last = count % 10; const lastTwo = count % 100;
  if (count === 1) return "1 pozycja";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} pozycje`;
  return `${count} pozycji`;
}

/* ---------- pole wyboru z podpowiedziami ---------- */

export function BomPicker({ items, value, onChange, usedIds = [], label = "Element BOM" }) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const selected = useMemo(() => (items || []).find(item => String(item.component_id) === String(value)), [items, value]);
  const results = useMemo(() => (open ? searchBom(items, query) : []), [items, query, open]);
  const used = useMemo(() => new Set(usedIds.map(String)), [usedIds]);

  function choose(item) {
    if (!item || used.has(String(item.component_id))) return;
    onChange(String(item.component_id));
    setQuery("");
    setOpen(false);
  }
  function onKeyDown(event) {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive(current => Math.min(current + 1, Math.max(results.length - 1, 0))); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(current => Math.max(current - 1, 0)); }
    else if (event.key === "Enter" && open) { event.preventDefault(); choose(results[active]); }
    else if (event.key === "Escape") { setOpen(false); setQuery(""); }
  }

  return <div className="bom-picker">
    <input
      role="combobox"
      aria-label={label}
      aria-expanded={open}
      aria-controls={`${id}-list`}
      aria-autocomplete="list"
      autoComplete="off"
      placeholder="Szukaj: M16, rura, płatew, Jinko, kod…"
      value={open ? query : (selected ? itemLabel(selected) : "")}
      onFocus={() => { setOpen(true); setQuery(""); setActive(0); }}
      onBlur={() => { setOpen(false); setQuery(""); }}
      onChange={event => { setQuery(event.target.value); setOpen(true); setActive(0); }}
      onKeyDown={onKeyDown}
    />
    {selected && !open && <small className="bom-picker-meta">{selected.category} · {selected.spec || "—"} · wymagane {qty(selected.required)} {selected.unit}</small>}
    {open && <ul className="bom-picker-list" id={`${id}-list`} role="listbox" aria-label="Podpowiedzi z katalogu BOM">
      {results.map((item, index) => {
        const taken = used.has(String(item.component_id));
        return <li key={item.component_id} role="option" aria-selected={index === active} aria-disabled={taken} className={`${index === active ? "active" : ""} ${taken ? "taken" : ""}`}
          onMouseDown={event => { event.preventDefault(); choose(item); }} onMouseEnter={() => setActive(index)}>
          <strong>{item.name}</strong>
          <small>{item.key} · {item.category}{item.spec ? ` · ${item.spec}` : ""}{taken ? " · już w tym WZ" : item.required > 0 ? ` · wymagane ${qty(item.required)} ${item.unit}` : ""}</small>
        </li>;
      })}
      {!results.length && <li className="empty-option" aria-disabled="true">Brak pozycji pasujących do „{query}”</li>}
    </ul>}
  </div>;
}

/* ---------- formularz WZ (nowy i edycja) ---------- */

const newLine = () => ({ id: uid(), component_id: "", quantity_received: "", quantity_damaged: "0" });
const blankForm = () => ({ delivery_date: today(), wz_number: "", supplier: "", note: "", lines: [newLine()] });
const DRAFT_PREFIX = "asolar_wz_draft:";

function readDraft(key) {
  if (!key) return null;
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_PREFIX + key) || "null");
    return draft && Array.isArray(draft.lines) && draft.lines.length ? draft : null;
  } catch { return null; }
}
const isEmpty = form => !form.wz_number && !form.supplier && !form.note && form.lines.every(line => !line.component_id && !line.quantity_received);

function fromDelivery(delivery) {
  return {
    delivery_date: String(delivery.delivery_date || today()).slice(0, 10),
    wz_number: delivery.wz_number || "",
    supplier: delivery.supplier || "",
    note: delivery.note || "",
    lines: (delivery.items || []).map(line => ({ id: uid(), component_id: String(line.component_id), quantity_received: String(line.quantity_received), quantity_damaged: String(line.quantity_damaged || 0) })),
  };
}

/** Stan formularza należy wyłącznie do tego komponentu — odświeżanie danych w tle (sync, WebSocket) go nie zmienia. */
export function DeliveryForm({ items, delivery = null, draftKey = null, onSubmit, onCancel }) {
  const editing = !!delivery;
  const [form, setForm] = useState(() => (editing ? fromDelivery(delivery) : readDraft(draftKey) || blankForm()));
  const [restored] = useState(() => !editing && !!readDraft(draftKey));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const byId = useMemo(() => new Map((items || []).map(item => [String(item.component_id), item])), [items]);
  useEscape(() => onCancel?.(), editing && !!onCancel);

  // Szkic nowego WZ przetrwa przełączenie zakładki lub odświeżenie strony.
  useEffect(() => {
    if (!draftKey) return;
    try {
      if (isEmpty(form)) localStorage.removeItem(DRAFT_PREFIX + draftKey);
      else localStorage.setItem(DRAFT_PREFIX + draftKey, JSON.stringify(form));
    } catch { /* brak miejsca w pamięci — formularz działa dalej */ }
  }, [form, draftKey]);

  const setField = (field, value) => setForm(current => ({ ...current, [field]: value }));
  const setLine = (lineId, field, value) => setForm(current => ({ ...current, lines: current.lines.map(line => (line.id === lineId ? { ...line, [field]: value } : line)) }));
  const addLine = () => setForm(current => ({ ...current, lines: [...current.lines, newLine()] }));
  const removeLine = lineId => setForm(current => ({ ...current, lines: current.lines.length > 1 ? current.lines.filter(line => line.id !== lineId) : current.lines }));
  const reset = () => { setForm(blankForm()); setError(""); };

  function validate() {
    if (!form.wz_number.trim()) return "Wpisz numer WZ.";
    const lines = form.lines.filter(line => line.component_id || line.quantity_received);
    if (!lines.length) return "Dodaj przynajmniej jedną pozycję WZ.";
    const seen = new Set();
    for (const line of lines) {
      const item = byId.get(line.component_id);
      if (!item) return "Wybierz element z katalogu BOM w każdej pozycji.";
      if (seen.has(line.component_id)) return `Element „${item.name}” występuje w WZ dwukrotnie — połącz ilości w jednej pozycji.`;
      seen.add(line.component_id);
      const received = Number(line.quantity_received);
      const damaged = Number(line.quantity_damaged || 0);
      if (!(received > 0)) return `Wpisz ilość dostarczoną dla „${item.name}”.`;
      if (damaged < 0 || damaged > received) return `Ilość uszkodzona dla „${item.name}” nie może przekraczać dostarczonej.`;
    }
    return "";
  }

  async function submit(event) {
    event.preventDefault();
    const problem = validate();
    setError(problem);
    if (problem) return;
    const payload = {
      delivery_date: form.delivery_date,
      wz_number: form.wz_number.trim(),
      supplier: form.supplier.trim(),
      note: form.note,
      items: form.lines.filter(line => line.component_id).map(line => ({ component_id: Number(line.component_id), quantity_received: Number(line.quantity_received), quantity_damaged: Number(line.quantity_damaged || 0) })),
    };
    setBusy(true);
    try {
      const ok = await onSubmit(payload);
      if (ok && !editing) { reset(); if (draftKey) localStorage.removeItem(DRAFT_PREFIX + draftKey); }
    } catch (failure) {
      setError(failure?.message || "Nie udało się zapisać WZ");
    } finally { setBusy(false); }
  }

  const usedIds = form.lines.map(line => line.component_id).filter(Boolean);
  return <form id={editing ? undefined : "wz-form"} className={`card bom-delivery-form ${editing ? "editing" : ""}`} onSubmit={submit} noValidate>
    <div className="card-head"><div><p className="eyebrow">{editing ? "KOREKTA PRZYJĘTEGO DOKUMENTU" : "NOWE PRZYJĘCIE"}</p><h2>{editing ? `Edytuj WZ ${delivery.wz_number}` : "Dodaj dokument WZ"}</h2></div>
      {editing ? <span className="badge warning">bilans zostanie przeliczony</span> : <span className="badge neutral">stan początkowy 0</span>}</div>
    {restored && <p className="hint draft-note">Przywrócono niezapisany szkic WZ. <button type="button" className="text-button" onClick={reset}>Wyczyść formularz</button></p>}
    <div className="form-grid">
      <label>Data dostawy<input required type="date" value={form.delivery_date} onChange={event => setField("delivery_date", event.target.value)} /></label>
      <label>Numer WZ<input required value={form.wz_number} onChange={event => setField("wz_number", event.target.value)} placeholder="np. WZ/2026/001" /></label>
      <label>Dostawca<input value={form.supplier} onChange={event => setField("supplier", event.target.value)} /></label>
    </div>
    <div className="delivery-lines">
      {form.lines.map((line, index) => {
        const item = byId.get(line.component_id);
        return <div className="delivery-form-line" key={line.id} data-testid="wz-line">
          <span className="line-number">{index + 1}</span>
          <BomPicker items={items} value={line.component_id} onChange={value => setLine(line.id, "component_id", value)} usedIds={usedIds.filter(used => used !== line.component_id)} label={`Element BOM, pozycja ${index + 1}`} />
          <label className="qty-field">Dostarczono{item ? ` [${item.unit}]` : ""}<input aria-label={`Ilość dostarczona, pozycja ${index + 1}`} type="number" inputMode="decimal" min="0.01" step="0.01" value={line.quantity_received} onChange={event => setLine(line.id, "quantity_received", event.target.value)} /></label>
          <label className="qty-field">Uszkodzone<input aria-label={`Ilość uszkodzona, pozycja ${index + 1}`} type="number" inputMode="decimal" min="0" step="0.01" value={line.quantity_damaged} onChange={event => setLine(line.id, "quantity_damaged", event.target.value)} /></label>
          <button type="button" className="remove-line" aria-label={`Usuń pozycję ${index + 1}`} disabled={form.lines.length === 1} onClick={() => removeLine(line.id)}>×</button>
        </div>;
      })}
    </div>
    <button type="button" className="secondary add-delivery-line" onClick={addLine}>+ Dodaj pozycję WZ</button>
    <label>Uwagi<textarea rows="2" value={form.note} onChange={event => setField("note", event.target.value)} /></label>
    {error && <div className="alert error" role="alert">{error}</div>}
    <div className="card-actions">
      <button className="primary" disabled={busy}>{busy ? "Zapisywanie…" : editing ? "Zapisz zmiany WZ" : "Przyjmij dostawę"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Anuluj</button>}
    </div>
  </form>;
}

/* ---------- widok „Dostawy na budowę” ---------- */

function DeliveryComparisonTable({ items }) {
  return <div className="bom-table-wrap"><table className="bom-table delivery-comparison"><thead><tr><th>Element BOM</th><th>Wymagane</th><th>Dostarczone</th><th>Uszkodzone</th><th>Dostępne</th><th>Brak / nadwyżka</th></tr></thead><tbody>{items.map(item => <tr key={item.key} data-testid={`balance-${item.key}`}><td><strong>{item.name}</strong><small>{item.category} · {item.key}</small></td><td><b>{qty(item.required)} {item.unit}</b></td><td>{qty(item.delivered)} {item.unit}</td><td>{qty(item.damaged)} {item.unit}</td><td><strong>{qty(item.available)} {item.unit}</strong><Progress value={item.completion_pct} /></td><td><span className={`balance ${item.balance < 0 ? "negative" : "positive"}`}>{item.balance < 0 ? `brakuje ${qty(Math.abs(item.balance))}` : item.required > 0 ? `nadwyżka ${qty(item.balance)}` : item.available > 0 ? `poza planem ${qty(item.available)}` : "—"} {item.balance !== 0 || item.available > 0 ? item.unit : ""}</span></td></tr>)}</tbody></table></div>;
}

export const DELETE_CONFIRMATION = "Czy na pewno chcesz usunąć ten dokument WZ? Bilans dostaw zostanie skorygowany.";

export default function BomDeliveries({ project, sync, notify, user }) {
  const projectId = project?.id;
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const requestSeq = useRef(0);
  const confirm = useConfirm();

  // Odświeżanie w tle (co 15 s i po zdarzeniach WebSocket) aktualizuje wyłącznie dane — nigdy formularzy.
  const load = useCallback(async () => {
    if (!projectId) return;
    const seq = ++requestSeq.current;
    try {
      const [comparison, deliveries] = await Promise.all([cachedGet(`/api/projects/${projectId}/bom-delivery-status`), cachedGet(`/api/bom-deliveries?project_id=${projectId}`)]);
      if (seq !== requestSeq.current) return;
      setStatus(comparison);
      setHistory(Array.isArray(deliveries) ? deliveries : []);
    } catch (error) { notify(error.message, "error"); }
  }, [projectId]);
  useEffect(() => { load(); }, [load, sync]);
  useEffect(() => { setEditingId(null); setStatus(null); setHistory([]); }, [projectId]);

  const visible = useMemo(() => {
    const items = (status?.items || []).filter(item => showAll || item.required > 0);
    return search.trim() ? searchBom(items, search, items.length) : items;
  }, [status, showAll, search]);

  async function create(payload) {
    const result = await mutate("/api/bom-deliveries", "POST", { ...payload, project_id: projectId, client_id: uid() });
    if (result.queued) { notify("WZ zapisane w pamięci urządzenia — zostanie wysłane po odzyskaniu połączenia"); return true; }
    await load();
    notify(`WZ ${payload.wz_number} przyjęte — bilans dostaw zaktualizowany`);
    return true;
  }
  async function update(delivery, payload) {
    const result = await mutate(`/api/bom-deliveries/${delivery.id}`, "PUT", payload);
    setEditingId(null);
    if (result.queued) { notify("Korekta WZ zapisana offline — zostanie wysłana po odzyskaniu połączenia"); return true; }
    await load();
    notify(`WZ ${payload.wz_number} poprawione — bilans przeliczony`);
    return true;
  }
  async function remove(delivery) {
    if (!(await confirm({ title: "Usunąć dokument WZ?", message: `${DELETE_CONFIRMATION}\n\nWZ ${delivery.wz_number} z dnia ${fmt(delivery.delivery_date)}, ${positionsLabel(delivery.items.length)}.`, danger: true, confirmLabel: "Usuń WZ" }))) return;
    try {
      const result = await mutate(`/api/bom-deliveries/${delivery.id}`, "DELETE");
      if (result?.queued) notify("Usunięcie WZ zapisane offline — zostanie wykonane po odzyskaniu połączenia");
      else { await load(); notify(`WZ ${delivery.wz_number} usunięte — bilans skorygowany`); }
    } catch (error) { notify(error.message, "error"); }
  }

  if (!project) return <Empty>Wybierz aktywny projekt.</Empty>;
  if (!status) return <Loader />;
  const isManager = user.role === "kierownik";
  return <><PageHead eyebrow="FIZYCZNY STAN NA BUDOWIE" title="Dostawy na budowę"><span className="badge success">WZ · pełna lista BOM</span>{canWrite(user) && <AddButton target="wz-form">Nowy WZ</AddButton>}</PageHead>
    <section className="logistics-explainer"><div><strong>Zapotrzebowanie</strong><span>Wyliczane ze stref i wariantów</span></div><i>→</i><div><strong>Dostawy WZ</strong><span>Faktycznie przyjęte ilości</span></div><i>→</i><div><strong>Stan na polu</strong><span>Dostarczone minus uszkodzone</span></div></section>
    <section className="delivery-kpis"><article className="card"><small>Pozycje wymagane</small><strong>{status.summary.required_items}</strong></article><article className="card"><small>Pozycje kompletne</small><strong>{status.summary.complete_items}</strong></article><article className="card"><small>Pozycje z brakami</small><strong>{status.summary.missing_items}</strong></article><article className="card"><small>Dokumenty WZ</small><strong data-testid="wz-count">{status.summary.deliveries_count}</strong></article></section>
    {canWrite(user) && <DeliveryForm key={`new-${projectId}`} items={status.items} draftKey={`${projectId}`} onSubmit={create} />}
    <section className="card delivery-status-card"><div className="card-head delivery-toolbar"><div><p className="eyebrow">DOSTARCZONE VS WYMAGANE</p><h2>Zestawienie stanu na polu</h2></div><label className="delivery-search">Szukaj<input value={search} onChange={event => setSearch(event.target.value)} placeholder="nazwa, kod, kategoria" /></label><label className="check-line"><input type="checkbox" checked={showAll} onChange={event => setShowAll(event.target.checked)} /> Pokaż cały katalog ({status.summary.catalogue_items})</label></div><DeliveryComparisonTable items={visible} />{!visible.length && <Empty>Brak pozycji pasujących do filtra.</Empty>}</section>
    <section className="card delivery-history"><div className="card-head"><div><p className="eyebrow">HISTORIA PRZYJĘĆ</p><h2>Dokumenty WZ</h2></div></div>
      {history.map(delivery => editingId === delivery.id
        ? <DeliveryForm key={`edit-${delivery.id}`} items={status.items} delivery={delivery} onSubmit={payload => update(delivery, payload)} onCancel={() => setEditingId(null)} />
        : <details className="delivery" key={delivery.id} data-testid="wz-history-item"><summary><div><strong>WZ {delivery.wz_number}</strong><small>{delivery.supplier || "bez dostawcy"} · dodał(a): {delivery.created_by}{delivery.updated_by ? ` · poprawił(a): ${delivery.updated_by}, ${fmt(delivery.updated_at)}` : ""}</small></div><span>{fmt(delivery.delivery_date)}</span></summary>
          {delivery.items.map(line => <div className="delivery-line" key={line.component_id}><span>{line.name}<small>{line.key}</small></span><strong>{qty(line.quantity_received)} {line.unit}</strong>{line.quantity_damaged > 0 && <em>uszkodzone {qty(line.quantity_damaged)}</em>}</div>)}
          {delivery.note && <p className="delivery-note">{delivery.note}</p>}
          {isManager && <div className="card-actions"><button type="button" className="secondary" onClick={() => setEditingId(delivery.id)}>Edytuj WZ</button><button type="button" className="danger-button" onClick={() => remove(delivery)}>Usuń WZ</button></div>}
        </details>)}
      {!history.length && <Empty>Stan dostaw wynosi 0. Dodaj pierwszy dokument WZ.</Empty>}
    </section></>;
}
