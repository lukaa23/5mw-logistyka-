import test from "node:test";
import assert from "node:assert/strict";
import { canRenderPdf, createLatestGuard, createPdfLoader, findPlan, formatPlanDate, formatSize, nextZoom, normalizePlans, pdfViewerHash, resolveSelection, resourceKey } from "../src/planimetria.js";

const plan = (id, extra = {}) => ({ id, title: `Plan ${id}`, filename: `plan-${id}.pdf`, size: 2048, uploaded_at: "2026-10-01T08:00:00", uploaded_by: "Kierownik", file_url: `/api/documents/${id}/file`, approved_source: false, deletable: true, ...extra });

function harness() {
  const pending = new Map();
  const revoked = [];
  const created = [];
  const states = [];
  let counter = 0;
  const loader = createPdfLoader({
    fetchBlob: url => new Promise((resolve, reject) => { pending.set(url, { resolve, reject }); }),
    createObjectURL: blob => { counter += 1; const url = `blob:test/${counter}-${blob.name}`; created.push(url); return url; },
    revokeObjectURL: url => revoked.push(url),
    onChange: state => states.push(state),
  });
  const settle = (url, blob) => pending.get(url).resolve(blob);
  const fail = (url, message) => pending.get(url).reject(new Error(message));
  return { loader, settle, fail, revoked, created, states };
}

test("normalizePlans odrzuca null, nie-tablice i niepoprawne rekordy", () => {
  assert.deepEqual(normalizePlans(null), []);
  assert.deepEqual(normalizePlans(undefined), []);
  assert.deepEqual(normalizePlans({}), []);
  assert.deepEqual(normalizePlans([]), []);
  const result = normalizePlans([null, undefined, 5, "x", {}, { id: null }, { id: {} }, { title: "bez id" }, plan(1), plan(1), plan(2)]);
  assert.deepEqual(result.map(item => item.id), [1, 2]);
});

test("normalizePlans uzupełnia brakujący tytuł i neutralizuje błędną datę", () => {
  const [noTitle] = normalizePlans([{ id: 7, filename: "uklad.pdf", uploaded_at: "to-nie-data" }]);
  assert.equal(noTitle.title, "uklad.pdf");
  assert.equal(noTitle.uploaded_at, null);
  assert.equal(formatPlanDate(noTitle.uploaded_at), "—");
  assert.equal(formatPlanDate("32.13.2026"), "—");
  assert.notEqual(formatPlanDate("2026-10-01T08:00:00"), "—");
  const [bare] = normalizePlans([{ id: 9 }]);
  assert.equal(bare.title, "Plan 9");
  assert.equal(bare.file_url, "/api/documents/9/file");
  const [blank] = normalizePlans([{ id: 3, title: "   ", filename: "" }]);
  assert.equal(blank.title, "Plan 3");
});

test("normalizePlans nie pozwala usuwać zatwierdzonych źródeł", () => {
  const [source] = normalizePlans([plan(1, { approved_source: true, deletable: true })]);
  assert.equal(source.deletable, false);
});

test("formatSize obsługuje brak i błędne wartości", () => {
  assert.equal(formatSize(undefined), "—");
  assert.equal(formatSize("abc"), "—");
  assert.equal(formatSize(512), "1 KB");
  assert.equal(formatSize(5 * 1024 * 1024), "5.0 MB");
});

test("odświeżenie synchronizacji zachowuje wybór, a PDF nie jest ładowany ponownie", async () => {
  const plans = normalizePlans([plan(1), plan(2)]);
  let selected = resolveSelection(plans, null);
  assert.equal(selected, 1);
  selected = 2;
  const { loader, settle } = harness();
  const first = loader.load(10, findPlan(plans, selected));
  settle("/api/documents/2/file", { name: "a" });
  await first;
  assert.equal(canRenderPdf(loader.getState(), 10, findPlan(plans, selected)), true);
  // kolejne odświeżenia listy (WebSocket / co 15 s) dają nowe obiekty, ale ten sam klucz
  for (let i = 0; i < 3; i += 1) {
    const refreshed = normalizePlans([plan(1), plan(2)]);
    selected = resolveSelection(refreshed, selected);
    assert.equal(selected, 2);
    assert.equal(resourceKey(10, findPlan(refreshed, selected)), loader.getState().key);
  }
});

test("usunięcie bieżącego dokumentu z listy wybiera inny plan albo nic i nie renderuje starego PDF", async () => {
  const { loader, settle, revoked } = harness();
  const first = loader.load(1, plan(5));
  settle("/api/documents/5/file", { name: "a" });
  await first;
  const stateBefore = loader.getState();
  assert.equal(canRenderPdf(stateBefore, 1, plan(5)), true);
  assert.equal(resolveSelection(normalizePlans([plan(6)]), 5), 6);
  assert.equal(resolveSelection([], 5), null);
  // plan zniknął: komponent nie ma wybranego planu, więc ramka nie może się wyrenderować mimo starego adresu
  assert.equal(canRenderPdf(stateBefore, 1, undefined), false);
  await loader.load(1, null);
  assert.equal(loader.getState().status, "idle");
  assert.deepEqual(revoked, [stateBefore.url]);
});

test("stary PDF nie pojawia się pod tytułem nowego dokumentu", async () => {
  const { loader, settle } = harness();
  const first = loader.load(1, plan(1));
  settle("/api/documents/1/file", { name: "a" });
  await first;
  const oldState = loader.getState();
  // użytkownik wybiera plan 2, ale jego PDF jeszcze się nie pobrał
  assert.equal(canRenderPdf(oldState, 1, plan(2)), false);
  const second = loader.load(1, plan(2));
  assert.equal(loader.getState().status, "loading");
  assert.equal(canRenderPdf(loader.getState(), 1, plan(2)), false);
  assert.equal(canRenderPdf(loader.getState(), 1, plan(1)), false);
  settle("/api/documents/2/file", { name: "b" });
  await second;
  assert.equal(canRenderPdf(loader.getState(), 1, plan(2)), true);
  assert.equal(canRenderPdf(loader.getState(), 1, plan(1)), false);
});

test("zmiana projektu z tym samym identyfikatorem planu wymaga osobnego zasobu", async () => {
  const { loader, settle } = harness();
  const first = loader.load(1, plan(4));
  settle("/api/documents/4/file", { name: "a" });
  await first;
  assert.equal(canRenderPdf(loader.getState(), 1, plan(4)), true);
  assert.equal(canRenderPdf(loader.getState(), 2, plan(4)), false);
});

test("spóźniona odpowiedź poprzedniego projektu jest ignorowana, a jej blob zwolniony", async () => {
  const { loader, settle, revoked, created } = harness();
  const slow = loader.load(1, plan(1, { file_url: "/api/documents/1/file" }));
  const fast = loader.load(2, plan(2, { file_url: "/api/documents/2/file" }));
  settle("/api/documents/2/file", { name: "projekt2" });
  await fast;
  settle("/api/documents/1/file", { name: "projekt1" });
  await slow;
  const state = loader.getState();
  assert.equal(state.status, "ready");
  assert.equal(state.key, resourceKey(2, plan(2)));
  assert.match(state.url, /projekt2/);
  assert.equal(created.length, 1, "dla spóźnionej odpowiedzi nie powinien powstać adres blob");
  assert.deepEqual(revoked, []);
});

test("zmiana planu w trakcie pobierania ignoruje wcześniejsze żądanie", async () => {
  const { loader, settle } = harness();
  const a = loader.load(1, plan(1));
  const b = loader.load(1, plan(2));
  settle("/api/documents/1/file", { name: "a" });
  await a;
  assert.equal(loader.getState().status, "loading");
  assert.equal(canRenderPdf(loader.getState(), 1, plan(1)), false);
  settle("/api/documents/2/file", { name: "b" });
  await b;
  assert.equal(loader.getState().key, resourceKey(1, plan(2)));
});

test("blob URL jest zwalniany przy zmianie planu i odmontowaniu", async () => {
  const { loader, settle, revoked } = harness();
  const a = loader.load(1, plan(1));
  settle("/api/documents/1/file", { name: "a" });
  await a;
  const firstUrl = loader.getState().url;
  const b = loader.load(1, plan(2));
  assert.deepEqual(revoked, [firstUrl]);
  settle("/api/documents/2/file", { name: "b" });
  await b;
  const secondUrl = loader.getState().url;
  loader.dispose();
  assert.deepEqual(revoked, [firstUrl, secondUrl]);
  assert.equal(loader.getState().status, "idle");
});

test("odpowiedź, która przyszła po odmontowaniu, nie tworzy adresu blob", async () => {
  const { loader, settle, created } = harness();
  const pending = loader.load(1, plan(1));
  loader.dispose();
  settle("/api/documents/1/file", { name: "a" });
  await pending;
  assert.equal(created.length, 0);
  assert.equal(loader.getState().status, "idle");
});

test("błąd pobierania daje stan error z komunikatem zamiast wyjątku", async () => {
  const { loader, fail } = harness();
  const pending = loader.load(1, plan(1));
  fail("/api/documents/1/file", "Błąd 500");
  await assert.doesNotReject(pending);
  assert.equal(loader.getState().status, "error");
  assert.equal(loader.getState().error, "Błąd 500");
  assert.equal(canRenderPdf(loader.getState(), 1, plan(1)), false);
});

test("spóźniony błąd poprzedniego żądania nie nadpisuje aktualnego stanu", async () => {
  const { loader, settle, fail } = harness();
  const old = loader.load(1, plan(1));
  const current = loader.load(1, plan(2));
  settle("/api/documents/2/file", { name: "b" });
  await current;
  fail("/api/documents/1/file", "stary błąd");
  await old;
  assert.equal(loader.getState().status, "ready");
  assert.equal(loader.getState().error, null);
});

test("pusta odpowiedź serwera daje komunikat błędu", async () => {
  const { loader, settle } = harness();
  const pending = loader.load(1, plan(1));
  settle("/api/documents/1/file", null);
  await pending;
  assert.equal(loader.getState().status, "error");
});

test("strażnik zachowuje tylko ostatnią odpowiedź listy planów", () => {
  const guard = createLatestGuard();
  const first = guard.begin();
  const second = guard.begin();
  assert.equal(guard.isCurrent(first), false);
  assert.equal(guard.isCurrent(second), true);
  guard.invalidate();
  assert.equal(guard.isCurrent(second), false);
});

test("canRenderPdf nigdy nie zgłasza wyjątku dla brakujących danych", () => {
  assert.equal(canRenderPdf(undefined, 1, undefined), false);
  assert.equal(canRenderPdf(null, 1, plan(1)), false);
  assert.equal(canRenderPdf({ status: "ready", url: "blob:x", key: "inny" }, 1, plan(1)), false);
  assert.equal(findPlan(undefined, 1), undefined);
  assert.equal(findPlan([], null), undefined);
});

test("przybliżanie i fragment adresu dla wbudowanej przeglądarki PDF", () => {
  assert.equal(nextZoom(100, 1), 125);
  assert.equal(nextZoom(100, -1), 75);
  assert.equal(nextZoom(400, 1), 400);
  assert.equal(nextZoom(50, -1), 50);
  assert.equal(nextZoom(333, 1), 125);
  assert.equal(pdfViewerHash(150), "#zoom=150&toolbar=1");
  assert.equal(pdfViewerHash("fit"), "#view=Fit&toolbar=1");
});
