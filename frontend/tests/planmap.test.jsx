import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../src/api", () => ({
  api: vi.fn(),
  cachedGet: vi.fn(),
  download: vi.fn(async () => undefined),
  upload: vi.fn(),
}));

import { api, cachedGet } from "../src/api";
import PlanMap, { formatPlanDate, normalizePlans } from "../src/PlanMap";

const manager = { id: 1, role: "kierownik", full_name: "Kierownik" };
const foreman = { id: 2, role: "brygadzista", full_name: "Brygadzista 1" };
const plan = (id, extra = {}) => ({ id, title: `Plan ${id}`, filename: `plan-${id}.pdf`, uploaded_by: "Kierownik", uploaded_at: "2026-10-01T10:00:00", file_url: `/api/documents/${id}/file`, deletable: true, ...extra });

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const pdfBlob = name => new Blob([`%PDF ${name}`], { type: "application/pdf" });
const flush = async () => { await act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); }); };
const iframe = () => document.querySelector("iframe");

let objectUrls;
let revoked;

beforeEach(() => {
  objectUrls = 0;
  revoked = [];
  URL.createObjectURL = vi.fn(blob => `blob:test/${++objectUrls}-${blob.size}`);
  URL.revokeObjectURL = vi.fn(url => revoked.push(url));
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

function setupFiles(map) {
  api.mockImplementation(path => {
    if (path in map) return typeof map[path] === "function" ? map[path]() : Promise.resolve(map[path]);
    return Promise.resolve({ ok: true });
  });
}

const renderMap = (props = {}) => {
  const notify = vi.fn();
  const view = render(<PlanMap project={{ id: 1 }} sync={0} notify={notify} user={manager} {...props} />);
  const rerender = next => view.rerender(<PlanMap project={{ id: 1 }} sync={0} notify={notify} user={manager} {...props} {...next} />);
  return { ...view, rerender, notify };
};

describe("normalizacja danych planów", () => {
  it("obsługuje null, pustą listę i niepoprawne rekordy", () => {
    expect(normalizePlans(null)).toEqual([]);
    expect(normalizePlans(undefined)).toEqual([]);
    expect(normalizePlans({})).toEqual([]);
    expect(normalizePlans([])).toEqual([]);
    const result = normalizePlans([null, 7, "x", {}, { id: 3 }, { id: null, file_url: "/a" }, plan(4), plan(4)]);
    expect(result.map(item => item.id)).toEqual([4]);
  });

  it("uzupełnia brak tytułu i obsługuje błędną datę", () => {
    const [first, second] = normalizePlans([{ id: 9, file_url: "/f/9" }, { id: 10, title: "  ", filename: "rev02.pdf", file_url: "/f/10" }]);
    expect(first.title).toBe("Plan #9");
    expect(second.title).toBe("rev02.pdf");
    expect(formatPlanDate("nie-data")).toBe("—");
    expect(formatPlanDate(null)).toBe("—");
    expect(formatPlanDate("2026-10-01T10:00:00")).not.toBe("—");
  });
});

describe("Mapa / Planimetria", () => {
  it("otwiera PDF i zachowuje go po kolejnym odświeżeniu synchronizacji", async () => {
    cachedGet.mockResolvedValue([plan(1), plan(2)]);
    setupFiles({ "/api/documents/1/file": pdfBlob("one") });
    const view = renderMap();
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 1");
    expect(iframe().getAttribute("title")).toBe("Plan 1");
    const firstSrc = iframe().getAttribute("src");

    view.rerender({ sync: 1 });
    await flush();
    view.rerender({ sync: 2 });
    await flush();
    expect(cachedGet).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 1");
    expect(iframe().getAttribute("src")).toBe(firstSrc);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("zachowuje wybrany drugi plan po odświeżeniu", async () => {
    cachedGet.mockResolvedValue([plan(1), plan(2)]);
    setupFiles({ "/api/documents/1/file": pdfBlob("one"), "/api/documents/2/file": pdfBlob("second") });
    const view = renderMap();
    await flush();
    fireEvent.click(screen.getByText("Plan 2"));
    await flush();
    view.rerender({ sync: 1 });
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 2");
    expect(iframe().getAttribute("title")).toBe("Plan 2");
  });

  it("po usunięciu aktualnego dokumentu z listy przechodzi na pozostały plan bez starego PDF", async () => {
    cachedGet.mockResolvedValueOnce([plan(1), plan(2)]);
    const second = deferred();
    setupFiles({ "/api/documents/1/file": pdfBlob("one"), "/api/documents/2/file": () => second.promise });
    const view = renderMap();
    await flush();
    const oldSrc = iframe().getAttribute("src");

    cachedGet.mockResolvedValueOnce([plan(2)]);
    view.rerender({ sync: 1 });
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 2");
    expect(iframe()).toBeNull();
    expect(revoked).toContain(oldSrc.split("#")[0]);

    await act(async () => second.resolve(pdfBlob("second")));
    await flush();
    expect(iframe().getAttribute("title")).toBe("Plan 2");
    expect(iframe().getAttribute("src")).not.toBe(oldSrc);
  });

  it("po usunięciu ostatniego dokumentu pokazuje pusty stan zamiast białego ekranu", async () => {
    cachedGet.mockResolvedValueOnce([plan(1)]);
    setupFiles({ "/api/documents/1/file": pdfBlob("one") });
    const view = renderMap();
    await flush();
    cachedGet.mockResolvedValueOnce([]);
    view.rerender({ sync: 1 });
    await flush();
    expect(iframe()).toBeNull();
    expect(screen.getByText("Brak wybranego planu")).toBeTruthy();
    expect(screen.getByText("Brak planimetrii w tym projekcie.")).toBeTruthy();
  });

  it("zmiana projektu ładuje nową listę i nie pokazuje PDF poprzedniego projektu", async () => {
    cachedGet.mockImplementation(async path => path.endsWith("project_id=1") ? [plan(1)] : [plan(5, { title: "Plan projektu B" })]);
    const fiveFile = deferred();
    setupFiles({ "/api/documents/1/file": pdfBlob("one"), "/api/documents/5/file": () => fiveFile.promise });
    const view = renderMap();
    await flush();
    expect(iframe().getAttribute("title")).toBe("Plan 1");

    view.rerender({ project: { id: 2 } });
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan projektu B");
    expect(iframe()).toBeNull();
    await act(async () => fiveFile.resolve(pdfBlob("five")));
    await flush();
    expect(iframe().getAttribute("title")).toBe("Plan projektu B");
  });

  it("ignoruje spóźnioną odpowiedź listy poprzedniego projektu", async () => {
    const slowOld = deferred();
    cachedGet.mockImplementation(path => path.endsWith("project_id=1") ? slowOld.promise : Promise.resolve([plan(7, { title: "Nowy projekt" })]));
    setupFiles({ "/api/documents/7/file": pdfBlob("seven"), "/api/documents/1/file": pdfBlob("one") });
    const view = renderMap();
    view.rerender({ project: { id: 2 } });
    await flush();
    await act(async () => slowOld.resolve([plan(1, { title: "Stary projekt" })]));
    await flush();
    expect(screen.queryByText("Stary projekt")).toBeNull();
    expect(screen.getByTestId("plan-title").textContent).toBe("Nowy projekt");
    expect(api).not.toHaveBeenCalledWith("/api/documents/1/file");
  });

  it("ignoruje nieaktualną odpowiedź listy w tym samym projekcie", async () => {
    const first = deferred();
    const second = deferred();
    cachedGet.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    setupFiles({ "/api/documents/2/file": pdfBlob("two"), "/api/documents/1/file": pdfBlob("one") });
    const view = renderMap();
    view.rerender({ sync: 1 });
    await act(async () => second.resolve([plan(2)]));
    await flush();
    await act(async () => first.resolve([plan(1)]));
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 2");
    expect(screen.queryByText("Plan 1")).toBeNull();
  });

  it("zmiana planu podczas pobierania PDF nie pokazuje starego pliku pod nowym tytułem", async () => {
    cachedGet.mockResolvedValue([plan(1), plan(2)]);
    const one = deferred();
    const two = deferred();
    setupFiles({ "/api/documents/1/file": () => one.promise, "/api/documents/2/file": () => two.promise });
    renderMap();
    await flush();
    fireEvent.click(screen.getByText("Plan 2"));
    await flush();
    await act(async () => one.resolve(pdfBlob("one-late")));
    await flush();
    expect(iframe()).toBeNull();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 2");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    await act(async () => two.resolve(pdfBlob("two")));
    await flush();
    expect(iframe().getAttribute("title")).toBe("Plan 2");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("zwalnia adresy blob przy zmianie planu i odmontowaniu", async () => {
    cachedGet.mockResolvedValue([plan(1), plan(2)]);
    setupFiles({ "/api/documents/1/file": pdfBlob("one"), "/api/documents/2/file": pdfBlob("second") });
    const view = renderMap();
    await flush();
    const first = iframe().getAttribute("src").split("#")[0];
    fireEvent.click(screen.getByText("Plan 2"));
    await flush();
    expect(revoked).toContain(first);
    const second = iframe().getAttribute("src").split("#")[0];
    view.unmount();
    expect(revoked).toContain(second);
  });

  it("ignoruje odpowiedzi po odmontowaniu komponentu", async () => {
    const list = deferred();
    cachedGet.mockReturnValue(list.promise);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const view = renderMap();
    view.unmount();
    await act(async () => list.resolve([plan(1)]));
    await flush();
    expect(api).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
  });

  it("obsługuje null, pustą listę, niepoprawne rekordy, brak tytułu i błędną datę", async () => {
    for (const payload of [null, [], [null, { id: 1 }, "x"], { unexpected: true }]) {
      cachedGet.mockResolvedValueOnce(payload);
      const view = renderMap();
      await flush();
      expect(screen.getByText("Brak wybranego planu")).toBeTruthy();
      view.unmount();
    }
    cachedGet.mockResolvedValueOnce([{ id: 3, file_url: "/api/documents/3/file", uploaded_at: "nie-data", uploaded_by: null }]);
    setupFiles({ "/api/documents/3/file": pdfBlob("three") });
    renderMap();
    await flush();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan #3");
    expect(iframe().getAttribute("title")).toBe("Plan #3");
    expect(screen.getByText(/— · —/)).toBeTruthy();
  });

  it("błąd pobierania PDF pokazuje komunikat zamiast wywracać aplikację", async () => {
    cachedGet.mockResolvedValue([plan(1)]);
    setupFiles({ "/api/documents/1/file": () => Promise.reject(new Error("Brak pliku dokumentu")) });
    renderMap();
    await flush();
    expect(screen.getByRole("alert").textContent).toContain("Brak pliku dokumentu");
    expect(iframe()).toBeNull();
    expect(screen.getByTestId("plan-title").textContent).toBe("Plan 1");
  });

  it("błąd listy planów pokazuje komunikat", async () => {
    cachedGet.mockRejectedValue(new Error("Serwer niedostępny"));
    renderMap();
    await flush();
    expect(screen.getByRole("alert").textContent).toContain("Serwer niedostępny");
  });

  it("chroni zatwierdzone źródła: brak przycisku usuwania, a brygadzista nie usuwa niczego", async () => {
    cachedGet.mockResolvedValue([plan(1, { deletable: false, approved_source: true }), plan(2)]);
    setupFiles({ "/api/documents/1/file": pdfBlob("one"), "/api/documents/2/file": pdfBlob("two") });
    const view = renderMap();
    await flush();
    expect(screen.queryByText("Usuń")).toBeNull();
    fireEvent.click(screen.getByText("Plan 2"));
    await flush();
    expect(screen.getByText("Usuń")).toBeTruthy();
    view.unmount();
    renderMap({ user: foreman });
    await flush();
    expect(screen.queryByText("Usuń")).toBeNull();
    expect(screen.queryByText("Wgraj planimetrię")).toBeNull();
  });
});
