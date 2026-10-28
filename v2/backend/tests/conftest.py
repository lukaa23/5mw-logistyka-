import os
import sys
import tempfile
from pathlib import Path

# Pakiet asolar2 z folderu v2/backend; każde uruchomienie testów na świeżych danych lokalnych
# (CI ustawia DATABASE_URL na PostgreSQL — wtedy izolacja budów to osobne schematy).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ASOLAR_DATA_DIR", tempfile.mkdtemp(prefix="asolar-v2-test-"))
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret-v2")
os.environ.setdefault("ASOLAR_ADMIN_PASSWORD", "Asolar2026!")
