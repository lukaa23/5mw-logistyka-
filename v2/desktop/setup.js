"use strict";
/* Ekran wyboru serwera: walidacja adresu, test połączenia, Enter = połącz, Esc = wyczyść komunikat. */
(async function () {
  const api = window.asolarDesktop;
  const $ = id => document.getElementById(id);
  const status = (text, kind) => { const box = $("status"); box.textContent = text; box.className = text ? `message ${kind}` : "message"; };
  const busy = (button, on, label) => { button.disabled = on; if (label) button.textContent = label; };
  if (!api) { status("Ten ekran działa tylko w aplikacji desktopowej ASOLAR.", "error"); return; }

  const settings = await api.getSettings();
  $("version").textContent = `wersja ${settings.version}`;
  if (settings.serverUrl) $("url").value = settings.serverUrl;
  const params = new URLSearchParams(location.search);
  if (params.get("error")) { status(params.get("error"), "error"); $("retry").hidden = !settings.serverUrl; }
  else if (settings.mode === "remote") status(`Aktualnie: serwer w chmurze ${settings.serverUrl}`, "info");
  else if (settings.mode === "local") status("Aktualnie: serwer na tym komputerze.", "info");
  $("url").focus();

  $("remote-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("connect");
    busy(button, true, "Sprawdzanie połączenia…");
    status("Łączę z serwerem… (darmowy serwer może się wybudzać do minuty)", "info");
    try {
      const result = await api.connect($("url").value);
      status(`Połączono: ${result.origin} · wersja ${result.version} · baza ${result.database}`, "ok");
    } catch (error) {
      status(String(error.message || error).replace(/^Error invoking remote method '[^']+': (Error: )?/, ""), "error");
      busy(button, false, "Sprawdź i połącz");
    }
  });
  $("retry").addEventListener("click", async () => { busy($("retry"), true, "Łączenie…"); await api.retry(); });
  $("local").addEventListener("click", async () => {
    busy($("local"), true, "Uruchamianie…");
    try { await api.useLocal(); } catch (error) { status(String(error.message || error), "error"); busy($("local"), false, "Uruchom serwer na tym komputerze"); }
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape") status("", ""); });
})();
