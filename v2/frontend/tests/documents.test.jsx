/* ASOLAR v2, etap 2: wgrywanie wielu PDF, lista dokumentów, ekran przeglądu propozycji. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Documents, { describe as describeItem } from "../src/Documents";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 7, name: "Farma Test", archived: false, stats: {} };
const source = (page, filename = "montaz.pdf") => ({ document_id: 1, filename, page, excerpt: `fragment ze strony ${page}` });
const suggestion = (id, kind, payload, extra = {}) => ({ id, kind, key: `${kind}|${id}`, payload, original: payload, sources: [source(53)], confidence: 0.9, status: "nowa", edited: false, applied_ref: "", ...extra });

let server;
beforeEach(() => {
  server = {
    documents: [
      { id: 1, filename: "montaz.pdf", size: 4500000, status: "gotowy", pages: 60, summary: { suggestions: { bom_line: 3 } }, warnings: [], error: "", uploaded_at: "2026-10-28T08:00:00" },
      { id: 2, filename: "planimetria.pdf", size: 7900000, status: "gotowy", pages: 12, summary: { suggestions: {} }, warnings: ["Strony zapisane jako obraz (skan) — bez OCR nie da się odczytać ich treści: 1, 2."], error: "", uploaded_at: "2026-10-28T08:01:00" },
    ],
    suggestions: [
      suggestion(1, "bom_line", { name: "Purlin 1", code: "LT1-1450", spec: "J60x30x1.8", quantity: 44, unit: "szt.", group: "1x42" }),
      suggestion(2, "bom_line", { name: "Purlin 1", code: "LT1-1450", spec: "J60x30x1.8", quantity: 58, unit: "szt.", group: "1x56" }),
      suggestion(3, "bom_line", { name: "Clamp", code: "CL-7", spec: "M8", quantity: 88, unit: "szt.", group: "1x42", conflict: [88, 90] }, { confidence: 0.5 }),
      suggestion(4, "zone", { name: "Zone A1", occurrences: 3 }),
      suggestion(5, "numbering", { prefix: "T", first: 1, last: 55, count: 55, example: "T-1", missing: [] }, { confidence: 0.75 }),
    ],
    calls: [],
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body });
    if (path.endsWith("/documents") && method === "GET") return json(server.documents);
    if (path.includes("/documents?category=")) return json({ accepted: [{ id: 9 }], duplicates: [], rejected: [] });
    if (path.endsWith("/suggestions")) return json(server.suggestions);
    const one = /\/suggestions\/(\d+)$/.exec(path);
    if (one && method === "PATCH") {
      const item = server.suggestions.find(s => s.id === Number(one[1]));
      const body = JSON.parse(options.body);
      Object.assign(item, { status: body.status || item.status, payload: { ...item.payload, ...(body.payload || {}) }, edited: item.edited || !!body.payload });
      return json(item);
    }
    if (path.endsWith("/suggestions/bulk")) { const body = JSON.parse(options.body); server.suggestions.filter(s => body.ids.includes(s.id)).forEach(s => { s.status = body.status; }); return json({ updated: body.ids.length }); }
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notify = vi.fn();
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const show = (access = manager, proj = project) => render(<DialogProvider><Documents project={proj} access={access} notify={notify} /></DialogProvider>);
const patches = () => server.calls.filter(call => call.method === "PATCH").map(call => ({ path: call.path, body: JSON.parse(call.body) }));

describe("dokumenty i przegląd propozycji", () => {
  it("pokazuje pliki z ostrzeżeniem OCR i propozycje pogrupowane wg rodzaju i typu konstrukcji", async () => {
    show();
    expect(await screen.findByText("montaz.pdf")).toBeTruthy();
    expect(screen.getByText(/bez OCR nie da się odczytać/)).toBeTruthy();
    const bom = await screen.findByTestId("section-bom_line");
    expect(within(bom).getByText(/Typ konstrukcji: 1x42/)).toBeTruthy();
    expect(within(bom).getByText(/Typ konstrukcji: 1x56/)).toBeTruthy();
    expect(within(bom).getByText(/Rozbieżność ilości między źródłami: 88 \/ 90/)).toBeTruthy();
    expect(within(bom).getAllByText(/Źródło: montaz.pdf s. 53/).length).toBe(3);
    expect(screen.getByTestId("section-zone")).toBeTruthy();
    expect(screen.getByText("T 1–55")).toBeTruthy();
  });

  it("zatwierdza i odrzuca pojedynczą propozycję", async () => {
    show();
    const zone = await screen.findByTestId("section-zone");
    fireEvent.click(within(zone).getByText("Zatwierdź"));
    await waitFor(() => expect(patches()).toEqual([{ path: "/api/projects/7/suggestions/4", body: { status: "zatwierdzona" } }]));
    const numbering = screen.getByTestId("section-numbering");
    fireEvent.click(within(numbering).getByText("Odrzuć"));
    await waitFor(() => expect(patches()[1]).toEqual({ path: "/api/projects/7/suggestions/5", body: { status: "odrzucona" } }));
  });

  it("poprawia ilość przed zatwierdzeniem; Esc anuluje edycję", async () => {
    show();
    const bom = await screen.findByTestId("section-bom_line");
    const row = within(bom).getAllByTestId("suggestion-row")[0];
    fireEvent.click(within(row).getByText("Popraw"));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(within(row).queryByLabelText("Ilość")).toBeNull());
    fireEvent.click(within(row).getByText("Popraw"));
    fireEvent.change(within(row).getByLabelText("Ilość"), { target: { value: "46" } });
    fireEvent.click(within(row).getByText("Zapisz i zatwierdź"));
    await waitFor(() => expect(patches()).toEqual([{ path: "/api/projects/7/suggestions/1", body: { status: "zatwierdzona", payload: { quantity: 46 } } }]));
  });

  it("zatwierdzenie zbiorcze pomija pozycje z rozbieżnością i wymaga potwierdzenia", async () => {
    show();
    const bom = await screen.findByTestId("section-bom_line");
    fireEvent.click(within(bom).getByText("Zatwierdź wszystkie (2)"));
    fireEvent.click(await screen.findByText("Zatwierdź 2"));
    await waitFor(() => expect(server.calls.some(call => call.path.endsWith("/bulk"))).toBe(true));
    const bulk = server.calls.find(call => call.path.endsWith("/bulk"));
    expect(JSON.parse(bulk.body)).toEqual({ ids: [1, 2], status: "zatwierdzona" });
  });

  it("brygadzista ma tylko podgląd: bez wgrywania i bez przycisków decyzji", async () => {
    show(foreman);
    await screen.findByTestId("section-bom_line");
    expect(screen.queryByTestId("drop-zone")).toBeNull();
    expect(screen.queryByText("Zatwierdź")).toBeNull();
    expect(screen.queryByText("Usuń")).toBeNull();
    expect(screen.getByText(/Masz podgląd/)).toBeTruthy();
  });

  it("wgrywa wiele PDF jednym żądaniem i pomija pliki innego typu", async () => {
    show();
    await screen.findByText("montaz.pdf");
    const files = [new File(["%PDF-1"], "a.pdf", { type: "application/pdf" }), new File(["%PDF-1"], "b.pdf", { type: "application/pdf" }), new File(["x"], "c.docx", { type: "application/msword" })];
    fireEvent.change(screen.getByLabelText("Pliki PDF"), { target: { files } });
    await waitFor(() => expect(server.calls.some(call => call.path.includes("/documents?category=auto"))).toBe(true));
    const upload = server.calls.find(call => call.path.includes("/documents?category=auto"));
    expect(upload.body.getAll("files").map(file => file.name)).toEqual(["a.pdf", "b.pdf"]);
    expect(notify).toHaveBeenCalledWith("Pominięto 1 plik(ów) innych niż PDF", "error");
  });

  it("opisuje propozycje czytelnie", () => {
    expect(describeItem({ kind: "torque", payload: { bolt: "M10", min_nm: 25, max_nm: 32, context: "" } }).value).toBe("25–32 N·m");
    expect(describeItem({ kind: "numbering", payload: { prefix: "T", first: 1, last: 55, count: 53, example: "T-1", missing: [7, 9] } }).detail).toContain("brak w zakresie: 7, 9");
  });
});

describe("pozycje BOM bez typu", () => {
  it("nie wchodzą do „Zatwierdź wszystkie”; można im przypisać typ zbiorczo", async () => {
    server.suggestions.push(
      suggestion(6, "bom_line", { name: "Pole 1", code: "", spec: "", quantity: 11, unit: "szt.", group: "" }),
      suggestion(7, "bom_line", { name: "Pole 2", code: "", spec: "", quantity: 11, unit: "szt.", group: "" }),
      suggestion(8, "structure_type", { code: "2x26", modules: 52, tables: 157, occurrences: 1 }),
    );
    render(<DialogProvider><Documents project={project} access={manager} notify={notify} /></DialogProvider>);
    const bom = await screen.findByTestId("section-bom_line");
    expect(within(bom).getByText("Zatwierdź wszystkie (2)")).toBeTruthy();
    expect(screen.getByText(/liczba stołów wg dokumentu: 157/)).toBeTruthy();
    const select = await within(bom).findByLabelText("Typ dla pozycji bez typu");
    await within(select).findByRole("option", { name: "2x26" });
    fireEvent.change(select, { target: { value: "2x26" } });
    fireEvent.click(within(bom).getByText("Przypisz 2x26 i zatwierdź (2)"));
    fireEvent.click(await screen.findByText("Zatwierdź 2"));
    await waitFor(() => expect(server.calls.some(call => call.path.endsWith("/bulk"))).toBe(true));
    expect(JSON.parse(server.calls.find(call => call.path.endsWith("/bulk")).body)).toEqual({ ids: [6, 7], status: "zatwierdzona", group: "2x26" });
  });
});

describe("odrzucanie pozycji bez typu", () => {
  it("jednym kliknięciem z potwierdzeniem", async () => {
    server.suggestions.push(suggestion(6, "bom_line", { name: "Pole 1", code: "", spec: "", quantity: 11, unit: "szt.", group: "" }));
    render(<DialogProvider><Documents project={project} access={manager} notify={notify} /></DialogProvider>);
    const bom = await screen.findByTestId("section-bom_line");
    fireEvent.click(within(bom).getByText("Odrzuć pozycje bez typu (1)"));
    fireEvent.click(await screen.findByText("Odrzuć 1"));
    await waitFor(() => expect(server.calls.some(call => call.path.endsWith("/bulk"))).toBe(true));
    expect(JSON.parse(server.calls.find(call => call.path.endsWith("/bulk")).body)).toEqual({ ids: [6], status: "odrzucona" });
  });
});
