/* Praca bez zasięgu (etap 4a) — przeniesione z v1 (offlineStore + kolejka), ścieżki per budowa.
 *
 * Zapisy z terenu (postęp stołu, notatki, zdjęcia) przy braku sieci trafiają do trwałej kolejki
 * w IndexedDB i są wysyłane po powrocie zasięgu. Każdy wpis niesie client_time (moment czynności)
 * i — dla notatek i zdjęć — client_id, więc ponowne wysłanie nie tworzy duplikatów na serwerze.
 * Odczyty (cachedGet) pokazują ostatnią zapisaną kopię widoku, gdy serwer jest niedostępny.
 */
import { api, ApiError, getToken } from "./api";

const DB_NAME = "asolar2-offline";
const STORE = "queue";
const FALLBACK_KEY = "asolar2_offline_queue";
export const CACHE_PREFIX = "asolar2_cache:";

let dbPromise = null;
let counts = { pending: 0, failed: 0 };

const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
export const isNetworkError = error => error instanceof TypeError || error?.name === "TypeError" || error?.name === "AbortError";
const online = () => typeof navigator === "undefined" || navigator.onLine !== false;

function openDb() {
  try { if (typeof indexedDB === "undefined" || !indexedDB) return Promise.reject(new Error("IndexedDB niedostępne")); } catch { return Promise.reject(new Error("IndexedDB niedostępne")); }
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: "seq", autoIncrement: true }); };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => { dbPromise = null; reject(request.error || new Error("Nie można otworzyć IndexedDB")); };
      request.onblocked = () => { dbPromise = null; reject(new Error("IndexedDB zablokowane przez inną kartę")); };
    });
  }
  return dbPromise;
}

function run(mode, action) {
  return openDb().then(db => new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    let result;
    const request = action(transaction.objectStore(STORE));
    if (request) request.onsuccess = () => { result = request.result; };
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(transaction.error || new Error("Błąd zapisu IndexedDB"));
    transaction.onabort = () => reject(transaction.error || new Error("Przerwano zapis IndexedDB"));
  }));
}

function readFallback() { try { const value = JSON.parse(localStorage.getItem(FALLBACK_KEY) || "[]"); return Array.isArray(value) ? value : []; } catch { return []; } }
function writeFallback(items) { localStorage.setItem(FALLBACK_KEY, JSON.stringify(items)); }

async function insert(item) {
  const record = { attempts: 0, failed: false, lastError: "", queuedAt: new Date().toISOString(), ...item };
  try { await run("readwrite", store => store.add(record)); }
  catch (error) {
    // Bez IndexedDB zdjęcia nie mają gdzie czekać — lepiej powiedzieć to od razu niż je zgubić.
    if (record.kind === "photo") throw new Error(`Nie można zapisać zdjęcia w pamięci urządzenia (${error.message}). Spróbuj ponownie z zasięgiem.`);
    const items = readFallback();
    items.push({ ...record, seq: items.reduce((max, entry) => Math.max(max, entry.seq || 0), 0) + 1, storage: "localStorage" });
    writeFallback(items);
  }
  await refreshCounts();
}

export async function allItems() {
  let items = [];
  try { items = (await run("readonly", store => store.getAll())) || []; } catch { items = []; }
  return [...items, ...readFallback()].sort((a, b) => String(a.queuedAt).localeCompare(String(b.queuedAt)) || a.seq - b.seq);
}

async function removeItem(item) {
  if (item.storage === "localStorage") writeFallback(readFallback().filter(entry => entry.seq !== item.seq));
  else await run("readwrite", store => store.delete(item.seq));
}

async function updateItem(item) {
  if (item.storage === "localStorage") writeFallback(readFallback().map(entry => (entry.seq === item.seq ? item : entry)));
  else await run("readwrite", store => store.put(item));
}

export async function refreshCounts() {
  const items = await allItems();
  counts = { pending: items.filter(item => !item.failed).length, failed: items.filter(item => item.failed).length };
  try { window.dispatchEvent(new CustomEvent("asolar2:queue", { detail: counts })); } catch { /* bez window */ }
  return counts;
}
export const queueCounts = () => counts;

const LABELS = [
  [/\/tables\/\d+\/progress$/, () => "Postęp stołu"],
  [/\/tables\/\d+\/notes\/\d+$/, method => (method === "DELETE" ? "Usunięcie notatki" : "Edycja notatki")],
  [/\/tables\/\d+\/notes$/, () => "Notatka do stołu"],
  [/\/deliveries(\/\d+)?$/, method => (method === "POST" ? "Dostawa WZ" : method === "DELETE" ? "Usunięcie WZ" : "Edycja WZ")],
  [/\/worklogs(\/\d+)?$/, method => (method === "POST" ? "Meldunek" : method === "DELETE" ? "Usunięcie meldunku" : "Edycja meldunku")],
];
export function describe(path, method) {
  const found = LABELS.find(([pattern]) => pattern.test(path));
  return found ? found[1](method) : `${method} ${path}`;
}

/** Zapis JSON: online od razu; bez zasięgu albo przy zerwanym połączeniu — do kolejki. */
export async function mutate(path, method, body = {}) {
  const queuedAt = new Date().toISOString();
  const payload = method === "DELETE" ? undefined : { ...body, client_time: body.client_time || queuedAt };
  const enqueue = async () => { await insert({ kind: "json", path, method, body: payload, queuedAt, label: describe(path, method) }); return { queued: true }; };
  if (!online()) return enqueue();
  try { return await api(path, { method, body: payload === undefined ? undefined : JSON.stringify(payload) }); }
  catch (error) { if (!isNetworkError(error)) throw error; return enqueue(); }
}

export const noteClientId = () => `note-${newId()}`;
export const clientId = prefix => `${prefix}-${newId()}`;

function photoForm(item, file) {
  const form = new FormData();
  form.append("file", file || new Blob([item.data], { type: item.type || "image/jpeg" }), item.name || "zdjecie.jpg");
  form.append("client_id", item.clientId);
  form.append("client_time", item.queuedAt);
  return form;
}

/** Zdjęcia: online wysyła od razu, bez zasięgu zapisuje bajty w IndexedDB i wyśle później.
 *  queue=true: od razu do kolejki (np. zdjęcia meldunku, który sam czeka w kolejce — wyślą się po nim). */
export async function savePhotos(path, files, label = "Zdjęcie stołu", { queue = false } = {}) {
  let sent = 0, queued = 0;
  for (const file of Array.from(files || [])) {
    const item = { kind: "photo", path, clientId: `photo-${newId()}`, name: file.name || "zdjecie.jpg", type: file.type || "image/jpeg", size: file.size, queuedAt: new Date().toISOString(), label };
    if (online() && !queue) {
      try { await api(path, { method: "POST", body: photoForm(item, file) }); sent += 1; continue; }
      catch (error) { if (!isNetworkError(error)) throw error; }
    }
    await insert({ ...item, data: await file.arrayBuffer() });
    queued += 1;
  }
  return { sent, queued };
}

let flushing = null;
/** Wysyła kolejkę po kolei; przy braku sieci przerywa, błędne wpisy oznacza (nie usuwa). */
export function flushQueue() {
  if (!flushing) flushing = doFlush().finally(() => { flushing = null; });
  return flushing;
}

async function doFlush() {
  if (!online() || !getToken()) return 0;
  let sent = 0;
  for (const item of (await allItems()).filter(entry => !entry.failed)) {
    try {
      if (item.kind === "photo") await api(item.path, { method: "POST", body: photoForm(item) });
      else await api(item.path, { method: item.method, body: item.body === undefined ? undefined : JSON.stringify(item.body) });
      await removeItem(item);
      sent += 1;
    } catch (error) {
      if (isNetworkError(error) || error.status === 401 || error.status >= 500) break; // spróbujemy później
      // Usunięcie czegoś, czego już nie ma — cel osiągnięty.
      if (item.method === "DELETE" && error.status === 404) { await removeItem(item); sent += 1; continue; }
      await updateItem({ ...item, attempts: (item.attempts || 0) + 1, failed: true, lastError: error.message || String(error) });
    }
  }
  await refreshCounts();
  if (sent) try { window.dispatchEvent(new CustomEvent("asolar2:synced", { detail: { sent } })); } catch { /* bez window */ }
  return sent;
}

export async function retryFailed() {
  for (const item of await allItems()) if (item.failed) await updateItem({ ...item, failed: false, lastError: "" });
  await refreshCounts();
  return flushQueue();
}

export async function discardQueued(seq) {
  const item = (await allItems()).find(entry => entry.seq === seq);
  if (item) await removeItem(item);
  await refreshCounts();
  return !!item;
}

/** Zmienia treść notatki, która jeszcze czeka w kolejce (nie trafiła na serwer). */
export async function editQueuedNote(seq, text) {
  const item = (await allItems()).find(entry => entry.seq === seq);
  if (!item || item.kind !== "json" || item.method !== "POST") return false;
  await updateItem({ ...item, body: { ...item.body, text } });
  await refreshCounts();
  return true;
}

export async function pendingItems() { try { return await allItems(); } catch { return []; } }

/** Odczyt z kopią na wypadek braku zasięgu. */
export async function cachedGet(path) {
  try {
    const data = await api(path);
    try { localStorage.setItem(CACHE_PREFIX + path, JSON.stringify({ at: Date.now(), data })); } catch { /* pełna pamięć */ }
    return data;
  } catch (error) {
    if (error instanceof ApiError && error.status < 500) throw error;
    const cached = localStorage.getItem(CACHE_PREFIX + path);
    if (cached) { try { return JSON.parse(cached).data; } catch { /* uszkodzony wpis */ } }
    throw isNetworkError(error) ? new Error("Brak połączenia i brak zapisanej kopii tego widoku") : error;
  }
}

export function clearCache() {
  try { Object.keys(localStorage).filter(key => key.startsWith(CACHE_PREFIX)).forEach(key => localStorage.removeItem(key)); } catch { /* brak dostępu */ }
}

/* ---- nakładanie niewysłanych zmian na dane z serwera / kopii ---- */

const tableIdOf = (prefix, path) => { const match = new RegExp(`^${prefix}/tables/(\\d+)/(progress|notes|photos)`).exec(path || ""); return match ? [Number(match[1]), match[2]] : null; };

export function applyPendingTables(base, tables, items) {
  if (!Array.isArray(tables) || !items?.length) return tables;
  const patches = new Map(), notes = new Map(), photos = new Map();
  for (const item of items) {
    if (item.failed) continue;
    const found = tableIdOf(base, item.path);
    if (!found) continue;
    const [id, kind] = found;
    if (kind === "photos") photos.set(id, (photos.get(id) || 0) + 1);
    else if (kind === "notes" && item.method === "POST") notes.set(id, (notes.get(id) || 0) + 1);
    else if (kind === "notes" && item.method === "DELETE") notes.set(id, (notes.get(id) || 0) - 1);
    else if (kind === "progress") {
      const { client_time, ...change } = item.body || {};
      const current = { ...(patches.get(id) || {}), ...change };
      if (change.built === false) current.qc_checked = false;
      patches.set(id, current);
    }
  }
  return tables.map(table => (patches.has(table.id) || notes.has(table.id) || photos.has(table.id)
    ? { ...table, ...(patches.get(table.id) || {}), notes: Math.max(0, table.notes + (notes.get(table.id) || 0)), photos: table.photos + (photos.get(table.id) || 0), pending: true }
    : table));
}

export function pendingNotes(notesPath, items) {
  return (items || []).filter(item => !item.failed && item.kind === "json" && item.method === "POST" && item.path === notesPath)
    .map(item => ({ id: `pending-${item.seq}`, seq: item.seq, text: item.body?.text || "", created_at: item.queuedAt, pending: true }));
}

export function applyPendingNoteChanges(notesPath, notes, items) {
  const edits = new Map(), deleted = new Set();
  for (const item of items || []) {
    if (item.failed || item.kind !== "json" || !item.path?.startsWith(`${notesPath}/`)) continue;
    const id = Number(item.path.slice(notesPath.length + 1));
    if (item.method === "DELETE") deleted.add(id);
    else if (item.method === "PATCH") edits.set(id, item.body?.text);
  }
  return (notes || []).filter(note => !deleted.has(note.id)).map(note => (edits.has(note.id) ? { ...note, text: edits.get(note.id), pending_edit: true } : note));
}

export function pendingPhotos(photosPath, items) {
  return (items || []).filter(item => item.kind === "photo" && item.path === photosPath);
}

/** Tylko do testów. */
export async function resetOfflineStore() {
  try { await run("readwrite", store => store.clear()); } catch { /* brak IndexedDB */ }
  localStorage.removeItem(FALLBACK_KEY);
  counts = { pending: 0, failed: 0 };
}
