/* ASOLAR v2, etap 1: lista budów, nowa budowa, przełącznik budów, zespół, ustawienia, adresy. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App, { parseRoute, ProjectSwitcher } from "../src/App";
import ProjectView from "../src/ProjectView";
import Dashboard from "../src/Dashboard";
import { DialogProvider } from "../src/ui";

const admin = { id: 1, username: "kierownik", full_name: "Kierownik Budowy", is_admin: true, active: true };
const foreman = { id: 2, username: "bryg", full_name: "Jan Brygadzista", is_admin: false, active: true };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = (id, name, role = "kierownik", extra = {}) => ({ id, name, location: "Pole", capacity_mw: 5, description: "", archived: false, created_at: "2026-10-28T08:00:00", role, stats: { zones: 0, members: 1, last_activity: null }, ...extra });

let server;
function mockServer() {
  return vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    if (path === "/api/auth/me") return json(server.me);
    if (path.startsWith("/api/projects?")) return json(server.projects.filter(p => path.includes("include_archived=true") || !p.archived));
    if (path === "/api/projects" && method === "GET") return json(server.projects.filter(p => !p.archived));
    if (path === "/api/projects" && method === "POST") { const created = project(server.projects.length + 10, body.name); server.projects.push(created); return json(created); }
    const zones = /^\/api\/projects\/(\d+)\/zones$/.exec(path);
    if (zones) {
      const id = Number(zones[1]);
      if (method === "POST") { (server.zones[id] ||= []).push({ id: Date.now(), name: body.name, description: body.description }); return json({}); }
      return server.delay?.[id] ? new Promise(resolve => setTimeout(() => resolve(json(server.zones[id] || [])), server.delay[id])) : json(server.zones[id] || []);
    }
    const members = /^\/api\/projects\/(\d+)\/members$/.exec(path);
    if (members) { if (method === "PUT") { server.memberCalls.push(body); return json({ ok: true }); } return json(server.members); }
    if (path === "/api/users") return json(server.users);
    const one = /^\/api\/projects\/(\d+)(\?.*)?$/.exec(path);
    if (one) {
      const id = Number(one[1]);
      if (method === "DELETE") { server.deleted.push(path); return json({ ok: true }); }
      const found = server.projects.find(p => p.id === id);
      return found ? json(found) : json({ detail: "Nie znaleziono budowy" }, 404);
    }
    if (path.includes("/events")) return json([]);
    return json({});
  });
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "";
  server = { me: admin, projects: [project(1, "Farma Kalisz"), project(2, "Farma Momo")], zones: { 1: [{ id: 11, name: "Strefa Kalisz A", description: "" }], 2: [{ id: 21, name: "Strefa Momo B", description: "" }] }, members: [], users: [admin, foreman], memberCalls: [], deleted: [], delay: {} };
  vi.stubGlobal("fetch", mockServer());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notify = vi.fn();

describe("adresy widoków", () => {
  it("rozpoznaje listę budów, budowę z zakładką i konta", () => {
    expect(parseRoute("")).toEqual({ view: "dashboard" });
    expect(parseRoute("#/p/12/strefy")).toEqual({ view: "project", projectId: 12, tab: "strefy" });
    expect(parseRoute("#/p/12/nieznana")).toEqual({ view: "project", projectId: 12, tab: "przeglad" });
    expect(parseRoute("#/p/abc")).toEqual({ view: "dashboard" });
    expect(parseRoute("#/konta")).toEqual({ view: "users" });
  });
});

describe("lista budów i nowa budowa", () => {
  it("administrator widzi wszystkie budowy i tworzy nową (Esc anuluje formularz)", async () => {
    const open = vi.fn();
    render(<DialogProvider><Dashboard user={admin} notify={notify} openProject={open} /></DialogProvider>);
    await waitFor(() => expect(screen.getAllByTestId("project-card")).toHaveLength(2));
    fireEvent.click(screen.getByText("+ Nowa budowa"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByText("+ Nowa budowa"));
    fireEvent.change(screen.getByLabelText("Nazwa budowy"), { target: { value: "Farma Konin 8 MW" } });
    fireEvent.click(screen.getByText("Utwórz budowę"));
    await waitFor(() => expect(open).toHaveBeenCalledWith(12));
    expect(notify).toHaveBeenCalledWith(expect.stringContaining("własną przestrzenią danych"));
  });

  it("brygadzista nie ma przycisku „Nowa budowa” i widzi swoją rolę", async () => {
    server.projects = [project(1, "Farma Kalisz", "brygadzista")];
    render(<DialogProvider><Dashboard user={foreman} notify={notify} openProject={() => {}} /></DialogProvider>);
    const card = await screen.findByTestId("project-card");
    expect(within(card).getByText("Brygadzista")).toBeTruthy();
    expect(screen.queryByText("+ Nowa budowa")).toBeNull();
  });
});

describe("przełączanie budów", () => {
  it("przełącznik zachowuje zakładkę i nie pokazuje danych poprzedniej budowy", async () => {
    server.delay = { 1: 80 };
    const navigate = vi.fn();
    const view = render(<DialogProvider><ProjectView key={1} projectId={1} tab="strefy" user={admin} notify={notify} navigate={navigate} /></DialogProvider>);
    // Natychmiastowe przełączenie na budowę 2, zanim odpowiedź dla budowy 1 dotrze.
    view.rerender(<DialogProvider><ProjectView key={2} projectId={2} tab="strefy" user={admin} notify={notify} navigate={navigate} /></DialogProvider>);
    await screen.findByText("Strefa Momo B");
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 120)); });
    expect(screen.queryByText("Strefa Kalisz A")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Farma Momo");
  });

  it("wybór w przełączniku przechodzi do tej samej zakładki innej budowy", async () => {
    const navigate = vi.fn();
    render(<ProjectSwitcher route={{ view: "project", projectId: 1, tab: "zespol" }} navigate={navigate} refreshKey={0} />);
    await screen.findByText("Farma Momo");
    fireEvent.change(screen.getByLabelText("Przełącz budowę"), { target: { value: "2" } });
    expect(navigate).toHaveBeenCalledWith("#/p/2/zespol");
    fireEvent.change(screen.getByLabelText("Przełącz budowę"), { target: { value: "" } });
    expect(navigate).toHaveBeenCalledWith("#/");
  });

  it("budowa bez dostępu: czytelny komunikat zamiast danych", async () => {
    render(<DialogProvider><ProjectView projectId={99} tab="przeglad" user={foreman} notify={notify} navigate={() => {}} /></DialogProvider>);
    await screen.findByText(/nie masz do niej dostępu/);
  });
});

describe("zespół i ustawienia", () => {
  it("kierownik dodaje osobę z rolą brygadzisty", async () => {
    server.members = [{ user: admin, role: "kierownik", since: null }];
    render(<DialogProvider><ProjectView projectId={1} tab="zespol" user={admin} notify={notify} navigate={() => {}} /></DialogProvider>);
    const select = await screen.findByLabelText("Konto");
    await waitFor(() => expect(within(select).getByText(/Jan Brygadzista/)).toBeTruthy());
    fireEvent.change(select, { target: { value: "2" } });
    fireEvent.click(screen.getByText("Dodaj do zespołu"));
    await waitFor(() => expect(server.memberCalls).toEqual([{ user_id: 2, role: "brygadzista" }]));
  });

  it("usunięcie budowy wymaga archiwizacji i przepisania nazwy", async () => {
    server.projects[0].archived = true;
    render(<DialogProvider><ProjectView projectId={1} tab="ustawienia" user={admin} notify={notify} navigate={() => {}} /></DialogProvider>);
    fireEvent.click(await screen.findByText("Usuń budowę"));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Usuń budowę").disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Farma Kalisz" } });
    fireEvent.click(within(dialog).getByText("Usuń budowę"));
    await waitFor(() => expect(server.deleted).toEqual(["/api/projects/1?confirm_name=Farma%20Kalisz"]));
  });

  it("brygadzista nie zmienia ustawień budowy", async () => {
    server.projects = [project(1, "Farma Kalisz", "brygadzista")];
    render(<DialogProvider><ProjectView projectId={1} tab="ustawienia" user={foreman} notify={notify} navigate={() => {}} /></DialogProvider>);
    await screen.findByText("Ustawienia budowy zmienia kierownik.");
  });
});

describe("aplikacja", () => {
  it("logowanie bez wpisanych danych i bez haseł w kodzie", async () => {
    render(<App />);
    expect(screen.getByLabelText("Login").value).toBe("");
    expect(document.querySelector('input[type="password"]').value).toBe("");
  });

  it("zalogowany użytkownik widzi listę budów i przechodzi do budowy", async () => {
    localStorage.setItem("asolar2_token", "t");
    localStorage.setItem("asolar2_user", JSON.stringify(admin));
    render(<App />);
    await waitFor(() => expect(screen.getAllByTestId("project-card")).toHaveLength(2));
    fireEvent.click(within(screen.getAllByTestId("project-card")[1]).getByText("Otwórz"));
    await waitFor(() => expect(window.location.hash).toBe("#/p/2/przeglad"));
    await screen.findByRole("heading", { level: 1, name: "Farma Momo" });
  });
});
