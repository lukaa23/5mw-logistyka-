/* Dostawy na budowę (WZ): stabilny formularz przy odświeżaniu w tle, wyszukiwarka BOM,
 * edycja i usuwanie WZ oraz pełny przepływ dodawania dostawy. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

vi.mock("../src/api", () => ({ cachedGet: vi.fn(), mutate: vi.fn() }));

import { cachedGet, mutate } from "../src/api";
import BomDeliveries, { DELETE_CONFIRMATION, normalize, positionsLabel, searchBom } from "../src/Deliveries";

// Prawdziwy katalog ESET z zatwierdzonej bazy + moduł Jinko (jak w API /bom-delivery-status).
const bom = JSON.parse(readFileSync(resolve(__dirname, "../../project_sources/eset-bom.json"), "utf8"));
const CATALOGUE = [
  ...Object.entries(bom.components).map(([key, value], index) => ({ key, ...value, component_id: index + 1, required: index % 3 === 0 ? 40 : 0 })),
  { key: "MODULE-JINKO-JKM710-735", name: "Moduł PV JKM710-735N-66HL5-BDV", category: "Moduły PV", unit: "szt.", spec: "2384×1303×33 mm; 710–735 W", component_id: 999, required: 504 },
];
const byKey = key => CATALOGUE.find(item => item.key === key);

const manager = { id: 1, role: "kierownik", full_name: "Kierownik Budowy" };
const foreman = { id: 2, role: "brygadzista", full_name: "Brygadzista 1" };
const project = { id: 7, name: "Projekt WZ" };

let server;
function statusPayload() {
  const totals = new Map();
  for (const delivery of server.deliveries) for (const line of delivery.items) {
    const current = totals.get(line.component_id) || { received: 0, damaged: 0 };
    totals.set(line.component_id, { received: current.received + line.quantity_received, damaged: current.damaged + line.quantity_damaged });
  }
  const items = CATALOGUE.map(item => {
    const { received = 0, damaged = 0 } = totals.get(item.component_id) || {};
    const available = received - damaged;
    return { ...item, delivered: received, damaged, available, balance: available - item.required, completion_pct: item.required ? Math.min(100, available / item.required * 100) : 0 };
  });
  return { summary: { catalogue_items: items.length, required_items: items.filter(i => i.required > 0).length, complete_items: 0, missing_items: 0, deliveries_count: server.deliveries.length }, items };
}
function historyPayload() {
  return server.deliveries.map(delivery => ({ ...delivery, items: delivery.items.map(line => { const item = CATALOGUE.find(i => i.component_id === line.component_id); return { ...line, key: item.key, name: item.name, unit: item.unit }; }) }));
}

beforeEach(() => {
  localStorage.clear();
  server = { deliveries: [], nextId: 1 };
  cachedGet.mockImplementation(async path => (path.includes("bom-delivery-status") ? statusPayload() : historyPayload()));
  mutate.mockImplementation(async (path, method, body) => {
    if (method === "POST") { const id = server.nextId++; server.deliveries.unshift({ id, created_by: "Brygadzista 1", ...body }); return { id }; }
    const id = Number(path.split("/").pop());
    if (method === "PUT") { server.deliveries = server.deliveries.map(d => (d.id === id ? { ...d, ...body, updated_by: "Kierownik Budowy", updated_at: "2026-10-17T12:00:00" } : d)); return { id }; }
    if (method === "DELETE") { server.deliveries = server.deliveries.filter(d => d.id !== id); return { ok: true }; }
    throw new Error("unexpected");
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const notify = vi.fn();
async function renderView(props = {}) {
  const view = render(<BomDeliveries project={project} sync={0} notify={notify} user={foreman} {...props} />);
  await screen.findByText("Dodaj dokument WZ");
  return { ...view, rerender: next => view.rerender(<BomDeliveries project={project} sync={0} notify={notify} user={foreman} {...props} {...next} />) };
}
function pickBom(position, query, optionText) {
  const input = screen.getByRole("combobox", { name: `Element BOM, pozycja ${position}` });
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: query } });
  const option = optionText ? within(screen.getByRole("listbox")).getAllByRole("option").find(el => el.textContent.includes(optionText)) : within(screen.getByRole("listbox")).getAllByRole("option")[0];
  fireEvent.mouseDown(option);
  return input;
}
const qtyInput = (kind, position) => screen.getByLabelText(`Ilość ${kind}, pozycja ${position}`);

describe("wyszukiwarka katalogu BOM", () => {
  const names = (query, limit = 40) => searchBom(CATALOGUE, query, limit).map(item => item.name);

  it("znajduje elementy po fragmencie nazwy, kodu i rozmiaru śruby", () => {
    expect(names("M16").length).toBeGreaterThan(0);
    expect(searchBom(CATALOGUE, "M16").every(item => normalize(`${item.key} ${item.name} ${item.spec}`).includes("m16"))).toBe(true);
    const tubes = searchBom(CATALOGUE, "rura");
    expect(tubes.length).toBeGreaterThan(10);
    expect(tubes.every(item => /rur/i.test(`${item.name} ${item.category}`))).toBe(true); // „rura” trafia też w kategorię „Rury”
    expect(names("rura torsyjna C1")[0]).toBe("Rura torsyjna C1");
    expect(searchBom(CATALOGUE, "L-7290")[0].key).toBe("L-7290-2.8");
    expect(searchBom(CATALOGUE, "7290")[0].key).toBe("L-7290-2.8");
    expect(names("Jinko")).toEqual(["Moduł PV JKM710-735N-66HL5-BDV"]);
  });

  it("ignoruje polskie znaki i toleruje jedną literówkę („płatiew”)", () => {
    expect(names("platew")).toContain("Płatew");
    expect(names("płatiew")).toContain("Płatew");
    expect(names("PŁATEW")).toContain("Płatew");
    expect(names("xyzxyz")).toEqual([]);
  });

  it("pusta fraza pokazuje katalog, a pozycje wymagane są wyżej", () => {
    const results = searchBom(CATALOGUE, "", 1000);
    expect(results).toHaveLength(CATALOGUE.length);
    expect(results[0].required).toBeGreaterThan(0);
  });
});

it("liczba pozycji z poprawną odmianą", () => {
  expect([1, 2, 4, 5, 12, 22, 25].map(positionsLabel)).toEqual(["1 pozycja", "2 pozycje", "4 pozycje", "5 pozycji", "12 pozycji", "22 pozycje", "25 pozycji"]);
});

describe("formularz WZ", () => {
  it("odświeżanie w tle (sync co 15 s / WebSocket) nie kasuje wpisanych danych", async () => {
    const view = await renderView();
    fireEvent.change(screen.getByPlaceholderText("np. WZ/2026/001"), { target: { value: "WZ/2026/555" } });
    fireEvent.change(screen.getByLabelText("Dostawca"), { target: { value: "ESET" } });
    pickBom(1, "M16");
    fireEvent.change(qtyInput("dostarczona", 1), { target: { value: "120" } });
    fireEvent.click(screen.getByText("+ Dodaj pozycję WZ"));
    pickBom(2, "Jinko");
    fireEvent.change(qtyInput("dostarczona", 2), { target: { value: "56" } });

    // Kilka cykli synchronizacji: nowe dane z serwera, nowy obiekt katalogu, ponowny render.
    for (const sync of [1, 2, 3]) {
      view.rerender({ sync });
      await waitFor(() => expect(cachedGet).toHaveBeenCalledTimes(2 * (sync + 1)));
    }
    expect(screen.getByPlaceholderText("np. WZ/2026/001").value).toBe("WZ/2026/555");
    expect(screen.getByLabelText("Dostawca").value).toBe("ESET");
    expect(qtyInput("dostarczona", 1).value).toBe("120");
    expect(qtyInput("dostarczona", 2).value).toBe("56");
    expect(screen.getByRole("combobox", { name: "Element BOM, pozycja 2" }).value).toContain("Jinko".replace("Jinko", "Moduł PV"));
    expect(screen.getAllByTestId("wz-line")).toHaveLength(2);
  });

  it("szkic WZ przetrwa przełączenie zakładki (odmontowanie) i jest czyszczony po zapisie", async () => {
    const first = await renderView();
    fireEvent.change(screen.getByPlaceholderText("np. WZ/2026/001"), { target: { value: "WZ/SZKIC" } });
    pickBom(1, "rura torsyjna A1");
    fireEvent.change(qtyInput("dostarczona", 1), { target: { value: "8" } });
    first.unmount();
    await renderView();
    expect(screen.getByText(/Przywrócono niezapisany szkic WZ/)).toBeTruthy();
    expect(screen.getByPlaceholderText("np. WZ/2026/001").value).toBe("WZ/SZKIC");
    expect(qtyInput("dostarczona", 1).value).toBe("8");
    fireEvent.click(screen.getByText("Przyjmij dostawę"));
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    await waitFor(() => expect(localStorage.getItem("asolar_wz_draft:7")).toBeNull());
  });

  it("pełny przepływ: wybór po kodzie/nazwie, ilości, zapis → historia i bilans od razu", async () => {
    await renderView();
    const bolt = searchBom(CATALOGUE, "M16")[0];
    fireEvent.change(screen.getByPlaceholderText("np. WZ/2026/001"), { target: { value: "WZ/2026/001" } });
    const picker = pickBom(1, "M16");
    expect(picker.value).toContain(bolt.key);
    fireEvent.change(qtyInput("dostarczona", 1), { target: { value: "100" } });
    fireEvent.change(qtyInput("uszkodzona", 1), { target: { value: "4" } });
    fireEvent.click(screen.getByText("+ Dodaj pozycję WZ"));
    pickBom(2, "płatiew", "LT1-1450-18");
    fireEvent.change(qtyInput("dostarczona", 2), { target: { value: "30" } });
    fireEvent.click(screen.getByText("Przyjmij dostawę"));

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
    const [path, method, body] = mutate.mock.calls[0];
    expect([path, method]).toEqual(["/api/bom-deliveries", "POST"]);
    expect(body).toMatchObject({ project_id: 7, wz_number: "WZ/2026/001", items: [{ component_id: bolt.component_id, quantity_received: 100, quantity_damaged: 4 }, { component_id: byKey("LT1-1450-18").component_id, quantity_received: 30, quantity_damaged: 0 }] });
    expect(body.client_id).toBeTruthy();

    // Historia i bilans widoczne natychmiast po zapisie (bez czekania na synchronizację).
    await waitFor(() => expect(screen.getByTestId("wz-count").textContent).toBe("1"));
    expect(screen.getByText("WZ WZ/2026/001")).toBeTruthy();
    fireEvent.click(screen.getByText("Pokaż cały katalog", { exact: false }));
    const row = screen.getByTestId(`balance-${bolt.key}`);
    expect(row.textContent).toContain("100");
    expect(row.textContent).toContain("96");
    // Formularz gotowy na kolejny dokument.
    expect(screen.getByPlaceholderText("np. WZ/2026/001").value).toBe("");
    expect(screen.getAllByTestId("wz-line")).toHaveLength(1);
  });

  it("blokuje dwukrotne dodanie tego samego elementu i uszkodzone > dostarczone", async () => {
    await renderView();
    fireEvent.change(screen.getByPlaceholderText("np. WZ/2026/001"), { target: { value: "WZ/BLAD" } });
    pickBom(1, "Jinko");
    fireEvent.change(qtyInput("dostarczona", 1), { target: { value: "5" } });
    fireEvent.change(qtyInput("uszkodzona", 1), { target: { value: "9" } });
    fireEvent.click(screen.getByText("Przyjmij dostawę"));
    expect((await screen.findByRole("alert")).textContent).toContain("nie może przekraczać");

    fireEvent.click(screen.getByText("+ Dodaj pozycję WZ"));
    const second = screen.getByRole("combobox", { name: "Element BOM, pozycja 2" });
    fireEvent.focus(second);
    fireEvent.change(second, { target: { value: "Jinko" } });
    const option = within(screen.getByRole("listbox")).getAllByRole("option")[0];
    expect(option.textContent).toContain("już w tym WZ");
    fireEvent.mouseDown(option);
    expect(second.value).toBe("Jinko"); // nie wybrano duplikatu
    expect(mutate).not.toHaveBeenCalled();
  });

  it("obsługa klawiatury: strzałki i Enter wybierają podpowiedź", async () => {
    await renderView();
    const input = screen.getByRole("combobox", { name: "Element BOM, pozycja 1" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "rura torsyjna" } });
    const options = within(screen.getByRole("listbox")).getAllByRole("option");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.value).toContain(options[1].querySelector("strong").textContent);
  });
});

describe("edycja i usuwanie WZ", () => {
  async function withOneDelivery(user) {
    server.deliveries = [{ id: 41, delivery_date: "2026-10-16", wz_number: "WZ/41", supplier: "ESET", note: "", created_by: "Brygadzista 1", items: [{ component_id: byKey("LT1-1450-18").component_id, quantity_received: 50, quantity_damaged: 0 }] }];
    server.nextId = 42;
    await renderView({ user });
    fireEvent.click(screen.getByText("WZ WZ/41"));
  }

  it("brygadzista nie widzi przycisków edycji i usuwania", async () => {
    await withOneDelivery(foreman);
    expect(screen.queryByText("Edytuj WZ")).toBeNull();
    expect(screen.queryByText("Usuń WZ")).toBeNull();
  });

  it("usunięcie wymaga potwierdzenia; anulowanie nic nie zmienia, potwierdzenie koryguje bilans", async () => {
    await withOneDelivery(manager);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(screen.getByText("Usuń WZ"));
    expect(confirm.mock.calls[0][0]).toContain(DELETE_CONFIRMATION);
    expect(confirm.mock.calls[0][0]).toContain("1 pozycja");
    expect(DELETE_CONFIRMATION).toBe("Czy na pewno chcesz usunąć ten dokument WZ? Bilans dostaw zostanie skorygowany.");
    expect(mutate).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByText("Usuń WZ"));
    await waitFor(() => expect(mutate).toHaveBeenCalledWith("/api/bom-deliveries/41", "DELETE"));
    await waitFor(() => expect(screen.getByTestId("wz-count").textContent).toBe("0"));
    expect(screen.queryByText("WZ WZ/41")).toBeNull();
  });

  it("edycja WZ: formularz wypełniony danymi dokumentu, zapis przelicza bilans i pokazuje autora korekty", async () => {
    await withOneDelivery(manager);
    fireEvent.click(screen.getByText("Edytuj WZ"));
    expect(screen.getByText("Edytuj WZ WZ/41")).toBeTruthy();
    const editForm = screen.getByText("Edytuj WZ WZ/41").closest("form");
    const inputs = within(editForm);
    expect(inputs.getByDisplayValue("WZ/41")).toBeTruthy();
    expect(inputs.getByLabelText("Ilość dostarczona, pozycja 1").value).toBe("50");
    fireEvent.change(inputs.getByLabelText("Ilość dostarczona, pozycja 1"), { target: { value: "45" } });
    fireEvent.change(inputs.getByLabelText("Ilość uszkodzona, pozycja 1"), { target: { value: "5" } });
    fireEvent.click(inputs.getByText("Zapisz zmiany WZ"));

    await waitFor(() => expect(mutate).toHaveBeenCalledWith("/api/bom-deliveries/41", "PUT", expect.objectContaining({ wz_number: "WZ/41", items: [{ component_id: byKey("LT1-1450-18").component_id, quantity_received: 45, quantity_damaged: 5 }] })));
    await waitFor(() => expect(screen.queryByText("Edytuj WZ WZ/41")).toBeNull());
    expect(screen.getByText(/poprawił\(a\): Kierownik Budowy/)).toBeTruthy();
    fireEvent.click(screen.getByText("Pokaż cały katalog", { exact: false }));
    expect(screen.getByTestId("balance-LT1-1450-18").textContent).toContain("40");
  });

  it("anulowanie edycji zostawia dokument bez zmian", async () => {
    await withOneDelivery(manager);
    fireEvent.click(screen.getByText("Edytuj WZ"));
    fireEvent.click(within(screen.getByText("Edytuj WZ WZ/41").closest("form")).getByText("Anuluj"));
    expect(screen.queryByText("Edytuj WZ WZ/41")).toBeNull();
    expect(mutate).not.toHaveBeenCalled();
  });
});
