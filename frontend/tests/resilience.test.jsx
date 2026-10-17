/* Test odporności: brak sieci, zerwanie połączenia podczas wysyłania zdjęć, błędy wczytania
 * komponentów i błędy globalne — w żadnym scenariuszu nie może pojawić się biały ekran. */
import "fake-indexeddb/auto";
import React, { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { applyPendingRows, flushQueue, mutate, pendingItems, queuedCount, retryFailed, savePhotos } from "../src/api";
import { exportBackup, importBackup, resetOfflineStore } from "../src/offlineStore";
import ErrorBoundary from "../src/ErrorBoundary";
import { installGlobalErrorHandlers, lazyWithRetry, errorLog } from "../src/errors";
import App from "../src/App";

const setOnline = value => Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => value });
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const photo = (name = "foto.jpg", bytes = [1, 2, 3, 4]) => new File([new Uint8Array(bytes)], name, { type: "image/jpeg" });
const networkDown = () => Promise.reject(new TypeError("Failed to fetch"));

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("asolar_token", "test-token");
  setOnline(true);
  await resetOfflineStore();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("praca bez zasięgu i synchronizacja", () => {
  it("statusy, notatki i zdjęcia zapisane offline trafiają do IndexedDB i są wysyłane po odzyskaniu sieci", async () => {
    const fetchMock = vi.fn(networkDown);
    vi.stubGlobal("fetch", fetchMock);
    setOnline(false);
    expect((await mutate("/api/rows/7", "PATCH", { built: true })).queued).toBe(true);
    expect((await mutate("/api/rows/7/notes", "POST", { text: "Brak śruby M16", client_id: "n-1" })).queued).toBe(true);
    expect(await savePhotos("row", 7, [photo()])).toEqual({ sent: 0, queued: 1 });
    expect(queuedCount()).toBe(3);
    expect(fetchMock).not.toHaveBeenCalled();

    const items = await pendingItems();
    expect(items.map(item => item.kind)).toEqual(["json", "json", "photo"]);
    expect(items[0].body.client_time).toBeTruthy();
    expect(new Uint8Array(items[2].data)).toEqual(new Uint8Array([1, 2, 3, 4]));

    setOnline(true);
    fetchMock.mockImplementation(async () => json({ id: 1 }));
    expect(await flushQueue()).toBe(3);
    expect(queuedCount()).toBe(0);
    const [statusCall, noteCall, photoCall] = fetchMock.mock.calls;
    expect(statusCall[0]).toBe("/api/rows/7");
    expect(JSON.parse(noteCall[1].body).client_id).toBe("n-1");
    expect(photoCall[0]).toBe("/api/row/7/photos");
    expect(photoCall[1].body.get("client_id")).toMatch(/^photo-/);
    expect(photoCall[1].body.get("client_time")).toBeTruthy();
  });

  it("zerwanie połączenia w trakcie wysyłania zdjęcia zapisuje je w telefonie bez błędu i bez duplikatu", async () => {
    const fetchMock = vi.fn(networkDown);
    vi.stubGlobal("fetch", fetchMock);
    const result = await savePhotos("row", 3, [photo("a.jpg"), photo("b.jpg")]);
    expect(result).toEqual({ sent: 0, queued: 2 });
    const firstAttemptIds = fetchMock.mock.calls.map(call => call[1].body.get("client_id"));

    fetchMock.mockImplementation(async () => json({ id: 9 }));
    expect(await flushQueue()).toBe(2);
    const resentIds = fetchMock.mock.calls.slice(2).map(call => call[1].body.get("client_id"));
    expect(resentIds).toEqual(firstAttemptIds); // ten sam client_id → serwer nie utworzy duplikatu
  });

  it("połączenie zrywa się w połowie kolejki — wysłane wpisy znikają, reszta czeka", async () => {
    setOnline(false);
    for (const id of [1, 2, 3]) await mutate(`/api/rows/${id}`, "PATCH", { built: true });
    setOnline(true);
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => (++calls === 2 ? networkDown() : json({ ok: true }))));
    expect(await flushQueue()).toBe(1);
    expect(queuedCount()).toBe(2);
  });

  it("odpowiedź 4xx oznacza wpis jako odrzucony, ale go nie usuwa i nie blokuje kolejnych", async () => {
    setOnline(false);
    await mutate("/api/rows/1", "PATCH", { qc_checked: true });
    await mutate("/api/rows/2", "PATCH", { built: true });
    setOnline(true);
    vi.stubGlobal("fetch", vi.fn(async path => path === "/api/rows/1" ? json({ detail: "Najpierw oznacz rząd jako zbudowany" }, 400) : json({ ok: true })));
    expect(await flushQueue()).toBe(1);
    const [rejected] = await pendingItems();
    expect(rejected.failed).toBe(true);
    expect(rejected.lastError).toContain("Najpierw oznacz");
    vi.stubGlobal("fetch", vi.fn(async () => json({ ok: true })));
    await retryFailed();
    expect(await pendingItems()).toEqual([]);
  });

  it("zdjęcie do meldunku utworzonego offline jest wysyłane po meldunku i wskazuje go przez client_id", async () => {
    setOnline(false);
    await mutate("/api/worklogs", "POST", { project_id: 1, stage: "Płatwie", client_id: "log-offline" });
    await savePhotos("worklog", null, [photo()], { parentClientId: "log-offline" });
    setOnline(true);
    const fetchMock = vi.fn(async () => json({ id: 5 }));
    vi.stubGlobal("fetch", fetchMock);
    await flushQueue();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/worklogs", "/api/worklog/by-client/log-offline/photos"]);
  });

  it("niewysłane zmiany są nakładane na zapisaną kopię rzędów", async () => {
    setOnline(false);
    await mutate("/api/rows/10", "PATCH", { built: false });
    await mutate("/api/rows/10/notes", "POST", { text: "x", client_id: "n" });
    await savePhotos("row", 11, [photo()]);
    const rows = applyPendingRows([{ id: 10, built: true, qc_checked: true, notes_count: 1, photos: 0 }, { id: 11, built: false, photos: 2 }, { id: 12, built: true }], await pendingItems());
    expect(rows[0]).toMatchObject({ built: false, qc_checked: false, notes_count: 2, pending_sync: true });
    expect(rows[1]).toMatchObject({ photos: 3, pending_sync: true });
    expect(rows[2].pending_sync).toBeUndefined();
  });

  it("kopia niewysłanych zmian (z bajtami zdjęć) daje się zapisać i przywrócić", async () => {
    setOnline(false);
    await mutate("/api/rows/4/notes", "POST", { text: "kopia", client_id: "backup-1" });
    await savePhotos("row", 4, [photo("k.jpg", [9, 8, 7])]);
    const backup = JSON.parse(JSON.stringify(await exportBackup()));
    expect(backup.items).toHaveLength(2);
    await resetOfflineStore();
    expect(await importBackup(backup)).toBe(2);
    expect(await importBackup(backup)).toBe(0); // bez duplikatów
    const restored = await pendingItems();
    expect(new Uint8Array(restored.find(item => item.kind === "photo").data)).toEqual(new Uint8Array([9, 8, 7]));
    await expect(importBackup({ app: "inna" })).rejects.toThrow("kopii ASOLAR");
  });
});

describe("brak białego ekranu", () => {
  it("aplikacja uruchomiona bez sieci pokazuje zapamiętane konto i tryb offline zamiast logowania", async () => {
    localStorage.setItem("asolar_user", JSON.stringify({ id: 2, username: "brygadzista1", full_name: "Brygadzista 1", role: "brygadzista" }));
    setOnline(false);
    vi.stubGlobal("fetch", vi.fn(networkDown));
    vi.stubGlobal("WebSocket", class { close() {} });
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Brygadzista 1").length).toBeGreaterThan(0));
    expect(screen.getByText("Offline")).toBeTruthy();
    expect(screen.queryByText("Zaloguj się")).toBeNull();
    expect(document.body.textContent.trim().length).toBeGreaterThan(50);
  });

  it("błąd wczytania modułu (brak sieci) pokazuje ekran ratunkowy z przyciskiem odświeżenia", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = lazyWithRetry(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")), 1, 1);
    render(<ErrorBoundary fullScreen><Suspense fallback={<p>ładowanie</p>}><Broken /></Suspense></ErrorBoundary>);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText(/brak połączenia z serwerem/)).toBeTruthy();
    expect(screen.getByText("Odśwież aplikację")).toBeTruthy();
    expect(screen.getByText("Przywróć dane z kopii")).toBeTruthy();
  });

  it("chwilowy błąd wczytania modułu jest ponawiany", async () => {
    let attempts = 0;
    const Lazy = lazyWithRetry(async () => { attempts += 1; if (attempts === 1) throw new TypeError("Failed to fetch"); return { default: () => <p>Moduł działa</p> }; }, 1, 1);
    render(<ErrorBoundary><Suspense fallback={<p>ładowanie</p>}><Lazy /></Suspense></ErrorBoundary>);
    await waitFor(() => expect(screen.getByText("Moduł działa")).toBeTruthy());
    expect(attempts).toBe(2);
  });

  it("przycisk „Odśwież aplikację” przeładowuje stronę, a „Spróbuj ponownie” odtwarza widok", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    let fail = true;
    const Flaky = () => { if (fail) throw new Error("Cannot read properties of undefined (reading 'title')"); return <p>Widok wrócił</p>; };
    render(<ErrorBoundary fullScreen><Flaky /></ErrorBoundary>);
    fireEvent.click(screen.getByText("Odśwież aplikację"));
    expect(reload).toHaveBeenCalled();
    fail = false;
    fireEvent.click(screen.getByText("Spróbuj ponownie"));
    expect(screen.getByText("Widok wrócił")).toBeTruthy();
  });

  it("nieobsłużone błędy i odrzucone obietnice są rejestrowane zamiast przerywać aplikację", () => {
    installGlobalErrorHandlers(window);
    const seen = [];
    window.addEventListener("asolar:error", event => seen.push(event.detail.message));
    const rejection = new Event("unhandledrejection");
    rejection.reason = new Error("Serwer zerwał połączenie");
    window.dispatchEvent(rejection);
    window.dispatchEvent(new ErrorEvent("error", { error: new Error("Błąd w obsłudze kliknięcia"), message: "Błąd w obsłudze kliknięcia" }));
    expect(seen).toEqual(["Serwer zerwał połączenie", "Błąd w obsłudze kliknięcia"]);
    expect(errorLog()[0].message).toBe("Błąd w obsłudze kliknięcia");
  });

  it("gdy główny skrypt się nie wczyta, index.html pokazuje ekran ratunkowy", () => {
    const html = readFileSync(resolve(__dirname, "../index.html"), "utf8");
    const inline = html.match(/<script>([\s\S]*?)<\/script>/)[1];
    delete window.__asolarMounted;
    new Function(inline)();
    const script = document.createElement("script");
    document.head.appendChild(script);
    script.dispatchEvent(new Event("error"));
    const rescue = document.getElementById("asolar-rescue");
    expect(rescue).toBeTruthy();
    expect(rescue.textContent).toContain("Odśwież aplikację");
    expect(rescue.textContent).toContain("Wyczyść pamięć podręczną");
    rescue.remove();
  });
});
