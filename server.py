"""Zgodny wstecznie punkt startowy aplikacji ASOLAR Enterprise."""

import os
import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("ASOLAR_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8765")),
        reload=False,
    )
