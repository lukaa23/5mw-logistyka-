import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, cachedGet, download, flushQueue, getToken, mutate, queuedCount, setToken, upload } from "./api";

const pages = [
  ["dashboard", "Pulpit", "▦"], ["structure", "Budowa", "▤"], ["documents", "Dokumenty", "▱"],
  ["calculator", "Kalkulator", "⌗"], ["rfi", "RFI / problemy", "!"], ["logistics", "Logistyka", "⇄"],
  ["reports", "Czas i raporty", "◷"], ["users", "Użytkownicy", "♙"],
];

const today = () => new Date().toISOString().slice(0, 10);
const uid = () => crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
const fmt = value => value ? new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: value.includes?.("T") ? "short" : undefined }).format(new Date(value)) : "—";
const pct = (value, total) => total ? Math.round(value / total * 100) : 0;

function roleName(role) {
  return { kierownik: "Kierownik budowy", brygadzista: "Brygadzista", magazynier: "Magazynier" }[role] || role;
}

function Login({ onLogin }) {
  const [username, setUsername] = useState("kierownik");
  const [password, setPassword] = useState("Asolar2026!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }), headers: { "Content-Type": "application/json" } });
      setToken(result.token); onLogin(result.user);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const accounts = [
    ["kierownik", "Asolar2026!", "Kierownik"], ["brygadzista", "Brygada2026!", "Brygadzista"], ["magazynier", "Magazyn2026!", "Magazynier"],
  ];
  return <main className="login-page">
    <section className="login-brand">
      <div className="brand-mark large">A</div>
      <p className="eyebrow">ASOLAR ENTERPRISE</p>
      <h1>Budowa pod kontrolą.<br />Także bez zasięgu.</h1>
      <p>Postęp konstrukcji, jakość, dokumentacja, RFI i dostawy w jednym miejscu dla całego zespołu farmy PV.</p>
      <div className="login-feature"><span>✓</span> Synchronizacja wielu urządzeń</div>
      <div className="login-feature"><span>✓</span> Tryb offline na placu budowy</div>
      <div className="login-feature"><span>✓</span> Raport dzienny PDF i KPI</div>
    </section>
    <section className="login-panel">
      <form className="login-card" onSubmit={submit}>
        <div className="mobile-brand"><div className="brand-mark">A</div><strong>ASOLAR</strong></div>
        <p className="eyebrow">PANEL OPERACYJNY</p><h2>Zaloguj się</h2>
        <label>Login<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" /></label>
        <label>Hasło<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="alert error">{error}</div>}
        <button className="primary wide" disabled={busy}>{busy ? "Logowanie…" : "Zaloguj się"}</button>
        <div className="demo-accounts"><span>Konta startowe</span>{accounts.map(([u, p, name]) => <button type="button" key={u} onClick={() => { setUsername(u); setPassword(p); }}>{name}</button>)}</div>
        <small>Po pierwszym uruchomieniu kierownik powinien utworzyć indywidualne konta zespołu.</small>
      </form>
    </section>
  </main>;
}

function PageHead({ eyebrow, title, children }) {
  return <div className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div><div className="head-actions">{children}</div></div>;
}

function Empty({ children }) { return <div className="empty"><span>◇</span><p>{children}</p></div>; }
function Progress({ value, color = "green" }) { return <div className="progress"><i className={color} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>; }
function Loader() { return <div className="loading"><i /><span>Ładowanie danych…</span></div>; }

function Dashboard({ project, sync, notify, user, reloadProjects }) {
  const [data, setData] = useState(null); const [stock, setStock] = useState([]); const [rfis, setRfis] = useState([]);
  const load = useCallback(async () => {
    if (!project) return;
    try {
      const [dashboard, stockData, rfiData] = await Promise.all([cachedGet(`/api/dashboard?project_id=${project.id}`), cachedGet(`/api/logistics/stock?project_id=${project.id}`), cachedGet(`/api/rfis?project_id=${project.id}`)]);
      setData(dashboard); setStock(stockData); setRfis(rfiData);
    } catch (e) { notify(e.message, "error"); }
  }, [project, sync]);
  useEffect(() => { load(); }, [load]);
  const [newProject, setNewProject] = useState({ name: "", location: "", capacity_mw: "" });
  async function createProject(e) {
    e.preventDefault(); try { await mutate("/api/projects", "POST", { ...newProject, capacity_mw: Number(newProject.capacity_mw || 0) }); notify("Projekt utworzony"); setNewProject({ name: "", location: "", capacity_mw: "" }); reloadProjects(); } catch (err) { notify(err.message, "error"); }
  }
  if (!project) return <Empty>Utwórz pierwszy projekt, aby rozpocząć pracę.</Empty>;
  if (!data) return <Loader />;
  const missing = stock.filter(x => x.balance < 0).slice(0, 5);
  return <>
    <PageHead eyebrow="CENTRUM OPERACYJNE" title={`Dzień dobry, ${user.full_name.split(" ")[0]}`}><span className="date-chip">{new Intl.DateTimeFormat("pl-PL", { dateStyle: "full" }).format(new Date())}</span></PageHead>
    <section className="kpi-grid">
      <article className="kpi hero-kpi"><span>Postęp konstrukcji</span><strong>{data.completion_pct}%</strong><Progress value={data.completion_pct} /><small>{data.rows_built} z {data.rows_total} rzędów zbudowanych</small></article>
      <article className="kpi"><div className="kpi-icon green">✓</div><span>Odbiór QA/QC</span><strong>{data.rows_qc}<small> / {data.rows_total}</small></strong><Progress value={data.qc_pct} /></article>
      <article className="kpi"><div className="kpi-icon amber">!</div><span>Otwarte RFI</span><strong>{data.open_rfi}</strong><small>{rfis.filter(x => x.priority === "wysoki").length} o wysokim priorytecie</small></article>
      <article className="kpi"><div className="kpi-icon blue">◷</div><span>Wydajność</span><strong>{data.productivity}<small> rz./rbh</small></strong><small>{data.manhours} zarejestrowanych rbh</small></article>
      <article className="kpi"><div className="kpi-icon violet">→</div><span>Prognoza zakończenia</span><strong>{data.forecast_days ?? "—"}<small>{data.forecast_days != null ? " dni" : ""}</small></strong><small>na podstawie bieżącego tempa</small></article>
    </section>
    <div className="split two-thirds">
      <section className="card"><div className="card-head"><div><p className="eyebrow">MATERIAŁY</p><h2>Najważniejsze braki</h2></div><span className={`badge ${missing.length ? "danger" : "success"}`}>{missing.length ? `${missing.length} pozycji` : "Komplet"}</span></div>
        {missing.length ? <div className="compact-list">{missing.map(item => <div key={item.component_id}><div><strong>{item.name}</strong><small>{item.sku}</small></div><span className="negative">{item.balance.toLocaleString("pl-PL")} {item.unit}</span></div>)}</div> : <Empty>Wszystkie wyliczone pozycje są pokryte dostawami.</Empty>}
      </section>
      <section className="card"><div className="card-head"><div><p className="eyebrow">ALERTY</p><h2>Ostatnie RFI</h2></div></div>
        {rfis.slice(0, 4).map(rfi => <div className="rfi-mini" key={rfi.id}><span className={`priority ${rfi.priority}`}></span><div><strong>#{rfi.id} {rfi.title}</strong><small>{rfi.status} · {fmt(rfi.created_at)}</small></div></div>)}{!rfis.length && <Empty>Brak otwartych zgłoszeń.</Empty>}
      </section>
    </div>
    {user.role === "kierownik" && <details className="card collapsible"><summary>Dodaj nowy projekt</summary><form className="form-grid" onSubmit={createProject}><label>Nazwa projektu<input required value={newProject.name} onChange={e => setNewProject({ ...newProject, name: e.target.value })} /></label><label>Lokalizacja<input value={newProject.location} onChange={e => setNewProject({ ...newProject, location: e.target.value })} /></label><label>Moc [MW]<input type="number" step="0.1" value={newProject.capacity_mw} onChange={e => setNewProject({ ...newProject, capacity_mw: e.target.value })} /></label><button className="primary">Utwórz projekt</button></form></details>}
  </>;
}

function Structure({ project, sync, notify, user, navigate }) {
  const [tree, setTree] = useState(null); const [types, setTypes] = useState([]); const [selected, setSelected] = useState(null); const [query, setQuery] = useState("");
  const load = useCallback(async () => {
    if (!project) return;
    try { const [a, b] = await Promise.all([cachedGet(`/api/projects/${project.id}/tree`), cachedGet("/api/row-types")]); setTree(a); setTypes(b); if (!selected) setSelected(a.zones.flatMap(z => z.sections)[0]?.id); } catch (e) { notify(e.message, "error"); }
  }, [project, sync]);
  useEffect(() => { load(); }, [load]);
  const sections = tree?.zones.flatMap(zone => zone.sections.map(section => ({ ...section, zoneName: zone.name }))) || [];
  const section = sections.find(x => x.id === selected) || sections[0];
  const filteredRows = section?.rows.filter(row => row.code.toLowerCase().includes(query.toLowerCase())) || [];
  const [zoneName, setZoneName] = useState(""); const [sectionForm, setSectionForm] = useState({ zone_id: "", name: "" });
  const [rowsForm, setRowsForm] = useState({ prefix: "R", start_number: 1, count: 10, row_type_id: "", length_m: "" });
  async function doAction(path, method, body, message) { try { const r = await mutate(path, method, body); notify(r.queued ? "Zapisano offline — zmiana zostanie wysłana po odzyskaniu zasięgu" : message); if (!r.queued) load(); } catch (e) { notify(e.message, "error"); } }
  async function photo(rowId, file) { if (!file) return; const form = new FormData(); form.append("file", file); try { await upload(`/api/row/${rowId}/photos`, form); notify("Zdjęcie przypisane do rzędu"); } catch (e) { notify(e.message, "error"); } }
  if (!tree) return <Loader />;
  return <>
    <PageHead eyebrow="REALIZACJA" title="Struktura i postęp budowy"><span className="badge neutral">{sections.reduce((n, s) => n + s.rows.length, 0)} rzędów</span></PageHead>
    <div className="structure-layout">
      <aside className="tree-panel card"><h3>Struktura projektu</h3>{tree.zones.map(zone => <div className="tree-zone" key={zone.id}><strong>{zone.name}</strong>{zone.sections.map(item => <button className={section?.id === item.id ? "active" : ""} onClick={() => setSelected(item.id)} key={item.id}><span>{item.name}</span><small>{item.rows.filter(r => r.built).length}/{item.rows.length}</small></button>)}</div>)}
        {user.role === "kierownik" && <details className="inline-add"><summary>+ Dodaj strefę / sekcję</summary><form onSubmit={e => { e.preventDefault(); doAction("/api/zones", "POST", { project_id: project.id, name: zoneName }, "Strefa dodana"); setZoneName(""); }}><input required placeholder="Nazwa nowej strefy" value={zoneName} onChange={e => setZoneName(e.target.value)} /><button>Dodaj strefę</button></form><form onSubmit={e => { e.preventDefault(); doAction("/api/sections", "POST", { zone_id: Number(sectionForm.zone_id), name: sectionForm.name }, "Sekcja dodana"); setSectionForm({ zone_id: "", name: "" }); }}><select required value={sectionForm.zone_id} onChange={e => setSectionForm({ ...sectionForm, zone_id: e.target.value })}><option value="">Wybierz strefę</option>{tree.zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}</select><input required placeholder="Nazwa sekcji" value={sectionForm.name} onChange={e => setSectionForm({ ...sectionForm, name: e.target.value })} /><button>Dodaj sekcję</button></form></details>}
      </aside>
      <section className="work-panel">
        {!section ? <Empty>Dodaj strefę i sekcję, aby utworzyć rzędy.</Empty> : <>
          <div className="section-summary card"><div><p className="eyebrow">{section.zoneName}</p><h2>{section.name}</h2><small>{section.archived ? "Sekcja zarchiwizowana" : "Sekcja aktywna"}</small></div><div className="summary-progress"><strong>{pct(section.rows.filter(r => r.built).length, section.rows.length)}%</strong><Progress value={pct(section.rows.filter(r => r.built).length, section.rows.length)} /></div>{user.role === "kierownik" && !section.archived && <button className="secondary" onClick={() => doAction(`/api/sections/${section.id}/archive`, "POST", {}, "Sekcja zarchiwizowana")}>Zakończ i archiwizuj</button>}</div>
          <div className="toolbar"><div className="search"><span>⌕</span><input placeholder="Szukaj rzędu…" value={query} onChange={e => setQuery(e.target.value)} /></div>{user.role === "kierownik" && <details className="add-menu"><summary className="primary">+ Dodaj rzędy</summary><form onSubmit={e => { e.preventDefault(); doAction("/api/rows/bulk", "POST", { section_id: section.id, ...rowsForm, start_number: Number(rowsForm.start_number), count: Number(rowsForm.count), row_type_id: Number(rowsForm.row_type_id) || null, length_m: Number(rowsForm.length_m || 0) }, "Rzędy utworzone"); }}><label>Prefiks<input value={rowsForm.prefix} onChange={e => setRowsForm({ ...rowsForm, prefix: e.target.value })} /></label><label>Numer początkowy<input type="number" value={rowsForm.start_number} onChange={e => setRowsForm({ ...rowsForm, start_number: e.target.value })} /></label><label>Liczba rzędów<input type="number" min="1" value={rowsForm.count} onChange={e => setRowsForm({ ...rowsForm, count: e.target.value })} /></label><label>Typ konstrukcji<select value={rowsForm.row_type_id} onChange={e => { const t = types.find(x => x.id === Number(e.target.value)); setRowsForm({ ...rowsForm, row_type_id: e.target.value, length_m: t?.reference_length_m || "" }); }}><option value="">Bez typu</option>{types.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label><label>Długość [m]<input type="number" step="0.001" value={rowsForm.length_m} onChange={e => setRowsForm({ ...rowsForm, length_m: e.target.value })} /></label><button className="primary">Utwórz</button></form></details>}</div>
          <div className="row-list"><div className="row-header"><span>Rząd / typ</span><span>Wykonanie</span><span>Kontrola QA/QC</span><span>Akcje</span></div>{filteredRows.map(row => <article className={`construction-row ${row.qc_checked ? "verified" : row.built ? "built" : ""}`} key={row.id}><div className="row-name"><strong>{row.code}</strong><small>{row.row_type || "bez typu"} · {row.length_m ? `${row.length_m} m` : "długość —"}</small>{row.note && <em>{row.note}</em>}</div><div><button className={`status-button ${row.built ? "done" : ""}`} disabled={section.archived} onClick={() => doAction(`/api/rows/${row.id}`, "PATCH", { built: !row.built }, row.built ? "Cofnięto wykonanie" : "Rząd oznaczony jako zbudowany")}><span>{row.built ? "✓" : "○"}</span><div>{row.built ? "Zbudowane" : "Do zrobienia"}<small>{row.built_by || ""}{row.built_at ? ` · ${fmt(row.built_at)}` : ""}</small></div></button></div><div><button className={`status-button ${row.qc_checked ? "qc" : ""}`} disabled={user.role !== "kierownik" || !row.built || section.archived} onClick={() => doAction(`/api/rows/${row.id}`, "PATCH", { qc_checked: !row.qc_checked }, row.qc_checked ? "Cofnięto odbiór" : "Odbiór QA/QC zapisany")}><span>{row.qc_checked ? "✓" : "○"}</span><div>{row.qc_checked ? "Sprawdzone" : "Oczekuje"}<small>{row.qc_by || ""}{row.qc_at ? ` · ${fmt(row.qc_at)}` : ""}</small></div></button></div><div className="row-actions"><button title="Notatka" onClick={() => { const note = window.prompt("Notatka do rzędu", row.note || ""); if (note !== null) doAction(`/api/rows/${row.id}`, "PATCH", { note }, "Notatka zapisana"); }}>✎</button><label title="Dodaj zdjęcie">▧<input type="file" accept="image/*" capture="environment" onChange={e => photo(row.id, e.target.files[0])} /></label><button title="Zgłoś RFI" onClick={() => navigate("rfi", row.id)}>!</button></div></article>)}</div>
          {!filteredRows.length && <Empty>W tej sekcji nie ma rzędów pasujących do filtra.</Empty>}
        </>}
      </section>
    </div>
  </>;
}

function Documents({ project, sync, notify }) {
  const [docs, setDocs] = useState([]); const [instructions, setInstructions] = useState([]); const [busy, setBusy] = useState(false); const [file, setFile] = useState(null);
  const load = useCallback(async () => { if (!project) return; try { const [d, i] = await Promise.all([cachedGet(`/api/documents?project_id=${project.id}`), cachedGet(`/api/instructions?project_id=${project.id}`)]); setDocs(d); setInstructions(i); } catch (e) { notify(e.message, "error"); } }, [project, sync]);
  useEffect(() => { load(); }, [load]);
  async function submit(e) { e.preventDefault(); if (!file) return; setBusy(true); const form = new FormData(); form.append("project_id", project.id); form.append("file", file); try { const result = await upload("/api/documents", form); notify(result.status === "przeanalizowany" ? "Dokument wgrany i przeanalizowany" : "Dokument zapisany — sprawdź ostrzeżenia"); setFile(null); e.target.reset(); load(); } catch (err) { notify(err.message, "error"); } finally { setBusy(false); } }
  return <><PageHead eyebrow="DOKUMENTACJA PROJEKTOWA" title="Dokumenty i inteligentny BOM"><span className="badge neutral">PDF · DWG · DXF · XLSX</span></PageHead>
    <section className="upload-card"><div className="upload-icon">⇧</div><div><h2>Wgraj dokumentację budowy</h2><p>Parser rozpoznaje instrukcje montażu mechanicznego, warianty trackerów, momenty dokręcania oraz relacje BOM.</p></div><form onSubmit={submit}><label className="file-drop"><input required type="file" accept=".pdf,.dwg,.dxf,.xlsx,.xlsm" onChange={e => setFile(e.target.files[0])} /><span>{file ? file.name : "Wybierz plik z urządzenia"}</span></label><button className="primary" disabled={busy}>{busy ? "Analizowanie…" : "Wgraj i analizuj"}</button></form></section>
    <div className="split"><section className="card"><div className="card-head"><div><p className="eyebrow">PLIKI</p><h2>Dokumenty projektu</h2></div></div>{docs.map(doc => <article className="document" key={doc.id}><div className={`file-type ${doc.kind.toLowerCase()}`}>{doc.kind}</div><div><strong>{doc.filename}</strong><small>{(doc.size / 1024 / 1024).toFixed(2)} MB · {fmt(doc.uploaded_at)}</small><span className={`badge ${doc.status === "przeanalizowany" ? "success" : "warning"}`}>{doc.status}</span></div><a className="icon-button" href={`/api/documents/${doc.id}/file`} onClick={e => { e.preventDefault(); download(`/api/documents/${doc.id}/file`, doc.filename).catch(x => notify(x.message, "error")); }}>↓</a></article>)}{!docs.length && <Empty>Nie wgrano jeszcze dokumentów.</Empty>}</section>
      <section className="card"><div className="card-head"><div><p className="eyebrow">INSTRUKCJE</p><h2>Montaż mechaniczny</h2></div><span className="badge success">bez elektryki i palowania</span></div>{instructions.map((item, index) => <details className="instruction" key={`${item.document_id}-${index}`}><summary><span>{item.section || index + 1}</span><strong>{item.title}</strong></summary><p>{item.excerpt}</p>{item.source_points?.length > 0 && <ol>{item.source_points.map((point, i) => <li key={i}>{point}</li>)}</ol>}<small>Źródło: {item.source}</small></details>)}{!instructions.length && <Empty>Wgraj manual PDF, aby utworzyć instrukcje krok po kroku.</Empty>}</section></div>
  </>;
}

function Calculator({ notify }) {
  const [types, setTypes] = useState([]); const [form, setForm] = useState({ row_type_id: "", length_m: "", row_count: 1 }); const [result, setResult] = useState(null);
  useEffect(() => { cachedGet("/api/row-types").then(data => { setTypes(data); if (data[0]) setForm({ row_type_id: data[0].id, length_m: data[0].reference_length_m, row_count: 1 }); }).catch(e => notify(e.message, "error")); }, []);
  async function calculate(e) { e.preventDefault(); try { setResult(await api("/api/calculator", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ row_type_id: Number(form.row_type_id), length_m: Number(form.length_m), row_count: Number(form.row_count) }) })); } catch (err) { notify(err.message, "error"); } }
  return <><PageHead eyebrow="PLANOWANIE ZASOBÓW" title="Kalkulator sprzętu i materiałów" />
    <div className="calculator-layout"><form className="card calculator-form" onSubmit={calculate}><h2>Parametry robót</h2><label>Typ konstrukcji<select value={form.row_type_id} onChange={e => { const type = types.find(x => x.id === Number(e.target.value)); setForm({ ...form, row_type_id: e.target.value, length_m: type?.reference_length_m || form.length_m }); }} required>{types.map(type => <option key={type.id} value={type.id}>{type.name} · {type.structure_kind}</option>)}</select></label><label>Długość pojedynczego rzędu [m]<input type="number" step="0.001" min="0.1" required value={form.length_m} onChange={e => setForm({ ...form, length_m: e.target.value })} /></label><label>Liczba rzędów<input type="number" min="1" required value={form.row_count} onChange={e => setForm({ ...form, row_count: e.target.value })} /></label><button className="primary wide">Oblicz zapotrzebowanie</button><p className="hint">Kalkulator skaluje zatwierdzony BOM względem długości referencyjnej typu i zawsze zaokrągla sztuki w górę.</p></form>
      <section className="calculator-results">{!result ? <div className="card result-placeholder"><span>⌗</span><h2>Uzupełnij parametry</h2><p>Otrzymasz zestawienie śrub, podkładek, elementów konstrukcji oraz narzędzi.</p></div> : <><div className="result-banner"><div><p className="eyebrow">WYNIK DLA</p><h2>{result.input.row_count} × {result.row_type.name}</h2></div><div><small>Długość łączna</small><strong>{(result.input.length_m * result.input.row_count).toLocaleString("pl-PL")} m</strong></div></div><div className="card table-card"><div className="card-head"><h2>Materiały i elementy złączne</h2></div><div className="data-table"><div className="thead"><span>Element</span><span>Na rząd</span><span>Łącznie</span><span>Moment</span></div>{result.materials.map(item => <div className="trow" key={item.component_id}><span><strong>{item.name}</strong><small>{item.sku} · {item.category}</small></span><span>{item.per_row} {item.unit}</span><span><strong>{item.total.toLocaleString("pl-PL")} {item.unit}</strong></span><span>{item.torque_min_nm != null ? `${item.torque_min_nm}–${item.torque_max_nm} Nm` : "—"}</span></div>)}</div></div><div className="card"><div className="card-head"><h2>Sprzęt i narzędzia brygady</h2></div><div className="tool-grid">{result.tools.map(tool => <div key={tool.name}><span>{tool.quantity}</span><div><strong>{tool.name}</strong><small>{tool.specification}</small></div></div>)}</div><p className="hint">{result.assumption}</p></div></>}</section>
    </div>
  </>;
}

function RfiPage({ project, sync, notify, user, preselectedRow, clearPreselected }) {
  const [items, setItems] = useState([]); const [tree, setTree] = useState(null); const [form, setForm] = useState({ row_id: preselectedRow || "", title: "", description: "", priority: "normalny" }); const [photo, setPhoto] = useState(null);
  const load = useCallback(async () => { if (!project) return; try { const [a, b] = await Promise.all([cachedGet(`/api/rfis?project_id=${project.id}`), cachedGet(`/api/projects/${project.id}/tree`)]); setItems(a); setTree(b); } catch (e) { notify(e.message, "error"); } }, [project, sync]);
  useEffect(() => { load(); }, [load]); useEffect(() => { if (preselectedRow) { setForm(x => ({ ...x, row_id: preselectedRow })); clearPreselected(); } }, [preselectedRow]);
  const rows = tree?.zones.flatMap(z => z.sections.flatMap(s => s.rows.map(r => ({ ...r, path: `${z.name} / ${s.name} / ${r.code}` })))) || [];
  async function submit(e) { e.preventDefault(); try { const result = await mutate("/api/rfis", "POST", { project_id: project.id, row_id: Number(form.row_id) || null, title: form.title, description: form.description, priority: form.priority, client_id: uid() }); if (result.queued) { notify(photo ? "RFI zapisane offline. Zdjęcie dodaj po synchronizacji." : "RFI zapisane offline"); } else { if (photo) { const fd = new FormData(); fd.append("file", photo); await upload(`/api/rfi/${result.id}/photos`, fd); } notify("RFI przekazane do kierownika"); load(); } setForm({ row_id: "", title: "", description: "", priority: "normalny" }); setPhoto(null); e.target.reset(); } catch (err) { notify(err.message, "error"); } }
  async function status(id, value) { try { await mutate(`/api/rfis/${id}`, "PATCH", { status: value }); notify("Status RFI zaktualizowany"); load(); } catch (e) { notify(e.message, "error"); } }
  return <><PageHead eyebrow="NIEZGODNOŚCI I KOLIZJE" title="RFI / zgłoszenia problemów"><span className="badge danger">{items.filter(x => x.status !== "zamknięty").length} otwartych</span></PageHead>
    <div className="split rfi-layout"><form className="card sticky-form" onSubmit={submit}><h2>Nowe zgłoszenie</h2><label>Rząd / lokalizacja<select value={form.row_id} onChange={e => setForm({ ...form, row_id: e.target.value })}><option value="">Problem ogólny</option>{rows.map(row => <option key={row.id} value={row.id}>{row.path}</option>)}</select></label><label>Tytuł<input required placeholder="np. Kolizja rury z fundamentem" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label><label>Opis<textarea required rows="5" placeholder="Opisz stan faktyczny i oczekiwaną decyzję…" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label><label>Priorytet<select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}><option value="niski">Niski</option><option value="normalny">Normalny</option><option value="wysoki">Wysoki</option><option value="krytyczny">Krytyczny</option></select></label><label className="camera-button"><input type="file" accept="image/*" capture="environment" onChange={e => setPhoto(e.target.files[0])} /><span>▧</span>{photo ? photo.name : "Zrób lub dodaj zdjęcie"}</label><button className="primary wide">Wyślij zgłoszenie</button></form>
      <section className="rfi-list">{items.map(item => <article className="card rfi-card" key={item.id}><div className="rfi-top"><div><span className={`badge ${item.priority === "krytyczny" || item.priority === "wysoki" ? "danger" : "warning"}`}>{item.priority}</span><small>RFI #{item.id} · {fmt(item.created_at)}</small></div><span className={`status-pill ${item.status}`}>{item.status}</span></div><h2>{item.title}</h2><p>{item.description}</p><div className="rfi-meta"><span>Rząd: {rows.find(r => r.id === item.row_id)?.code || "ogólne"}</span><span>▧ {item.photos} zdjęć</span></div>{user.role === "kierownik" && <div className="rfi-controls"><button onClick={() => status(item.id, "w analizie")}>W analizie</button><button onClick={() => status(item.id, "zamknięty")}>Zamknij</button></div>}</article>)}{!items.length && <Empty>Nie ma jeszcze zgłoszeń RFI.</Empty>}</section>
    </div>
  </>;
}

function Logistics({ project, sync, notify, user }) {
  const [stock, setStock] = useState([]); const [deliveries, setDeliveries] = useState([]); const [components, setComponents] = useState([]); const [form, setForm] = useState({ delivery_date: today(), wz_number: "", supplier: "", note: "", items: [{ component_id: "", quantity_received: "", quantity_damaged: 0 }] });
  const load = useCallback(async () => { if (!project) return; try { const [a, b, c] = await Promise.all([cachedGet(`/api/logistics/stock?project_id=${project.id}`), cachedGet(`/api/deliveries?project_id=${project.id}`), cachedGet("/api/components")]); setStock(a); setDeliveries(b); setComponents(c); } catch (e) { notify(e.message, "error"); } }, [project, sync]);
  useEffect(() => { load(); }, [load]);
  function updateLine(index, key, value) { setForm({ ...form, items: form.items.map((line, i) => i === index ? { ...line, [key]: value } : line) }); }
  async function submit(e) { e.preventDefault(); try { const payload = { ...form, project_id: project.id, client_id: uid(), items: form.items.map(x => ({ component_id: Number(x.component_id), quantity_received: Number(x.quantity_received), quantity_damaged: Number(x.quantity_damaged || 0) })) }; const result = await mutate("/api/deliveries", "POST", payload); notify(result.queued ? "Dostawa zapisana offline" : "Przyjęcie dostawy zapisane"); setForm({ delivery_date: today(), wz_number: "", supplier: "", note: "", items: [{ component_id: "", quantity_received: "", quantity_damaged: 0 }] }); if (!result.queued) load(); } catch (err) { notify(err.message, "error"); } }
  return <><PageHead eyebrow="GOSPODARKA MAGAZYNOWA" title="Dostawy i stan materiałów"><span className="badge neutral">WZ / stan faktyczny</span></PageHead>
    <section className="card table-card"><div className="card-head"><div><p className="eyebrow">BILANS PROJEKTU</p><h2>Zapotrzebowanie a przyjęcia</h2></div></div><div className="data-table stock-table"><div className="thead"><span>Komponent</span><span>Wymagane</span><span>Dostępne</span><span>Bilans</span><span>Status</span></div>{stock.map(item => <div className="trow" key={item.component_id}><span><strong>{item.name}</strong><small>{item.sku}</small></span><span>{item.required.toLocaleString("pl-PL")} {item.unit}</span><span>{item.available.toLocaleString("pl-PL")} {item.unit}</span><span className={item.balance < 0 ? "negative" : "positive"}>{item.balance.toLocaleString("pl-PL")} {item.unit}</span><span><span className={`badge ${item.status === "komplet" ? "success" : "danger"}`}>{item.status}</span></span></div>)}</div>{!stock.length && <Empty>Przypisz typy konstrukcji do rzędów, aby wyliczyć zapotrzebowanie.</Empty>}</section>
    <div className="split"><section className="card"><div className="card-head"><h2>Historia dostaw</h2></div>{deliveries.map(delivery => <details className="delivery" key={delivery.id}><summary><div><strong>WZ {delivery.wz_number}</strong><small>{delivery.supplier || "dostawca —"}</small></div><span>{fmt(delivery.delivery_date)}</span></summary>{delivery.items.map((item, i) => <div className="delivery-line" key={i}><span>{item.name}<small>{item.sku}</small></span><strong>{item.quantity_received} {item.unit}</strong>{item.quantity_damaged > 0 && <em>uszkodzone: {item.quantity_damaged}</em>}</div>)}</details>)}{!deliveries.length && <Empty>Brak zarejestrowanych dostaw.</Empty>}</section>
      {(user.role === "kierownik" || user.role === "magazynier") && <form className="card" onSubmit={submit}><h2>Przyjęcie dostawy</h2><div className="form-grid"><label>Data<input type="date" required value={form.delivery_date} onChange={e => setForm({ ...form, delivery_date: e.target.value })} /></label><label>Numer WZ<input required value={form.wz_number} onChange={e => setForm({ ...form, wz_number: e.target.value })} /></label><label>Dostawca<input value={form.supplier} onChange={e => setForm({ ...form, supplier: e.target.value })} /></label></div><h3>Pozycje dostawy</h3>{form.items.map((line, index) => <div className="delivery-form-line" key={index}><select required value={line.component_id} onChange={e => updateLine(index, "component_id", e.target.value)}><option value="">Wybierz komponent</option>{components.map(c => <option key={c.id} value={c.id}>{c.sku} · {c.name}</option>)}</select><input required type="number" step="0.01" min="0.01" placeholder="Ilość" value={line.quantity_received} onChange={e => updateLine(index, "quantity_received", e.target.value)} /><input type="number" step="0.01" min="0" placeholder="Uszkodzone" value={line.quantity_damaged} onChange={e => updateLine(index, "quantity_damaged", e.target.value)} />{form.items.length > 1 && <button type="button" onClick={() => setForm({ ...form, items: form.items.filter((_, i) => i !== index) })}>×</button>}</div>)}<button type="button" className="text-button" onClick={() => setForm({ ...form, items: [...form.items, { component_id: "", quantity_received: "", quantity_damaged: 0 }] })}>+ Dodaj pozycję</button><label>Uwagi<textarea value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} /></label><button className="primary wide">Zapisz przyjęcie WZ</button></form>}
    </div>
  </>;
}

function Reports({ project, sync, notify, user }) {
  const [logs, setLogs] = useState([]); const [reportDate, setReportDate] = useState(today()); const [form, setForm] = useState({ work_date: today(), team: "Brygada 1", stage: "Montaż konstrukcji", people: 4, hours: 8, rows_completed: 0, note: "" });
  const load = useCallback(async () => { if (!project) return; try { setLogs(await cachedGet(`/api/worklogs?project_id=${project.id}`)); } catch (e) { notify(e.message, "error"); } }, [project, sync]);
  useEffect(() => { load(); }, [load]);
  async function submit(e) { e.preventDefault(); try { const result = await mutate("/api/worklogs", "POST", { ...form, project_id: project.id, people: Number(form.people), hours: Number(form.hours), rows_completed: Number(form.rows_completed), client_id: uid() }); notify(result.queued ? "Czas pracy zapisany offline" : "Wpis czasu pracy zapisany"); if (!result.queued) load(); } catch (err) { notify(err.message, "error"); } }
  const totalHours = logs.reduce((sum, x) => sum + x.manhours, 0); const totalRows = logs.reduce((sum, x) => sum + x.rows_completed, 0);
  return <><PageHead eyebrow="CZAS PRACY I ANALITYKA" title="Raport dzienny i wydajność"><button className="primary" onClick={() => download(`/api/reports/daily?project_id=${project.id}&report_date=${reportDate}`, `ASOLAR-raport-${reportDate}.pdf`).catch(e => notify(e.message, "error"))}>↓ Pobierz raport PDF</button></PageHead>
    <div className="report-strip"><label>Data raportu<input type="date" value={reportDate} onChange={e => setReportDate(e.target.value)} /></label><div><span>Łączne rbh</span><strong>{totalHours.toFixed(1)}</strong></div><div><span>Zgłoszone rzędy</span><strong>{totalRows}</strong></div><div><span>Tempo</span><strong>{totalHours ? (totalRows / totalHours).toFixed(3) : "—"} <small>rz./rbh</small></strong></div></div>
    <div className="split"><form className="card" onSubmit={submit}><h2>Dodaj wpis pracy</h2><div className="form-grid"><label>Data<input type="date" value={form.work_date} onChange={e => setForm({ ...form, work_date: e.target.value })} /></label><label>Brygada<input required value={form.team} onChange={e => setForm({ ...form, team: e.target.value })} /></label><label>Etap<select value={form.stage} onChange={e => setForm({ ...form, stage: e.target.value })}><option>Montaż konstrukcji</option><option>Montaż rur momentowych</option><option>Montaż płatwi</option><option>Montaż przekładni</option><option>Kontrola QA/QC</option><option>Poprawki</option></select></label><label>Liczba osób<input type="number" min="1" value={form.people} onChange={e => setForm({ ...form, people: e.target.value })} /></label><label>Godziny / osoba<input type="number" step="0.5" min="0.5" max="24" value={form.hours} onChange={e => setForm({ ...form, hours: e.target.value })} /></label><label>Ukończone rzędy<input type="number" step="0.1" min="0" value={form.rows_completed} onChange={e => setForm({ ...form, rows_completed: e.target.value })} /></label></div><label>Uwagi<textarea value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} /></label><button className="primary wide">Zapisz czas pracy</button></form>
      <section className="card"><div className="card-head"><h2>Ostatnie wpisy</h2></div><div className="timeline">{logs.slice(0, 15).map(log => <div key={log.id}><span>{new Date(log.work_date).getDate()}</span><div><strong>{log.team} · {log.stage}</strong><small>{fmt(log.work_date)} · {log.people} os. × {log.hours} h = {log.manhours} rbh</small>{log.note && <p>{log.note}</p>}</div><em>{log.rows_completed} rz.</em></div>)}</div>{!logs.length && <Empty>Brak wpisów czasu pracy.</Empty>}</section></div>
  </>;
}

function Users({ notify, user }) {
  const [items, setItems] = useState([]); const [form, setForm] = useState({ username: "", full_name: "", role: "brygadzista", password: "" });
  const load = useCallback(() => { if (user.role === "kierownik") cachedGet("/api/users").then(setItems).catch(e => notify(e.message, "error")); }, [user]);
  useEffect(() => { load(); }, [load]);
  async function submit(e) { e.preventDefault(); try { await api("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) }); notify("Konto użytkownika utworzone"); setForm({ username: "", full_name: "", role: "brygadzista", password: "" }); load(); } catch (err) { notify(err.message, "error"); } }
  if (user.role !== "kierownik") return <Empty>Tylko Kierownik Budowy zarządza kontami.</Empty>;
  return <><PageHead eyebrow="ADMINISTRACJA" title="Użytkownicy i role" /><div className="split"><section className="card"><div className="card-head"><h2>Zespół projektu</h2></div>{items.map(item => <div className="user-row" key={item.id}><div className="avatar">{item.full_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</div><div><strong>{item.full_name}</strong><small>@{item.username}</small></div><span className="badge neutral">{roleName(item.role)}</span></div>)}</section><form className="card" onSubmit={submit}><h2>Nowe konto</h2><label>Imię i nazwisko<input required value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></label><label>Login<input required value={form.username} onChange={e => setForm({ ...form, username: e.target.value.toLowerCase().replace(/\s/g, "") })} /></label><label>Rola<select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}><option value="kierownik">Kierownik Budowy</option><option value="brygadzista">Brygadzista</option><option value="magazynier">Magazynier</option></select></label><label>Hasło startowe<input type="password" minLength="8" required value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></label><button className="primary wide">Utwórz konto</button></form></div></>;
}

export default function App() {
  const [user, setUser] = useState(null); const [loading, setLoading] = useState(!!getToken()); const [projects, setProjects] = useState([]); const [projectId, setProjectId] = useState(Number(localStorage.getItem("asolar_project")) || null); const [page, setPage] = useState("dashboard"); const [sync, setSync] = useState(0); const [online, setOnline] = useState(navigator.onLine); const [queue, setQueue] = useState(queuedCount()); const [toast, setToast] = useState(null); const [preselectedRow, setPreselectedRow] = useState(null);
  const notify = useCallback((message, type = "success") => { setToast({ message, type }); setTimeout(() => setToast(null), 4200); }, []);
  const loadProjects = useCallback(async () => { try { const result = await cachedGet("/api/projects"); setProjects(result); const selected = result.find(x => x.id === projectId) || result[0]; if (selected) { setProjectId(selected.id); localStorage.setItem("asolar_project", selected.id); } } catch (e) { notify(e.message, "error"); } }, [projectId]);
  useEffect(() => { if (!getToken()) { setLoading(false); return; } api("/api/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false)); }, []);
  useEffect(() => { if (user) loadProjects(); }, [user]);
  useEffect(() => {
    const update = async () => { setOnline(navigator.onLine); if (navigator.onLine && user) { const sent = await flushQueue(); if (sent) { notify(`Zsynchronizowano ${sent} zapisów offline`); setSync(x => x + 1); } } setQueue(queuedCount()); };
    const unauthorized = () => setUser(null); window.addEventListener("online", update); window.addEventListener("offline", update); window.addEventListener("asolar:queue", update); window.addEventListener("asolar:unauthorized", unauthorized); update();
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); window.removeEventListener("asolar:queue", update); window.removeEventListener("asolar:unauthorized", unauthorized); };
  }, [user]);
  useEffect(() => {
    if (!user || !getToken()) return;
    const protocol = location.protocol === "https:" ? "wss" : "ws"; const ws = new WebSocket(`${protocol}://${location.host}/ws?token=${encodeURIComponent(getToken())}`);
    ws.onmessage = () => setSync(x => x + 1); const keepalive = setInterval(() => { if (ws.readyState === 1) ws.send("ping"); }, 30000);
    return () => { clearInterval(keepalive); ws.close(); };
  }, [user]);
  const project = projects.find(x => x.id === projectId) || projects[0];
  function navigate(target, rowId = null) { setPage(target); if (rowId) setPreselectedRow(rowId); window.scrollTo({ top: 0, behavior: "smooth" }); }
  function logout() { setToken(null); setUser(null); }
  if (loading) return <Loader />;
  if (!user) return <Login onLogin={setUser} />;
  const visiblePages = pages.filter(([id]) => id !== "users" || user.role === "kierownik");
  const common = { project, sync, notify, user };
  return <div className="app-shell">
    <aside className="sidebar"><div className="logo"><div className="brand-mark">A</div><div><strong>ASOLAR</strong><small>Enterprise</small></div></div><nav>{visiblePages.map(([id, label, icon]) => <button key={id} className={page === id ? "active" : ""} onClick={() => navigate(id)}><span>{icon}</span>{label}{id === "rfi" && <i />}</button>)}</nav><div className="sidebar-foot"><div className="user-mini"><div className="avatar">{user.full_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</div><div><strong>{user.full_name}</strong><small>{roleName(user.role)}</small></div></div><button className="logout" onClick={logout}>Wyloguj</button></div></aside>
    <header className="topbar"><div className="mobile-logo"><div className="brand-mark">A</div><strong>ASOLAR</strong></div><label className="project-select"><span>Aktywny projekt</span><select value={project?.id || ""} onChange={e => { const id = Number(e.target.value); setProjectId(id); localStorage.setItem("asolar_project", id); setSync(x => x + 1); }}>{projects.map(item => <option key={item.id} value={item.id}>{item.name} · {item.capacity_mw} MW</option>)}</select></label><div className={`connection ${online ? "online" : "offline"}`}><i />{online ? "Online" : "Offline"}{queue > 0 && <b>{queue}</b>}</div><button className="avatar top-avatar" onClick={logout} title="Wyloguj">{user.full_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</button></header>
    <main className="content">
      {page === "dashboard" && <Dashboard {...common} reloadProjects={loadProjects} />}
      {page === "structure" && <Structure {...common} navigate={navigate} />}
      {page === "documents" && <Documents {...common} />}
      {page === "calculator" && <Calculator notify={notify} />}
      {page === "rfi" && <RfiPage {...common} preselectedRow={preselectedRow} clearPreselected={() => setPreselectedRow(null)} />}
      {page === "logistics" && <Logistics {...common} />}
      {page === "reports" && <Reports {...common} />}
      {page === "users" && <Users {...common} />}
    </main>
    <nav className="bottom-nav">{visiblePages.slice(0, 6).map(([id, label, icon]) => <button key={id} className={page === id ? "active" : ""} onClick={() => navigate(id)}><span>{icon}</span><small>{label.split(" ")[0]}</small></button>)}</nav>
    {toast && <div className={`toast ${toast.type}`}>{toast.type === "error" ? "!" : "✓"}<span>{toast.message}</span></div>}
  </div>;
}
