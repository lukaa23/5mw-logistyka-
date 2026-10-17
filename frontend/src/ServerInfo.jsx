import React, { useEffect, useState } from "react";
import { api } from "./api";

/** Karta dla kierownika: adresy, pod którymi telefony w tej samej sieci Wi-Fi otworzą aplikację. */
export default function ServerInfo() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api("/api/server-info").then(data => { if (active) setInfo(data); }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);
  if (error) return null;
  if (!info) return null;
  return <section className="card server-info">
    <p className="eyebrow">DOSTĘP Z TELEFONÓW</p>
    <h2>Adres dla telefonów</h2>
    {info.lan_enabled
      ? info.urls.length
        ? <><p>Telefony w tej samej sieci Wi-Fi łączą się pod jednym z adresów (wpisz go w aplikacji Android lub w przeglądarce):</p><ul>{info.urls.map(url => <li key={url}><code>{url}</code></li>)}</ul></>
        : <p>Tryb sieciowy jest włączony, ale nie wykryto adresu sieci lokalnej. Sprawdź, czy laptop jest połączony z Wi-Fi.</p>
      : <p>Serwer działa tylko na tym komputerze. Aby udostępnić go telefonom, uruchom program przez <b>Uruchom-Windows-Siec.bat</b>.</p>}
    <small className="hint">Połączenie w sieci lokalnej nie jest szyfrowane (HTTP) — używaj prywatnej sieci Wi-Fi, nie publicznej.</small>
  </section>;
}
