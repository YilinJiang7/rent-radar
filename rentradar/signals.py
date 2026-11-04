"""Turn city complaint / violation records into renter signals.

RentSmart rows carry a coarse `violation_type` (Housing Complaints, Housing
Violations, Building Violations, Sanitation Requests, Civic Maintenance
Requests) and a free-text-ish `description`. Renters care about a different
taxonomy -- "will I have heat?", "are there rats?" -- so each record gets one
renter signal.

Two classifiers share this taxonomy:
  * `classify_rule` -- transparent keyword rules (always available, used by
    default, and the baseline in eval/signal_agreement.py);
  * an optional LLM pass (rentradar.classify) that labels descriptions the
    rules leave as "other". Its labels are cached in SQLite.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

SIGNALS: Dict[str, str] = {
    "heat_hot_water": "No / insufficient heat or hot water",
    "pests": "Rodents, mice, roaches or bed bugs",
    "water_mold": "Leaks, water damage or mold",
    "utilities": "Gas, electric or water service problems",
    "fire_life_safety": "Smoke/CO detectors, egress, electrical or fire hazards",
    "structural": "Porches, stairs, ceilings, walls, structural damage",
    "sanitation_trash": "Trash, dumpsters, illegal dumping",
    "noise": "Noise or nuisance",
    "living_conditions": "General unsanitary / poor living conditions",
    "permits_admin": "Permits, registrations, paperwork violations",
    "street_public": "Street-level public works (lights, potholes, sidewalks)",
    "other": "Other / unclear",
}

# Higher = worse for a renter. Used by scoring and shown in the UI.
SEVERITY = {
    "heat_hot_water": 3.0, "pests": 2.5, "water_mold": 2.5, "utilities": 3.0,
    "fire_life_safety": 3.0, "structural": 2.5, "living_conditions": 2.0,
    "sanitation_trash": 1.0, "noise": 1.0, "permits_admin": 0.5,
    "street_public": 0.25, "other": 0.75,
}

# Order matters: first match wins.
RULES: List[Tuple[str, re.Pattern]] = [
    ("heat_hot_water", re.compile(r"\bheat|\bhot water|boiler|furnace|no heat|radiator", re.I)),
    ("pests", re.compile(r"rodent|\brat\b|\brats\b|mice|mouse|roach|insect|bed ?bug|pest|vermin|infestation", re.I)),
    ("utilities", re.compile(r"utilit|\bgas\b|electric(?!al hazard)|no water|water service|water shut", re.I)),
    ("water_mold", re.compile(r"leak|mold|mould|water damage|moisture|plumb|sewage|flood", re.I)),
    ("fire_life_safety", re.compile(r"smoke|carbon monoxide|\bco detector|egress|fire|sprinkler|electrical|wiring|unsafe|dangerous", re.I)),
    ("structural", re.compile(r"porch|stair|ceiling|wall|floor|roof|structur|collapse|window|door|railing|foundation", re.I)),
    ("sanitation_trash", re.compile(r"trash|dumpster|garbage|barrel|litter|dumping|recycl|bulk item|overflowing", re.I)),
    ("noise", re.compile(r"noise|loud|party|nuisance", re.I)),
    ("living_conditions", re.compile(r"unsanitary|living condition|poor condition|unsatisfactory|squalor|maintenance|hoarding|filth", re.I)),
    ("permits_admin", re.compile(r"permit|registration|certificate|license|occupancy|failure to|work without|inspection report", re.I)),
    ("street_public", re.compile(r"street ?light|pothole|sidewalk|traffic|signal|graffiti|tree|snow|catch basin|needle|abandoned (vehicle|bike)", re.I)),
]

VIOLATION_TYPE_DEFAULT = {
    "sanitation requests": "sanitation_trash",
    "civic maintenance requests": "street_public",
}


def classify_rule(description: str, violation_type: str = "") -> str:
    text = f"{description or ''}"
    for label, pat in RULES:
        if pat.search(text):
            return label
    vt = (violation_type or "").strip().lower()
    if vt in VIOLATION_TYPE_DEFAULT:
        return VIOLATION_TYPE_DEFAULT[vt]
    if vt == "housing complaints" or vt == "housing violations":
        return "living_conditions"
    return "other"


def building_level(violation_type: str, signal: str) -> bool:
    """Is this record about the building itself (vs the street in front)?"""
    vt = (violation_type or "").lower()
    if signal == "street_public":
        return False
    if "civic maintenance" in vt:
        return False
    return True
