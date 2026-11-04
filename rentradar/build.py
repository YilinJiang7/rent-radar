"""Build data/rentradar.sqlite from raw files.

    python -m rentradar.build            # real data in data/raw + data/vendor
    python -m rentradar.build --fixtures # tiny synthetic data (tests / offline demo)

Missing optional sources are reported, not fatal: the app then shows "not
available" for that evidence layer instead of a made-up value.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config, db, signals
from .features import EvidenceIndex
from .ingest import SchemaError, assessment, crashes, listings, mbta, rentsmart


def _glob(d: Path, *patterns: str) -> List[Path]:
    out: List[Path] = []
    for p in patterns:
        out.extend(sorted(d.glob(p)))
    return out


def _llm_labels() -> Dict[str, str]:
    p = config.DATA_DIR / "signal_labels_llm.json"
    return json.loads(p.read_text()) if p.exists() else {}


def source_paths(fixtures: bool) -> Dict[str, List[Path]]:
    if fixtures:
        f = config.FIXTURE_DIR
        return {
            "listings": _glob(f, "listings*.json"),
            "rentsmart": _glob(f, "rentsmart*.csv"),
            "assessment": _glob(f, "assessment*.csv"),
            "crashes": _glob(f, "crashes*.csv"),
            "stops": _glob(f, "stops*.txt"),
        }
    r, v = config.RAW_DIR, config.VENDOR_DIR
    return {
        "listings": _glob(r / "rentcast", "*.json"),
        "rentsmart": _glob(r / "rentsmart", "*.csv", "*.csv.gz"),
        "assessment": _glob(r / "assessment", "*.csv", "*.csv.gz"),
        "crashes": _glob(v / "crashes", "*.csv.gz", "*.csv") + _glob(r / "crashes", "*.csv.gz", "*.csv"),
        "stops": _glob(r / "mbta", "stops.txt"),
    }


def build(db_path: Path, fixtures: bool = False, today: Optional[date] = None, log=print) -> dict:
    t0 = time.time()
    paths = source_paths(fixtures)
    if not paths["listings"]:
        raise SystemExit(
            "No listings found. Put RentCast JSON in data/raw/rentcast/ "
            "(scripts/fetch_rentcast.py or --import-snapshot), or run with --fixtures."
        )
    today = today or (date(2026, 10, 27) if fixtures else date.today())
    report: Dict[str, dict] = {}

    L = listings.load(paths["listings"], today=datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
    report["listings"] = {"files": [p.name for p in paths["listings"]], "rows": len(L)}

    def optional(name, fn):
        if not paths[name]:
            report[name] = {"files": [], "rows": 0, "status": "missing"}
            log(f"  [skip] {name}: no file found")
            return []
        try:
            rows = fn(paths[name])
            report[name] = {"files": [p.name for p in paths[name]], "rows": len(rows), "status": "ok"}
            return rows
        except SchemaError as e:
            report[name] = {"files": [p.name for p in paths[name]], "rows": 0, "status": f"schema error: {e}"}
            log(f"  [error] {e}")
            return []

    R = optional("rentsmart", lambda ps: rentsmart.load(ps))
    llm_labels = {} if fixtures else _llm_labels()
    if llm_labels:
        n = 0
        for r in R:
            lab = llm_labels.get(r["description"])
            if r["signal"] == "other" and lab and lab != "other":
                r["signal"], r["signal_source"] = lab, "llm"
                r["building_level"] = int(signals.building_level(r["violation_type"], lab))
                n += 1
        report["rentsmart"]["llm_relabelled"] = n
    P = optional("assessment", lambda ps: assessment.load(ps))
    C = optional("crashes", lambda ps: crashes.load(ps))
    S = optional("stops", lambda ps: mbta.load(ps[0]))

    conn = db.reset(db_path)
    db.insert_many(conn, "listings", L)
    db.insert_many(conn, "city_records", R)
    db.insert_many(conn, "parcels", P)
    db.insert_many(conn, "crashes", C)
    db.insert_many(conn, "stations", S)

    idx = EvidenceIndex(R, P, C, S, today=today)
    links, feats = [], []
    matched = 0
    for l in L:
        f = idx.compute(l)
        m = f.pop("_matches")
        if m:
            matched += 1
        links.extend({"listing_id": l["id"], "record_id": rid, "match_type": mt} for rid, mt in m)
        feats.append({"listing_id": l["id"], "json": json.dumps(f)})
    db.insert_many(conn, "listing_records", links)
    db.insert_many(conn, "features", feats)

    boston = [l for l in L if (l.get("city") or "").lower() == "boston"]
    linked = {x["listing_id"] for x in links}
    report["linking"] = {
        "boston_listings": len(boston),
        "boston_listings_with_records": sum(1 for l in boston if l["id"] in linked),
        "boston_listings_with_owner": sum(1 for l, f in zip(L, feats) if (l.get("city") or "").lower() == "boston" and json.loads(f["json"])["owner"].get("available")),
        "listings_with_any_match": matched,
        "zip_corrected": sum(l["zip_corrected"] for l in L),
        "stale_listings": sum(l["stale"] for l in L),
    }
    db.set_meta(conn, "build", {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "fixtures": fixtures,
        "sources": report,
        "seconds": round(time.time() - t0, 1),
    })
    conn.commit()
    conn.close()
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", action="store_true", help="build from data/fixtures (synthetic)")
    ap.add_argument("--db", type=Path, default=None)
    a = ap.parse_args(argv)
    db_path = a.db or (config.DATA_DIR / "fixtures.sqlite" if a.fixtures else config.DB_PATH)
    print(f"Building {db_path} ...")
    rep = build(db_path, fixtures=a.fixtures)
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
