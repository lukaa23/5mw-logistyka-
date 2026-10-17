"use strict";
/* Czyste funkcje pomocnicze aplikacji desktopowej — bez zależności od Electrona (testowane przez node:test). */
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");

const DEFAULT_PORT = 8765;

/** Zwraca poprawny adres http(s) albo null. */
function normalizeServerUrl(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  let url;
  try { url = new URL(text); } catch { return null; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  return url.origin;
}

/** Odczytuje konfigurację: config.json w profilu użytkownika oraz (zgodność wstecz) server-url.txt obok programu. */
function readConfig(configPath, exeDir) {
  let config = {};
  try { config = JSON.parse(fs.readFileSync(configPath, "utf8")); } catch { config = {}; }
  if (!config || typeof config !== "object" || Array.isArray(config)) config = {};
  let serverUrl = normalizeServerUrl(config.serverUrl);
  if (!serverUrl && exeDir) {
    try { serverUrl = normalizeServerUrl(fs.readFileSync(path.join(exeDir, "server-url.txt"), "utf8").split(/\r?\n/)[0]); } catch { /* brak pliku */ }
  }
  const port = Number.isInteger(config.port) && config.port > 1023 && config.port < 65536 ? config.port : DEFAULT_PORT;
  return { serverUrl, shareOnLan: config.shareOnLan === true, port };
}

function writeConfig(configPath, values) {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify({ serverUrl: values.serverUrl || "", shareOnLan: !!values.shareOnLan, port: values.port || DEFAULT_PORT }, null, 2), "utf8");
}

/** Stały, losowy klucz sesji przechowywany w profilu użytkownika (tworzony przy pierwszym uruchomieniu). */
function ensureSecret(secretPath) {
  try {
    const existing = fs.readFileSync(secretPath, "utf8").trim();
    if (existing.length >= 32) return existing;
  } catch { /* pierwszy start */ }
  const secret = crypto.randomBytes(32).toString("hex");
  fs.mkdirSync(path.dirname(secretPath), { recursive: true });
  fs.writeFileSync(secretPath, secret, { encoding: "utf8", mode: 0o600 });
  return secret;
}

/** true, gdy na porcie lokalnym coś już nasłuchuje. */
function isPortBusy(port, host = "127.0.0.1") {
  return new Promise(resolve => {
    const socket = net.connect({ port, host });
    socket.setTimeout(800);
    socket.once("connect", () => { socket.destroy(); resolve(true); });
    socket.once("timeout", () => { socket.destroy(); resolve(false); });
    socket.once("error", () => resolve(false));
  });
}

function getJson(url, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, response => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", chunk => { body += chunk; });
      response.on("end", () => {
        if (response.statusCode !== 200) return reject(new Error(`HTTP ${response.statusCode}`));
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    });
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", reject);
  });
}

/** Czeka, aż backend odpowie na /api/health. Przerywa, gdy proces serwera zakończy się wcześniej. */
async function waitForHealth(baseUrl, { timeoutMs = 60000, intervalMs = 500, isAlive = () => true } = {}) {
  const started = Date.now();
  let lastError = null;
  while (Date.now() - started < timeoutMs) {
    if (!isAlive()) throw new Error("Proces serwera zakończył się podczas uruchamiania");
    try {
      const health = await getJson(`${baseUrl}/api/health`);
      if (health && health.status === "ok") return health;
    } catch (error) { lastError = error; }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Serwer nie odpowiedział w ciągu ${Math.round(timeoutMs / 1000)} s${lastError ? ` (${lastError.message})` : ""}`);
}

/** Adresy IPv4 w sieci lokalnej — dla telefonów brygadzistów. */
function lanAddresses(interfaces = os.networkInterfaces()) {
  const result = [];
  for (const entries of Object.values(interfaces || {})) {
    for (const entry of entries || []) {
      const v4 = entry.family === "IPv4" || entry.family === 4;
      if (v4 && !entry.internal && !entry.address.startsWith("169.254.")) result.push(entry.address);
    }
  }
  return [...new Set(result)];
}

/** Czy okno może przejść pod ten adres (tylko własny serwer); inne adresy otwieramy w przeglądarce. */
function isAppUrl(target, appOrigin) {
  try {
    const url = new URL(target);
    return url.origin === appOrigin || url.protocol === "blob:" || url.protocol === "data:";
  } catch { return false; }
}

module.exports = { DEFAULT_PORT, normalizeServerUrl, readConfig, writeConfig, ensureSecret, isPortBusy, waitForHealth, lanAddresses, isAppUrl, getJson };
