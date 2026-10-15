"""Uruchamia lokalny serwer ASOLAR ESET Tracker Manager w przeglądarce."""

import os
import threading
import webbrowser

import uvicorn


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8765"))
    host = os.getenv("ASOLAR_HOST", "127.0.0.1")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"ASOLAR ESET Tracker Manager działa pod adresem http://127.0.0.1:{port}")
    print("Aby zakończyć, zamknij to okno lub naciśnij Ctrl+C.")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
