"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const lib = require("../lib");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "asolar2-desktop-"));

test("adres serwera: tylko http/https, zwracany origin", () => {
  assert.equal(lib.normalizeServerUrl(" https://asolar.onrender.com/app/ "), "https://asolar.onrender.com");
  assert.equal(lib.normalizeServerUrl("http://192.168.1.20:8765"), "http://192.168.1.20:8765");
  for (const bad of ["", null, "ftp://x", "javascript:alert(1)", "file:///C:/x", "nie adres"]) assert.equal(lib.normalizeServerUrl(bad), null);
});

test("pierwsze uruchomienie: brak konfiguracji = ekran wyboru trybu", () => {
  const profile = tmp();
  const config = lib.readConfig(path.join(profile, "config.json"), tmp());
  assert.deepEqual(config, { serverUrl: null, shareOnLan: false, port: 8770, mode: null, firstRun: true, source: null });
});

test("server-url.txt w profilu użytkownika lub obok programu włącza tryb chmury", () => {
  const profile = tmp();
  const exe = tmp();
  const configPath = path.join(profile, "config.json");
  fs.writeFileSync(path.join(exe, "server-url.txt"), "https://obok-programu.example\r\n");
  assert.deepEqual(lib.readConfig(configPath, exe), { serverUrl: "https://obok-programu.example", shareOnLan: false, port: 8770, mode: "remote", firstRun: false, source: "server-url.txt" });
  fs.writeFileSync(path.join(profile, "server-url.txt"), "https://twoja-farma.onrender.com/\n");
  assert.equal(lib.readConfig(configPath, exe).serverUrl, "https://twoja-farma.onrender.com");
  fs.writeFileSync(path.join(profile, "server-url.txt"), "ftp://zly-adres\n");
  assert.equal(lib.readConfig(configPath, null).serverUrl, null);
});

test("zapisana konfiguracja: tryb chmury i tryb lokalny (lokalny ignoruje server-url.txt)", () => {
  const profile = tmp();
  const configPath = path.join(profile, "config.json");
  lib.writeConfig(configPath, { serverUrl: "https://inny.example", shareOnLan: true, port: 9000 });
  assert.deepEqual(lib.readConfig(configPath, null), { serverUrl: "https://inny.example", shareOnLan: true, port: 9000, mode: "remote", firstRun: false, source: "config.json" });
  fs.writeFileSync(path.join(profile, "server-url.txt"), "https://z-pliku.example");
  lib.writeConfig(configPath, { serverUrl: null });
  assert.deepEqual(lib.readConfig(configPath, null), { serverUrl: null, shareOnLan: false, port: 8770, mode: "local", firstRun: false, source: null });
  fs.writeFileSync(configPath, "{zepsuty json");
  assert.equal(lib.readConfig(configPath, null).serverUrl, "https://z-pliku.example");
});

test("sprawdzenie serwera: poprawny ASOLAR v2, serwer v1, obcy serwer, zły adres, brak połączenia", async () => {
  let v1 = false;
  const server = http.createServer((request, response) => {
    response.writeHead(200, { "Content-Type": "application/json" });
    if (request.url === "/api/health" && v1) response.end('{"status":"ok","version":"4.7.1","database":"postgresql"}');
    else if (request.url === "/api/health" && request.headers.host.startsWith("127.0.0.1")) response.end('{"status":"ok","version":"2.0.0","database":"postgresql","isolation":"schema-per-project"}');
    else response.end('{"hello":"world"}');
  }).listen(0, "127.0.0.1");
  await new Promise(resolve => server.once("listening", resolve));
  const { port } = server.address();
  const result = await lib.checkServer(`http://127.0.0.1:${port}/dowolna/sciezka`, { timeoutMs: 3000 });
  assert.deepEqual(result, { origin: `http://127.0.0.1:${port}`, version: "2.0.0", database: "postgresql", isolation: "schema-per-project", secure: false });
  v1 = true;
  await assert.rejects(lib.checkServer(`http://127.0.0.1:${port}`, { timeoutMs: 3000 }), /działa ASOLAR v1 \(wersja 4\.7\.1\)/);
  v1 = false;
  await assert.rejects(lib.checkServer(`http://localhost:${port}`, { timeoutMs: 3000 }), /nie działa serwer ASOLAR/);
  await assert.rejects(lib.checkServer("twoja-farma.onrender.com"), /https:\/\//);
  await assert.rejects(lib.checkServer("http://127.0.0.1:1", { timeoutMs: 1000 }), /Nie udało się połączyć/);
  server.close();
});

test("klucz sesji jest tworzony raz i zachowywany", () => {
  const file = path.join(tmp(), "secret.key");
  const first = lib.ensureSecret(file);
  assert.equal(first.length, 64);
  assert.equal(lib.ensureSecret(file), first);
});

test("wykrywanie zajętego portu", async () => {
  const server = net.createServer().listen(0, "127.0.0.1");
  await new Promise(resolve => server.once("listening", resolve));
  const { port } = server.address();
  assert.equal(await lib.isPortBusy(port), true);
  await new Promise(resolve => server.close(resolve));
  assert.equal(await lib.isPortBusy(port), false);
});

test("oczekiwanie na /api/health i przerwanie, gdy serwer padnie", async () => {
  let ready = false;
  const server = http.createServer((request, response) => {
    if (request.url === "/api/health" && ready) { response.writeHead(200, { "Content-Type": "application/json" }); response.end('{"status":"ok","version":"4.6.0"}'); }
    else { response.writeHead(503); response.end(); }
  }).listen(0, "127.0.0.1");
  await new Promise(resolve => server.once("listening", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  setTimeout(() => { ready = true; }, 300);
  const health = await lib.waitForHealth(base, { timeoutMs: 5000, intervalMs: 100 });
  assert.equal(health.version, "4.6.0");
  await assert.rejects(lib.waitForHealth("http://127.0.0.1:1", { timeoutMs: 2000, intervalMs: 50, isAlive: () => false }), /zakończył się/);
  await assert.rejects(lib.waitForHealth("http://127.0.0.1:1", { timeoutMs: 300, intervalMs: 50 }), /nie odpowiedział/);
  server.close();
});

test("adresy LAN pomijają pętlę zwrotną i adresy link-local", () => {
  const addresses = lib.lanAddresses({
    lo: [{ family: "IPv4", address: "127.0.0.1", internal: true }],
    wifi: [{ family: "IPv4", address: "192.168.1.15", internal: false }, { family: "IPv6", address: "fe80::1", internal: false }],
    apipa: [{ family: 4, address: "169.254.3.3", internal: false }],
  });
  assert.deepEqual(addresses, ["192.168.1.15"]);
});

test("okno aplikacji pozostaje przy własnym serwerze", () => {
  const origin = "http://127.0.0.1:8765";
  assert.equal(lib.isAppUrl("http://127.0.0.1:8765/raporty", origin), true);
  assert.equal(lib.isAppUrl("blob:http://127.0.0.1:8765/abc", origin), true);
  assert.equal(lib.isAppUrl("https://evil.example", origin), false);
  assert.equal(lib.isAppUrl("nie-url", origin), false);
});
