/* ASOLAR v2 — service worker (przeniesiony z v1).
 *
 * Zasady:
 * - obsługujemy wyłącznie GET przez http/https do własnego origin;
 * - nie dotykamy API, WebSocket, żądań Range, rozszerzeń przeglądarki ani blob:;
 * - do cache trafiają tylko pełne odpowiedzi 200 typu "basic";
 * - błąd Cache API nigdy nie blokuje poprawnej odpowiedzi sieciowej;
 * - fallback do index.html wyłącznie dla nawigacji.
 */
const CACHE_PREFIX = "asolar2-";
const CACHE_NAME = "asolar2-shell-2.0.1";
const SHELL = ["/", "/index.html", "/manifest.json", "/icon.svg", "/icon-192.png", "/icon-512.png"];

function shouldHandle(request) {
  if (!request || request.method !== "GET") return false;
  let url;
  try { url = new URL(request.url); } catch { return false; }
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  if (url.origin !== self.location.origin) return false;
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return false;
  if (url.pathname === "/ws" || url.pathname.startsWith("/ws/")) return false;
  const headers = request.headers;
  if (headers && typeof headers.get === "function") {
    if (headers.get("range")) return false;
    if ((headers.get("upgrade") || "").toLowerCase() === "websocket") return false;
  }
  return true;
}

function isCacheableResponse(response) {
  return !!response && response.status === 200 && response.ok && !["opaque", "opaqueredirect", "error"].includes(response.type);
}

async function safeCachePut(request, response) {
  try {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response);
  } catch (error) {
    // Cache jest tylko przyspieszeniem — awaria nie może przerwać działania aplikacji.
    console.warn("[ASOLAR v2 SW] Nie zapisano odpowiedzi w cache", error);
  }
}

async function safeMatch(request) {
  try { return await caches.match(request); } catch { return undefined; }
}

/** Pliki /assets/… wskazane w index.html (nazwy z hashem po buildzie Vite). */
function assetsFromHtml(html) {
  const found = new Set();
  for (const match of String(html).matchAll(/(?:src|href)="(\/assets\/[^"?#]+)"/g)) found.add(match[1]);
  return [...found];
}

async function precache() {
  try {
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(SHELL.map(path => cache.add(path).catch(() => undefined)));
    // Bez tego pierwsza wizyta nie zapisałaby skryptów i offline aplikacja by się nie uruchomiła.
    try {
      const response = await fetch("/index.html", { cache: "no-store" });
      if (response.ok) await Promise.all(assetsFromHtml(await response.text()).map(path => cache.add(path).catch(() => undefined)));
    } catch { /* brak sieci podczas instalacji — pliki zostaną zapisane przy pierwszym użyciu */ }
  } catch (error) {
    console.warn("[ASOLAR v2 SW] Nie przygotowano cache powłoki", error);
  }
}

async function cleanup() {
  try {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
      .map(key => caches.delete(key).catch(() => false)));
  } catch (error) {
    console.warn("[ASOLAR v2 SW] Nie usunięto starych wersji cache", error);
  }
}

async function handleFetch(event) {
  const request = event.request;
  try {
    const response = await fetch(request);
    if (isCacheableResponse(response)) {
      let copy = null;
      try { copy = response.clone(); } catch { copy = null; }
      if (copy) event.waitUntil(safeCachePut(request, copy));
    }
    return response;
  } catch (networkError) {
    const hit = await safeMatch(request);
    if (hit) return hit;
    if (request.mode === "navigate") {
      const shell = (await safeMatch("/index.html")) || (await safeMatch("/"));
      if (shell) return shell;
    }
    return Response.error();
  }
}

self.addEventListener("install", event => {
  event.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(cleanup().then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  if (!shouldHandle(event.request)) return;
  event.respondWith(handleFetch(event));
});
