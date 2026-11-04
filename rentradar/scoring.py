"""Transparent, user-adjustable scoring.

Instructor feedback (10/29): "data sources + weights are what matters -- make
the weights transparent". So the score is a plain weighted average of 0-100
factor scores, every factor's formula is listed in FACTORS, and the API
returns the full breakdown. Factors without data (e.g. RentSmart for a
Cambridge listing) are *left out* of the average and reported as missing --
never filled with a guess.

No factor uses demographics (Fair Housing Act); see guardrails.py.
"""
from __future__ import annotations

import bisect
from typing import Dict, List, Optional

FACTORS: Dict[str, Dict[str, str]] = {
    "price": {"label": "Price", "how": "With a budget: 100 at <=85% of budget, 50 at budget, 0 at 115%. Without: rank of rent per bedroom (cheaper = higher)."},
    "commute": {"label": "Bike commute", "how": "Estimated bike minutes to your campus: 100 at <=10 min, 0 at >=45 min (straight line x 1.3 at 15 km/h)."},
    "transit": {"label": "T access", "how": "Walk minutes to the nearest subway / Green Line station: 100 at <=5 min, 0 at >=20 min."},
    "building": {"label": "Building record", "how": "City complaints + violations at this address in the last 3 years, weighted by severity (heat, pests, mold, safety count most): 100 x exp(-weighted/6)."},
    "landlord": {"label": "Owner record", "how": "Start 70; +20 if owner-occupied; -5 per serious record (heat, pests, mold, safety, structural) at any property of the same owner in 3 years (max -60); -10 if the owner mails from outside MA."},
    "street_safety": {"label": "Street safety", "how": "Rank of (injury crashes + 2 x pedestrian/bike crashes) within 150 m, 2021-2025, plus dark-hour bike crashes along the line to campus (fewer = higher)."},
    "quiet": {"label": "Traffic noise", "how": "Rank of the busiest road (AADT, vehicles/day) within 100 m (quieter = higher)."},
    "freshness": {"label": "Listing freshness", "how": "Days on market: 100 at <=14 days, 0 at >=365 days. Very old listings are often stale or already rented."},
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "price": 3, "commute": 3, "building": 3, "landlord": 2,
    "street_safety": 2, "quiet": 1, "transit": 1, "freshness": 1,
}


def _lin(x: float, best: float, worst: float) -> float:
    """100 at `best`, 0 at `worst`, linear in between (works for either order)."""
    if best == worst:
        return 100.0
    t = (x - best) / (worst - best)
    return round(100.0 * (1.0 - max(0.0, min(1.0, t))), 1)


def _rank_score(sorted_vals: List[float], x: float) -> float:
    """Share of listings that are *worse* (higher) than x, as 0-100."""
    if not sorted_vals:
        return 50.0
    lo = bisect.bisect_left(sorted_vals, x)
    hi = bisect.bisect_right(sorted_vals, x)
    mid = (lo + hi) / 2
    return round(100.0 * (1 - mid / len(sorted_vals)), 1)


def _street_raw(f: dict, campus: str) -> Optional[float]:
    s = f.get("street") or {}
    if not s.get("available"):
        return None
    raw = s["injury_crashes"] + 2 * s["ped_bike_crashes"]
    raw += (f.get("commute", {}).get(campus, {}) or {}).get("corridor_bike_crashes_dark", 0)
    return float(raw)


def _ppb(listing: dict) -> float:
    return listing["price"] / max(1.0, float(listing.get("bedrooms") or 0) or 1.0)


class Scorer:
    def __init__(self, listings: List[dict], features: Dict[str, dict]):
        self.ppb = sorted(_ppb(l) for l in listings)
        self.street = {c: sorted(v for v in (_street_raw(features[l["id"]], c) for l in listings) if v is not None)
                       for c in ("mit", "harvard", "seas")}
        self.aadt = sorted((features[l["id"]].get("noise") or {}).get("max_aadt_100m") or 0
                           for l in listings if (features[l["id"]].get("noise") or {}).get("available"))

    def factor_scores(self, listing: dict, f: dict, campus: str, budget: Optional[float] = None) -> Dict[str, Optional[float]]:
        out: Dict[str, Optional[float]] = {}
        price = listing["price"]
        if budget:
            step = 0.15 * budget
            if price <= 0.85 * budget:
                out["price"] = 100.0
            elif price <= budget:
                out["price"] = round(100 - 50 * (price - 0.85 * budget) / step, 1)
            else:
                out["price"] = round(max(0.0, 50 - 50 * (price - budget) / step), 1)
        else:
            out["price"] = _rank_score(self.ppb, _ppb(listing))

        c = (f.get("commute") or {}).get(campus)
        out["commute"] = _lin(c["bike_min"], 10, 45) if c else None

        t = f.get("transit") or {}
        if t.get("available"):
            out["transit"] = _lin(t["station_walk_min"], 5, 20) if t.get("station") else 0.0
        else:
            out["transit"] = None

        b = f.get("building") or {}
        out["building"] = round(100 * pow(2.718281828, -b["severity_weighted"] / 6.0), 1) if b.get("available") else None

        o = f.get("owner") or {}
        if o.get("available"):
            s = 70.0
            if o.get("owner_occupied"):
                s += 20
            s -= min(60, 5 * (o.get("portfolio_serious_records_window") or 0))
            if o.get("out_of_state"):
                s -= 10
            out["landlord"] = max(0.0, min(100.0, s))
        else:
            out["landlord"] = None

        raw = _street_raw(f, campus)
        out["street_safety"] = _rank_score(self.street.get(campus, []), raw) if raw is not None else None

        n = f.get("noise") or {}
        out["quiet"] = _rank_score(self.aadt, n.get("max_aadt_100m") or 0) if n.get("available") else None

        dom = (f.get("listing") or {}).get("days_on_market")
        out["freshness"] = _lin(dom, 14, 365) if dom is not None else None
        return out

    def score(self, listing: dict, f: dict, campus: str = "mit", weights: Optional[Dict[str, float]] = None, budget: Optional[float] = None) -> dict:
        w = dict(DEFAULT_WEIGHTS)
        if weights:
            for k, v in weights.items():
                if k in w and v is not None:
                    w[k] = max(0.0, min(5.0, float(v)))
        fs = self.factor_scores(listing, f, campus, budget)
        num = den = 0.0
        breakdown = []
        for k, s in fs.items():
            entry = {"factor": k, "label": FACTORS[k]["label"], "score": s, "weight": w[k]}
            if s is None:
                entry["missing"] = True
            elif w[k] > 0:
                num += w[k] * s
                den += w[k]
                entry["contribution"] = round(w[k] * s, 1)
            breakdown.append(entry)
        total = round(num / den, 1) if den else None
        covered = round(100 * den / sum(v for v in w.values()) if sum(w.values()) else 0)
        return {"total": total, "weight_coverage_pct": covered, "breakdown": breakdown, "campus": campus}
