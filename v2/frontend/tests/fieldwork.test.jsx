/* ASOLAR v2, etap 4a: praca w terenie i kolejka offline. */
import "fake-indexeddb/auto";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Fieldwork from "../src/Fieldwork";
import { allItems, cachedGet, flushQueue, mutate, resetOfflineStore, savePhotos } from "../src/offline";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 4, name: "Farma Test", archived: false };
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const user = { id: 1, full_name: "Kierownik Budowy" };
const notify = vi.fn();
const table = (id, code, extra = {}) => ({ id, code, zone_id: null, row_id: null, structure_type_id: null, built: false, qc_checked: false, notes: 0, photos: 0, ...extra });

let server, offline;
function setOnline(value) {
  offline = !value;
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => !offline });
}

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar2_token", "token");
  await resetOfflineStore();
  notify.mockClear();
  setOnline(true);
  server = { calls: [], tables: [table(1, "T-1"), table(2, "T-2", { built: true }), table(3, "T-3", { built: true, qc_checked: true })], notes: [] };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    if (offline) throw new TypeError("Failed to fetch");
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body instanceof FormData ? options.body : options.body ? JSON.parse(options.body) : null });
    if (path.endsWith("/tables")) return json(server.tables);
    if (/\/tables\/\d+\/notes$/.test(path) && method === "GET") return json(server.notes);
    if (/\/tables\/\d+\/photos$/.test(path) && method === "GET") return json([]);
    if (/\/(zones|rows|types)$/.test(path)) return json([]);
    return json({ ok: true });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const writes = () => server.calls.filter(call => call.method !== "GET");
const show = (access = manager) => render(<DialogProvider><Fieldwork project={project} access={access} user={user} notify={notify} /></DialogProvider>);

describe("kolejka offline", () => {
  it("bez zasięgu zapisuje zmianę z czasem czynności i wysyła ją po powrocie sieci", async () => {
    setOnline(false);
    expect(await mutate("/api/projects/4/tables/1/progress", "PATCH", { built: true })).toEqual({ queued: true });
    const [item] = await allItems();
    expect(item.label).toBe("Postęp stołu");
    expect(item.body.client_time).toBeTruthy();
    setOnline(true);
    expect(await flushQueue()).toBe(1);
    expect(writes()).toEqual([{ path: "/api/projects/4/tables/1/progress", method: "PATCH", body: { built: true, client_time: item.body.client_time } }]);
    expect(await allItems()).toEqual([]);
  });

  it("zdjęcie bez zasięgu czeka w IndexedDB z client_id; zerwane połączenie też trafia do kolejki", async () => {
    setOnline(false);
    const file = new File([new Uint8Array([1, 2, 3])], "a.jpg", { type: "image/jpeg" });
    expect(await savePhotos("/api/projects/4/tables/1/photos", [file])).toEqual({ sent: 0, queued: 1 });
    const [photo] = await allItems();
    expect(photo.clientId).toMatch(/^photo-/);
    expect(photo.data.byteLength).toBe(3);
    setOnline(true);
    await flushQueue();
    const upload = writes()[0];
    expect(upload.body.get("client_id")).toBe(photo.clientId);
  });

  it("usunięcie, którego serwer już nie zna (404), jest uznane za wykonane; inne błędy zostają oznaczone", async () => {
    setOnline(false);
    await mutate("/api/projects/4/tables/1/notes/9", "DELETE");
    await mutate("/api/projects/4/tables/1/notes/8", "PATCH", { text: "x" });
    setOnline(true);
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Notatka nie istnieje" }, 404)));
    await flushQueue();
    const left = await allItems();
    expect(left).toHaveLength(1);
    expect(left[0]).toMatchObject({ method: "PATCH", failed: true, lastError: "Notatka nie istnieje" });
  });

  it("cachedGet pokazuje ostatnią kopię, gdy brak zasięgu", async () => {
    expect(await cachedGet("/api/projects/4/tables")).toHaveLength(3);
    setOnline(false);
    expect(await cachedGet("/api/projects/4/tables")).toHaveLength(3);
    await expect(cachedGet("/api/projects/4/zones")).rejects.toThrow("Brak połączenia");
  });
});

describe("zakładka Postęp prac", () => {
  it("brygadzista oznacza montaż; nie widzi przycisku odbioru", async () => {
    show(foreman);
    const row = (await screen.findAllByTestId("field-row"))[0];
    expect(within(row).queryByText("Odbiór QC")).toBeNull();
    fireEvent.click(within(row).getByText("Zamontowany"));
    await waitFor(() => expect(writes()[0]).toMatchObject({ path: "/api/projects/4/tables/1/progress", method: "PATCH", body: { built: true } }));
  });

  it("bez zasięgu zmiana jest widoczna od razu jako „czeka na wysłanie”", async () => {
    show();
    const rows = await screen.findAllByTestId("field-row");
    setOnline(false);
    fireEvent.click(within(rows[0]).getByText("Zamontowany"));
    expect(await within(rows[0]).findByText("czeka na wysłanie")).toBeTruthy();
    expect(within(rows[0]).getByText("✓ Zamontowany")).toBeTruthy();
    expect(notify).toHaveBeenCalledWith("Brak zasięgu — T-1 zapisany na urządzeniu");
  });

  it("cofnięcie montażu odebranego stołu wymaga potwierdzenia", async () => {
    show();
    const rows = await screen.findAllByTestId("field-row");
    fireEvent.click(within(rows[2]).getByText("✓ Zamontowany"));
    expect(await screen.findByText(/usunie również odbiór/)).toBeTruthy();
    fireEvent.click(screen.getByText("Cofnij montaż"));
    await waitFor(() => expect(writes()[0].body).toMatchObject({ built: false }));
  });

  it("filtr stanu i notatka dodana offline w panelu stołu", async () => {
    show();
    await screen.findAllByTestId("field-row");
    fireEvent.change(screen.getByLabelText("Stan"), { target: { value: "todo" } });
    expect(screen.getAllByTestId("field-row")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("Szczegóły stołu T-1"));
    const panel = await screen.findByRole("dialog", { name: "Stół T-1" });
    await within(panel).findByText("Brak notatek.");
    setOnline(false);
    fireEvent.change(within(panel).getByLabelText("Nowa notatka"), { target: { value: "Brak śruby" } });
    fireEvent.click(within(panel).getByText("Dodaj notatkę"));
    expect(await within(panel).findByText("Brak śruby")).toBeTruthy();
    expect(await within(panel).findByText("czeka na wysłanie")).toBeTruthy();
    expect(within(panel).getByTestId("note").textContent).toContain("Brak śruby");
    const [queued] = await allItems();
    expect(queued.body.client_id).toMatch(/^note-/);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Stół T-1" })).toBeNull());
  });
});
