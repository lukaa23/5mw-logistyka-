import React, { useEffect, useState } from "react";
import { discardQueued, flushQueue, pendingItems, queueCounts, refreshCounts, retryFailed } from "./offline";
import { fmt, useConfirm, useEscape } from "./ui";

/* Wskaźnik w górnym pasku: stan połączenia i niewysłane zmiany tego urządzenia. */

const FLUSH_EVERY_MS = 30000;

export function useAutoFlush(active) {
  useEffect(() => {
    if (!active) return undefined;
    const flush = () => { flushQueue().catch(() => {}); };
    refreshCounts().catch(() => {});
    flush();
    window.addEventListener("online", flush);
    const timer = setInterval(flush, FLUSH_EVERY_MS);
    return () => { window.removeEventListener("online", flush); clearInterval(timer); };
  }, [active]);
}

export default function SyncStatus({ notify }) {
  const confirm = useConfirm();
  const [online, setOnline] = useState(() => navigator.onLine !== false);
  const [counts, setCounts] = useState(queueCounts());
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  useEscape(() => setOpen(false), open);
  useEffect(() => {
    const up = () => setOnline(true), down = () => setOnline(false);
    const queue = event => setCounts(event.detail);
    const synced = event => notify?.(`Wysłano ${event.detail.sent} zapisanych zmian`);
    window.addEventListener("online", up); window.addEventListener("offline", down);
    window.addEventListener("asolar2:queue", queue); window.addEventListener("asolar2:synced", synced);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); window.removeEventListener("asolar2:queue", queue); window.removeEventListener("asolar2:synced", synced); };
  }, [notify]);
  useEffect(() => { if (open) pendingItems().then(setItems); }, [open, counts]);
  async function discard(item) {
    if (!(await confirm({ title: "Odrzucić tę zmianę?", message: `${item.label} — zmiana nie trafi na serwer.`, danger: true, confirmLabel: "Odrzuć" }))) return;
    await discardQueued(item.seq);
  }
  return <div className="sync-status">
    {/* Jak wskaźnik połączenia w v1: kropka stanu, liczba niewysłanych zmian, błędy wysyłki. */}
    <button type="button" className={`connection ${online ? "online" : "offline"} ${counts.failed ? "has-failed" : ""}`} onClick={() => setOpen(value => !value)} aria-expanded={open}
      title="Synchronizacja" aria-label={`${online ? "Online" : "Offline"}${counts.pending ? `, ${counts.pending} do wysłania` : ""}${counts.failed ? `, ${counts.failed} błędów wysyłki` : ""}`}>
      <i />{online ? "Online" : "Offline"}{counts.pending > 0 && <b>{counts.pending}</b>}{counts.failed > 0 && <b className="failed">!{counts.failed}</b>}</button>
    {open && <div className="sync-panel card" role="dialog" aria-label="Niewysłane zmiany">
      <h3>Niewysłane zmiany</h3>
      {!online && <p className="hint">Brak połączenia. Zmiany są bezpieczne w pamięci tego urządzenia i zostaną wysłane automatycznie.</p>}
      {!items.length ? <p className="hint">Brak.</p> : <ul className="plain-list">{items.map(item => <li key={item.seq}>
        <strong>{item.label}</strong><small>{fmt(item.queuedAt)}{item.failed ? ` · ${item.lastError}` : ""}</small>
        <button type="button" className="danger-button small" onClick={() => discard(item)}>Odrzuć</button></li>)}</ul>}
      <div className="card-actions">
        <button type="button" className="primary" disabled={!online} onClick={() => flushQueue()}>Wyślij teraz</button>
        {counts.failed > 0 && <button type="button" className="secondary" disabled={!online} onClick={() => retryFailed()}>Ponów nieudane</button>}
      </div>
    </div>}
  </div>;
}
