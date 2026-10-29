/* „Strefy i rzędy” jak w v1: strefa → rzędy z zakresu → warianty tej budowy; widok operacyjny. */
import "fake-indexeddb/auto";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ZonesAndRows from "../src/Zones";
import { resetOfflineStore } from "../src/offline";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 5, name: "Farma Test", archived: false };
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const user = { id: 1, full_name: "Kierownik Budowy" };
const notify = vi.fn();
const table = (id, number, extra = {}) => ({ id, code: `A-${number}`, prefix: "A", number, zone_id: 1, row_id: null, structure_type_id: null, built: false, qc_checked: false, notes: 0, photos: 0, ...extra });

let server;
beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar2_token", "t");
  await resetOfflineStore();
  notify.mockClear();
  server = {
    calls: [],
    zones: [{ id: 1, name: "Strefa A", description: "północ", stats: { total: 4, built: 1, qc: 0 } }, { id: 2, name: "Strefa B", description: "", stats: { total: 0, built: 0, qc: 0 } }],
    types: [{ id: 7, code: "1x28", modules: 28 }, { id: 8, code: "1x56+1x42", modules: 98 }],
    tables: [table(10, 1, { structure_type_id: 7, built: true }), table(11, 2, { structure_type_id: 7 }), table(12, 3), table(13, 4)],
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body ? JSON.parse(options.body) : null });
    if (path.endsWith("/zones") && method === "GET") return json(server.zones);
    if (path.endsWith("/zones") && method === "POST") return json({ id: 3, name: JSON.parse(options.body).name, description: "", stats: { total: 0, built: 0, qc: 0 } });
    if (path.endsWith("/types") && method === "GET") return json(server.types);
    if (path.endsWith("/tables") && method === "GET") return json(server.tables);
    if (path.endsWith("/tables/range")) return json({ added: 50, skipped: 0 });
    if (path.endsWith("/tables/assign")) return json({ updated: JSON.parse(options.body).ids.length });
    if (path.endsWith("/protocol")) return new Response("%PDF", { headers: { "Content-Type": "application/pdf" } });
    if (/\/tables\/\d+\/(notes|photos)$/.test(path)) return json([]);
    return json({ ok: true, id: 9 });
  }));
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const writes = () => server.calls.filter(call => call.method !== "GET");
const show = (access = manager, tab = "strefy", navigate = vi.fn()) => render(<DialogProvider><ZonesAndRows project={project} access={access} user={user} notify={notify} navigate={navigate} tab={tab} /></DialogProvider>);

describe("konfiguracja stref (jak w v1)", () => {
  it("przewodnik 3 kroków, warianty budowy, strefy z postępem i tabela rzędów", async () => {
    show();
    expect(await screen.findByText("1. Utwórz strefę")).toBeTruthy();
    expect(screen.getByText("3. Przypisz warianty")).toBeTruthy();
    expect(screen.getAllByTestId("variant-chip").map(chip => chip.textContent)).toEqual([expect.stringContaining("1x28"), expect.stringContaining("1x56+1x42")]);
    expect(screen.getByLabelText("Usuń wariant 1x28").disabled).toBe(true);   // przypisany do rzędów
    expect(screen.getByLabelText("Usuń wariant 1x56+1x42").disabled).toBe(false);
    const rows = await screen.findByTestId("zone-rows");
    expect(within(rows).getAllByRole("row")).toHaveLength(5);
    expect(screen.getByText("bez wariantu")).toBeTruthy();
  });

  it("krok 1: nowa strefa; krok 3: własny wariant (bez listy w kodzie)", async () => {
    show();
    await screen.findByTestId("zone-rows");
    const zoneForm = screen.getByRole("form", { name: "Nowa strefa" });
    fireEvent.change(within(zoneForm).getByLabelText("Nazwa nowej strefy"), { target: { value: "Strefa C" } });
    fireEvent.change(within(zoneForm).getByLabelText("Opis nowej strefy"), { target: { value: "wschód" } });
    fireEvent.click(within(zoneForm).getByText("Utwórz strefę"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/5/zones", method: "POST", body: { name: "Strefa C", description: "wschód" } }));
    const variantForm = screen.getByRole("form", { name: "Nowy wariant" });
    fireEvent.change(within(variantForm).getByLabelText("Oznaczenie wariantu"), { target: { value: "2x13" } });
    fireEvent.click(within(variantForm).getByText("+ Dodaj wariant"));
    await waitFor(() => expect(writes()[1]).toEqual({ path: "/api/projects/5/types", method: "POST", body: { code: "2x13", modules: 0 } }));
  });

  it("krok 2: rzędy z zakresu w strefie (prefiks i numer podpowiedziane); krok 3: wariant dla zakresu", async () => {
    show();
    await screen.findByTestId("zone-rows");
    const addForm = screen.getByRole("form", { name: "Dodaj rzędy" });
    expect(within(addForm).getByLabelText("Prefiks").placeholder).toBe("A");
    expect(within(addForm).getByLabelText("Od").placeholder).toBe("5");
    fireEvent.change(within(addForm).getByLabelText("Do"), { target: { value: "54" } });
    fireEvent.change(within(addForm).getByLabelText("Wariant"), { target: { value: "8" } });
    fireEvent.click(within(addForm).getByText("Dodaj rzędy A-5…A-54"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/5/tables/range", method: "POST", body: { prefix: "A", first: 5, last: 54, zone_id: 1, structure_type_id: 8 } }));
    const assignForm = screen.getByRole("form", { name: "Przypisz wariant" });
    fireEvent.change(within(assignForm).getByLabelText("Od rzędu"), { target: { value: "2" } });
    fireEvent.change(within(assignForm).getByLabelText("Do rzędu"), { target: { value: "4" } });
    fireEvent.change(within(assignForm).getByLabelText("Wariant"), { target: { value: "8" } });
    fireEvent.click(within(assignForm).getByText("Przypisz A-2…A-4"));
    await waitFor(() => expect(writes()[1]).toEqual({ path: "/api/projects/5/tables/assign", method: "POST", body: { ids: [11, 12, 13], structure_type_id: 8 } }));
  });

  it("wariant pojedynczego rzędu w tabeli, pamięć rzędu (notatki/zdjęcia), protokół, usunięcie strefy", async () => {
    show();
    const rows = await screen.findByTestId("zone-rows");
    fireEvent.change(within(rows).getByLabelText("Wariant A-3"), { target: { value: "7" } });
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/5/tables/assign", method: "POST", body: { ids: [12], structure_type_id: 7 } }));
    fireEvent.click(within(rows).getByText("A-2"));
    expect(await screen.findByRole("dialog", { name: "Stół A-2" })).toBeTruthy();
    fireEvent.click(screen.getByText("Zamknij"));
    fireEvent.click(screen.getByText("Protokół PDF"));
    await waitFor(() => expect(server.calls.some(call => call.path === "/api/projects/5/zones/1/protocol")).toBe(true));
    fireEvent.click(screen.getByText("Usuń strefę"));
    expect(await screen.findByText(/razem z 4 rzędami/)).toBeTruthy();
    fireEvent.click(screen.getAllByText("Usuń strefę").at(-1));
    await waitFor(() => expect(writes().at(-1)).toEqual({ path: "/api/projects/5/zones/1?with_tables=true", method: "DELETE", body: null }));
  });

  it("brygadzista: podgląd bez formularzy; przełącznik widoków prowadzi do rzędów operacyjnych", async () => {
    const navigate = vi.fn();
    show(foreman, "strefy", navigate);
    await screen.findByTestId("zone-rows");
    expect(screen.queryByRole("form", { name: "Dodaj rzędy" })).toBeNull();
    expect(screen.queryByText("Usuń strefę")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Rzędy operacyjne" }));
    expect(navigate).toHaveBeenCalledWith("#/p/5/postep");
  });

  it("rzędy operacyjne: status montażu z v1 (także offline)", async () => {
    show(foreman, "postep");
    const rows = await screen.findAllByTestId("field-row");
    expect(rows).toHaveLength(4);
    fireEvent.click(within(rows[1]).getByText("Zamontowany"));
    await waitFor(() => expect(writes()[0]).toMatchObject({ path: "/api/projects/5/tables/11/progress", method: "PATCH", body: { built: true } }));
  });
});
