"use strict";
/* ASOLAR ESET Tracker Manager — aplikacja desktopowa (Electron).
 *
 * Tryb serwera (komputer kierownika): uruchamia lokalny backend FastAPI (Python 3.11),
 * baza SQLite i zdjęcia trafiają do profilu użytkownika, opcjonalnie udostępnia serwer
 * telefonom w sieci lokalnej. Tryb klienta: gdy ustawiono adres serwera, otwiera go.
 */
const { app, BrowserWindow, Menu, dialog, shell, clipboard } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const lib = require("./lib");

const APP_TITLE = "ASOLAR ESET Tracker Manager";
const DEPS_MARKER = ".asolar-deps-v4";

let mainWindow = null;
let serverProcess = null;
let quitting = false;
let config = null;

const userDir = () => app.getPath("userData");
const configPath = () => path.join(userDir(), "config.json");
const dataDir = () => path.join(userDir(), "data");
const logDir = () => path.join(userDir(), "logs");
const runtimeDir = () => path.join(userDir(), "runtime-packages");
const exeDir = () => process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath("exe"));
const backendDir = () => (app.isPackaged ? path.join(process.resourcesPath, "backend") : path.resolve(__dirname, ".."));
const iconPath = () => path.join(__dirname, "build", "icon.ico");

function statusPage(title, message, detail = "") {
  const escape = value => String(value).replace(/[&<>"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
  const html = `<!doctype html><html lang="pl"><meta charset="utf-8"><title>${APP_TITLE}</title>
  <body style="margin:0;font-family:Segoe UI,system-ui,sans-serif;background:#0b2b21;color:#fff;display:grid;place-items:center;min-height:100vh">
  <main style="max-width:560px;padding:32px"><div style="width:56px;height:56px;border-radius:16px;background:#f4c64e;color:#0b2b21;display:grid;place-items:center;font-weight:800;font-size:28px">A</div>
  <h1 style="font-size:24px">${escape(title)}</h1><p style="line-height:1.6;color:#d6e5dd">${escape(message)}</p>
  ${detail ? `<pre style="white-space:pre-wrap;background:rgba(255,255,255,.08);padding:12px;border-radius:10px;font-size:12px">${escape(detail)}</pre>` : ""}</main></body></html>`;
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 380,
    minHeight: 560,
    title: APP_TITLE,
    icon: iconPath(),
    backgroundColor: "#f3f6f4",
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false },
  });
  mainWindow.on("page-title-updated", event => event.preventDefault());
  mainWindow.on("closed", () => { mainWindow = null; });
}

/** Zewnętrzne adresy otwieramy w przeglądarce; okno aplikacji pozostaje przy własnym serwerze. */
function lockNavigation(appOrigin) {
  const contents = mainWindow.webContents;
  contents.setWindowOpenHandler(({ url }) => {
    if (lib.isAppUrl(url, appOrigin)) return { action: "allow", overrideBrowserWindowOptions: { icon: iconPath(), autoHideMenuBar: true } };
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (!lib.isAppUrl(url, appOrigin) && !url.startsWith("data:")) { event.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); }
  });
}

function python(args, options = {}) {
  return spawnSync("py", ["-3.11", ...args], { windowsHide: true, encoding: "utf8", ...options });
}

async function ensurePythonDependencies() {
  const check = python(["--version"]);
  if (check.error || check.status !== 0) {
    throw Object.assign(new Error("Nie znaleziono Pythona 3.11 (polecenie „py -3.11”)."), { hint: "Zainstaluj Python 3.11 z python.org razem z Python Launcher albo ustaw w menu Serwer → „Połącz z serwerem zdalnym” adres wspólnego serwera HTTPS." });
  }
  const marker = path.join(runtimeDir(), DEPS_MARKER);
  if (fs.existsSync(marker)) return;
  mainWindow.loadURL(statusPage("Pierwsze uruchomienie", "Instaluję składniki serwera (jednorazowo, wymaga Internetu). To może potrwać kilka minut…"));
  fs.mkdirSync(runtimeDir(), { recursive: true });
  await new Promise((resolve, reject) => {
    const child = spawn("py", ["-3.11", "-m", "pip", "install", "--upgrade", "--target", runtimeDir(), "-r", path.join(backendDir(), "requirements.txt")], { windowsHide: true });
    let output = "";
    child.stdout.on("data", chunk => { output += chunk; });
    child.stderr.on("data", chunk => { output += chunk; });
    child.on("error", reject);
    child.on("exit", code => (code === 0 ? resolve() : reject(Object.assign(new Error("Instalacja składników nie powiodła się."), { hint: output.slice(-1500) }))));
  });
  fs.writeFileSync(marker, new Date().toISOString());
}

async function startLocalServer() {
  const port = config.port;
  const base = `http://127.0.0.1:${port}`;
  if (await lib.isPortBusy(port)) {
    throw Object.assign(new Error(`Port ${port} jest już zajęty.`), { hint: "Prawdopodobnie działa już inna instancja ASOLAR (np. Uruchom-Windows.bat) lub inny program. Zamknij ją i uruchom aplikację ponownie — program nie otwiera starej instancji, aby nie pracować na nieaktualnej wersji." });
  }
  await ensurePythonDependencies();
  mainWindow.loadURL(statusPage("Uruchamianie serwera", "Uruchamiam lokalny serwer ASOLAR na tym komputerze…"));
  fs.mkdirSync(logDir(), { recursive: true });
  const log = fs.openSync(path.join(logDir(), "server.log"), "a");
  const env = {
    ...process.env,
    PYTHONPATH: [runtimeDir(), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    PYTHONUNBUFFERED: "1",
    ASOLAR_DATA_DIR: dataDir(),
    ASOLAR_HOST: config.shareOnLan ? "0.0.0.0" : "127.0.0.1",
    ASOLAR_SECRET: process.env.ASOLAR_SECRET || lib.ensureSecret(path.join(userDir(), "secret.key")),
    PORT: String(port),
  };
  serverProcess = spawn("py", ["-3.11", "server.py"], { cwd: backendDir(), env, windowsHide: true, stdio: ["ignore", log, log] });
  let exited = false;
  serverProcess.on("exit", code => {
    exited = true;
    serverProcess = null;
    if (!quitting && mainWindow) mainWindow.loadURL(statusPage("Serwer zatrzymał się", `Lokalny serwer zakończył pracę (kod ${code}). Dane są zapisane w folderze danych. Uruchom aplikację ponownie.`, `Dziennik: ${path.join(logDir(), "server.log")}`));
  });
  await lib.waitForHealth(base, { timeoutMs: 90000, isAlive: () => !exited });
  return base;
}

function stopLocalServer() {
  if (!serverProcess) return;
  const pid = serverProcess.pid;
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
    else serverProcess.kill("SIGTERM");
  } catch { /* proces już zakończony */ }
  serverProcess = null;
}

function buildMenu(mode) {
  const local = mode === "local";
  const template = [
    { label: "Plik", submenu: [
      { label: "Otwórz folder danych (baza i zdjęcia)", enabled: local, click: () => { fs.mkdirSync(dataDir(), { recursive: true }); shell.openPath(dataDir()); } },
      { label: "Otwórz dziennik serwera", enabled: local, click: () => shell.openPath(path.join(logDir(), "server.log")) },
      { type: "separator" },
      { role: "quit", label: "Zakończ" },
    ] },
    { label: "Serwer", submenu: [
      { label: "Udostępnij serwer telefonom w sieci lokalnej", type: "checkbox", checked: config.shareOnLan, enabled: local, click: item => { config.shareOnLan = item.checked; lib.writeConfig(configPath(), config); restartApp("Ustawienie zostanie zastosowane po ponownym uruchomieniu serwera."); } },
      { label: "Pokaż adresy dla telefonów", enabled: local, click: showLanAddresses },
      { type: "separator" },
      { label: "Połącz z serwerem zdalnym (plik konfiguracji)…", click: editConfig },
      { label: "Wróć do serwera na tym komputerze", enabled: !local, click: () => { config.serverUrl = null; lib.writeConfig(configPath(), config); restartApp("Aplikacja uruchomi lokalny serwer."); } },
    ] },
    { label: "Widok", submenu: [{ role: "reload", label: "Odśwież" }, { role: "togglefullscreen", label: "Pełny ekran" }, { role: "resetZoom", label: "Rzeczywisty rozmiar" }, { role: "zoomIn", label: "Powiększ" }, { role: "zoomOut", label: "Pomniejsz" }, { type: "separator" }, { role: "toggleDevTools", label: "Narzędzia deweloperskie" }] },
    { label: "Pomoc", submenu: [{ label: "O programie", click: () => dialog.showMessageBox(mainWindow, { type: "info", title: APP_TITLE, message: `${APP_TITLE} ${app.getVersion()}`, detail: local ? `Tryb: serwer na tym komputerze\nDane: ${dataDir()}` : `Tryb: klient serwera ${config.serverUrl}` }) }] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function showLanAddresses() {
  const addresses = lib.lanAddresses();
  const urls = addresses.map(address => `http://${address}:${config.port}`);
  const detail = config.shareOnLan
    ? (urls.length ? `${urls.join("\n")}\n\nTelefon musi być w tej samej sieci Wi-Fi. Zapora Windows może zapytać o zgodę dla Pythona.\n\nUwaga: przez http:// w sieci lokalnej telefon pracuje online, ale nie zainstaluje pełnej PWA offline — do tego potrzebny jest adres HTTPS (README).` : "Nie wykryto połączenia z siecią lokalną.")
    : "Udostępnianie jest wyłączone. Włącz: Serwer → „Udostępnij serwer telefonom w sieci lokalnej”.";
  dialog.showMessageBox(mainWindow, { type: "info", title: "Adresy dla telefonów", message: "Adres serwera dla brygadzistów", detail, buttons: urls.length && config.shareOnLan ? ["Kopiuj pierwszy adres", "Zamknij"] : ["Zamknij"] })
    .then(({ response }) => { if (response === 0 && urls.length && config.shareOnLan) clipboard.writeText(urls[0]); });
}

function editConfig() {
  lib.writeConfig(configPath(), config);
  dialog.showMessageBox(mainWindow, { type: "info", title: "Serwer zdalny", message: "W pliku konfiguracji wpisz adres wspólnego serwera w polu \"serverUrl\" (np. https://asolar-eset-tracker.onrender.com), zapisz plik i uruchom aplikację ponownie.", detail: configPath() })
    .then(() => shell.openPath(configPath()));
}

function restartApp(message) {
  dialog.showMessageBox(mainWindow, { type: "info", title: APP_TITLE, message, buttons: ["Uruchom ponownie teraz", "Później"] }).then(({ response }) => {
    if (response === 0) { app.relaunch(); app.quit(); }
  });
}

async function boot() {
  config = lib.readConfig(configPath(), exeDir());
  createWindow();
  mainWindow.loadURL(statusPage("Uruchamianie", "Przygotowuję aplikację…"));
  try {
    let target;
    if (config.serverUrl) {
      buildMenu("remote");
      target = config.serverUrl;
    } else {
      buildMenu("local");
      target = await startLocalServer();
    }
    lockNavigation(new URL(target).origin);
    await mainWindow.loadURL(target);
  } catch (error) {
    if (mainWindow) mainWindow.loadURL(statusPage("Nie udało się uruchomić", error.message, error.hint || ""));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); } });
  app.setAppUserModelId("pl.asolar.eset-tracker");
  app.whenReady().then(boot);
  app.on("before-quit", () => { quitting = true; stopLocalServer(); });
  app.on("window-all-closed", () => app.quit());
}
