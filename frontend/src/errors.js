import { lazy } from "react";

/* Globalne łapanie błędów: nieobsłużony wyjątek lub odrzucona obietnica nie może zostawić białego ekranu.
 * Błędy są zapisywane (ostatnie 20) i zgłaszane do interfejsu zdarzeniem "asolar:error". */
const LOG_KEY = "asolar_error_log";
const IGNORED = [/ResizeObserver loop/i, /^Script error\.?$/i];

export function recordError(source, error) {
  const message = String(error?.message || error || "Nieznany błąd");
  if (IGNORED.some(pattern => pattern.test(message))) return null;
  const entry = { at: new Date().toISOString(), source, message: message.slice(0, 500) };
  try {
    const log = JSON.parse(localStorage.getItem(LOG_KEY) || "[]");
    localStorage.setItem(LOG_KEY, JSON.stringify([entry, ...(Array.isArray(log) ? log : [])].slice(0, 20)));
  } catch { /* brak dostępu do localStorage */ }
  try { window.dispatchEvent(new CustomEvent("asolar:error", { detail: entry })); } catch { /* brak window */ }
  return entry;
}

export function errorLog() {
  try { return JSON.parse(localStorage.getItem(LOG_KEY) || "[]"); } catch { return []; }
}

let installed = false;
export function installGlobalErrorHandlers(target = window) {
  if (installed) return;
  installed = true;
  target.addEventListener("error", event => {
    // Błąd wczytania skryptu/arkusza obsługuje skrypt ratunkowy w index.html.
    if (event.target && event.target !== target && (event.target.tagName === "SCRIPT" || event.target.tagName === "LINK")) return;
    recordError("window.onerror", event.error || event.message);
  }, true);
  target.addEventListener("unhandledrejection", event => {
    recordError("unhandledrejection", event.reason);
    event.preventDefault?.();
  });
}

/** React.lazy z jedną ponowną próbą — chwilowy brak sieci nie kończy się błędem modułu. */
export function lazyWithRetry(loader, retries = 1, delayMs = 800) {
  return lazy(() => attempt(loader, retries, delayMs));
}

async function attempt(loader, retries, delayMs) {
  try { return await loader(); }
  catch (error) {
    if (retries <= 0) throw error;
    await new Promise(resolve => setTimeout(resolve, delayMs));
    return attempt(loader, retries - 1, delayMs);
  }
}
