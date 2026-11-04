"""Renter-signal classifier check against hand labels.

Step 1 -- sample 200 distinct RentSmart descriptions to label by hand:
    python eval/signal_agreement.py sample          # writes eval/signal_labels.csv (human_label empty)
Step 2 -- open eval/signal_labels.csv, fill `human_label` with one key from
          rentradar/signals.py SIGNALS (heat_hot_water, pests, ...).
Step 3 -- score the rules and (if data/signal_labels_llm.json exists) the LLM:
    python eval/signal_agreement.py score

Proposal success criterion: >= 85% agreement on 200 hand labels.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rentradar import config, db, signals  # noqa: E402

LABELS = ROOT / "eval" / "signal_labels.csv"


def sample(n: int = 200) -> None:
    conn = db.connect()
    rows = conn.execute(
        "SELECT description, violation_type, COUNT(*) n FROM city_records WHERE description != '' "
        "GROUP BY description, violation_type"
    ).fetchall()
    if not rows:
        sys.exit("No RentSmart records in the database. Fetch + build first.")
    random.seed(1125)
    # weight by frequency so common descriptions dominate, but keep the long tail
    pool = list(rows)
    picked = random.sample(pool, min(n, len(pool)))
    with open(LABELS, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["description", "violation_type", "count", "rule_label", "human_label"])
        for r in sorted(picked, key=lambda r: -r["n"]):
            w.writerow([r["description"], r["violation_type"], r["n"], signals.classify_rule(r["description"], r["violation_type"]), ""])
    print(f"wrote {LABELS} ({len(picked)} rows). Fill in human_label, then run `score`.")
    print("Allowed labels:", ", ".join(signals.SIGNALS))


def score() -> None:
    rows = [r for r in csv.DictReader(open(LABELS)) if r["human_label"].strip()]
    if not rows:
        sys.exit("No human labels yet.")
    bad = [r["human_label"] for r in rows if r["human_label"] not in signals.SIGNALS]
    if bad:
        sys.exit(f"Unknown labels: {sorted(set(bad))}")
    llm_path = config.DATA_DIR / "signal_labels_llm.json"
    llm = json.loads(llm_path.read_text()) if llm_path.exists() else {}
    res = {}
    for name, pred in [("rules", lambda r: signals.classify_rule(r["description"], r["violation_type"])),
                       ("rules+llm", lambda r: (lambda base: llm.get(r["description"], base) if base == "other" else base)(
                           signals.classify_rule(r["description"], r["violation_type"]))),
                       ("llm_only", lambda r: llm.get(r["description"]))]:
        if name != "rules" and not llm:
            continue
        hits = sum(1 for r in rows if pred(r) == r["human_label"])
        res[name] = {"agreement": round(hits / len(rows), 3), "n": len(rows)}
    confusion = Counter((r["human_label"], signals.classify_rule(r["description"], r["violation_type"]))
                        for r in rows if signals.classify_rule(r["description"], r["violation_type"]) != r["human_label"])
    res["top_rule_errors"] = [{"human": h, "rule": p, "n": n} for (h, p), n in confusion.most_common(8)]
    out = ROOT / "eval" / "results" / "signal_agreement.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"sample": sample, "score": score}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
