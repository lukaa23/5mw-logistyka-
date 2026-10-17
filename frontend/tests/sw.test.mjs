import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const SW_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "sw.js");
const ORIGIN = "https://asolar.test";

function createEnv({ fetchImpl, caches: cacheStores = {}, openFails = false, putFails = false } = {}) {
  const listeners = {};
  const stores = new Map(Object.entries(cacheStores).map(([name, entries]) => [name, new Map(Object.entries(entries))]));
  const puts = [];
  const deleted = [];
  const cacheApi = {
    async open(name) {
      if (openFails) throw new Error("caches.open failed");
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        async put(request, response) {
          if (putFails) throw new TypeError("Request scheme 'chrome-extension' is unsupported");
          const key = typeof request === "string" ? request : request.url;
          puts.push(key); store.set(key, response);
        },
        async add(key) { store.set(key, new Response("shell")); },
      };
    },
    async match(request) {
      const key = typeof request === "string" ? new URL(request, ORIGIN).href : request.url;
      for (const store of stores.values()) { for (const [stored, value] of store) { if (new URL(stored, ORIGIN).href === key) return value; } }
      return undefined;
    },
    async keys() { return [...stores.keys()]; },
    async delete(name) { deleted.push(name); return stores.delete(name); },
  };
  const self = {
    location: { origin: ORIGIN },
    addEventListener(type, handler) { listeners[type] = handler; },
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
  };
  const context = vm.createContext({ self, caches: cacheApi, fetch: fetchImpl || (async () => new Response("ok")), Response, URL, console, Promise });
  vm.runInContext(fs.readFileSync(SW_PATH, "utf8"), context);
  return { listeners, stores, puts, deleted };
}

function makeRequest(url, { method = "GET", mode = "cors", headers = {} } = {}) {
  const lower = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  return { url, method, mode, headers: { get: name => lower[name.toLowerCase()] ?? null } };
}

async function dispatchFetch(env, request) {
  let responded = null; const waits = [];
  const event = { request, respondWith(promise) { responded = Promise.resolve(promise); }, waitUntil(promise) { waits.push(Promise.resolve(promise)); } };
  env.listeners.fetch(event);
  const response = responded ? await responded : null;
  await Promise.all(waits);
  return { response, intercepted: responded !== null, waits: waits.length };
}

const jsResponse = (body = "console.log(1)") => new Response(body, { status: 200, headers: { "content-type": "text/javascript" } });

test("ignoruje żądania rozszerzeń przeglądarki i inne niedozwolone schematy", async () => {
  const env = createEnv();
  for (const url of ["chrome-extension://abcdef/content.js", "moz-extension://abcdef/x.js", "blob:https://asolar.test/1234", "data:text/plain,hi", "ftp://asolar.test/x", "not a url"]) {
    const result = await dispatchFetch(env, makeRequest(url));
    assert.equal(result.intercepted, false, url);
  }
  assert.deepEqual(env.puts, []);
});

test("ignoruje obcy origin, API, WebSocket, POST i Range", async () => {
  const env = createEnv();
  const cases = [
    makeRequest("https://cdn.example.com/lib.js"),
    makeRequest(`${ORIGIN}/api/projects`),
    makeRequest(`${ORIGIN}/api/documents/3/file`),
    makeRequest(`${ORIGIN}/ws?token=abc`),
    makeRequest(`${ORIGIN}/assets/app.js`, { method: "POST" }),
    makeRequest(`${ORIGIN}/assets/video.mp4`, { headers: { Range: "bytes=0-1023" } }),
  ];
  for (const request of cases) assert.equal((await dispatchFetch(env, request)).intercepted, false, request.url);
});

test("obsługuje własny GET i buforuje poprawną odpowiedź przez waitUntil", async () => {
  const env = createEnv({ fetchImpl: async () => jsResponse() });
  const result = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/app.js`));
  assert.equal(result.intercepted, true);
  assert.equal(await result.response.text(), "console.log(1)");
  assert.equal(result.waits, 1);
  assert.deepEqual(env.puts, [`${ORIGIN}/assets/app.js`]);
});

test("zachowuje odpowiedź sieciową, gdy cache.put zgłasza błąd", async () => {
  const env = createEnv({ fetchImpl: async () => jsResponse("ok-body"), putFails: true });
  const result = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/app.js`));
  assert.equal(await result.response.text(), "ok-body");
});

test("zachowuje odpowiedź sieciową, gdy caches.open zgłasza błąd", async () => {
  const env = createEnv({ fetchImpl: async () => jsResponse("ok-body"), openFails: true });
  const result = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/app.js`));
  assert.equal(await result.response.text(), "ok-body");
});

test("nie buforuje odpowiedzi błędów ani częściowych", async () => {
  for (const status of [500, 404, 206]) {
    const env = createEnv({ fetchImpl: async () => new Response("x", { status, headers: { "content-type": "text/javascript" } }) });
    const result = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/app.js`));
    assert.equal(result.response.status, status);
    assert.deepEqual(env.puts, [], `status ${status}`);
  }
});

test("nie buforuje HTML zwróconego zamiast skryptu", async () => {
  const env = createEnv({ fetchImpl: async () => new Response("<!doctype html>", { status: 200, headers: { "content-type": "text/html" } }) });
  await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/missing.js`));
  assert.deepEqual(env.puts, []);
});

test("fallback do powłoki aplikacji działa tylko dla nawigacji", async () => {
  const offline = async () => { throw new TypeError("Failed to fetch"); };
  const env = createEnv({ fetchImpl: offline, caches: { "asolar-eset-shell-v44": { "/": "powłoka" } } });
  env.stores.get("asolar-eset-shell-v44").set("/", new Response("<html>shell</html>", { headers: { "content-type": "text/html" } }));
  const navigation = await dispatchFetch(env, makeRequest(`${ORIGIN}/dokumenty`, { mode: "navigate" }));
  assert.match(await navigation.response.text(), /shell/);
  const script = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/missing.js`));
  assert.equal(script.response.type, "error");
});

test("zapisany plik jest zwracany offline, a brakujący skrypt nie dostaje HTML", async () => {
  const env = createEnv({ fetchImpl: async () => { throw new TypeError("offline"); } });
  env.stores.set("asolar-eset-shell-v44", new Map([[`${ORIGIN}/assets/app.js`, jsResponse("cached-js")]]));
  const hit = await dispatchFetch(env, makeRequest(`${ORIGIN}/assets/app.js`));
  assert.equal(await hit.response.text(), "cached-js");
});

test("aktywacja usuwa tylko stare cache ASOLAR i zostawia cache innych aplikacji", async () => {
  const env = createEnv({ caches: { "asolar-eset-shell-v43": {}, "asolar-eset-shell-v44": {}, "inna-aplikacja-v1": {}, "workbox-precache": {} } });
  let finished;
  env.listeners.activate({ waitUntil: promise => { finished = promise; } });
  await finished;
  assert.deepEqual(env.deleted, ["asolar-eset-shell-v43"]);
  assert.deepEqual([...env.stores.keys()].sort(), ["asolar-eset-shell-v44", "inna-aplikacja-v1", "workbox-precache"]);
});

test("instalacja przechodzi mimo awarii cache i ma nowy identyfikator wersji", async () => {
  const env = createEnv({ openFails: true });
  let finished;
  env.listeners.install({ waitUntil: promise => { finished = promise; } });
  await assert.doesNotReject(finished);
  assert.match(fs.readFileSync(SW_PATH, "utf8"), /shell-v44/);
});
