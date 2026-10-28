/* ASOLAR v2, etap 4b: dostawy WZ, stan materiałów, meldunki (także offline). */
import "fake-indexeddb/auto";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Deliveries, Worklogs } from "../src/Logistics";
import { allItems, flushQueue, resetOfflineStore } from "../src/offline";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 6, name: "Farma Test", archived: false };
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const user = { id: 1, full_name: "Kierownik Budowy" };
const notify = vi.fn();
const PURLIN = "lt1|j60|szt.";

let server, offline;
const setOnline = value => { offline = !value; Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => !offline }); };

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar2_token", "token");
  await resetOfflineStore();
  notify.mockClear();
  setOnline(true);
  server = {
    calls: [],
    materials: [{ key: PURLIN, name: "Purlin", code: "LT1", spec: "J60", unit: "szt.", required: 60 }, { key: "u bolt|m10|szt.", name: "U bolt", code: "", spec: "M10", unit: "szt.", required: 120 }],
    stock: { items: [
      { key: PURLIN, name: "Purlin", code: "LT1", spec: "J60", unit: "szt.", required: 60, delivered: 40, damaged: 2, available: 38, balance: -22, completion_pct: 63.3, status: "brak" },
      { key: "u bolt|m10|szt.", name: "U bolt", code: "", spec: "M10", unit: "szt.", required: 120, delivered: 120, damaged: 0, available: 120, balance: 0, completion_pct: 100, status: "komplet" },
    ], summary: { required_items: 2, complete_items: 1, missing_items: 1, deliveries: 1 } },
    deliveries: [{ id: 3, delivery_date: "2026-10-20", wz_number: "WZ/1", supplier: "Huta", note: "", created_by: "Jan", updated_by: null, items: [{ material_key: PURLIN, name: "Purlin", spec: "J60", unit: "szt.", quantity_received: 40, quantity_damaged: 2 }] }],
    worklogs: [],
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    if (offline) throw new TypeError("Failed to fetch");
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body instanceof FormData ? options.body : options.body ? JSON.parse(options.body) : null });
    if (path.endsWith("/materials")) return json(server.materials);
    if (path.endsWith("/stock")) return json(server.stock);
    if (path.endsWith("/deliveries") && method === "GET") return json(server.deliveries);
    if (path.endsWith("/worklogs") && method === "GET") return json(server.worklogs);
    if (path.endsWith("/worklogs") && method === "POST") return json({ id: 77 });
    if (path.endsWith("/tables")) return json([{ id: 1, code: "T-1" }]);
    return json({ id: 5, ok: true });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const writes = () => server.calls.filter(call => call.method !== "GET");
const show = node => render(<DialogProvider>{node}</DialogProvider>);

describe("dostawy WZ i magazyn", () => {
  it("pokazuje stan z brakami i filtrem „tylko braki”", async () => {
    show(<Deliveries project={project} access={manager} notify={notify} />);
    const table = await screen.findByTestId("stock-table");
    expect(within(table).getByText("-22")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("tylko braki"));
    expect(within(screen.getByTestId("stock-table")).queryByText("U bolt")).toBeNull();
  });

  it("przyjmuje WZ z client_id; brygadzista nie edytuje", async () => {
    show(<Deliveries project={project} access={foreman} notify={notify} />);
    await screen.findByTestId("wz-entry");
    expect(screen.queryByText("Edytuj")).toBeNull();
    fireEvent.change(screen.getByLabelText("Numer WZ"), { target: { value: " WZ/2 " } });
    fireEvent.change(screen.getByLabelText("Materiał 1"), { target: { value: PURLIN } });
    fireEvent.change(screen.getByLabelText("Dostarczono 1"), { target: { value: "20" } });
    fireEvent.click(screen.getByText("Przyjmij dostawę"));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const [call] = writes();
    expect(call.path).toBe("/api/projects/6/deliveries");
    expect(call.body).toMatchObject({ wz_number: "WZ/2", items: [{ material_key: PURLIN, quantity_received: 20, quantity_damaged: 0 }] });
    expect(call.body.client_id).toMatch(/^wz-/);
  });

  it("kierownik edytuje WZ (Esc anuluje) i usuwa z potwierdzeniem", async () => {
    show(<Deliveries project={project} access={manager} notify={notify} />);
    const entry = await screen.findByTestId("wz-entry");
    fireEvent.click(within(entry).getByText("Edytuj"));
    expect(await screen.findByText("Edycja WZ WZ/1")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Edycja WZ WZ/1")).toBeNull());
    fireEvent.click(within(entry).getByText("Edytuj"));
    fireEvent.change(screen.getByLabelText("Dostarczono 1"), { target: { value: "42" } });
    fireEvent.click(screen.getByText("Zapisz WZ"));
    await waitFor(() => expect(writes()[0]).toMatchObject({ path: "/api/projects/6/deliveries/3", method: "PUT", body: { items: [{ material_key: PURLIN, quantity_received: 42, quantity_damaged: 2 }] } }));
    fireEvent.click(within(entry).getByText("Usuń"));
    fireEvent.click(await screen.findByText("Usuń WZ"));
    await waitFor(() => expect(writes()[1]).toMatchObject({ path: "/api/projects/6/deliveries/3", method: "DELETE" }));
  });
});

describe("meldunki", () => {
  it("offline: meldunek i zdjęcie czekają w kolejce; zdjęcie wysyła się po client_id meldunku", async () => {
    show(<Worklogs project={project} access={foreman} user={user} notify={notify} />);
    await screen.findByText("Brak meldunków.");
    setOnline(false);
    fireEvent.change(screen.getByLabelText("Brygada"), { target: { value: "Brygada A" } });
    fireEvent.change(screen.getByLabelText("Wykonane prace"), { target: { value: "Montaż płatwi" } });
    fireEvent.change(screen.getByLabelText("Zdjęcia meldunku"), { target: { files: [new File([new Uint8Array([1])], "f.jpg", { type: "image/jpeg" })] } });
    fireEvent.click(screen.getByText("Wyślij meldunek"));
    expect(await screen.findByText("czeka na wysłanie")).toBeTruthy();
    const items = await allItems();
    expect(items.map(item => item.kind)).toEqual(["json", "photo"]);
    expect(items[1].path).toBe(`/api/projects/6/worklogs/by-client/${items[0].body.client_id}/photos`);
    setOnline(true);
    await flushQueue();
    expect(writes().map(call => call.path)).toEqual(["/api/projects/6/worklogs", `/api/projects/6/worklogs/by-client/${items[0].body.client_id}/photos`]);
  });

  it("online: liczy roboczogodziny i wysyła zdjęcia do utworzonego meldunku", async () => {
    show(<Worklogs project={project} access={manager} user={user} notify={notify} />);
    await screen.findByText("Brak meldunków.");
    fireEvent.change(screen.getByLabelText("Brygada"), { target: { value: "B" } });
    fireEvent.change(screen.getByLabelText("Wykonane prace"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Osoby"), { target: { value: "4" } });
    expect(screen.getByText("Roboczogodziny: 32 rbh")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Zdjęcia meldunku"), { target: { files: [new File([new Uint8Array([1])], "f.jpg", { type: "image/jpeg" })] } });
    fireEvent.click(screen.getByText("Wyślij meldunek"));
    await waitFor(() => expect(writes().map(call => call.path)).toEqual(["/api/projects/6/worklogs", "/api/projects/6/worklogs/77/photos"]));
    expect(writes()[0].body).toMatchObject({ team: "B", people: 4, hours: 8, table_id: null });
  });
});
