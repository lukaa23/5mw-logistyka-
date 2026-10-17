import test from "node:test";
import assert from "node:assert/strict";
import { classifyUploadError, createMemoryStore, createPhotoQueue, createPhotoSubmitter, shouldQueueAfterError } from "../src/photoQueue.js";
import { fitWithin } from "../src/imageTools.js";

const httpError = status => Object.assign(new Error(`Błąd ${status}`), { status });
const networkError = () => new TypeError("Failed to fetch");
const item = (id, createdAt) => ({ id, entityType: "row", entityId: 7, blob: { size: 10 }, filename: `${id}.jpg`, mime: "image/jpeg", createdAt });

test("klasyfikacja błędów: brak sieci i błędy serwera zostają w kolejce, trwałe błędy klienta są odrzucane", () => {
  assert.equal(classifyUploadError(networkError()), "keep");
  for (const status of [401, 403, 408, 429, 500, 502, 503]) assert.equal(classifyUploadError(httpError(status)), "keep", String(status));
  for (const status of [400, 404, 413, 415]) assert.equal(classifyUploadError(httpError(status)), "drop", String(status));
});

test("do kolejki trafia tylko to, co ma szansę się udać później", () => {
  assert.equal(shouldQueueAfterError(networkError()), true);
  assert.equal(shouldQueueAfterError(httpError(503)), true);
  assert.equal(shouldQueueAfterError(httpError(401)), true);
  assert.equal(shouldQueueAfterError(httpError(403)), false);
  assert.equal(shouldQueueAfterError(httpError(400)), false);
  assert.equal(shouldQueueAfterError(httpError(413)), false);
});

test("flush wysyła po kolei i opróżnia kolejkę", async () => {
  const sent = [];
  const queue = createPhotoQueue({ store: createMemoryStore(), send: async entry => { sent.push(entry.id); } });
  await queue.enqueue(item("b", 2)); await queue.enqueue(item("a", 1)); await queue.enqueue(item("c", 3));
  const result = await queue.flush();
  assert.deepEqual(sent, ["a", "b", "c"]);
  assert.deepEqual(result, { sent: 3, dropped: 0, remaining: 0 });
  assert.equal(await queue.count(), 0);
});

test("utrata sieci zatrzymuje wysyłkę i zachowuje resztę w kolejności", async () => {
  let online = false; const attempts = [];
  const queue = createPhotoQueue({ store: createMemoryStore(), send: async entry => { attempts.push(entry.id); if (!online) throw networkError(); } });
  for (const [id, at] of [["a", 1], ["b", 2], ["c", 3]]) await queue.enqueue(item(id, at));
  assert.deepEqual(await queue.flush(), { sent: 0, dropped: 0, remaining: 3 });
  assert.deepEqual(attempts, ["a"], "po pierwszym błędzie sieci nie ma dalszych prób");
  online = true; attempts.length = 0;
  assert.deepEqual(await queue.flush(), { sent: 3, dropped: 0, remaining: 0 });
  assert.deepEqual(attempts, ["a", "b", "c"]);
});

test("zdjęcie dla usuniętego rzędu (404) jest odrzucane, a kolejka idzie dalej", async () => {
  const sent = [];
  const queue = createPhotoQueue({ store: createMemoryStore(), send: async entry => { if (entry.id === "b") throw httpError(404); sent.push(entry.id); } });
  for (const [id, at] of [["a", 1], ["b", 2], ["c", 3]]) await queue.enqueue(item(id, at));
  assert.deepEqual(await queue.flush(), { sent: 2, dropped: 1, remaining: 0 });
  assert.deepEqual(sent, ["a", "c"]);
});

test("równoległe wywołania flush nie wysyłają tego samego zdjęcia dwa razy", async () => {
  let calls = 0; let release;
  const gate = new Promise(resolve => { release = resolve; });
  const queue = createPhotoQueue({ store: createMemoryStore(), send: async () => { calls += 1; await gate; } });
  await queue.enqueue(item("a", 1));
  const first = queue.flush(); const second = queue.flush();
  assert.equal(first, second);
  release();
  await Promise.all([first, second]);
  assert.equal(calls, 1);
});

test("licznik zmienia się po dodaniu i po wysyłce", async () => {
  const counts = [];
  const queue = createPhotoQueue({ store: createMemoryStore(), send: async () => {}, onChange: count => counts.push(count) });
  await queue.enqueue(item("a", 1)); await queue.enqueue(item("b", 2)); await queue.flush();
  assert.deepEqual(counts, [1, 2, 0]);
});

function submitter({ online = true, upload, compress = async file => file } = {}) {
  const store = createMemoryStore(); const uploads = [];
  const queue = createPhotoQueue({ store, send: async entry => { uploads.push(["flush", entry.id]); } });
  let counter = 0;
  const submit = createPhotoSubmitter({ queue, isOnline: () => online, compress, newId: () => `id-${++counter}`, uploadNow: upload || (async args => { uploads.push(["now", args.clientId]); return { id: 1 }; }) });
  return { submit, store, uploads, queue };
}
const photo = { name: "teren.jpg", type: "image/jpeg", size: 1000 };

test("online: zdjęcie jest wysyłane od razu z identyfikatorem klienta i nie trafia do kolejki", async () => {
  const { submit, store, uploads } = submitter();
  const result = await submit({ entityType: "row", entityId: 3, file: photo });
  assert.equal(result.queued, false);
  assert.deepEqual(uploads, [["now", "id-1"]]);
  assert.equal(await store.count(), 0);
});

test("offline: zdjęcie ląduje w kolejce bez próby wysyłki", async () => {
  const { submit, store, uploads } = submitter({ online: false });
  const result = await submit({ entityType: "worklog", entityId: 9, file: photo });
  assert.equal(result.queued, true);
  assert.deepEqual(uploads, []);
  const [saved] = await store.getAll();
  assert.equal(saved.id, "id-1"); assert.equal(saved.entityType, "worklog"); assert.equal(saved.entityId, 9);
});

test("online, ale zasięg padł w trakcie wysyłki: zdjęcie trafia do kolejki z tym samym identyfikatorem", async () => {
  const { submit, store } = submitter({ upload: async () => { throw networkError(); } });
  const result = await submit({ entityType: "row", entityId: 3, file: photo });
  assert.equal(result.queued, true);
  assert.equal((await store.getAll())[0].id, result.id);
});

test("błąd uprawnień lub niepoprawny plik nie trafia do kolejki, tylko jest zgłaszany", async () => {
  for (const status of [403, 400, 413]) {
    const { submit, store } = submitter({ upload: async () => { throw httpError(status); } });
    await assert.rejects(submit({ entityType: "row", entityId: 3, file: photo }), error => error.status === status);
    assert.equal(await store.count(), 0);
  }
});

test("awaria kompresji nie blokuje zdjęcia — wysyłany jest oryginał", async () => {
  let received;
  const { submit } = submitter({ compress: async () => { throw new Error("canvas"); }, upload: async args => { received = args.file; return {}; } });
  await submit({ entityType: "row", entityId: 3, file: photo });
  assert.equal(received, photo);
});

test("fitWithin zmniejsza tylko większe zdjęcia i zachowuje proporcje", () => {
  assert.deepEqual(fitWithin(4000, 3000, 1600), { width: 1600, height: 1200, scaled: true });
  assert.deepEqual(fitWithin(3000, 4000, 1600), { width: 1200, height: 1600, scaled: true });
  assert.deepEqual(fitWithin(800, 600, 1600), { width: 800, height: 600, scaled: false });
  assert.equal(fitWithin(0, 0, 1600).scaled, false);
});
