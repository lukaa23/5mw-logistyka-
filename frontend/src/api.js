const TOKEN_KEY = "asolar_token";
const QUEUE_KEY = "asolar_offline_queue";
const CACHE_PREFIX = "asolar_cache:";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = token => token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY);

async function parseResponse(response) {
  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("asolar:unauthorized"));
  }
  if (!response.ok) {
    let message = `Błąd ${response.status}`;
    try { message = (await response.json()).detail || message; } catch { /* response has no JSON */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
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
    localStorage.setItem(CACHE_PREFIX + path, JSON.stringify({ at: Date.now(), data }));
    return data;
  } catch (error) {
    const cached = localStorage.getItem(CACHE_PREFIX + path);
    if (cached) return JSON.parse(cached).data;
    throw error;
  }
}

export function queuedCount() {
  return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]").length;
}

export async function mutate(path, method, body) {
  const request = { path, method, body, queuedAt: new Date().toISOString() };
  if (!navigator.onLine) {
    const queue = JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
    queue.push(request); localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    window.dispatchEvent(new Event("asolar:queue"));
    return { queued: true };
  }
  try {
    return await api(path, { method, body: JSON.stringify(body) });
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    const queue = JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
    queue.push(request); localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    window.dispatchEvent(new Event("asolar:queue"));
    return { queued: true };
  }
}

export async function flushQueue() {
  if (!navigator.onLine) return 0;
  const queue = JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
  const pending = [];
  let sent = 0;
  for (let index = 0; index < queue.length; index += 1) {
    const request = queue[index];
    try {
      await api(request.path, { method: request.method, body: JSON.stringify(request.body) });
      sent += 1;
    } catch (error) {
      pending.push(request);
      if (error instanceof TypeError) {
        pending.push(...queue.slice(index + 1));
        break;
      }
    }
  }
  localStorage.setItem(QUEUE_KEY, JSON.stringify(pending));
  return sent;
}

export async function upload(path, formData) {
  if (!navigator.onLine) throw new Error("Wgrywanie plików wymaga połączenia z serwerem");
  return api(path, { method: "POST", body: formData });
}

export async function download(path, filename) {
  const blob = await api(path);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
