/* ASOLAR v2, etap 3: konstrukcje i BOM, stoły i rzędy, zapotrzebowanie materiałów. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Constructions, Requirements, Tables } from "../src/Structure";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 3, name: "Farma Test", archived: false, stats: {} };
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const notify = vi.fn();

let server;
beforeEach(() => {
  notify.mockClear();
  server = {
    calls: [],
    tables: [
      { id: 1, code: "T-1", zone_id: 5, row_id: null, structure_type_id: 9 },
      { id: 2, code: "T-2", zone_id: null, row_id: null, structure_type_id: null },
      { id: 3, code: "T-3", zone_id: null, row_id: null, structure_type_id: null },
    ],
    types: [{ id: 9, code: "1x42", modules: 42, posts_per_table: null, description: "", from_pdf: true, tables: 1, bom: [{ id: 70, name: "Purlin 1", code: "LT1-1450", spec: "J60x30x1.8", quantity: 44, unit: "szt.", from_pdf: true }] }],
    zones: [{ id: 5, name: "Strefa A" }],
    rows: [],
    requirements: {
      types: [{ type_id: 9, code: "1x42", modules: 42, tables: 1, posts_per_table: null, modules_total: 42, bom_missing: false, lines: [] }],
      totals: [{ name: "Purlin 1", code: "LT1-1450", spec: "J60x30x1.8", unit: "szt.", total: 44, types: ["1x42"] }],
      tables_total: 3, tables_without_type: 2, modules_total: 42, posts_total: 0, posts_complete: false,
      warnings: ["2 stołów nie ma przypisanego typu konstrukcji — ich materiały nie są policzone (wymaga potwierdzenia)."],
    },
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body ? JSON.parse(options.body) : null });
    if (path.endsWith("/tables") && method === "GET") return json(server.tables);
    if (path.endsWith("/zones")) return json(server.zones);
    if (path.endsWith("/rows") && method === "GET") return json(server.rows);
    if (path.endsWith("/types") && method === "GET") return json(server.types);
    if (path.endsWith("/catalog")) return json({ items: [{ id: 1, kind: "tool", name: "Klucz dynamometryczny", code: "", spec: "" }], torques: [{ id: 1, bolt: "M10", min_nm: 25, max_nm: 32, context: "" }] });
    if (path.includes("/requirements")) return json(server.requirements);
    if (path.endsWith("/tables/assign")) return json({ updated: 2 });
    if (path.endsWith("/tables/range")) return json({ added: 5, skipped: 0 });
    return json({ ok: true });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const show = node => render(<DialogProvider>{node}</DialogProvider>);
const writes = () => server.calls.filter(call => call.method !== "GET");

describe("stoły i rzędy", () => {
  it("filtruje stoły bez typu, zaznacza i przypisuje typ zbiorczo", async () => {
    show(<Tables project={project} access={manager} notify={notify} />);
    await screen.findByText("T-1");
    fireEvent.change(screen.getByLabelText("Filtr typu"), { target: { value: "0" } });
    expect(screen.getAllByTestId("table-chip").map(chip => within(chip).getByText(/^T-/).textContent)).toEqual(["T-2", "T-3"]);
    fireEvent.click(screen.getByLabelText("Zaznacz widoczne"));
    expect(screen.getByText("Zaznaczono: 2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Przypisz typ"), { target: { value: "9" } });
    fireEvent.click(screen.getByText("Przypisz"));
    await waitFor(() => expect(writes()).toEqual([{ path: "/api/projects/3/tables/assign", method: "POST", body: { ids: [2, 3], structure_type_id: 9 } }]));
    expect(notify).toHaveBeenCalledWith("Zaktualizowano 2 stołów");
  });

  it("Esc czyści zaznaczenie; ręczne dodanie zakresu", async () => {
    show(<Tables project={project} access={manager} notify={notify} />);
    fireEvent.click((await screen.findAllByTestId("table-chip"))[0]);
    expect(screen.getByText("Zaznaczono: 1")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Zaznaczono: 1")).toBeNull());
    fireEvent.change(screen.getByLabelText("Od"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Do"), { target: { value: "14" } });
    fireEvent.click(screen.getByText("Dodaj zakres"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/3/tables/range", method: "POST", body: { prefix: "T", first: 10, last: 14 } }));
  });

  it("brygadzista tylko ogląda", async () => {
    show(<Tables project={project} access={foreman} notify={notify} />);
    const chips = await screen.findAllByTestId("table-chip");
    expect(chips.every(chip => chip.disabled)).toBe(true);
    expect(screen.queryByText("Dodaj zakres")).toBeNull();
    expect(screen.queryByLabelText("Zaznacz widoczne")).toBeNull();
  });
});

describe("konstrukcje i BOM", () => {
  it("pokazuje brak liczby słupów jako „wymaga potwierdzenia” i zapisuje ją", async () => {
    show(<Constructions project={project} access={manager} notify={notify} />);
    const card = await screen.findByTestId("type-1x42");
    const posts = within(card).getByLabelText("Słupy na stół 1x42");
    expect(posts.placeholder).toBe("wymaga potwierdzenia");
    fireEvent.change(posts, { target: { value: "7" } });
    fireEvent.blur(posts);
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/3/types/9", method: "PATCH", body: { posts_per_table: 7 } }));
    expect(await screen.findByText("Klucz dynamometryczny")).toBeTruthy();
  });

  it("edytuje ilość pozycji BOM i dodaje nową pozycję", async () => {
    show(<Constructions project={project} access={manager} notify={notify} />);
    const card = await screen.findByTestId("type-1x42");
    fireEvent.click(within(card).getByText("Edytuj"));
    fireEvent.change(within(card).getByLabelText("Ilość na stół"), { target: { value: "46" } });
    fireEvent.click(within(card).getByText("Zapisz"));
    await waitFor(() => expect(writes()[0].body).toEqual({ name: "Purlin 1", code: "LT1-1450", spec: "J60x30x1.8", quantity: 46, unit: "szt." }));
    fireEvent.change(within(card).getByLabelText("Nowa pozycja — nazwa"), { target: { value: "Clamp" } });
    fireEvent.change(within(card).getByLabelText("Nowa pozycja — ilość na stół"), { target: { value: "88" } });
    fireEvent.click(within(card).getByText("Dodaj pozycję"));
    await waitFor(() => expect(writes()[1]).toEqual({ path: "/api/projects/3/types/9/bom", method: "POST", body: { name: "Clamp", code: "", spec: "", quantity: 88, unit: "szt." } }));
  });
});

describe("zapotrzebowanie", () => {
  it("pokazuje ostrzeżenia, sumy i liczy dla wybranej strefy", async () => {
    show(<Requirements project={project} />);
    expect(await screen.findByText(/2 stołów nie ma przypisanego typu/)).toBeTruthy();
    const table = screen.getByTestId("requirements-table");
    expect(within(table).getByText("Purlin 1")).toBeTruthy();
    expect(within(table).getByText("44")).toBeTruthy();
    expect(screen.getByText(/\+ wymaga potwierdzenia/)).toBeTruthy();
    await screen.findByRole("option", { name: "Strefa A" });
    fireEvent.change(screen.getByLabelText("Zakres zapotrzebowania"), { target: { value: "5" } });
    await waitFor(() => expect(server.calls.some(call => call.path === "/api/projects/3/requirements?zone_id=5")).toBe(true));
  });
});
