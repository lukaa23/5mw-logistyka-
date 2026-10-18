/* Trwała kolejka zmian offline w IndexedDB (telefon / przeglądarka).
 *
 * Każdy wpis to zapis JSON (status rzędu, notatka, meldunek, RFI, dostawa…) albo zdjęcie
 * (bajty pliku przechowywane jako ArrayBuffer). Gdy IndexedDB jest niedostępne, zapisy JSON
 * trafiają do localStorage; zdjęć nie da się wtedy przechować — użytkownik dostaje komunikat.
 */
const DB_NAME = "asolar-offline";
const DB_VERSION = 1;
const STORE = "queue";
const FALLBACK_KEY = "asolar_offline_queue_v2";
const LEGACY_KEY = "asolar_offline_queue";

let dbPromise = null;
let memoryCount = { pending: 0, failed: 0 };

function idbAvailable() {
  try { return typeof indexedDB !== "undefined" && indexedDB !== null; } catch { return false; }
}

function openDb() {
  if (!idbAvailable()) return Promise.reject(new Error("IndexedDB niedostępne"));
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "seq", autoIncrement: true });
      };
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
    const store = transaction.objectStore(STORE);
    let result;
    const request = action(store);
    if (request) request.onsuccess = () => { result = request.result; };
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(transaction.error || new Error("Błąd zapisu IndexedDB"));
    transaction.onabort = () => reject(transaction.error || new Error("Przerwano zapis IndexedDB"));
  }));
}

function readFallback() {
  try { const value = JSON.parse(localStorage.getItem(FALLBACK_KEY) || "[]"); return Array.isArray(value) ? value : []; } catch { return []; }
}
function writeFallback(items) {
  localStorage.setItem(FALLBACK_KEY, JSON.stringify(items));
}

async function migrateLegacy() {
  let legacy;
  try { legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || "[]"); } catch { legacy = []; }
  if (!Array.isArray(legacy) || !legacy.length) return;
  for (const request of legacy) {
    if (request && request.path) await insert({ kind: "json", path: request.path, method: request.method, body: request.body, queuedAt: request.queuedAt || new Date().toISOString(), label: describe(request.path, request.method) });
  }
  localStorage.removeItem(LEGACY_KEY);
}

let migrated = null;
function ready() {
  if (!migrated) migrated = migrateLegacy().catch(() => undefined);
  return migrated;
}

export async function addItem(item) {
  await ready();
  await insert(item);
  await refreshCounts();
}

async function insert(item) {
  const record = { attempts: 0, failed: false, lastError: "", queuedAt: new Date().toISOString(), ...item };
  if (record.kind === "photo") {
    try { await run("readwrite", store => store.add(record)); }
    catch (error) { throw new Error(`Nie można zapisać zdjęcia w pamięci telefonu (${error.message}). Spróbuj ponownie z zasięgiem.`); }
  } else {
    try { await run("readwrite", store => store.add(record)); }
    catch {
      const items = readFallback();
      const seq = items.reduce((max, entry) => Math.max(max, entry.seq || 0), 0) + 1;
      items.push({ ...record, seq, storage: "localStorage" });
      writeFallback(items);
    }
  }
}

export async function allItems() {
  await ready();
  let items = [];
  try { items = (await run("readonly", store => store.getAll())) || []; } catch { items = []; }
  const fallback = readFallback();
  return [...items, ...fallback].sort((a, b) => String(a.queuedAt).localeCompare(String(b.queuedAt)) || (a.seq - b.seq));
}

export async function removeItem(item) {
  if (item.storage === "localStorage") writeFallback(readFallback().filter(entry => entry.seq !== item.seq));
  else await run("readwrite", store => store.delete(item.seq));
}

export async function updateItem(item) {
  if (item.storage === "localStorage") writeFallback(readFallback().map(entry => entry.seq === item.seq ? item : entry));
  else await run("readwrite", store => store.put(item));
}

export async function refreshCounts() {
  const items = await allItems();
  memoryCount = { pending: items.filter(item => !item.failed).length, failed: items.filter(item => item.failed).length };
  try { window.dispatchEvent(new CustomEvent("asolar:queue", { detail: memoryCount })); } catch { /* środowisko bez window */ }
  return memoryCount;
}

export const queueCounts = () => memoryCount;

export function describe(path, method) {
  if (/\/api\/rows\/\d+\/notes\/\d+$/.test(path)) return method === "DELETE" ? "Usunięcie notatki" : "Edycja notatki";
  if (/\/api\/rows\/\d+\/notes$/.test(path)) return "Notatka do rzędu";
  if (/\/api\/rows\/\d+\/move$/.test(path)) return "Kolejność rzędów";
  if (/\/api\/rows\/\d+$/.test(path)) return "Status rzędu";
  if (path.startsWith("/api/worklogs")) return "Meldunek";
  if (path.startsWith("/api/rfis")) return "RFI";
  if (path.startsWith("/api/bom-deliveries")) return "Dostawa WZ";
  if (path.startsWith("/api/tracker-zones")) return "Konfiguracja strefy";
  return `${method} ${path}`;
}

// --- kopia zapasowa niewysłanych zmian ---------------------------------------------------

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return btoa(binary);
}
function fromBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

export async function exportBackup() {
  const items = await allItems();
  return {
    app: "ASOLAR ESET Tracker Manager",
    format: 1,
    exportedAt: new Date().toISOString(),
    items: items.map(({ seq, storage, data, ...rest }) => (data ? { ...rest, data: toBase64(data) } : rest)),
  };
}

export async function importBackup(payload) {
  if (!payload || payload.app !== "ASOLAR ESET Tracker Manager" || !Array.isArray(payload.items)) throw new Error("To nie jest plik kopii ASOLAR");
  const existing = new Set((await allItems()).map(item => item.clientId || item.body?.client_id).filter(Boolean));
  let added = 0;
  for (const raw of payload.items) {
    if (!raw || (raw.kind !== "json" && raw.kind !== "photo")) continue;
    const key = raw.clientId || raw.body?.client_id;
    if (key && existing.has(key)) continue;
    const item = { ...raw, failed: false, attempts: 0, lastError: "" };
    if (raw.kind === "photo") item.data = fromBase64(raw.data || "");
    await addItem(item);
    added += 1;
  }
  return added;
}

/** Tylko do testów. */
export async function resetOfflineStore() {
  try { await run("readwrite", store => store.clear()); } catch { /* brak IndexedDB */ }
  localStorage.removeItem(FALLBACK_KEY);
  migrated = null;
  memoryCount = { pending: 0, failed: 0 };
}
