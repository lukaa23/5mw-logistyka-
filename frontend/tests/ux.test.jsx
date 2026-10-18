/* Ergonomia: okno potwierdzenia (Enter/Esc), stany ładowania, Edytuj/Zapisz/Anuluj/Usuń przy rekordach. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../src/api", async importOriginal => ({ ...(await importOriginal()), api: vi.fn(), cachedGet: vi.fn(), mutate: vi.fn(), pendingItems: vi.fn(async () => []) }));

import { api, cachedGet, mutate } from "../src/api";
import { PhotoGallery, Projects, RfiPage, Users } from "../src/App";
import { AsyncButton, DialogProvider, useAskText, useConfirm } from "../src/ui";

const manager = { id: 1, role: "kierownik", full_name: "Kierownik Budowy" };
const foreman1 = { id: 2, role: "brygadzista", full_name: "Brygadzista 1" };
const foreman2 = { id: 3, role: "brygadzista", full_name: "Brygadzista 2" };
const notify = vi.fn();
const withDialogs = ui => render(<DialogProvider>{ui}</DialogProvider>);
const key = (target, name, extra = {}) => fireEvent.keyDown(target, { key: name, ...extra });

beforeEach(() => { notify.mockClear(); localStorage.clear(); URL.createObjectURL = vi.fn(() => "blob:test"); URL.revokeObjectURL = vi.fn(); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function ConfirmProbe({ options, onResult }) {
  const confirm = useConfirm();
  return <button onClick={async () => onResult(await confirm(options))}>Otwórz</button>;
}
function AskProbe({ onResult }) {
  const ask = useAskText();
  return <button onClick={async () => onResult(await ask({ title: "Nowe hasło", input: { label: "Hasło", type: "password", minLength: 8 } }))}>Pytaj</button>;
}

describe("okno potwierdzenia", () => {
  it("Esc anuluje, Enter potwierdza, kliknięcie tła anuluje", async () => {
    const results = [];
    withDialogs(<ConfirmProbe options={{ title: "Usunąć?", message: "Na pewno?", danger: true }} onResult={value => results.push(value)} />);
    fireEvent.click(screen.getByText("Otwórz"));
    key(screen.getByRole("alertdialog"), "Escape");
    await waitFor(() => expect(results).toEqual([false]));
    expect(screen.queryByRole("alertdialog")).toBeNull();

    fireEvent.click(screen.getByText("Otwórz"));
    expect(document.activeElement.textContent).toBe("Usuń");
    key(screen.getByRole("alertdialog"), "Enter");
    await waitFor(() => expect(results).toEqual([false, true]));

    fireEvent.click(screen.getByText("Otwórz"));
    fireEvent.mouseDown(document.querySelector(".dialog-overlay"));
    await waitFor(() => expect(results).toEqual([false, true, false]));
  });

  it("wymagany tekst blokuje potwierdzenie do czasu przepisania nazwy", async () => {
    const results = [];
    withDialogs(<ConfirmProbe options={{ title: "Usunąć projekt?", requireText: "Farma A", danger: true }} onResult={value => results.push(value)} />);
    fireEvent.click(screen.getByText("Otwórz"));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Usuń").disabled).toBe(true);
    key(dialog, "Enter");
    expect(results).toEqual([]);
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Farma A" } });
    key(within(dialog).getByRole("textbox"), "Enter");
    await waitFor(() => expect(results).toEqual([true]));
  });

  it("pytanie o hasło wymaga minimalnej długości i zwraca wpisany tekst", async () => {
    const results = [];
    withDialogs(<AskProbe onResult={value => results.push(value)} />);
    fireEvent.click(screen.getByText("Pytaj"));
    const input = screen.getByLabelText(/Hasło/);
    fireEvent.change(input, { target: { value: "krótkie" } });
    key(input, "Enter");
    expect(results).toEqual([]);
    fireEvent.change(input, { target: { value: "Dlugie-haslo-1" } });
    key(input, "Enter");
    await waitFor(() => expect(results).toEqual(["Dlugie-haslo-1"]));
  });
});

describe("przycisk ze stanem ładowania", () => {
  it("pokazuje stan „Zapisywanie…”, blokuje podwójne kliknięcie", async () => {
    let finish;
    const action = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    render(<AsyncButton onClick={action} busyLabel="Zapisywanie…">Zapisz</AsyncButton>);
    fireEvent.click(screen.getByText("Zapisz"));
    expect(screen.getByText("Zapisywanie…").disabled).toBe(true);
    fireEvent.click(screen.getByText("Zapisywanie…"));
    expect(action).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    expect(screen.getByText("Zapisz").disabled).toBe(false);
  });
});

describe("RFI: Edytuj / Zapisz / Anuluj / Usuń", () => {
  const rfi = { id: 5, title: "Kolizja", description: "Opis", priority: "normalny", status: "otwarty", created_by: "Brygadzista 1", created_by_id: 2, created_at: "2026-10-18T08:00:00", photos: 0, row_id: null };
  beforeEach(() => {
    cachedGet.mockImplementation(async path => (path.startsWith("/api/rfis") ? [rfi] : path === "/api/team" ? [manager, foreman1, foreman2] : []));
    mutate.mockResolvedValue({ ok: true });
    api.mockResolvedValue([]);
  });
  const renderRfi = user => withDialogs(<RfiPage project={{ id: 1 }} sync={0} notify={notify} user={user} clearPreselected={() => {}} />);

  it("autor edytuje własne zgłoszenie; Esc anuluje; Zapisz wysyła zmiany", async () => {
    renderRfi(foreman1);
    fireEvent.click(await screen.findByText("Edytuj"));
    expect(screen.getByDisplayValue("Kolizja")).toBeTruthy();
    key(window, "Escape");
    await waitFor(() => expect(screen.queryByDisplayValue("Kolizja")).toBeNull());
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Edytuj"));
    fireEvent.change(screen.getByDisplayValue("Kolizja"), { target: { value: "Kolizja słupa z drogą" } });
    fireEvent.click(screen.getByText("Zapisz"));
    await waitFor(() => expect(mutate).toHaveBeenCalledWith("/api/rfis/5", "PATCH", expect.objectContaining({ title: "Kolizja słupa z drogą" })));
    expect(notify).toHaveBeenCalledWith("Zapisano zmiany zgłoszenia");
    expect(screen.queryByText("Usuń")).toBeNull(); // brygadzista nie usuwa
  });

  it("inny brygadzista nie edytuje cudzego zgłoszenia", async () => {
    renderRfi(foreman2);
    await screen.findByText("#5 Kolizja");
    expect(screen.queryByText("Edytuj")).toBeNull();
  });

  it("kierownik usuwa po potwierdzeniu; anulowanie w oknie nic nie usuwa", async () => {
    renderRfi(manager);
    fireEvent.click(await screen.findByText("Usuń"));
    expect(screen.getByRole("alertdialog").textContent).toContain("RFI #5");
    fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Anuluj"));
    expect(mutate).not.toHaveBeenCalledWith("/api/rfis/5", "DELETE");
    fireEvent.click(screen.getByText("Usuń"));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Usuń RFI"));
    await waitFor(() => expect(mutate).toHaveBeenCalledWith("/api/rfis/5", "DELETE"));
    expect(notify).toHaveBeenCalledWith("RFI usunięte");
  });
});

describe("Użytkownicy i projekty", () => {
  it("edycja danych z Anuluj oraz zmiana hasła w oknie zamiast window.prompt", async () => {
    cachedGet.mockResolvedValue([{ ...foreman1, username: "brygadzista1", active: true }]);
    api.mockResolvedValue({});
    const prompt = vi.spyOn(window, "prompt");
    withDialogs(<Users notify={notify} user={manager} />);
    fireEvent.click(await screen.findByText("Edytuj"));
    fireEvent.click(screen.getByText("Anuluj"));
    expect(screen.queryByDisplayValue("Brygadzista 1")).toBeNull();

    fireEvent.click(screen.getByText("Zmień hasło"));
    const input = screen.getByRole("alertdialog").querySelector('input[type="password"]');
    fireEvent.change(input, { target: { value: "Nowe-haslo-2026" } });
    key(input, "Enter");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/2", { method: "PATCH", body: JSON.stringify({ password: "Nowe-haslo-2026" }) }));
    expect(prompt).not.toHaveBeenCalled();
  });

  it("„+ Nowy projekt” w nagłówku, usunięcie wymaga przepisania nazwy", async () => {
    const reload = vi.fn();
    api.mockResolvedValue({ ok: true });
    withDialogs(<Projects projects={[{ id: 9, name: "Farma B", location: "", capacity_mw: 1, archived: true }]} reloadProjects={reload} notify={notify} user={manager} setProjectId={() => {}} projectId={null} />);
    expect(screen.getByText("+ Nowy projekt")).toBeTruthy();
    fireEvent.click(screen.getByText("Usuń"));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Farma" } });
    expect(within(dialog).getByText("Usuń projekt").disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Farma B" } });
    fireEvent.click(within(dialog).getByText("Usuń projekt"));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/projects/9", { method: "DELETE" }));
  });

  it("edycja projektu: Esc anuluje i czyści formularz", async () => {
    withDialogs(<Projects projects={[{ id: 3, name: "Farma C", location: "Łódź", capacity_mw: 2, archived: false }]} reloadProjects={vi.fn()} notify={notify} user={manager} setProjectId={() => {}} projectId={3} />);
    fireEvent.click(screen.getByText("Edytuj"));
    expect(screen.getByText("Edytuj projekt")).toBeTruthy();
    expect(screen.getByDisplayValue("Farma C")).toBeTruthy();
    key(window, "Escape");
    await waitFor(() => expect(screen.getByText("Nowy projekt")).toBeTruthy());
    expect(screen.queryByDisplayValue("Farma C")).toBeNull();
  });
});

describe("zdjęcia", () => {
  it("brygadzista usuwa tylko własne zdjęcie, po potwierdzeniu", async () => {
    api.mockImplementation(async path => (path === "/api/rfi/7/photos" ? [
      { id: 11, filename: "moje.jpg", uploaded_by: "Brygadzista 1", uploaded_by_id: 2, created_at: "2026-10-18T08:00:00", url: "/api/attachments/11" },
      { id: 12, filename: "cudze.jpg", uploaded_by: "Brygadzista 2", uploaded_by_id: 3, created_at: "2026-10-18T08:00:00", url: "/api/attachments/12" },
    ] : path.startsWith("/api/attachments/") ? new Blob(["x"]) : { ok: true }));
    withDialogs(<PhotoGallery entityType="rfi" entityId={7} notify={notify} user={foreman1} />);
    await screen.findByAltText("moje.jpg");
    expect(screen.getByLabelText("Usuń zdjęcie moje.jpg")).toBeTruthy();
    expect(screen.queryByLabelText("Usuń zdjęcie cudze.jpg")).toBeNull();
    fireEvent.click(screen.getByLabelText("Usuń zdjęcie moje.jpg"));
    key(screen.getByRole("alertdialog"), "Enter");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/attachments/11", { method: "DELETE" }));
    expect(notify).toHaveBeenCalledWith("Zdjęcie usunięte");
  });
});
