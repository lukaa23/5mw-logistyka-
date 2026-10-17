import React, { useEffect, useRef, useState } from "react";
import { exportBackup, importBackup, refreshCounts, saveBlob } from "./api";

/** Kopia niewysłanych zmian (notatki, statusy, zdjęcia) — pobranie do pliku i przywrócenie z pliku. */
export function BackupTools({ compact = false }) {
  const [counts, setCounts] = useState({ pending: 0, failed: 0 });
  const [message, setMessage] = useState("");
  const input = useRef(null);
  useEffect(() => {
    let active = true;
    const update = event => { if (active && event?.detail) setCounts(event.detail); };
    window.addEventListener("asolar:queue", update);
    refreshCounts().then(value => { if (active) setCounts(value); }).catch(() => undefined);
    return () => { active = false; window.removeEventListener("asolar:queue", update); };
  }, []);
  async function save() {
    try {
      const backup = await exportBackup();
      saveBlob(new Blob([JSON.stringify(backup)], { type: "application/json" }), `ASOLAR-niewyslane-zmiany-${new Date().toISOString().slice(0, 16).replace(":", "-")}.json`);
      setMessage(`Zapisano kopię: ${backup.items.length} zmian.`);
    } catch (error) { setMessage(`Nie udało się utworzyć kopii: ${error.message}`); }
  }
  async function restore(file) {
    if (!file) return;
    try {
      const added = await importBackup(JSON.parse(await file.text()));
      setMessage(added ? `Przywrócono ${added} zmian — zostaną wysłane po połączeniu z serwerem.` : "Wszystkie zmiany z kopii są już w kolejce.");
    } catch (error) { setMessage(`Nie udało się przywrócić kopii: ${error.message}`); }
    if (input.current) input.current.value = "";
  }
  return <div className={`backup-tools ${compact ? "compact" : ""}`}>
    <p><strong>{counts.pending}</strong> zmian czeka na wysłanie{counts.failed ? <>, <strong>{counts.failed}</strong> odrzuconych przez serwer</> : null}. Zmiany są zapisane w pamięci tego urządzenia.</p>
    <div className="card-actions">
      <button type="button" className="secondary" onClick={save}>Pobierz kopię niewysłanych zmian</button>
      <label className="secondary file-button">Przywróć dane z kopii<input ref={input} type="file" accept="application/json,.json" onChange={event => restore(event.target.files?.[0])} /></label>
    </div>
    {message && <p className="hint" role="status">{message}</p>}
  </div>;
}

/** Błąd widoku pokazuje ekran ratunkowy zamiast białego ekranu całej aplikacji. */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[ASOLAR] Błąd widoku", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const message = String(this.state.error?.message || this.state.error);
    const loadFailure = /dynamically imported module|Failed to fetch|Loading chunk|import/i.test(message);
    return <div className={`card alert error rescue-screen ${this.props.fullScreen ? "full" : ""}`} role="alert">
      <h2>{this.props.fullScreen ? "Aplikacja napotkała błąd" : "Ten widok napotkał błąd"}</h2>
      <p>{loadFailure ? "Nie udało się wczytać części aplikacji — prawdopodobnie brak połączenia z serwerem." : message}</p>
      <p>Dane zapisane na serwerze i w kolejce offline tego urządzenia są bezpieczne.</p>
      <div className="card-actions">
        <button className="primary" onClick={() => window.location.reload()}>Odśwież aplikację</button>
        <button className="secondary" onClick={() => this.setState({ error: null })}>Spróbuj ponownie</button>
      </div>
      <BackupTools />
    </div>;
  }
}
