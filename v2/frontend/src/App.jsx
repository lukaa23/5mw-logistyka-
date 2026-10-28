import React, { useCallback, useEffect, useState } from "react";
import { api, getCachedUser, getToken, send, setSession } from "./api";
import Dashboard from "./Dashboard";
import ProjectView, { TABS } from "./ProjectView";
import UsersAdmin from "./UsersAdmin";
import { DialogProvider, Loader } from "./ui";
import { useLoad } from "./useLoad";

export const APP_VERSION = "2.0 · etap 3";
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

/** Przełącznik budów w górnym pasku — zmiana budowy zachowuje bieżącą zakładkę. */
export function ProjectSwitcher({ route, navigate, refreshKey }) {
  // Odświeżany po akcjach w aplikacji i przy każdej zmianie widoku (np. nowa budowa dodana przez kogoś innego).
  const { data: projects } = useLoad(() => api("/api/projects"), [refreshKey, route.view, route.projectId]);
  const value = route.view === "project" ? String(route.projectId) : "";
  return <label className="project-select"><span>Budowa</span>
    <select aria-label="Przełącz budowę" value={value} onChange={event => navigate(event.target.value ? `#/p/${event.target.value}/${route.view === "project" ? route.tab : "przeglad"}` : "#/")}>
      <option value="">Wszystkie budowy</option>
      {(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
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
  const initials = user.full_name.split(" ").map(x => x[0]).slice(0, 2).join("");
  return <div className="app-shell v2">
    <header className="topbar v2-topbar">
      <button type="button" className="mobile-logo home-link" onClick={() => navigate("#/")}><div className="brand-mark">A</div><strong>ASOLAR <small>v{APP_VERSION}</small></strong></button>
      <ProjectSwitcher route={route} navigate={navigate} refreshKey={switcherKey} />
      <nav className="top-links"><button type="button" className={route.view === "dashboard" ? "active" : ""} onClick={() => navigate("#/")}>Budowy</button>{user.is_admin && <button type="button" className={route.view === "users" ? "active" : ""} onClick={() => navigate("#/konta")}>Konta</button>}</nav>
      <button type="button" className="avatar top-avatar" title={`${user.full_name} — wyloguj`} onClick={onLogout}>{initials}</button>
    </header>
    <main className="content v2-content">
      {route.view === "project" ? <ProjectView key={route.projectId} projectId={route.projectId} tab={route.tab} user={user} notify={notify} navigate={navigate} />
        : route.view === "users" ? <UsersAdmin user={user} notify={notify} />
          : <Dashboard user={user} notify={notify} openProject={id => navigate(`#/p/${id}/przeglad`)} />}
    </main>
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
  return <DialogProvider>{user ? <Shell user={user} onLogout={() => { setSession(null); setUser(null); }} /> : <Login onLogin={setUser} />}</DialogProvider>;
}
