import React, { useCallback, useEffect, useState } from "react";
import { api, getCachedUser, getToken, send, setSession } from "./api";
import Dashboard from "./Dashboard";
import ProjectView, { TABS } from "./ProjectView";
import UsersAdmin from "./UsersAdmin";
import SyncStatus, { useAutoFlush } from "./Sync";
import { cachedGet, clearCache } from "./offline";
import { DialogProvider, Loader } from "./ui";
import { useLoad } from "./useLoad";

export const APP_VERSION = "2.4.0";
const LAST_PROJECT = "asolar2_last_project";

/** Adres w pasku: #/ — budowy, #/p/12/strefy — budowa i zakładka, #/konta — konta. */
export function parseRoute(hash) {
  const parts = String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "p" && /^\d+$/.test(parts[1] || "")) {
    const tab = TABS.some(([id]) => id === parts[2]) ? parts[2] : "przeglad";
    return { view: "project", projectId: Number(parts[1]), tab };
  }
  if (parts[0] === "konta") return { view: "users" };
  return { view: "dashboard" };
}

function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await send("/api/auth/login", "POST", form); setSession(result.token, result.user); onLogin(result.user); }
    catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }
  return <main className="login-page"><section className="login-brand"><div className="brand-mark large">A</div><p className="eyebrow">ASOLAR · WERSJA 2</p><h1>Wiele budów. Jedno miejsce.</h1><p>Każda farma PV ma własną, odizolowaną przestrzeń danych. Przełączaj się między budowami jednym kliknięciem.</p></section>
    <section className="login-panel"><form className="login-card" onSubmit={submit}><p className="eyebrow">ASOLAR · v{APP_VERSION}</p><h2>Zaloguj się</h2>
      <label>Login<input required autoComplete="username" value={form.username} onChange={e => setForm(c => ({ ...c, username: e.target.value }))} /></label>
      <label>Hasło<input required type="password" autoComplete="current-password" value={form.password} onChange={e => setForm(c => ({ ...c, password: e.target.value }))} /></label>
      {error && <div className="alert error" role="alert">{error}</div>}
      <button className="primary wide" disabled={busy}>{busy ? "Logowanie…" : "Zaloguj się"}</button></form></section></main>;
}

/* Nawigacja jak w v1: te same pozycje, ikony i kolejność — działają na aktywnej budowie. */
export const NAV = [
  ["przeglad", "Pulpit", "▦"],
  ["budowy", "Budowy", "◆"],
  ["strefy", "Strefy i rzędy", "▤"],
  ["meldunki", "Meldunki", "◷"],
  ["materialy", "Zapotrzebowanie", "⌗"],
  ["dostawy", "Dostawy na budowę", "⇩"],
  ["planimetria", "Mapa / Planimetria", "⌖"],
  ["dokumenty", "Dokumenty", "▱"],
  ["konstrukcje", "Konstrukcje i BOM", "⚙"],
  ["zespol", "Zespół", "♙"],
  ["ustawienia", "Ustawienia budowy", "✎"],
];
// Na telefonie „Rzędy” prowadzi od razu do widoku operacyjnego (praca w terenie), jak w v1.
const MOBILE_NAV = [["przeglad", "Pulpit", "▦"], ["postep", "Rzędy", "▤"], ["meldunki", "Meldunki", "◷"], ["dostawy", "Dostawy", "⇩"], ["planimetria", "Mapa", "⌖"], ["dokumenty", "Dokumenty", "▱"], ["materialy", "Zapotrzebowanie", "⌗"], ["budowy", "Budowy", "◆"]];
const SECTION_OF = { postep: "strefy", stoly: "strefy" };  // widoki należące do pozycji „Strefy i rzędy”

/** Przełącznik budów w górnym pasku (jak „Aktywny projekt” w v1) — zmiana budowy zachowuje bieżący widok. */
export function ProjectSwitcher({ route, navigate, refreshKey }) {
  // Odświeżany po akcjach w aplikacji i przy każdej zmianie widoku (np. nowa budowa dodana przez kogoś innego).
  const { data: projects } = useLoad(() => cachedGet("/api/projects"), [refreshKey, route.view, route.projectId]);
  const value = route.view === "project" ? String(route.projectId) : "";
  return <label className="project-select"><span>Aktywna budowa</span>
    <select aria-label="Przełącz budowę" value={value} onChange={event => navigate(event.target.value ? `#/p/${event.target.value}/${route.view === "project" ? route.tab : "przeglad"}` : "#/")}>
      <option value="">— wszystkie budowy —</option>
      {(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}{project.capacity_mw ? ` · ${project.capacity_mw} MW` : ""}</option>)}
      {route.view === "project" && projects && !projects.some(p => p.id === route.projectId) && <option value={route.projectId}>Budowa #{route.projectId}</option>}
    </select></label>;
}

function Shell({ user, onLogout }) {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  const [toast, setToast] = useState(null);
  const [switcherKey, setSwitcherKey] = useState(0);
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => { if (route.view === "project") localStorage.setItem(LAST_PROJECT, String(route.projectId)); }, [route]);
  const navigate = useCallback(hash => { if (window.location.hash !== hash) window.location.hash = hash; else setRoute(parseRoute(hash)); window.scrollTo?.({ top: 0 }); }, []);
  const notify = useCallback((message, type = "success") => { setToast({ message, type }); setSwitcherKey(key => key + 1); setTimeout(() => setToast(null), 4200); }, []);
  useAutoFlush(true);
  const { data: projects } = useLoad(() => cachedGet("/api/projects"), [switcherKey]);
  // Aktywna budowa: otwarta teraz, ostatnio używana albo pierwsza z listy (jak domyślny projekt w v1).
  const last = Number(localStorage.getItem(LAST_PROJECT) || 0);
  const activeId = route.view === "project" ? route.projectId
    : (projects || []).some(item => item.id === last) ? last : projects?.[0]?.id ?? null;
  const tab = route.view === "project" ? route.tab : route.view === "users" ? "konta" : "budowy";
  const current = SECTION_OF[tab] || tab;
  const go = id => {
    if (id === "budowy") return navigate("#/");
    if (id === "konta") return navigate("#/konta");
    return navigate(activeId ? `#/p/${activeId}/${id}` : "#/");
  };
  const items = [...NAV, ...(user.is_admin ? [["konta", "Użytkownicy", "♙"]] : [])];
  const initials = user.full_name.split(" ").map(x => x[0]).slice(0, 2).join("");
  const navButton = ([id, label, icon], small) => <button type="button" key={id} className={current === id ? "active" : ""} aria-current={current === id ? "page" : undefined}
    disabled={!activeId && !["budowy", "konta"].includes(id)} onClick={() => go(id)}><span>{icon}</span>{small ? <small>{label.split(" ")[0]}</small> : label}</button>;
  return <div className="app-shell">
    <aside className="sidebar">
      <button type="button" className="logo" onClick={() => navigate("#/")}><div className="brand-mark">A</div><div><strong>ASOLAR</strong><small>Wiele budów · v{APP_VERSION}</small></div></button>
      <nav aria-label="Nawigacja">{items.map(item => navButton(item))}</nav>
      <div className="sidebar-foot"><div className="user-mini"><div className="avatar">{initials}</div><div><strong>{user.full_name}</strong><small>{user.is_admin ? "Administrator" : "Użytkownik"}</small></div></div><button type="button" className="logout" onClick={onLogout}>Wyloguj</button></div>
    </aside>
    <header className="topbar">
      <button type="button" className="mobile-logo" onClick={() => navigate("#/")}><div className="brand-mark">A</div><strong>ASOLAR <small>v{APP_VERSION}</small></strong></button>
      <ProjectSwitcher route={route} navigate={navigate} refreshKey={switcherKey} />
      <SyncStatus notify={notify} />
      <button type="button" className="avatar top-avatar" title={`${user.full_name} — wyloguj`} onClick={onLogout}>{initials}</button>
    </header>
    <main className="content">
      {route.view === "project" ? <ProjectView key={route.projectId} projectId={route.projectId} tab={route.tab} user={user} notify={notify} navigate={navigate} />
        : route.view === "users" ? <UsersAdmin user={user} notify={notify} />
          : <Dashboard user={user} notify={notify} openProject={id => navigate(`#/p/${id}/przeglad`)} />}
    </main>
    <nav className="bottom-nav" aria-label="Nawigacja (telefon)">{MOBILE_NAV.map(item => <button type="button" key={item[0]} className={tab === item[0] || (item[0] === "postep" && tab === "strefy") ? "active" : ""} disabled={!activeId && item[0] !== "budowy"} onClick={() => go(item[0])}><span>{item[2]}</span><small>{item[1]}</small></button>)}</nav>
    {toast && <div className={`toast ${toast.type}`} role={toast.type === "error" ? "alert" : "status"} aria-live="polite" onClick={() => setToast(null)}>{toast.type === "error" ? "!" : "✓"}<span>{toast.message}</span></div>}
  </div>;
}

export default function App() {
  const [user, setUser] = useState(() => (getToken() ? getCachedUser() : null));
  const [checking, setChecking] = useState(!!getToken());
  useEffect(() => {
    if (!getToken()) return;
    api("/api/auth/me").then(value => { setSession(getToken(), value); setUser(value); }).catch(error => { if (error.status === 401) setUser(null); }).finally(() => setChecking(false));
    const logout = () => setUser(null);
    window.addEventListener("asolar2:unauthorized", logout);
    return () => window.removeEventListener("asolar2:unauthorized", logout);
  }, []);
  if (checking && !user) return <Loader />;
  return <DialogProvider>{user ? <Shell user={user} onLogout={() => { setSession(null); clearCache(); setUser(null); }} /> : <Login onLogin={setUser} />}</DialogProvider>;
}
