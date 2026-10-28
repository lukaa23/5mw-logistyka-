/* Klient API ASOLAR v2. Token i ostatnio otwarta budowa w localStorage (osobne klucze niż v1). */
const TOKEN_KEY = "asolar2_token";
const USER_KEY = "asolar2_user";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export function setSession(token, user) {
  if (token) { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)); }
  else { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }
}
export function getCachedUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; }
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.name = "ApiError"; this.status = status; }
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) { setSession(null); window.dispatchEvent(new Event("asolar2:unauthorized")); }
  if (!response.ok) {
    let message = `Błąd ${response.status}`;
    try { const detail = (await response.json()).detail; if (typeof detail === "string") message = detail; } catch { /* bez treści JSON */ }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return null;
  return (response.headers.get("content-type") || "").includes("application/json") ? response.json() : response.blob();
}

export const send = (path, method, body) => api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
