/* Dokumenty (uproszczone): kafelki rodzajów + przeciągnij i upuść, postęp dla każdego pliku,
 * weryfikacja z podglądem po lewej i pozycjami po prawej, edycja jednym kliknięciem, tryb ręczny. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Documents, { describe as describeItem } from "../src/Documents";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 7, name: "Farma Test", archived: false, stats: {} };
const manager = { role: "kierownik", isManager: true };
const foreman = { role: "brygadzista", isManager: false };
const source = (documentId, page = 1) => ({ document_id: documentId, filename: "bom.pdf", page, excerpt: "..." });
const item = (id, kind, payload, extra = {}) => ({ id, kind, key: `${kind}|${id}`, payload, original: payload, sources: [source(1)], confidence: 0.9, status: "nowa", edited: false, applied_ref: "", ...extra });

let server, xhrs;

class FakeXHR {
  constructor() { this.upload = {}; this.headers = {}; xhrs.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(body) {
    this.body = body;
    const file = body.get("files");
    setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
      setTimeout(() => {
        const duplicate = file.name === "kopia.pdf";
        this.status = 200;
        this.responseText = JSON.stringify(duplicate ? { accepted: [], duplicates: [{ filename: file.name, existing: "bom.pdf" }], rejected: [] }
          : { accepted: [{ id: 100 + xhrs.length, filename: file.name }], duplicates: [], rejected: [] });
        this.onload();
      }, 5);
    }, 5);
  }
}

beforeEach(() => {
  xhrs = [];
  globalThis.URL.createObjectURL = vi.fn(() => "blob:preview");
  globalThis.URL.revokeObjectURL = vi.fn();
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  server = {
    calls: [],
    documents: [
      { id: 1, filename: "bom.pdf", format: "pdf", category: "bom", size: 190000, status: "gotowy", pages: 3, summary: {}, warnings: [], error: "", uploaded_at: "2026-10-29T08:00:00" },
      { id: 2, filename: "skan.pdf", format: "pdf", category: "bom", size: 500000, status: "ręcznie", pages: 2, summary: {}, warnings: [], error: "Nie znaleziono danych do automatycznego odczytu (np. skan albo nietypowy układ). Uzupełnij pozycje ręcznie obok podglądu.", uploaded_at: "2026-10-29T08:01:00" },
    ],
    suggestions: [
      item(10, "bom_line", { name: "Pole 1", code: "", spec: "C120", quantity: 11, unit: "PCS", group: "2x26" }, { sources: [source(1, 1)] }),
      item(11, "bom_line", { name: "Beam", code: "", spec: "C120x50", quantity: 11, unit: "PCS", group: "" }, { sources: [source(1, 3)] }),
      item(12, "structure_type", { code: "2x26", modules: 52, tables: 157 }),
      item(13, "bom_line", { name: "Purlin", code: "", spec: "", quantity: 4, unit: "PCS", group: "2x26" }, { status: "zatwierdzona" }),
    ],
    types: [{ id: 1, code: "2x13" }],
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    server.calls.push({ path, method, body: options.body ? JSON.parse(options.body) : null });
    if (path.endsWith("/documents") && method === "GET") return json(server.documents);
    if (path.endsWith("/suggestions") && method === "GET") return json(server.suggestions);
    if (path.endsWith("/suggestions") && method === "POST") return json({ id: 99 });
    if (path.endsWith("/types")) return json(server.types);
    if (path.includes("/pages/")) return new Response(new Uint8Array([137, 80]), { headers: { "Content-Type": "image/png" } });
    if (path.endsWith("/suggestions/bulk")) return json({ updated: JSON.parse(options.body).ids.length, failed: [] });
    const one = /\/suggestions\/(\d+)$/.exec(path);
    if (one && method === "PATCH") {
      const body = JSON.parse(options.body);
      if (Number(one[1]) === 11 && body.status === "zatwierdzona") return json({ detail: "„Beam”: brak typu konstrukcji — uzupełnij pole „Typ konstrukcji”" }, 409);
      const target = server.suggestions.find(s => s.id === Number(one[1]));
      Object.assign(target, { status: body.status || target.status, payload: { ...target.payload, ...(body.payload || {}) } });
      return json(target);
    }
    return json({ ok: true });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notify = vi.fn();
const show = (access = manager) => render(<DialogProvider><Documents project={project} access={access} notify={notify} /></DialogProvider>);
const writes = () => server.calls.filter(call => call.method !== "GET");
async function openReview(name = "bom.pdf") {
  const row = (await screen.findAllByTestId("document-row")).find(element => element.textContent.includes(name));
  fireEvent.click(within(row).getByText("Sprawdź"));
  return screen.findByTestId("review");
}

describe("dodawanie plików", () => {
  it("trzy kafelki rodzajów; wybór z dysku wgrywa każdy plik osobno z paskiem postępu i rodzajem", async () => {
    show();
    await screen.findAllByTestId("document-row");
    expect(screen.getByText("BOM / lista materiałowa")).toBeTruthy();
    expect(screen.getByText("Rysunki i schematy")).toBeTruthy();
    expect(screen.getByText("Instrukcje i manuale")).toBeTruthy();
    const files = [new File(["%PDF-1"], "a.pdf", { type: "application/pdf" }), new File(["%PDF-1"], "kopia.pdf", { type: "application/pdf" }), new File(["x"], "notatka.docx")];
    fireEvent.change(screen.getByLabelText("Pliki: BOM / lista materiałowa"), { target: { files } });
    const rows = await screen.findAllByTestId("queue-row");
    expect(rows).toHaveLength(3);
    await waitFor(() => expect(xhrs).toHaveLength(2));
    expect(xhrs.map(request => request.url)).toEqual(["/api/projects/7/documents?category=bom", "/api/projects/7/documents?category=bom"]);
    expect(xhrs[0].body.getAll("files").map(file => file.name)).toEqual(["a.pdf"]);
    await waitFor(() => expect(screen.getByText("Już wgrany jako „bom.pdf”")).toBeTruthy());
    expect(screen.getByText("Obsługiwane są pliki PDF, DWG i DXF")).toBeTruthy();
    expect(screen.getAllByRole("progressbar").length).toBe(3);
  });

  it("przeciągnij i upuść na kafelek rysunków wysyła z rodzajem „rysunek”", async () => {
    show();
    await screen.findAllByTestId("document-row");
    const tile = screen.getByTestId("tile-rysunek");
    fireEvent.dragOver(tile, { dataTransfer: { files: [] } });
    expect(tile.className).toContain("over");
    fireEvent.drop(tile, { dataTransfer: { files: [new File(["AC1032"], "layout.dwg")] } });
    await waitFor(() => expect(xhrs[0]?.url).toBe("/api/projects/7/documents?category=rysunek"));
  });

  it("lista pokazuje prosty stan dokumentów; brygadzista nie wgrywa", async () => {
    show(foreman);
    const rows = await screen.findAllByTestId("document-row");
    expect(within(rows[0]).getByText("Do sprawdzenia: 3")).toBeTruthy();
    expect(within(rows[1]).getByText("Uzupełnij ręcznie")).toBeTruthy();
    expect(screen.queryByTestId("tile-bom")).toBeNull();
    expect(screen.queryByText("Usuń")).toBeNull();
  });
});

describe("weryfikacja: podgląd po lewej, pozycje po prawej", () => {
  it("pokazuje podgląd strony i pozycje ze statusem; kliknięcie pozycji przenosi podgląd na jej stronę", async () => {
    show();
    const review = await openReview();
    await waitFor(() => expect(server.calls.some(call => call.path.endsWith("/documents/1/pages/1.png?scale=1.5"))).toBe(true));
    expect(within(review).getByText("Strona 1 / 3")).toBeTruthy();
    const rows = within(review).getAllByTestId("item-row");
    expect(rows.map(row => row.textContent).join(" ")).toContain("Wymaga potwierdzenia");
    expect(rows.map(row => row.textContent).join(" ")).toContain("Zatwierdzone");
    fireEvent.click(within(review).getByText("Beam"));
    await waitFor(() => expect(within(review).getByText("Strona 3 / 3")).toBeTruthy());
  });

  it("edycja jednym kliknięciem: zmiana ilości i Zapisz; Esc anuluje", async () => {
    show();
    const review = await openReview();
    fireEvent.click(within(review).getByText("Pole 1"));
    const form = await within(review).findByRole("form", { name: "Edycja: Pole 1" });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(within(review).queryByRole("form", { name: "Edycja: Pole 1" })).toBeNull());
    expect(screen.getByTestId("review")).toBe(review); // Esc w edycji nie zamyka ekranu weryfikacji
    fireEvent.click(within(review).getByText("Pole 1"));
    const again = await within(review).findByRole("form", { name: "Edycja: Pole 1" });
    fireEvent.change(within(again).getByLabelText("Ilość / stół"), { target: { value: "12" } });
    fireEvent.click(within(again).getByText("Zapisz"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/7/suggestions/10", method: "PATCH", body: { payload: { quantity: 12 } } }));
    expect(form).toBeTruthy();
  });

  it("zatwierdzenie ✓; odmowa serwera pokazuje się przy pozycji, nie jako błąd całej strony", async () => {
    show();
    const review = await openReview();
    fireEvent.click(within(review).getByLabelText("Zatwierdź: Pole 1"));
    await waitFor(() => expect(writes()[0].body).toEqual({ status: "zatwierdzona" }));
    fireEvent.click(within(review).getByLabelText("Zatwierdź: Beam"));
    expect(await within(review).findByRole("alert")).toBeTruthy();
    expect(within(review).getByRole("alert").textContent).toContain("brak typu konstrukcji");
  });

  it("„Zatwierdź wszystkie” pomija pozycje bez typu; te dostają typ jednym polem", async () => {
    show();
    const review = await openReview();
    fireEvent.click(within(review).getByText("Zatwierdź wszystkie (2)"));
    fireEvent.click(await screen.findByText("Zatwierdź 2"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/7/suggestions/bulk", method: "POST", body: { ids: [10, 12], status: "zatwierdzona" } }));
    fireEvent.change(within(review).getByLabelText("Typ dla pozycji bez typu"), { target: { value: "2x26" } });
    fireEvent.click(within(review).getByText("Ustaw i zatwierdź"));
    fireEvent.click(await screen.findByText("Zatwierdź 1"));
    await waitFor(() => expect(writes()[1].body).toEqual({ ids: [11], status: "zatwierdzona", group: "2x26" }));
  });

  it("dokument do uzupełnienia ręcznego: komunikat bez błędu i formularz obok podglądu", async () => {
    show();
    const review = await openReview("skan.pdf");
    expect(within(review).getByText(/Uzupełnij pozycje ręcznie obok podglądu/)).toBeTruthy();
    expect(within(review).getByText("Nic nie odczytano automatycznie. Dodaj pozycje ręcznie poniżej.")).toBeTruthy();
    fireEvent.click(within(review).getByLabelText("Następna strona"));
    const form = within(review).getByRole("form", { name: "Dodaj pozycję ręcznie" });
    fireEvent.change(within(form).getByLabelText("Nazwa"), { target: { value: "Pole 1" } });
    fireEvent.change(within(form).getByLabelText("Ilość / stół"), { target: { value: "11" } });
    fireEvent.change(within(form).getByLabelText("Typ stołu"), { target: { value: "2x26" } });
    fireEvent.click(within(form).getByText("Dodaj i zatwierdź"));
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/7/suggestions", method: "POST",
      body: { kind: "bom_line", payload: { name: "Pole 1", quantity: 11, group: "2x26" }, document_id: 2, page: 2, approve: true } }));
  });

  it("zmiana rodzaju dokumentu = ponowny odczyt; brygadzista bez przycisków decyzji", async () => {
    show();
    const review = await openReview();
    fireEvent.change(within(review).getByLabelText("Rodzaj dokumentu"), { target: { value: "instrukcja" } });
    await waitFor(() => expect(writes()[0]).toEqual({ path: "/api/projects/7/documents/1", method: "PATCH", body: { category: "instrukcja" } }));
    cleanup();
    show(foreman);
    const readOnly = await openReview();
    expect(within(readOnly).queryByLabelText("Zatwierdź: Pole 1")).toBeNull();
    expect(within(readOnly).queryByRole("form", { name: "Dodaj pozycję ręcznie" })).toBeNull();
  });

  it("opisuje pozycje czytelnie", () => {
    expect(describeItem({ kind: "torque", payload: { bolt: "M10", min_nm: 25, max_nm: 32, context: "" } }).value).toBe("25–32 N·m");
    expect(describeItem({ kind: "bom_line", payload: { name: "Pole 1", quantity: 11, unit: "PCS", group: "2x26", spec: "C120" } }).value).toBe("11 PCS / stół");
  });
});
