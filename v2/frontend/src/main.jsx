import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./ErrorBoundary";
import "./styles.css";
import "./v2.css";

// Aplikacja działa bez zasięgu dzięki service workerowi (tylko w wersji zbudowanej).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("/sw.js").catch(error => console.warn("[ASOLAR] Service worker nie został zarejestrowany", error)); });
}

createRoot(document.getElementById("root")).render(<React.StrictMode><ErrorBoundary><App /></ErrorBoundary></React.StrictMode>);
