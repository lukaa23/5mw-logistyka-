/* Notatki rzędu: Edytuj / Usuń z potwierdzeniem, online i bez zasięgu (kolejka IndexedDB), synchronizacja. */
import "fake-indexeddb/auto";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import RowNotes from "../src/RowNotes";
import { DialogProvider } from "../src/ui";
import { applyPendingRows, flushQueue, mutate, pendingItems, queuedCount } from "../src/api";
import { resetOfflineStore } from "../src/offlineStore";

const manager = { id: 1, role: "kierownik", full_name: "Kierownik Budowy" };
const foreman1 = { id: 2, role: "brygadzista", full_name: "Brygadzista 1" };
const row = { id: 7, code: "3" };
const setOnline = value => Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => value });
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const networkDown = () => Promise.reject(new TypeError("Failed to fetch"));

let server;
function serverFetch() {
  return vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    if (path === "/api/rows/7/notes" && method === "GET") return json(server.notes);
    const match = /^\/api\/rows\/7\/notes\/(\d+)$/.exec(path);
    if (match) {
      const id = Number(match[1]);
      const note = server.notes.find(item => item.id === id);
      if (!note) return json({ detail: "Notatka nie istnieje" }, 404);
      if (method === "DELETE") { server.notes = server.notes.filter(item => item.id !== id); return json({ ok: true }); }
      if (method === "PATCH") { note.text = JSON.parse(options.body).text; note.edited_at = "2026-10-18T12:00:00"; return json({ id }); }
    }
    if (path === "/api/rows/7/notes" && method === "POST") { const body = JSON.parse(options.body); const id = 100 + server.notes.length; server.notes.unshift({ id, text: body.text, author: "Brygadzista 1", author_id: 2, created_at: "2026-10-18T11:00:00" }); return json({ id }); }
    return json({ ok: true });
  });
}

const notify = vi.fn();
const renderNotes = (user, props = {}) => render(<DialogProvider><RowNotes row={row} user={user} notify={notify} refreshKey={0} {...props} /></DialogProvider>);
const noteCard = text => screen.getByText(text).closest("[data-testid=row-note]");

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar_token", "token");
  setOnline(true);
  await resetOfflineStore();
  notify.mockClear();
  server = { notes: [
    { id: 1, text: "Notatka brygadzisty 1", author: "Brygadzista 1", author_id: 2, created_at: "2026-10-18T08:00:00", edited_at: null },
    { id: 2, text: "Notatka brygadzisty 2", author: "Brygadzista 2", author_id: 3, created_at: "2026-10-18T07:00:00", edited_at: null },
  ] };
  vi.stubGlobal("fetch", serverFetch());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Edytuj / Usuń przy notatkach", () => {
  it("brygadzista widzi przyciski tylko przy własnej notatce, kierownik przy wszystkich", async () => {
    const view = renderNotes(foreman1);
    await screen.findByText("Notatka brygadzisty 1");
    expect(within(noteCard("Notatka brygadzisty 1")).getByText("Edytuj")).toBeTruthy();
    expect(within(noteCard("Notatka brygadzisty 1")).getByLabelText("Usuń notatkę")).toBeTruthy();
    expect(within(noteCard("Notatka brygadzisty 2")).queryByText("Edytuj")).toBeNull();
    view.unmount();
    renderNotes(manager);
    await screen.findByText("Notatka brygadzisty 2");
    expect(screen.getAllByText("Edytuj")).toHaveLength(2);
  });

  it("edycja: Esc anuluje, Ctrl+Enter zapisuje na serwerze", async () => {
    renderNotes(foreman1);
    await screen.findByText("Notatka brygadzisty 1");
    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByText("Edytuj"));
    const box = screen.getByLabelText("Treść notatki");
    fireEvent.change(box, { target: { value: "Zmieniona" } });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByLabelText("Treść notatki")).toBeNull();
    expect(server.notes[0].text).toBe("Notatka brygadzisty 1");

    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByText("Edytuj"));
    fireEvent.change(screen.getByLabelText("Treść notatki"), { target: { value: "Poprawiona treść" } });
    fireEvent.keyDown(screen.getByLabelText("Treść notatki"), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(screen.queryByLabelText("Treść notatki")).toBeNull()); // zapis zakończony
    await screen.findByText("Poprawiona treść", { selector: "p" });
    expect(server.notes[0].text).toBe("Poprawiona treść");
    expect(notify).toHaveBeenCalledWith("Zapisano zmianę notatki");
    expect(screen.getByText(/edytowano/)).toBeTruthy();
  });

  it("usunięcie pyta „Czy na pewno chcesz usunąć tę notatkę?”; Anuluj nic nie usuwa", async () => {
    renderNotes(foreman1);
    await screen.findByText("Notatka brygadzisty 1");
    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByLabelText("Usuń notatkę"));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Czy na pewno chcesz usunąć tę notatkę?")).toBeTruthy();
    fireEvent.click(within(dialog).getByText("Anuluj"));
    expect(server.notes).toHaveLength(2);

    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByLabelText("Usuń notatkę"));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Usuń notatkę"));
    await waitFor(() => expect(screen.queryByText("Notatka brygadzisty 1")).toBeNull());
    expect(server.notes.map(note => note.id)).toEqual([2]);
    expect(notify).toHaveBeenCalledWith("Notatka usunięta");
  });
});

describe("bez zasięgu i synchronizacja", () => {
  it("usunięcie offline: notatka znika od razu, po odzyskaniu sieci znika na serwerze (dla wszystkich urządzeń)", async () => {
    renderNotes(foreman1);
    await screen.findByText("Notatka brygadzisty 1");
    setOnline(false);
    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByLabelText("Usuń notatkę"));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Usuń notatkę"));
    await waitFor(() => expect(screen.queryByText("Notatka brygadzisty 1")).toBeNull());
    expect(server.notes).toHaveLength(2);
    expect(queuedCount()).toBe(1);
    expect((await pendingItems())[0]).toMatchObject({ method: "DELETE", path: "/api/rows/7/notes/1", label: "Usunięcie notatki" });

    setOnline(true);
    expect(await flushQueue()).toBe(1);
    expect(server.notes.map(note => note.id)).toEqual([2]);
    expect(queuedCount()).toBe(0);
  });

  it("edycja offline: nowa treść widoczna od razu jako „czeka na wysłanie”, po połączeniu trafia na serwer", async () => {
    renderNotes(foreman1);
    await screen.findByText("Notatka brygadzisty 1");
    setOnline(false);
    fireEvent.click(within(noteCard("Notatka brygadzisty 1")).getByText("Edytuj"));
    fireEvent.change(screen.getByLabelText("Treść notatki"), { target: { value: "Edycja bez zasięgu" } });
    fireEvent.click(screen.getByText("Zapisz"));
    await waitFor(() => expect(screen.queryByLabelText("Treść notatki")).toBeNull());
    await screen.findByText("Edycja bez zasięgu", { selector: "p" });
    expect(within(noteCard("Edycja bez zasięgu")).getByText(/czeka na wysłanie/)).toBeTruthy();
    setOnline(true);
    await flushQueue();
    expect(server.notes[0].text).toBe("Edycja bez zasięgu");
  });

  it("notatka dodana offline i niewysłana: edycja zmienia kolejkę, usunięcie usuwa ją z kolejki — bez żądań do serwera", async () => {
    setOnline(false);
    await mutate("/api/rows/7/notes", "POST", { text: "Nowa offline", client_id: "n-off" });
    const fetchMock = fetch;
    fetchMock.mockClear();
    renderNotes(foreman1);
    await screen.findByText("Nowa offline");
    fireEvent.click(within(noteCard("Nowa offline")).getByText("Edytuj"));
    fireEvent.change(screen.getByLabelText("Treść notatki"), { target: { value: "Nowa offline — poprawiona" } });
    fireEvent.click(screen.getByText("Zapisz"));
    await waitFor(() => expect(screen.queryByLabelText("Treść notatki")).toBeNull());
    await screen.findByText("Nowa offline — poprawiona", { selector: "p" });
    expect((await pendingItems()).map(item => item.body.text)).toEqual(["Nowa offline — poprawiona"]);

    fireEvent.click(within(noteCard("Nowa offline — poprawiona")).getByLabelText("Usuń notatkę"));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Usuń notatkę"));
    await waitFor(() => expect(screen.queryByText("Nowa offline — poprawiona")).toBeNull());
    expect(await pendingItems()).toEqual([]);
    expect(fetchMock.mock.calls.filter(([, options = {}]) => options.method && options.method !== "GET")).toEqual([]);
  });

  it("usunięcie z kolejki, gdy inne urządzenie już usunęło notatkę (404), kończy się sukcesem", async () => {
    setOnline(false);
    await mutate("/api/rows/7/notes/1", "DELETE");
    server.notes = server.notes.filter(note => note.id !== 1); // usunięta wcześniej na laptopie kierownika
    setOnline(true);
    expect(await flushQueue()).toBe(1);
    expect(await pendingItems()).toEqual([]);
  });

  it("niewysłane usunięcie zmniejsza licznik notatek rzędu w widoku offline", async () => {
    setOnline(false);
    await mutate("/api/rows/7/notes/1", "DELETE");
    const [updated] = applyPendingRows([{ id: 7, notes_count: 2 }], await pendingItems());
    expect(updated.notes_count).toBe(1);
  });

  it("odświeżenie po synchronizacji pokazuje zmiany z innego urządzenia", async () => {
    const view = renderNotes(manager);
    await screen.findByText("Notatka brygadzisty 2");
    server.notes = server.notes.filter(note => note.id !== 2); // brygadzista usunął na telefonie
    server.notes[0].text = "Zmienione na telefonie";
    view.rerender(<DialogProvider><RowNotes row={row} user={manager} notify={notify} refreshKey={1} /></DialogProvider>);
    await screen.findByText("Zmienione na telefonie");
    expect(screen.queryByText("Notatka brygadzisty 2")).toBeNull();
  });
});
