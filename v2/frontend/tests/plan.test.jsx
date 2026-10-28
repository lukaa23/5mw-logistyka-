/* ASOLAR v2, etap 4c: Planimetria i pulpit postępu. */
import "fake-indexeddb/auto";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DashboardCard, PlanView } from "../src/Plan";
import { resetOfflineStore } from "../src/offline";
import { DialogProvider } from "../src/ui";

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = { id: 8, name: "Farma Test", archived: false };
const manager = { role: "kierownik", isManager: true };
const user = { id: 1, full_name: "Kierownik Budowy" };
const notify = vi.fn();

let server;
beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar2_token", "token");
  await resetOfflineStore();
  globalThis.URL.createObjectURL = vi.fn(() => "blob:plan");
  globalThis.URL.revokeObjectURL = vi.fn();
  server = {
    calls: [],
    documents: [
      { id: 1, filename: "instrukcja.pdf", status: "gotowy", pages: 50, category: "auto" },
      { id: 2, filename: "planimetria.pdf", status: "gotowy", pages: 2, category: "rysunek" },
      { id: 3, filename: "w-analizie.pdf", status: "analiza", pages: 0, category: "auto" },
    ],
    tables: [{ id: 10, code: "T-1", built: false, qc_checked: false, notes: 0, photos: 0 }, { id: 11, code: "T-2", built: true, qc_checked: true, notes: 0, photos: 0 }],
    plan: { pages: 2, markers: [{ code: "T-1", table_id: 10, x: 0.1, y: 0.2, w: 0.02, h: 0.01 }, { code: "T-2", table_id: 11, x: 0.3, y: 0.2, w: 0.02, h: 0.01 }], codes_on_page: 2, tables_not_on_page: 0 },
  };
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    server.calls.push({ path, method: options.method || "GET" });
    if (path.endsWith("/documents")) return json(server.documents);
    if (path.endsWith("/tables")) return json(server.tables);
    if (path.includes("/plan?page=")) return json(server.plan);
    // Bajty zamiast Blob z jsdom — Response z Node 22 nie umie czytać Blob z jsdom.
    if (path.includes(".png")) return new Response(new Uint8Array([137, 80]), { headers: { "Content-Type": "image/png" } });
    if (/\/tables\/\d+\/(notes|photos)$/.test(path)) return json([]);
    if (path.endsWith("/dashboard")) return json({ tables_total: 10, tables_built: 3, tables_qc: 1, built_pct: 30, qc_pct: 10, built_today: 1, materials_missing: 2, materials_required: 5, worklogs_today: 1, manhours_today: 24,
      history: Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(15 + i).padStart(2, "0")}`, built: i === 13 ? 1 : i === 12 ? 2 : 0 })),
      forecast_days: 5, forecast_date: "2026-11-02", forecast_status: "szacunek", forecast_assumptions: ["Prognoza nie uwzględnia przerw."] });
    if (path.includes("/reports/daily")) return new Response("%PDF", { headers: { "Content-Type": "application/pdf" } });
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Planimetria", () => {
  it("domyślnie pokazuje rysunek, znaczniki w kolorze stanu i otwiera panel stołu", async () => {
    render(<DialogProvider><PlanView project={project} access={manager} user={user} notify={notify} /></DialogProvider>);
    const markers = await screen.findAllByTestId("plan-marker");
    expect(screen.getByLabelText("Rysunek").value).toBe("2");
    expect(screen.queryByRole("option", { name: /w-analizie/ })).toBeNull();
    expect(markers.map(m => m.className)).toEqual([expect.stringContaining("todo"), expect.stringContaining("qc")]);
    expect(markers[0].style.left).toBe("10%");
    fireEvent.change(screen.getByLabelText("Pokaż stoły"), { target: { value: "qc" } });
    expect(screen.getAllByTestId("plan-marker")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("Stół T-2"));
    expect(await screen.findByRole("dialog", { name: "Stół T-2" })).toBeTruthy();
  });

  it("strona bez oznaczeń stołów wyjaśnia, dlaczego nie ma znaczników", async () => {
    server.plan = { pages: 2, markers: [], codes_on_page: 0, tables_not_on_page: 2 };
    render(<DialogProvider><PlanView project={project} access={manager} user={user} notify={notify} /></DialogProvider>);
    expect(await screen.findByText(/nie znaleziono oznaczeń stołów/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Strona"), { target: { value: "2" } });
    await waitFor(() => expect(server.calls.some(c => c.path.endsWith("/documents/2/plan?page=2"))).toBe(true));
    expect(server.calls.some(c => c.path.endsWith("/documents/2/pages/2.png?scale=2"))).toBe(true);
  });
});

describe("pulpit postępu", () => {
  it("pokazuje wskaźniki, prognozę z założeniami i pobiera raport dzienny", async () => {
    render(<DashboardCard project={project} />);
    const card = await screen.findByTestId("dashboard");
    expect(within(card).getByText("z 10 zamontowanych (30%)")).toBeTruthy();
    expect(within(card).getByText(/5 dni/)).toBeTruthy();
    expect(within(card).getByText("Prognoza nie uwzględnia przerw.")).toBeTruthy();
    fireEvent.change(within(card).getByLabelText("Raport dzienny PDF"), { target: { value: "2026-10-27" } });
    fireEvent.click(within(card).getByText("↓ Pobierz raport"));
    await waitFor(() => expect(server.calls.some(c => c.path === "/api/projects/8/reports/daily?report_date=2026-10-27")).toBe(true));
  });
});
