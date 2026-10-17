/* Service worker ASOLAR ESET Tracker Manager.
 *
 * Zasady:
 *  - obsługuje tylko GET przez HTTP/HTTPS do własnego origin;
 *  - nie dotyka API, WebSocket, żądań Range, rozszerzeń przeglądarki, blob: ani obcych origin;
 *  - buforuje wyłącznie pełne odpowiedzi 200; błędy i odpowiedzi częściowe pomija;
 *  - awaria Cache API nigdy nie blokuje poprawnej odpowiedzi sieciowej;
 *  - fallback do powłoki aplikacji tylko dla nawigacji, nigdy dla skryptów i stylów.
 */
const CACHE_PREFIX = "asolar-eset-";
const CACHE = `${CACHE_PREFIX}shell-v44`;
const SHELL = ["/", "/manifest.webmanifest", "/icon.svg"];
const NETWORK_ONLY_PREFIXES = ["/api/", "/ws"];

function isHandled(request) {
  if (!request || request.method !== "GET") return false;
  let url;
  try { url = new URL(request.url); } catch { return false; }
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  if (url.origin !== self.location.origin) return false;
  if (NETWORK_ONLY_PREFIXES.some(prefix => url.pathname === prefix.replace(/\/$/, "") || url.pathname.startsWith(prefix))) return false;
  if (request.headers && request.headers.get("range")) return false;
  return true;
}

function isCacheable(request, response, navigation) {
  if (!response || response.status !== 200 || !response.ok) return false;
  if (response.type && response.type !== "basic" && response.type !== "default") return false;
  const headers = response.headers;
  const contentType = (headers && headers.get("content-type")) || "";
  const cacheControl = (headers && headers.get("cache-control")) || "";
  if (/no-store/i.test(cacheControl)) return false;
  if (!navigation && /text\/html/i.test(contentType)) return false;
  return true;
}

async function safeMatch(key) {
  try { return await caches.match(key); } catch { return undefined; }
}

async function store(request, response) {
  try {
    const cache = await caches.open(CACHE);
    await cache.put(request, response);
  } catch {
    /* Błąd cache nie może wpływać na działanie aplikacji. */
  }
}

async function handle(event) {
  const request = event.request;
  const navigation = request.mode === "navigate";
  try {
    const response = await fetch(request);
    let copy = null;
    try { if (isCacheable(request, response, navigation)) copy = response.clone(); } catch { copy = null; }
    if (copy) event.waitUntil(store(request, copy));
    return response;
  } catch {
    const hit = await safeMatch(request);
    if (hit) return hit;
    if (navigation) {
      const shell = await safeMatch("/");
      if (shell) return shell;
    }
    return Response.error();
  }
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE);
      await Promise.all(SHELL.map(async path => { try { await cache.add(path); } catch { /* element powłoki jest opcjonalny */ } }));
    } catch { /* instalacja działa bez cache */ }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE).map(key => caches.delete(key)));
    } catch { /* czyszczenie jest best-effort */ }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  if (!isHandled(event.request)) return;
  event.respondWith(handle(event));
});
