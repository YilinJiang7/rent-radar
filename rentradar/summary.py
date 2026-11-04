"""Plain-language flags: the evidence card condensed into a few short lines.

Every flag is built from numbers already in the listing's evidence, so the UI
and the agent can show it without new claims. Kinds: "bad" (a red flag),
"good" (a green flag), "info" (neutral context).
"""
from __future__ import annotations

from typing import Dict, List

from . import config, signals

# signal -> (singular, plural) in renter language
SIGNAL_WORDS: Dict[str, tuple] = {
    "heat_hot_water": ("heat / hot-water complaint", "heat / hot-water complaints"),
    "pests": ("pest report", "pest reports"),
    "water_mold": ("leak or mold report", "leak or mold reports"),
    "utilities": ("utility outage", "utility outages"),
    "fire_life_safety": ("safety violation", "safety violations"),
    "structural": ("structural problem", "structural problems"),
    "living_conditions": ("living-conditions complaint", "living-conditions complaints"),
    "noise": ("noise complaint", "noise complaints"),
    "sanitation_trash": ("trash ticket", "trash tickets"),
    "permits_admin": ("permit issue", "permit issues"),
    "street_public": ("street issue", "street issues"),
    "exterior_upkeep": ("yard / parking ticket", "yard / parking tickets"),
    "other": ("other record", "other records"),
}
CAMPUS_SHORT = {"mit": "MIT", "harvard": "Harvard Yard", "seas": "SEAS"}


def words(signal: str, n: int) -> str:
    one, many = SIGNAL_WORDS.get(signal, ("record", "records"))
    return f"{n} {one if n == 1 else many}"


def serious(signal: str) -> bool:
    return signals.SEVERITY.get(signal, 0) >= 2.0


def flags(listing: dict, f: dict, campus: str = config.DEFAULT_CAMPUS) -> List[dict]:
    out: List[dict] = []
    add = lambda kind, topic, text: out.append({"kind": kind, "topic": topic, "text": text})  # noqa: E731

    # listing freshness first: a gone listing makes everything else moot
    dom = (f.get("listing") or {}).get("days_on_market")
    if (f.get("listing") or {}).get("stale"):
        add("bad", "listing", f"Listed {dom} days ago, may be gone")

    b = f.get("building") or {}
    if b.get("available"):
        sig = b.get("by_signal") or {}
        bad = sorted(((s, n) for s, n in sig.items() if serious(s)), key=lambda t: -signals.SEVERITY[t[0]] * t[1])
        if bad:
            add("bad", "building", ", ".join(words(s, n) for s, n in bad[:2]) + f" ({b['window_years']} yrs)")
        elif b.get("records_window"):
            minor = sorted(sig.items(), key=lambda t: -t[1])[0]
            add("info", "building", f"Only minor records: {words(*minor)}")
        else:
            add("good", "building", f"No city complaints in {b['window_years']} yrs")

    o = f.get("owner") or {}
    if o.get("available"):
        if o.get("owner_occupied"):
            add("good", "owner", "Owner lives in the building")
        n_serious = o.get("portfolio_serious_records_window") or 0
        props = o.get("portfolio_properties")
        if n_serious >= 5:
            add("bad", "owner", f"{n_serious} serious issues across owner's buildings")
        elif props and props >= 10:
            add("info", "owner", f"Owner holds {props} Boston properties")
        if o.get("out_of_state"):
            add("info", "owner", f"Owner mails from {o.get('mail_state')}")

    c = (f.get("commute") or {}).get(campus) or {}
    if c:
        kind = "good" if c["bike_min"] <= 15 else "info"
        add(kind, "commute", f"{c['bike_min']} min bike to {CAMPUS_SHORT.get(campus, campus)}")

    t = f.get("transit") or {}
    if t.get("station") and t.get("station_walk_min") is not None and t["station_walk_min"] <= 10:
        add("good", "transit", f"{t['station']} T, {t['station_walk_min']} min walk")

    s = f.get("street") or {}
    if s.get("available"):
        if s["injury_crashes"] >= 5:
            add("bad", "street", f"{s['injury_crashes']} injury crashes within {s['radius_m']} m")
        elif s["injury_crashes"] == 0:
            add("good", "street", "No injury crashes nearby")
    return out


def top_flags(all_flags: List[dict], k: int = 3) -> List[dict]:
    """For list cards: red flags first, then green, then context."""
    order = {"bad": 0, "good": 1, "info": 2}
    return sorted(all_flags, key=lambda x: order[x["kind"]])[:k]
