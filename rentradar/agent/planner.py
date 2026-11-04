"""Offline intent parser: plain-language needs -> filters + weights.

Used when no GEMINI_API_KEY is set (demo fallback) and as a unit-testable
reference for what the LLM agent is expected to do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import config
from ..scoring import DEFAULT_WEIGHTS

AREA_WORDS = {
    "allston": "02134", "brighton": "02135", "fenway": "02215", "kenmore": "02215",
    "harvard square": "02138", "harvard sq": "02138", "west cambridge": "02138",
    "central": "02139", "cambridgeport": "02139", "porter": "02140", "north cambridge": "02140",
    "east cambridge": "02141", "kendall": "02142",
}


@dataclass
class Plan:
    campus: str = config.DEFAULT_CAMPUS
    max_price: Optional[float] = None
    min_beds: Optional[float] = None
    max_beds: Optional[float] = None
    areas: Optional[List[str]] = None
    max_bike_min: Optional[float] = None
    include_stale: bool = False
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    notes: List[str] = field(default_factory=list)

    def tool_args(self) -> dict:
        return {k: v for k, v in {
            "campus": self.campus, "max_price": self.max_price, "min_beds": self.min_beds,
            "max_beds": self.max_beds, "areas": self.areas, "max_bike_min": self.max_bike_min,
            "include_stale": self.include_stale, "weights": self.weights,
        }.items() if v is not None}


def _money(s: str) -> Optional[float]:
    s = s.replace(",", "").replace("$", "").strip().lower()
    mult = 1000 if s.endswith("k") else 1
    s = s.rstrip("k")
    try:
        v = float(s) * mult
    except ValueError:
        return None
    return v if 500 <= v <= 20000 else None


def parse(query: str, campus_hint: Optional[str] = None) -> Plan:
    q = (query or "").lower()
    p = Plan()

    # campus
    if campus_hint in config.CAMPUSES:
        p.campus = campus_hint
    if re.search(r"\bseas\b|allston campus|science and engineering complex|\bsec\b", q):
        p.campus = "seas"
    elif re.search(r"\bharvard\b", q) and not re.search(r"harvard (sq|square)", q):
        p.campus = "harvard"
    elif re.search(r"\bmit\b|kendall campus", q):
        p.campus = "mit"

    # budget
    m = re.search(r"(?:budget|under|below|max(?:imum)?|up to|less than|<=?|no more than)\s*(?:of|is|:)?\s*\$?\s*([\d,.]+k?)", q)
    if not m:
        m = re.search(r"\$\s*([\d,.]+k?)", q)
    if m:
        p.max_price = _money(m.group(1))
        if p.max_price:
            p.notes.append(f"budget <= ${p.max_price:,.0f}")

    # bedrooms
    if re.search(r"\bstudio\b", q):
        p.min_beds, p.max_beds = 0, 0
    m = re.search(r"(\d)\s*(?:-|\s)?(?:bed(?:room)?s?|br|b\b)", q)
    if m:
        p.min_beds = float(m.group(1))
        p.max_beds = float(m.group(1))
    m = re.search(r"(?:at least|min(?:imum)?)\s*(\d)\s*(?:bed|br)", q)
    if m:
        p.min_beds, p.max_beds = float(m.group(1)), None

    # areas
    found = sorted({z for w, z in AREA_WORDS.items() if re.search(r"\b" + re.escape(w) + r"\b", q)})
    found += [z for z in re.findall(r"\b(02\d{3})\b", q) if z in config.AREAS and z not in found]
    if found:
        p.areas = found

    # commute limit
    m = re.search(r"(?:within|under|less than|max)\s*(\d{1,2})\s*(?:min|minutes)\s*(?:bike|by bike|biking|ride)?", q)
    if m and re.search(r"bike|biking|cycle|ride", q):
        p.max_bike_min = float(m.group(1))

    if re.search(r"include (old|older|stale|all)|old listings|stale listings|all listings", q):
        p.include_stale = True

    # preferences -> weights
    w = p.weights
    if re.search(r"noise|noisy|quiet|light sleeper|loud|sleep", q):
        w["quiet"] = 5
        w["building"] = max(w["building"], 3)
        p.notes.append("quiet weighted up")
    if re.search(r"bike|biking|cycl", q):
        w["commute"] = 5
        w["street_safety"] = max(w["street_safety"], 4)
        p.notes.append("bike commute + street safety weighted up")
    if re.search(r"night|late|dark", q):
        w["street_safety"] = 5
        p.notes.append("night-time street safety weighted up")
    if re.search(r"\bsafe|safety\b", q):
        w["street_safety"] = max(w["street_safety"], 4)
        w["building"] = max(w["building"], 4)
    if re.search(r"landlord|scam|fraud|owner|deposit|management", q):
        w["landlord"] = 5
        p.notes.append("owner record weighted up")
    if re.search(r"heat|rat|mice|mouse|pest|roach|bed ?bug|mold|leak|condition", q):
        w["building"] = 5
        p.notes.append("building record weighted up")
    if re.search(r"\bt\b|subway|train|red line|green line|transit|mbta", q):
        w["transit"] = 4
        p.notes.append("T access weighted up")
    if re.search(r"cheap|affordable|save money|lowest price", q):
        w["price"] = 5
    if re.search(r"walk", q):
        w["commute"] = max(w["commute"], 4)
    return p
