"use strict";
/* Most między lokalnym ekranem ustawień (setup.html) a procesem głównym.
 * API jest udostępniane wyłącznie stronie z pliku lokalnego — nigdy stronie serwera w chmurze. */
const { contextBridge, ipcRenderer } = require("electron");

if (window.location.protocol === "file:") {
  contextBridge.exposeInMainWorld("asolarDesktop", {
    getSettings: () => ipcRenderer.invoke("asolar:get-settings"),
    connect: url => ipcRenderer.invoke("asolar:connect", url),
    useLocal: () => ipcRenderer.invoke("asolar:use-local"),
    retry: () => ipcRenderer.invoke("asolar:retry"),
  });
}
