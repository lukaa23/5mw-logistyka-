"""Etap 4b: dostawy WZ wobec zapotrzebowania i stan materiałów na budowie.

Katalog materiałów budowy = pozycje BOM wszystkich typów + zatwierdzone komponenty (bez ilości).
WZ może zawierać tylko materiały z katalogu — dzięki temu każda dostawa trafia do bilansu.
Zapotrzebowanie pochodzi wyłącznie z zatwierdzonych danych (BOM × stoły danego typu).
"""
from collections import defaultdict

from sqlalchemy import func, select

from . import structure
from .tenancy import BomItem, CatalogItem, Delivery, DeliveryItem


def catalogue(session) -> dict[str, dict]:
    items: dict[str, dict] = {}
    for bom in session.scalars(select(BomItem).order_by(BomItem.name)).all():
        key = structure.material_key(bom.code, bom.name, bom.spec, bom.unit)
        items.setdefault(key, {"key": key, "name": bom.name, "code": bom.code, "spec": bom.spec, "unit": bom.unit, "source": "BOM"})
    for entry in session.scalars(select(CatalogItem).where(CatalogItem.kind == "component").order_by(CatalogItem.name)).all():
        key = structure.material_key(entry.code, entry.name, entry.spec, "szt.")
        items.setdefault(key, {"key": key, "name": entry.name, "code": entry.code, "spec": entry.spec, "unit": "szt.", "source": "komponent"})
    return items


def stock(session, zone_id: int | None = None) -> dict:
    """Bilans: dostarczone − uszkodzone wobec zapotrzebowania (całej budowy lub strefy)."""
    needs = {line["key"]: line for line in structure.requirements(session, zone_id)["totals"]}
    delivered = defaultdict(lambda: [0.0, 0.0])
    names = {}
    rows = session.execute(select(DeliveryItem.material_key, func.sum(DeliveryItem.quantity_received), func.sum(DeliveryItem.quantity_damaged)).group_by(DeliveryItem.material_key)).all()
    for key, received, damaged in rows:
        delivered[key] = [float(received or 0), float(damaged or 0)]
    for item in session.scalars(select(DeliveryItem).order_by(DeliveryItem.id.desc())).all():
        names.setdefault(item.material_key, {"name": item.name, "code": item.code, "spec": item.spec, "unit": item.unit})
    known = catalogue(session)
    result = []
    for key in sorted(set(needs) | set(delivered), key=lambda k: (needs.get(k) or known.get(k) or names.get(k) or {"name": k})["name"].lower()):
        info = needs.get(key) or known.get(key) or names.get(key) or {"name": key, "code": "", "spec": "", "unit": ""}
        required = float(needs[key]["total"]) if key in needs else 0.0
        received, damaged = delivered.get(key, (0.0, 0.0))
        available = received - damaged
        status = ("komplet" if available >= required else "brak") if required > 0 else "poza zapotrzebowaniem"
        result.append({"key": key, "name": info["name"], "code": info.get("code", ""), "spec": info.get("spec", ""), "unit": info.get("unit", ""),
                       "required": required, "delivered": received, "damaged": damaged, "available": available, "balance": available - required,
                       "completion_pct": round(min(100.0, available / required * 100), 1) if required > 0 else None, "status": status})
    required_items = [item for item in result if item["required"] > 0]
    return {"items": result, "summary": {"required_items": len(required_items), "complete_items": sum(item["status"] == "komplet" for item in required_items),
                                         "missing_items": sum(item["status"] == "brak" for item in required_items),
                                         "deliveries": session.scalar(select(func.count(Delivery.id))) or 0}}


def validate_items(session, items, already_in_delivery: dict[str, dict] | None = None) -> dict[str, dict]:
    """Zwraca katalog; ValueError z komunikatem dla kierownika/brygadzisty, gdy pozycje są błędne."""
    keys = [line.material_key for line in items]
    if len(set(keys)) != len(keys):
        raise ValueError("Każdy materiał może wystąpić w jednym WZ tylko raz — zsumuj ilości")
    if any(line.quantity_damaged > line.quantity_received for line in items):
        raise ValueError("Ilość uszkodzona nie może przekraczać ilości dostarczonej")
    # Edycja WZ: pozycja przyjęta wcześniej zostaje dozwolona, nawet jeśli zniknęła z BOM.
    known = {**(already_in_delivery or {}), **catalogue(session)}
    unknown = [key for key in keys if key not in known]
    if unknown:
        raise ValueError("Pozycja spoza katalogu materiałów budowy (BOM / komponenty) — najpierw zatwierdź ją w zakładce „Dokumenty i import” albo dodaj do BOM")
    return known
