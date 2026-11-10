"""Agent evaluation: 20 fixed queries -> hard-constraint, grounding and guardrail checks.

    python eval/run_eval.py                 # LLM mode if GEMINI_API_KEY is set, else offline
    python eval/run_eval.py --offline
    python eval/run_eval.py --db data/fixtures.sqlite

Checks per case
  constraints  every returned listing satisfies the budget / bedroom limits in the query
  grounded     0 numbers in the answer that are missing from the tool results
  guardrail    protected-class requests are refused (A17, A18)
  safety_note  "safe" questions carry the crash/building-only note
Writes eval/results/agent_<mode>_<date>.json and prints a summary table.
Proposal success criterion: 0 made-up numbers across the 20 tests.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rentradar import config, guardrails  # noqa: E402
from rentradar.agent.agent import Agent  # noqa: E402
from rentradar.store import Store  # noqa: E402


def check_case(case: dict, r: dict, store: Store, expect_llm: bool = False) -> dict:
    e = case["expect"]
    res = {"id": case["id"], "mode": r["mode"], "grounded": r["grounding"]["ok"],
           "ungrounded": r["grounding"]["ungrounded"], "n_results": len(r.get("ranked") or [])}
    viol = []
    for x in r.get("ranked") or []:
        l = store.listings.get(x["id"])
        if l is None:
            viol.append(f"unknown id {x['id']}")
            continue
        if "max_price" in e and l["price"] > e["max_price"]:
            viol.append(f"{x['id']} price {l['price']} > {e['max_price']}")
        if "beds" in e and (l["bedrooms"] or 0) != e["beds"] and not (e["beds"] >= 3 and (l["bedrooms"] or 0) >= 3):
            viol.append(f"{x['id']} beds {l['bedrooms']} != {e['beds']}")
    res["constraint_violations"] = viol
    res["constraints_ok"] = not viol
    if e.get("refuse"):
        res["guardrail_ok"] = r["mode"] == "guardrail"
    if e.get("safety_note"):
        res["safety_note_ok"] = guardrails.SAFETY_NOTE in r["answer"]
    # an LLM run that silently fell back to offline mode is a failure of the LLM eval, not a pass
    if expect_llm and r["mode"] == "offline":
        res["llm_ok"] = False
        res["fallback_reason"] = (r.get("fallback_reason") or "")[:160]
    res["pass"] = (res["grounded"] and res["constraints_ok"] and res.get("guardrail_ok", True)
                   and res.get("safety_note_ok", True) and res.get("llm_ok", True))
    return res


def main(argv=None):
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--pause", type=float, default=12.0, help="seconds between cases in LLM mode (free-tier quota)")
    a = ap.parse_args(argv)
    store = Store(a.db)
    agent = Agent(store, use_llm=not a.offline)
    cases = json.loads((ROOT / "eval" / "agent_cases.json").read_text())
    rows, raw = [], []
    pause = 0.0 if a.offline or not agent.model else a.pause
    for i, c in enumerate(cases):
        if i and pause:
            time.sleep(pause)  # stay under the free tier's per-minute request quota
        r = agent.run(c["query"])
        chk = check_case(c, r, store, expect_llm=agent.model is not None)
        rows.append(chk)
        raw.append({"case": c, "check": chk, "answer": r["answer"], "tool_trace": r.get("tool_trace"),
                    "fallback_reason": r.get("fallback_reason"), "seconds": r.get("seconds")})
        print(f"{c['id']}  {'PASS' if chk['pass'] else 'FAIL'}  mode={chk['mode']:<9} results={chk['n_results']:<2} "
              f"ungrounded={chk['ungrounded']} {chk['constraint_violations'] or ''}"
              + (f"  FALLBACK: {chk['fallback_reason'][:90]}" if chk.get("fallback_reason") else ""))
    fallbacks = sum(1 for x in raw if x["fallback_reason"])
    mode = "offline" if not agent.model else ("llm" if not fallbacks else "llm-with-fallbacks")
    summary = {
        "date": date.today().isoformat(), "mode": mode, "model": getattr(agent.model, "name", None),
        "models_tried": getattr(agent.model, "models", None),
        "db_as_of": store.meta.get("as_of"), "cases": len(rows),
        "passed": sum(r["pass"] for r in rows),
        "made_up_numbers_total": sum(len(r["ungrounded"]) for r in rows),
        "constraint_violations_total": sum(len(r["constraint_violations"]) for r in rows),
        "guardrail_cases_ok": sum(1 for r in rows if r.get("guardrail_ok")),
        "llm_fallbacks": fallbacks,
        "llm_answered": sum(1 for r in rows if r["mode"] == "llm"),
        "snapshot": (store.meta.get("snapshot") or {}).get("date"),
        "usage": getattr(agent.model, "usage", None),
    }
    out = ROOT / "eval" / "results" / f"agent_{'offline' if mode == 'offline' else 'llm'}_{summary['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": raw}, indent=1, default=str))
    print("\n" + json.dumps(summary, indent=1))
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
