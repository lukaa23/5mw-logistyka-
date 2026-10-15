"""Zatwierdzona baza źródłowa projektu dostarczona razem z aplikacją."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "project_sources"
MANIFEST_PATH = SOURCE_DIR / "source-manifest.json"
BOM_PATH = SOURCE_DIR / "eset-bom.json"


@lru_cache(maxsize=1)
def load_source_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_eset_bom() -> dict:
    return json.loads(BOM_PATH.read_text(encoding="utf-8"))


def build_eset_demand(counts: dict[str, int]) -> dict:
    """Build immutable per-row and project demand from the approved ESET BOM."""
    bom = load_eset_bom()
    catalogue = bom["components"]
    grand: dict[str, int] = {}
    variants = []
    for definition in bom["variants"]:
        code = definition["code"]
        row_count = max(0, int(counts.get(code, 0)))
        per_row = []
        totals = []
        for key, quantity in bom["quantities"][code].items():
            component = {"key": key, **catalogue[key]}
            per_row.append({**component, "quantity_per_row": quantity})
            total = quantity * row_count
            totals.append({**component, "quantity_total": total})
            if total:
                grand[key] = grand.get(key, 0) + total
        variants.append({
            **definition,
            "row_count": row_count,
            "total_modules": definition["modules"] * row_count,
            "per_row": per_row,
            "totals": totals,
        })
    grand_total = [
        {"key": key, **catalogue[key], "quantity_total": quantity}
        for key, quantity in grand.items()
    ]
    order = {name: index for index, name in enumerate([
        "Słupy", "Napęd i łożyska", "Rury torsyjne", "Płatwie",
        "Amortyzatory", "Sterowanie", "Śruby i zestawy",
    ])}
    sorter = lambda item: (order.get(item["category"], 99), item["name"], item["spec"])
    for variant in variants:
        variant["per_row"].sort(key=sorter)
        variant["totals"].sort(key=sorter)
    grand_total.sort(key=sorter)
    return {
        "policy": bom["policy"],
        "total_rows": sum(item["row_count"] for item in variants),
        "total_modules": sum(item["total_modules"] for item in variants),
        "variants": variants,
        "grand_total": grand_total,
    }


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

