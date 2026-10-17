"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const lib = require("../lib");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "asolar-desktop-"));

test("adres serwera: tylko http/https, zwracany origin", () => {
  assert.equal(lib.normalizeServerUrl(" https://asolar.onrender.com/app/ "), "https://asolar.onrender.com");
  assert.equal(lib.normalizeServerUrl("http://192.168.1.20:8765"), "http://192.168.1.20:8765");
  for (const bad of ["", null, "ftp://x", "javascript:alert(1)", "file:///C:/x", "nie adres"]) assert.equal(lib.normalizeServerUrl(bad), null);
});

test("konfiguracja: config.json ma pierwszeństwo, server-url.txt jako zgodność wstecz, domyślny port", () => {
  const dir = tmp();
  const configPath = path.join(dir, "config.json");
  assert.deepEqual(lib.readConfig(configPath, dir), { serverUrl: null, shareOnLan: false, port: 8765 });
  fs.writeFileSync(path.join(dir, "server-url.txt"), "https://zdalny.example\r\n");
  assert.equal(lib.readConfig(configPath, dir).serverUrl, "https://zdalny.example");
  lib.writeConfig(configPath, { serverUrl: "https://inny.example", shareOnLan: true, port: 9000 });
  assert.deepEqual(lib.readConfig(configPath, dir), { serverUrl: "https://inny.example", shareOnLan: true, port: 9000 });
  fs.writeFileSync(configPath, "{zepsuty json");
  assert.equal(lib.readConfig(configPath, null).serverUrl, null);
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
