import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./ErrorBoundary";
import { installGlobalErrorHandlers } from "./errors";
import "./styles.css";

installGlobalErrorHandlers();

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(error => console.warn("[ASOLAR] Service worker niedostępny — aplikacja działa bez cache offline", error));
  });
}

createRoot(document.getElementById("root")).render(<React.StrictMode><ErrorBoundary fullScreen><App /></ErrorBoundary></React.StrictMode>);
window.__asolarMounted = true;
