import { addItem, allItems, describe, exportBackup, importBackup, queueCounts, refreshCounts, removeItem, updateItem } from "./offlineStore";

const TOKEN_KEY = "asolar_token";
const USER_KEY = "asolar_user";
const CACHE_PREFIX = "asolar_cache:";

export { exportBackup, importBackup, refreshCounts };

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = token => token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY);

/** Ostatnio zalogowany użytkownik — pozwala uruchomić aplikację bez zasięgu. */
export function getCachedUser() {
  try { const user = JSON.parse(localStorage.getItem(USER_KEY) || "null"); return user && user.id ? user : null; } catch { return null; }
}
export function setCachedUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user)); else localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.name = "ApiError"; this.status = status; }
}

/** Błąd sieci (brak zasięgu, zerwane połączenie) — w odróżnieniu od odpowiedzi serwera z kodem błędu. */
export const isNetworkError = error => error instanceof TypeError || error?.name === "TypeError" || error?.name === "AbortError";

async function parseResponse(response) {
  if (response.status === 401) {
    setToken(null);
    setCachedUser(null);
    window.dispatchEvent(new Event("asolar:unauthorized"));
  }
  if (!response.ok) {
    let message = `Błąd ${response.status}`;
    try { message = (await response.json()).detail || message; } catch { /* odpowiedź bez JSON */ }
    if (typeof message !== "string") message = `Błąd ${response.status}`;
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.blob();
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return parseResponse(await fetch(path, { ...options, headers }));
}

export async function cachedGet(path) {
  try {
    const data = await api(path);
    try { localStorage.setItem(CACHE_PREFIX + path, JSON.stringify({ at: Date.now(), data })); } catch { /* pełna pamięć — dane i tak są wyświetlane */ }
    return data;
  } catch (error) {
    if (error instanceof ApiError && error.status !== 503 && error.status < 500) throw error;
    const cached = localStorage.getItem(CACHE_PREFIX + path);
    if (cached) { try { return JSON.parse(cached).data; } catch { /* uszkodzony wpis */ } }
    throw isNetworkError(error) ? new Error("Brak połączenia i brak zapisanej kopii tego widoku") : error;
  }
}

const ROW_PATH = /^\/api\/rows\/\d+(\/notes)?$/;

/** Zapis JSON: online — od razu; bez zasięgu lub przy zerwaniu połączenia — do kolejki w telefonie. */
export async function mutate(path, method, body) {
  const changedAt = new Date().toISOString();
  const payload = body && typeof body === "object" && !Array.isArray(body) && ROW_PATH.test(path) && method !== "GET" ? { ...body, client_time: body.client_time || changedAt } : body;
  const enqueue = async () => { await addItem({ kind: "json", path, method, body: payload, queuedAt: changedAt, label: describe(path, method) }); return { queued: true }; };
  if (!navigator.onLine) return enqueue();
  try {
    return await api(path, { method, body: JSON.stringify(payload) });
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    return enqueue();
  }
}

export const queuedCount = () => queueCounts().pending;

function photoPath(item) {
  return item.entityId != null ? `/api/${item.entityType}/${item.entityId}/photos` : `/api/${item.entityType}/by-client/${encodeURIComponent(item.parentClientId)}/photos`;
}

function photoForm(item) {
  const fd = new FormData();
  fd.append("file", new Blob([item.data], { type: item.type || "image/jpeg" }), item.name || "zdjecie.jpg");
  fd.append("client_id", item.clientId);
  fd.append("client_time", item.queuedAt);
  return fd;
}

const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/**
 * Zapisuje zdjęcia. Online: wysyła od razu. Bez zasięgu albo gdy połączenie zerwie się w trakcie
 * wysyłania: zapisuje plik w IndexedDB z tym samym client_id i wyśle go automatycznie później.
 * Rodzica można wskazać przez id (rząd, meldunek, RFI) lub przez client_id wpisu utworzonego offline.
 */
export async function savePhotos(entityType, entityId, files, { parentClientId = null } = {}) {
  let sent = 0;
  let queued = 0;
  for (const file of Array.from(files || [])) {
    const item = { kind: "photo", entityType, entityId, parentClientId, clientId: `photo-${newId()}`, name: file.name || "zdjecie.jpg", type: file.type || "image/jpeg", size: file.size, queuedAt: new Date().toISOString(), label: `Zdjęcie (${entityType === "row" ? "rząd" : entityType === "rfi" ? "RFI" : "meldunek"})` };
    let uploaded = false;
    if (navigator.onLine && (entityId != null || !parentClientId)) {
      try {
        const fd = new FormData();
        fd.append("file", file, item.name);
        fd.append("client_id", item.clientId);
        fd.append("client_time", item.queuedAt);
        await api(photoPath(item), { method: "POST", body: fd });
        uploaded = true;
      } catch (error) {
        if (!isNetworkError(error)) throw error;
      }
    }
    if (uploaded) { sent += 1; continue; }
    item.data = await file.arrayBuffer();
    await addItem(item);
    queued += 1;
  }
  return { sent, queued };
}

/** Bezpośrednie wysłanie pliku (dokumenty, planimetria) — wymaga połączenia. */
export async function upload(path, formData) {
  if (!navigator.onLine) throw new Error("Wgrywanie dokumentów wymaga połączenia z serwerem");
  return api(path, { method: "POST", body: formData });
}

let flushing = null;

/** Wysyła kolejkę po kolei. Zatrzymuje się przy braku sieci; błędne wpisy oznacza, ale ich nie usuwa. */
export function flushQueue() {
  if (!flushing) flushing = doFlush().finally(() => { flushing = null; });
  return flushing;
}

async function doFlush() {
  if (!navigator.onLine || !getToken()) return 0;
  let sent = 0;
  const items = (await allItems()).filter(item => !item.failed);
  for (const item of items) {
    try {
      if (item.kind === "photo") await api(photoPath(item), { method: "POST", body: photoForm(item) });
      else await api(item.path, { method: item.method, body: JSON.stringify(item.body) });
      await removeItem(item);
      sent += 1;
    } catch (error) {
      if (isNetworkError(error) || error.status === 401 || error.status >= 500) break; // spróbujemy ponownie później
      item.attempts = (item.attempts || 0) + 1;
      item.failed = true;
      item.lastError = error.message || String(error);
      await updateItem(item);
    }
  }
  await refreshCounts();
  return sent;
}

/** Ponawia wpisy oznaczone jako nieudane (np. po wyjaśnieniu konfliktu). */
export async function retryFailed() {
  for (const item of await allItems()) if (item.failed) await updateItem({ ...item, failed: false, lastError: "" });
  await refreshCounts();
  return flushQueue();
}

export async function pendingItems() {
  try { return await allItems(); } catch { return []; }
}

/** Nakłada niewysłane zmiany statusów, notatek i zdjęć na dane rzędów (np. z kopii offline). */
export function applyPendingRows(rows, items) {
  if (!Array.isArray(rows) || !items?.length) return rows;
  const patches = new Map();
  const notes = new Map();
  const photos = new Map();
  for (const item of items) {
    if (item.failed) continue;
    if (item.kind === "photo" && item.entityType === "row") { photos.set(item.entityId, (photos.get(item.entityId) || 0) + 1); continue; }
    const match = item.kind === "json" && /^\/api\/rows\/(\d+)(\/notes)?$/.exec(item.path || "");
    if (!match) continue;
    const id = Number(match[1]);
    if (match[2]) { notes.set(id, (notes.get(id) || 0) + 1); continue; }
    const { client_time, ...change } = item.body || {};
    const current = { ...(patches.get(id) || {}), ...change };
    if (change.built === false) current.qc_checked = false;
    patches.set(id, current);
  }
  return rows.map(row => {
    if (!patches.has(row.id) && !notes.has(row.id) && !photos.has(row.id)) return row;
    return { ...row, ...(patches.get(row.id) || {}), notes_count: (row.notes_count || 0) + (notes.get(row.id) || 0), photos: (row.photos || 0) + (photos.get(row.id) || 0), pending_sync: true };
  });
}

export function pendingNotes(rowId, items) {
  return (items || []).filter(item => !item.failed && item.kind === "json" && item.path === `/api/rows/${rowId}/notes`).map(item => ({ id: `pending-${item.seq}`, text: item.body?.text || "", created_at: item.queuedAt, pending: true }));
}

export function pendingPhotos(entityType, entityId, items) {
  return (items || []).filter(item => item.kind === "photo" && item.entityType === entityType && item.entityId === entityId);
}

export async function download(path, filename) {
  const blob = await api(path);
  saveBlob(blob, filename);
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Usuwa jedną niewysłaną zmianę z kolejki tego urządzenia (np. błędnie zrobione zdjęcie). */
export async function discardQueued(seq) {
  const item = (await allItems()).find(entry => entry.seq === seq);
  if (item) await removeItem(item);
  await refreshCounts();
  return !!item;
}
