"""Zatwierdzona baza źródłowa projektu dostarczona razem z aplikacją."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "project_sources"
MANIFEST_PATH = SOURCE_DIR / "source-manifest.json"


@lru_cache(maxsize=1)
def load_source_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_entry_by_hash(digest: str) -> dict | None:
    return next(
        (item for item in load_source_manifest()["documents"] if item["sha256"] == digest),
        None,
    )


def source_analysis(entry: dict) -> dict:
    manifest = load_source_manifest()
    filename = entry["filename"]
    instructions = [
        item for item in manifest["instructions"] if item["source_file"] == filename
    ]
    result = {
        "approved_source": True,
        "sha256": entry["sha256"],
        "role": entry["role"],
        "facts": entry.get("facts", []),
        "summary": {
            "pages": entry["pages"],
            "instructions": len(instructions),
            "source_policy": "zatwierdzone źródło projektu",
        },
        "instructions": instructions,
    }
    if filename == "montaż mechaniczny.pdf":
        result["tools"] = manifest["tools"]
        result["torques"] = manifest["torques"]
        result["variants"] = manifest["templates"]
    return result

