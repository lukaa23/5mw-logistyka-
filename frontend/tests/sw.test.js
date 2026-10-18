// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const SOURCE = readFileSync(fileURLToPath(new URL("../public/sw.js", import.meta.url)), "utf8");
const ORIGIN = "https://asolar.example";

function createCaches({ putError = null, openError = null, initial = {} } = {}) {
  const stores = new Map(Object.entries(initial).map(([name, entries]) => [name, new Map(Object.entries(entries))]));
  const key = request => typeof request === "string" ? new URL(request, ORIGIN).href : request.url;
  const cacheFor = name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      put: vi.fn(async (request, response) => { if (putError) throw putError; store.set(key(request), response); }),
      add: vi.fn(async request => { store.set(key(request), new Response("shell")); }),
      match: async request => store.get(key(request)),
    };
  };
  return {
    stores,
    open: vi.fn(async name => { if (openError) throw openError; return cacheFor(name); }),
    keys: vi.fn(async () => [...stores.keys()]),
    delete: vi.fn(async name => stores.delete(name)),
    match: vi.fn(async request => {
      for (const store of stores.values()) { const hit = store.get(key(request)); if (hit) return hit; }
      return undefined;
    }),
  };
}

function loadWorker({ caches = createCaches(), fetchImpl = vi.fn(async () => new Response("ok", { status: 200 })) } = {}) {
  const listeners = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, handler) => { listeners[type] = handler; },
    skipWaiting: vi.fn(async () => undefined),
    clients: { claim: vi.fn(async () => undefined) },
  };
  const context = vm.createContext({ self, caches, fetch: fetchImpl, Response, Request, Headers, URL, console: { warn: () => {} }, Promise });
  vm.runInContext(SOURCE, context);
  return { listeners, caches, fetchImpl, self };
}

function fetchEvent(request) {
  const event = {
    request,
    responded: null,
    waits: [],
    respondWith(promise) { this.responded = promise; },
    waitUntil(promise) { this.waits.push(promise); },
  };
  return event;
}

async function dispatch(worker, request) {
  const event = fetchEvent(request);
  worker.listeners.fetch(event);
  const response = event.responded ? await event.responded : null;
  await Promise.all(event.waits);
  return { event, response };
}

const get = (path, init = {}) => new Request(new URL(path, ORIGIN).href, init);
const fakeRequest = (url, extra = {}) => ({ url, method: "GET", headers: new Headers(), mode: "no-cors", ...extra });

describe("service worker ASOLAR", () => {
  it("ignoruje żądania chrome-extension, moz-extension i blob", async () => {
    const worker = loadWorker();
    for (const url of ["chrome-extension://abcdef/script.js", "moz-extension://abcdef/icon.png", "blob:https://asolar.example/123"]) {
      const { event } = await dispatch(worker, fakeRequest(url));
      expect(event.responded).toBeNull();
    }
    expect(worker.fetchImpl).not.toHaveBeenCalled();
    expect(worker.caches.open).not.toHaveBeenCalled();
  });

  it("ignoruje obcy origin, API, WebSocket, POST i Range", async () => {
    const worker = loadWorker();
    const requests = [
      get("https://cdn.other.example/lib.js"),
      get("/api/projects"),
      get("/ws?token=1"),
      fakeRequest(`${ORIGIN}/socket`, { headers: new Headers({ Upgrade: "websocket" }) }),
      new Request(`${ORIGIN}/index.html`, { method: "POST", body: "x" }),
      get("/plan.pdf", { headers: { Range: "bytes=0-100" } }),
    ];
    for (const request of requests) {
      const { event } = await dispatch(worker, request);
      expect(event.responded).toBeNull();
    }
    expect(worker.fetchImpl).not.toHaveBeenCalled();
  });

  it("zwraca odpowiedź sieciową mimo błędu cache.put", async () => {
    const caches = createCaches({ putError: new TypeError("Request scheme 'chrome-extension' is unsupported") });
    const worker = loadWorker({ caches, fetchImpl: vi.fn(async () => new Response("app", { status: 200 })) });
    const { response } = await dispatch(worker, get("/assets/app.js"));
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("app");
  });

  it("zwraca odpowiedź sieciową mimo błędu caches.open", async () => {
    const caches = createCaches({ openError: new Error("quota") });
    const worker = loadWorker({ caches });
    const { response } = await dispatch(worker, get("/assets/app.js"));
    expect(response.status).toBe(200);
  });

  it("buforuje poprawne odpowiedzi 200 przez event.waitUntil", async () => {
    const worker = loadWorker();
    const { event } = await dispatch(worker, get("/assets/app.js"));
    expect(event.waits.length).toBe(1);
    expect(worker.caches.stores.get("asolar-eset-shell-v4.7.0").has(`${ORIGIN}/assets/app.js`)).toBe(true);
  });

  it("nie buforuje odpowiedzi 500 ani częściowych 206", async () => {
    for (const status of [500, 206, 404]) {
      const caches = createCaches();
      const worker = loadWorker({ caches, fetchImpl: vi.fn(async () => new Response("x", { status })) });
      const { response } = await dispatch(worker, get("/assets/app.js"));
      expect(response.status).toBe(status);
      expect(caches.open).not.toHaveBeenCalled();
    }
  });

  it("stosuje fallback index.html tylko dla nawigacji", async () => {
    const caches = createCaches({ initial: { "asolar-eset-shell-v4.7.0": { [`${ORIGIN}/index.html`]: new Response("<html>", { headers: { "Content-Type": "text/html" } }) } } });
    const worker = loadWorker({ caches, fetchImpl: vi.fn(async () => { throw new TypeError("offline"); }) });
    const nav = await dispatch(worker, fakeRequest(`${ORIGIN}/raporty`, { mode: "navigate" }));
    expect(await nav.response.text()).toBe("<html>");
    const script = await dispatch(worker, fakeRequest(`${ORIGIN}/assets/missing.js`, { mode: "no-cors" }));
    expect(script.response.type).toBe("error");
  });

  it("przy aktywacji usuwa tylko stare cache ASOLAR", async () => {
    const caches = createCaches({ initial: { "asolar-eset-shell-v45": {}, "asolar-eset-shell-v4.7.0": {}, "inna-aplikacja-v1": {}, "workbox-precache": {} } });
    const worker = loadWorker({ caches });
    const waits = [];
    worker.listeners.activate({ waitUntil: promise => waits.push(promise) });
    await Promise.all(waits);
    expect([...caches.stores.keys()].sort()).toEqual(["asolar-eset-shell-v4.7.0", "inna-aplikacja-v1", "workbox-precache"]);
    expect(worker.self.clients.claim).toHaveBeenCalled();
  });

  it("instalacja nie przerywa się przy błędzie cache", async () => {
    const worker = loadWorker({ caches: createCaches({ openError: new Error("blocked") }) });
    const waits = [];
    worker.listeners.install({ waitUntil: promise => waits.push(promise) });
    await expect(Promise.all(waits)).resolves.toBeDefined();
    expect(worker.self.skipWaiting).toHaveBeenCalled();
  });
});
