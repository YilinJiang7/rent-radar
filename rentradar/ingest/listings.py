"""RentCast long-term rental listings (JSON arrays saved by scripts/fetch_rentcast.py)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from .. import address, config
from ..geo import haversine_m, nearest_area


def _area_for(row: dict) -> tuple:
    """Return (area_zip, corrected?) -- trust the zip unless coords disagree."""
    z = address.norm_zip(row.get("zipCode"))
    lat, lon = row.get("latitude"), row.get("longitude")
    if z in config.AREAS:
        return z, False
    # A valid Boston/Cambridge zip that is simply outside v1 scope -> drop.
    if z.startswith(("021", "022")) or lat is None or lon is None:
        return None, False
    # Otherwise the zip is wrong for the city (RentCast gave 02720 for some
    # Cambridge rows): place by coordinates, same city, within 2 km.
    city = (row.get("city") or "").lower()
    candidates = {k: v for k, v in config.AREAS.items() if v[1].lower() == city}
    if not candidates:
        return None, False
    guess = nearest_area(lat, lon, candidates)
    _, _, clat, clon = config.AREAS[guess]
    if haversine_m(lat, lon, clat, clon) <= 2000:
        return guess, True
    return None, False


def load(paths: Iterable[Path], today: datetime = None) -> List[Dict]:
    today = today or datetime.now(timezone.utc)
    by_id: Dict[str, Dict] = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        if isinstance(data, dict):  # tolerate {"listings": [...]}
            data = data.get("listings") or data.get("data") or []
        for r in data:
            if r.get("status") and r["status"] != "Active":
                continue
            if r.get("price") in (None, 0) or r.get("latitude") is None:
                continue
            area_zip, corrected = _area_for(r)
            if area_zip is None:
                continue  # outside v1 scope
            key = address.parse(r.get("addressLine1") or r.get("formattedAddress", ""), area_zip if corrected else r.get("zipCode"))
            dom = r.get("daysOnMarket")
            if dom is None and r.get("listedDate"):
                try:
                    ld = datetime.fromisoformat(r["listedDate"].replace("Z", "+00:00"))
                    if ld.tzinfo is None:
                        ld = ld.replace(tzinfo=timezone.utc)
                    dom = (today - ld).days
                except (ValueError, TypeError):
                    dom = None
            agent = r.get("listingAgent") or {}
            office = r.get("listingOffice") or {}
            row = {
                "id": r["id"],
                "address": r.get("formattedAddress"),
                "address_line1": r.get("addressLine1"),
                "unit": r.get("addressLine2"),
                "city": r.get("city"),
                "zip": address.norm_zip(r.get("zipCode")),
                "area_zip": area_zip,
                "area": config.AREAS[area_zip][0],
                "zip_corrected": int(corrected),
                "lat": r["latitude"],
                "lon": r["longitude"],
                "price": int(r["price"]),
                "bedrooms": r.get("bedrooms"),
                "bathrooms": r.get("bathrooms"),
                "sqft": r.get("squareFootage"),
                "property_type": r.get("propertyType"),
                "listed_date": (r.get("listedDate") or "")[:10],
                "last_seen": (r.get("lastSeenDate") or "")[:10],
                "days_on_market": dom,
                "stale": int(dom is not None and dom > config.STALE_DAYS),
                "agent_name": agent.get("name"),
                "office_name": office.get("name"),
                "mls_name": r.get("mlsName"),
                "street_key": key.street_zip if key else None,
                "num_lo": key.lo if key else None,
                "num_hi": key.hi if key else None,
                "source_file": Path(p).name,
            }
            prev = by_id.get(row["id"])
            if prev is None or (row["last_seen"] or "") >= (prev["last_seen"] or ""):
                by_id[row["id"]] = row
    return list(by_id.values())
