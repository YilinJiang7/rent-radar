"""RentCast long-term rental listings (JSON arrays saved by scripts/fetch_rentcast.py).

Snapshot rules (feedback 11/4: "define the listing snapshot"):
  * only the newest snapshot is used -- files named YYYY-MM-DD_<zip>.json share a date;
  * status Active, with price and coordinates, inside the v1 zip codes;
  * tiers by days on market: <= FRESH_DAYS "fresh" (shown), <= BACKUP_DAYS "older"
    (kept as backups, hidden by default), older ones dropped;
  * dropped if RentCast has not seen it active for NOT_SEEN_DAYS before the pull.
Every rule's effect is counted in the coverage funnel.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .. import address, config
from ..geo import haversine_m, nearest_area

SNAP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def snapshot_date(p: Path) -> Optional[str]:
    m = SNAP_RE.match(Path(p).name)
    return m.group(1) if m else None


def group_snapshots(paths: Iterable[Path]) -> List[Tuple[str, List[Path]]]:
    """[(date or 'undated', files)] newest first; undated files only count when nothing is dated."""
    groups: Dict[str, List[Path]] = {}
    for p in paths:
        groups.setdefault(snapshot_date(p) or "undated", []).append(Path(p))
    dated = sorted((d for d in groups if d != "undated"), reverse=True)
    out = [(d, sorted(groups[d])) for d in dated]
    if "undated" in groups:
        out.append(("undated", sorted(groups["undated"])))
    return out


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


def _days(a: str, b: date) -> Optional[int]:
    try:
        return (b - date.fromisoformat(a[:10])).days
    except (ValueError, TypeError):
        return None


def load_snapshot(paths: Iterable[Path], today: datetime = None) -> Tuple[List[Dict], Dict]:
    """Rows kept + a funnel dict counting what each rule removed."""
    today = today or datetime.now(timezone.utc)
    pull_day = today.date()
    f = Counter()
    by_id: Dict[str, Dict] = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        if isinstance(data, dict):  # tolerate {"listings": [...]}
            data = data.get("listings") or data.get("data") or []
        for r in data:
            f["retrieved"] += 1
            if r.get("status") and r["status"] != "Active":
                f["dropped_inactive"] += 1
                continue
            if r.get("price") in (None, 0) or r.get("latitude") is None:
                f["dropped_no_price_or_location"] += 1
                continue
            area_zip, corrected = _area_for(r)
            if area_zip is None:
                f["dropped_outside_scope"] += 1
                continue
            last_seen = (r.get("lastSeenDate") or "")[:10]
            unseen = _days(last_seen, pull_day) if last_seen else None
            if unseen is not None and unseen > config.NOT_SEEN_DAYS:
                f["dropped_not_seen_recently"] += 1
                continue
            dom = r.get("daysOnMarket")
            if dom is None and r.get("listedDate"):
                dom = _days(r["listedDate"], pull_day)
            if dom is not None and dom > config.BACKUP_DAYS:
                f["dropped_older_than_backup"] += 1
                continue
            tier = "fresh" if dom is None or dom <= config.FRESH_DAYS else "older"
            key = address.parse(r.get("addressLine1") or r.get("formattedAddress", ""), area_zip if corrected else r.get("zipCode"))
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
                "last_seen": last_seen,
                "days_on_market": dom,
                "tier": tier,
                "stale": int(tier == "older"),
                "agent_name": agent.get("name"),
                "office_name": office.get("name"),
                "mls_name": r.get("mlsName"),
                "street_key": key.street_zip if key else None,
                "num_lo": key.lo if key else None,
                "num_hi": key.hi if key else None,
                "source_file": Path(p).name,
            }
            prev = by_id.get(row["id"])
            if prev is not None:
                f["duplicates_merged"] += 1
            if prev is None or (row["last_seen"] or "") >= (prev["last_seen"] or ""):
                by_id[row["id"]] = row
    rows = list(by_id.values())
    f["kept"] = len(rows)
    f["fresh"] = sum(1 for r in rows if r["tier"] == "fresh")
    f["older"] = sum(1 for r in rows if r["tier"] == "older")
    return rows, dict(f)


def load(paths: Iterable[Path], today: datetime = None) -> List[Dict]:
    return load_snapshot(paths, today)[0]


def active_ids(paths: Iterable[Path]) -> set:
    """In-scope Active listing ids of a snapshot (for comparing two pulls)."""
    ids = set()
    for p in paths:
        data = json.loads(Path(p).read_text())
        if isinstance(data, dict):
            data = data.get("listings") or data.get("data") or []
        for r in data:
            if (not r.get("status") or r["status"] == "Active") and _area_for(r)[0]:
                ids.add(r["id"])
    return ids
