"""Per-listing evidence: everything the map card, the scorer and the agent show.

Every number here is computed from a stored record and carries the IDs of the
records behind it, so the agent can cite them and the grounding check can
verify them.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional

from . import config, signals
from .geo import GridIndex, haversine_m

ENTITY_RE = re.compile(
    r"\b(LLC|L L C|INC|CORP|CORPORATION|TRUST|TRST|TR|LP|LLP|LTD|REALTY|PROPERTIES|HOLDINGS|MANAGEMENT|MGMT|ASSOC|ASSOCIATES|PARTNERS|GROUP|COMPANY|CO)\b"
)


def is_entity(owner: str) -> bool:
    return bool(owner and ENTITY_RE.search(owner.upper()))


class EvidenceIndex:
    """In-memory indices over the city tables, built once per build."""

    def __init__(self, records: List[dict], parcels: List[dict], crashes: List[dict], stations: List[dict], today: Optional[date] = None):
        self.today = today or date.today()
        self.records = records
        self.rec_by_street: Dict[str, List[dict]] = defaultdict(list)
        for r in records:
            if r.get("street_key"):
                self.rec_by_street[r["street_key"]].append(r)
        self.rec_grid = GridIndex(((r["lat"], r["lon"], r) for r in records if r.get("lat") and r.get("lon")), 100)
        self.rec_by_parcel: Dict[str, List[dict]] = defaultdict(list)
        for r in records:
            if r.get("parcel"):
                self.rec_by_parcel[r["parcel"]].append(r)
        self.rec_by_owner: Dict[str, List[dict]] = defaultdict(list)
        for r in records:
            if r.get("owner"):
                self.rec_by_owner[r["owner"]].append(r)

        self.parcels_by_street: Dict[str, List[dict]] = defaultdict(list)
        self.parcels_by_owner: Dict[str, List[dict]] = defaultdict(list)
        for p in parcels:
            self.parcels_by_street[p["street_key"]].append(p)
            if p.get("owner"):
                self.parcels_by_owner[p["owner"]].append(p)

        self.crash_grid = GridIndex(((c["lat"], c["lon"], c) for c in crashes), 200)
        self.rapid = GridIndex(((s["lat"], s["lon"], s) for s in stations if s["kind"] == "rapid_transit"), 400)
        self.bus = GridIndex(((s["lat"], s["lon"], s) for s in stations if s["kind"] == "bus"), 200)
        self.has_records = bool(records)
        self.has_parcels = bool(parcels)
        self.has_crashes = bool(crashes)
        self.has_stations = bool(stations)

    # -- building record -------------------------------------------------------
    def match_records(self, listing: dict) -> List[tuple]:
        """Return [(record, match_type)] for the listing's building."""
        hits = []
        sk = listing.get("street_key")
        if sk and sk in self.rec_by_street:
            lo, hi = listing["num_lo"], listing["num_hi"]
            for r in self.rec_by_street[sk]:
                if r["num_lo"] is not None and r["num_lo"] <= hi and lo <= r["num_hi"]:
                    exact = r["num_lo"] == lo and r["num_hi"] == hi
                    hits.append((r, "address" if exact else "address_range"))
        # parcel route: listing address -> assessment parcel ids -> RentSmart records on those parcels
        seen = {r["record_id"] for r, _m in hits}
        for pid in self.parcel_ids(listing):
            for r in self.rec_by_parcel.get(pid, []):
                if r["record_id"] not in seen:
                    hits.append((r, "parcel"))
                    seen.add(r["record_id"])
        if not hits and self.rec_grid.n:
            for _d, r in self.rec_grid.within(listing["lat"], listing["lon"], config.GEO_MATCH_M):
                hits.append((r, "geo"))
        return hits

    def parcels_for(self, listing: dict) -> List[dict]:
        sk = listing.get("street_key")
        if not sk or sk not in self.parcels_by_street:
            return []
        return [p for p in self.parcels_by_street[sk] if p["num_lo"] <= listing["num_hi"] and listing["num_lo"] <= p["num_hi"]]

    def parcel_ids(self, listing: dict) -> set:
        return {p["pid"] for p in self.parcels_for(listing) if p.get("pid")}

    def building(self, listing: dict, matches: List[tuple]) -> dict:
        covered = listing.get("city", "").lower() == "boston"
        if not covered or not self.has_records:
            return {"available": False, "reason": "RentSmart covers Boston only" if not covered else "RentSmart not loaded"}
        if not matches and not listing.get("street_key"):
            return {"available": False, "reason": "Listing address could not be parsed for matching"}
        cutoff = self.today.year - config.BUILDING_RECORD_YEARS
        recs = [r for r, _m in matches if r["building_level"]]
        window = [r for r in recs if (r.get("year") or 0) > cutoff]
        by_signal = Counter(r["signal"] for r in window)
        weighted = round(sum(signals.SEVERITY.get(r["signal"], 0.75) for r in window), 2)
        recent = sorted(recs, key=lambda r: r.get("date") or "", reverse=True)[:8]
        mtypes = Counter(m for _r, m in matches)
        return {
            "available": True,
            "match_type": mtypes.most_common(1)[0][0] if mtypes else "none",
            "records_total": len(recs),
            "window_years": config.BUILDING_RECORD_YEARS,
            "records_window": len(window),
            "by_signal": dict(by_signal.most_common()),
            "severity_weighted": weighted,
            "recent": [
                {k: r.get(k) for k in ("record_id", "date", "violation_type", "description", "signal")}
                for r in recent
            ],
        }

    # -- owner of record -------------------------------------------------------
    def owner(self, listing: dict, matches: List[tuple]) -> dict:
        contact = {"agent": listing.get("agent_name"), "office": listing.get("office_name")}
        parcels = self.parcels_for(listing)
        owners = Counter(p["owner"] for p in parcels if p.get("owner"))
        source = "property_assessment"
        if not owners:
            owners = Counter(r["owner"] for r, _m in matches if r.get("owner"))
            source = "rentsmart"
        if not owners:
            return {"available": False, "listing_contact": contact,
                    "reason": "No owner of record found for this address" if listing.get("city", "").lower() == "boston" else "Owner lookup covers Boston only"}
        top = owners.most_common(1)[0][0]
        top_parcels = [p for p in parcels if p.get("owner") == top]
        portfolio = self.parcels_by_owner.get(top, [])
        addrs = {(p["street_key"], p["num_lo"]) for p in portfolio}
        cutoff = self.today.year - config.BUILDING_RECORD_YEARS
        p_recs = [r for r in self.rec_by_owner.get(top, []) if r["building_level"] and (r.get("year") or 0) > cutoff]
        serious = [r for r in p_recs if signals.SEVERITY.get(r["signal"], 0) >= 2.5]
        mail_state = top_parcels[0].get("mail_state") if top_parcels else None
        occ_vals = [p.get("owner_occupied") for p in top_parcels if p.get("owner_occupied") is not None]
        owner_occ = any(occ_vals) if occ_vals else None
        return {
            "available": True,
            "source": source,
            "owner": top,
            "other_owners_in_building": len(owners) - 1,
            "is_entity": is_entity(top),
            "owner_occupied": owner_occ,
            "mail_state": mail_state,
            "out_of_state": bool(mail_state and mail_state != "MA"),
            "portfolio_properties": len(addrs) if addrs else None,
            "portfolio_records_window": len(p_recs),
            "portfolio_serious_records_window": len(serious),
            "portfolio_record_ids": [r["record_id"] for r in serious[:5]],
            "listing_contact": contact,
        }

    # -- street safety ---------------------------------------------------------
    def street(self, listing: dict) -> dict:
        if not self.has_crashes:
            return {"available": False, "reason": "Crash data not loaded"}
        near = [c for _d, c in self.crash_grid.within(listing["lat"], listing["lon"], config.CRASH_RADIUS_M)]
        years = sorted({c["year"] for c in near if c.get("year")})
        return {
            "available": True,
            "radius_m": config.CRASH_RADIUS_M,
            "crashes": len(near),
            "injury_crashes": sum(c["injury"] for c in near),
            "fatal_crashes": sum(1 for c in near if c["fatal"]),
            "ped_bike_crashes": sum(1 for c in near if c["ped"] or c["bike"]),
            "dark_crashes": sum(c["dark"] for c in near),
            "years": f"{years[0]}-{years[-1]}" if years else None,
            "sample_crash_ids": [c["crash_id"] for c in near if c["injury"]][:5],
        }

    # -- commute -----------------------------------------------------------------
    def commute(self, listing: dict) -> dict:
        out = {}
        for key, c in config.CAMPUSES.items():
            d = haversine_m(listing["lat"], listing["lon"], c["lat"], c["lon"])
            street_d = d * config.DETOUR_FACTOR
            entry = {
                "campus": c["name"],
                "straight_m": round(d),
                "walk_min": round(street_d / config.WALK_M_PER_MIN),
                "bike_min": round(street_d / config.BIKE_M_PER_MIN),
            }
            if self.has_crashes:
                along = [cr for _d, cr in self.crash_grid.along_segment(listing["lat"], listing["lon"], c["lat"], c["lon"], config.CORRIDOR_WIDTH_M)]
                entry["corridor_bike_crashes"] = sum(cr["bike"] for cr in along)
                entry["corridor_bike_crashes_dark"] = sum(1 for cr in along if cr["bike"] and cr["dark"])
            out[key] = entry
        return out

    # -- transit -----------------------------------------------------------------
    def transit(self, listing: dict) -> dict:
        if not self.has_stations:
            return {"available": False, "reason": "MBTA stops not loaded"}
        hit = self.rapid.nearest(listing["lat"], listing["lon"], config.STATION_SEARCH_M)
        buses = self.bus.within(listing["lat"], listing["lon"], config.BUS_STOP_RADIUS_M)
        res = {"available": True, "bus_stops_400m": len(buses)}
        if hit:
            d, s = hit
            res.update({"station": s["name"], "lines": s.get("lines") or "", "station_m": round(d),
                        "station_walk_min": round(d * config.DETOUR_FACTOR / config.WALK_M_PER_MIN)})
        else:
            res.update({"station": None, "station_m": None})
        return res

    # -- noise proxy -------------------------------------------------------------
    def noise(self, listing: dict, matches: List[tuple]) -> dict:
        res = {"available": self.has_crashes}
        if self.has_crashes:
            near = self.crash_grid.within(listing["lat"], listing["lon"], config.BUSY_ROAD_RADIUS_M)
            aadts = [(c.get("aadt") or 0, c.get("street")) for _d, c in near if c.get("aadt")]
            if aadts:
                top = max(aadts)
                res.update({"max_aadt_100m": top[0], "busiest_road": top[1]})
            else:
                res.update({"max_aadt_100m": None, "busiest_road": None})
        res["noise_records"] = sum(1 for r, _m in matches if r["signal"] == "noise")
        return res

    def compute(self, listing: dict) -> dict:
        matches = self.match_records(listing)
        return {
            "listing": {"days_on_market": listing.get("days_on_market"), "stale": bool(listing.get("stale"))},
            "building": self.building(listing, matches),
            "owner": self.owner(listing, matches),
            "street": self.street(listing),
            "commute": self.commute(listing),
            "transit": self.transit(listing),
            "noise": self.noise(listing, matches),
            "_matches": [(r["record_id"], m) for r, m in matches],
        }
