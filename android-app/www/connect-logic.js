/* Logika ekranu połączenia — bez zależności, testowana w Node. */
(function (root) {
  var DEFAULT_PORT = "8765";

  // Zamienia wpis użytkownika ("192.168.0.15", "laptop:8765", "http://10.0.0.2:8765/") na adres serwera.
  function normalizeServerUrl(input) {
    var value = String(input == null ? "" : input).trim();
    if (!value) return { ok: false, error: "Wpisz adres laptopa, np. 192.168.0.15" };
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
      if (!/^http:\/\//i.test(value) && !/^https:\/\//i.test(value)) return { ok: false, error: "Dozwolone są adresy http:// i https://" };
    } else {
      value = "http://" + value;
    }
    var url;
    try { url = new URL(value); } catch (e) { return { ok: false, error: "Nieprawidłowy adres" }; }
    if (!url.hostname || /\s/.test(url.hostname)) return { ok: false, error: "Nieprawidłowy adres" };
    if (!url.port && url.protocol === "http:") url.port = DEFAULT_PORT;
    return { ok: true, url: url.protocol + "//" + url.host };
  }

  var api = { normalizeServerUrl: normalizeServerUrl, DEFAULT_PORT: DEFAULT_PORT };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AsolarConnect = api;
})(typeof self !== "undefined" ? self : this);
