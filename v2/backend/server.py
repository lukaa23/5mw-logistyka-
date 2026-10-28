"""Uruchamia serwer ASOLAR v2 (http://127.0.0.1:8770 lokalnie, PORT na serwerze)."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("asolar2.main:app", host=os.getenv("ASOLAR_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8770")), reload=False)
