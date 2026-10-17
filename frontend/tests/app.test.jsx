import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import App from "../src/App";
import ErrorBoundary from "../src/ErrorBoundary";
import { flushQueue, mutate, queuedCount } from "../src/api";

const setOnline = value => Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => value });

beforeEach(() => { localStorage.clear(); setOnline(true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("logowanie", () => {
  it("formularz nie zawiera wpisanego loginu ani hasła", () => {
    render(<App />);
    const password = document.querySelector('input[type="password"]');
    expect(password.value).toBe("");
    expect(screen.getByLabelText("Login").value).toBe("");
  });

  it("kod frontendu nie zawiera haseł startowych", () => {
    for (const file of ["../src/App.jsx", "../src/api.js", "../src/PlanMap.jsx"]) {
      const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), "utf8");
      expect(source).not.toMatch(/Asolar2026!|Brygada1-2026!|Brygada2-2026!/);
    }
  });
});

describe("ErrorBoundary", () => {
  it("pokazuje komunikat zamiast białego ekranu", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = () => { throw new TypeError("Cannot read properties of undefined (reading 'title')"); };
    render(<ErrorBoundary><Broken /></ErrorBoundary>);
    expect(screen.getByRole("alert").textContent).toContain("reading 'title'");
  });
});

describe("kolejka offline", () => {
  it("zapisuje proste zapisy offline i wysyła je po odzyskaniu sieci z tym samym client_id", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    setOnline(false);
    const result = await mutate("/api/rows/5/notes", "POST", { text: "Offline", client_id: "abc-1" });
    expect(result.queued).toBe(true);
    expect(queuedCount()).toBe(1);
    expect(fetchMock).not.toHaveBeenCalled();

    setOnline(true);
    expect(await flushQueue()).toBe(1);
    expect(queuedCount()).toBe(0);
    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/rows/5/notes");
    expect(JSON.parse(options.body).client_id).toBe("abc-1");
    vi.unstubAllGlobals();
  });

  it("zachowuje zapis w kolejce, gdy serwer nadal jest nieosiągalny", async () => {
    setOnline(false);
    await mutate("/api/worklogs", "POST", { client_id: "log-1" });
    setOnline(true);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    expect(await flushQueue()).toBe(0);
    expect(queuedCount()).toBe(1);
    vi.unstubAllGlobals();
  });
});
