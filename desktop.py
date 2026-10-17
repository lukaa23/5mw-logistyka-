"""Uruchamia lokalny serwer ASOLAR ESET Tracker Manager w przeglądarce."""

import os
import socket
import sys
import threading
import webbrowser

import uvicorn


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8765"))
    host = os.getenv("ASOLAR_HOST", "127.0.0.1")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Port {port} jest już zajęty — prawdopodobnie działa poprzednia wersja ASOLAR.")
            print("Zamknij wcześniejsze czarne okno programu, a następnie ponownie uruchom Uruchom-Windows.bat.")
            if os.getenv("ASOLAR_DESKTOP_EXE"):
                try:
                    input("Naciśnij Enter, aby zamknąć to okno...")
                except EOFError:
                    pass
            sys.exit(2)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"ASOLAR ESET Tracker Manager v4.5.1 działa pod adresem http://127.0.0.1:{port}")
    print("Aby zakończyć, zamknij to okno lub naciśnij Ctrl+C.")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
