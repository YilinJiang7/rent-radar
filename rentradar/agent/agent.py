"""The Rent Radar agent.

Plain-language needs -> (LLM decides) tool calls -> ranked listings -> grounded
explanation with citations. Two engines share the same tools:

* LLM mode (Gemini function calling) when GEMINI_API_KEY is set;
* offline mode (rule-based planner + templated answer) otherwise, or when the
  LLM call fails, so the demo never depends on network access.

Every answer passes the grounding check (agent/grounding.py) and the Fair
Housing guardrail (guardrails.py).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from .. import config, guardrails
from ..store import Store
from . import grounding, planner, tools
from .llm import ChatModel, LLMError, default_model

SYSTEM_PROMPT = """You are Rent Radar, a rental-search assistant for Harvard and MIT students. Full evidence
(city complaints, owner of record, crashes) exists for Boston: Allston, Brighton, Fenway. Cambridge
listings are listing-only for now. You help students rule out bad listings using public records.

How to work:
1. Turn the student's needs into tool arguments: budget -> max_price; bedrooms -> min_beds AND max_beds
   ("1 bedroom" / "1 bed" / "1br" means min_beds=1, max_beds=1; "studio" means 0 and 0; only "at least"
   or "N+" leaves max_beds unset); campus (mit, harvard, seas); neighborhoods -> areas; priorities ->
   weights (0-5) on price, commute, building, landlord, street_safety, quiet, transit, freshness. Raise
   weights for what they stress; leave the others at their defaults. Do NOT set include_cambridge or
   include_stale unless the student asks for Cambridge or for older listings.
2. Call rank_listings first. Then call get_listing_evidence for the top 2-3 results before recommending.
3. Answer in short markdown: one line on how you read the request (filters + weights you changed), then
   2-3 recommended listings, each with the concrete evidence that drove its score, then one line of caveats.

Hard rules:
- Use ONLY numbers that appear in tool results. Never estimate, round loosely, or invent numbers,
  dates, names or counts. If a factor has no data (e.g. RentSmart covers Boston only), say "no data".
- Cite every listing as [L:<listing id>] and every city record you mention as [R:<record_id>].
- "Safe" means crash history and building safety records only. Never use or speculate about who lives
  in an area (race, religion, national origin, family status, disability, income source, etc.).
- Owner of record is public data; say it may differ from the person advertising the listing, and
  remind the student to verify ownership before paying any deposit.
- If nothing matches, say so and suggest which constraint to relax.
- No complaint records is limited evidence, not proof the building is fine; say so when it comes up.
- Every count needs its context: the time window and the radius (e.g. "within 150 m, 2021-2025").
- Cambridge listings are included automatically for MIT and Harvard Yard commutes and have listing
  data only (no complaints or owner); say so when you recommend one. Older listings (91-180 days)
  are backups that may be gone; include them only if asked or if nothing fresh matches, and label
  them as older.
"""


def _summary(name: str, out: dict) -> str:
    if "error" in out:
        return f"error: {out['error']}"
    if name == "rank_listings":
        return f"{out['count_matching']} matching, top {len(out['results'])} returned"
    if name == "get_listing_evidence":
        return f"{out.get('address')} (score {out.get('score', {}).get('total')})"
    if name == "compare_listings":
        return f"{len(out.get('listings', []))} listings compared"
    return "ok"


class Agent:
    def __init__(self, store: Store, model: Optional[ChatModel] = None, use_llm: bool = True):
        self.store = store
        self.model = model if model is not None else (default_model() if use_llm else None)

    # ------------------------------------------------------------------
    def run(self, query: str, campus: Optional[str] = None, weights: Optional[Dict[str, float]] = None) -> dict:
        t0 = time.time()
        refusal = guardrails.check(query)
        if refusal:
            return {"mode": "guardrail", "answer": refusal, "ranked": [], "tool_trace": [], "plan": None,
                    "grounding": {"numbers_checked": 0, "ungrounded": [], "ok": True}, "guardrail": "fair_housing",
                    "seconds": round(time.time() - t0, 2)}
        res = None
        if self.model is not None:
            try:
                res = self._run_llm(query, campus, weights)
            except LLMError as e:
                res = self._run_offline(query, campus, weights)
                res["fallback_reason"] = str(e)[:200]
        else:
            res = self._run_offline(query, campus, weights)
        if guardrails.mentions_safety(query) and guardrails.SAFETY_NOTE not in res["answer"]:
            res["answer"] += "\n\n_" + guardrails.SAFETY_NOTE + "_"
        res["seconds"] = round(time.time() - t0, 2)
        return res

    # ------------------------------------------------------------------
    def _context_line(self, campus, weights) -> str:
        bits = []
        if campus:
            bits.append(f"campus selected in the UI: {campus}")
        if weights:
            bits.append("weights set on the sliders: " + json.dumps(weights))
        return ("\n\n(Context: " + "; ".join(bits) + ")") if bits else ""

    def _run_llm(self, query: str, campus, weights) -> dict:
        contents: List[dict] = [{"role": "user", "parts": [{"text": query + self._context_line(campus, weights)}]}]
        trace: List[dict] = []
        outputs: List[Any] = []
        plan = ranked = None
        answer = ""
        retried = False
        for step in range(config.AGENT_MAX_STEPS):
            last = step == config.AGENT_MAX_STEPS - 1
            if last:  # force a written answer on the final step
                contents.append({"role": "user", "parts": [{"text": "Step limit reached: answer now from the tool results you have, without calling tools."}]})
            content = self.model.generate(SYSTEM_PROMPT, contents, tools.DECLARATIONS, force_text=last)
            contents.append(content)
            calls = [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]
            if calls:
                responses = []
                for c in calls:
                    args = c.get("args") or {}
                    out = tools.call(self.store, c["name"], args, campus=campus)
                    outputs.append(out)
                    trace.append({"tool": c["name"], "args": args, "result": _summary(c["name"], out)})
                    if c["name"] == "rank_listings" and "results" in out:
                        # plan and ranked always come from the same (latest) ranking call
                        plan = {"args": args, "weights_used": out["weights_used"], "filters": out["filters"]}
                        ranked = out
                    fr = {"name": c["name"], "response": {"result": out}}
                    if c.get("id"):
                        fr["id"] = c["id"]
                    responses.append({"functionResponse": fr})
                contents.append({"role": "user", "parts": responses})
                continue
            answer = "".join(p.get("text", "") for p in content.get("parts", [])).strip()
            g = grounding.check(answer, outputs, query)
            if not g["ok"] and not retried and not last:
                retried = True
                contents.append({"role": "user", "parts": [{"text": (
                    "Grounding check failed: these numbers are not in any tool result: "
                    + ", ".join(g["ungrounded"]) + ". Rewrite the answer using only numbers from tool results.")}]})
                continue
            break
        else:
            answer = answer or "I ran out of steps before finishing. Try a more specific request."
        if not answer:
            raise LLMError("model returned no answer")
        g = grounding.check(answer, outputs, query)
        return {"mode": "llm", "model": getattr(self.model, "name", "llm"), "answer": answer, "plan": plan,
                "ranked": (ranked or {}).get("results", []), "count_matching": (ranked or {}).get("count_matching"),
                "tool_trace": trace, "grounding": g, "grounding_retry": retried,
                "usage": getattr(self.model, "usage", None)}

    # ------------------------------------------------------------------
    def _run_offline(self, query: str, campus, weights) -> dict:
        info = self._offline_info(query)
        if info:
            return info
        p = planner.parse(query, campus)
        if weights:
            p.weights.update({k: v for k, v in weights.items() if k in p.weights})
        args = p.tool_args()
        trace, outputs = [], []
        ranked = tools.call(self.store, "rank_listings", args)
        outputs.append(ranked)
        trace.append({"tool": "rank_listings", "args": args, "result": _summary("rank_listings", ranked)})
        evid = []
        for r in ranked["results"][:3]:
            e = tools.call(self.store, "get_listing_evidence", {"listing_id": r["id"], "campus": p.campus, "weights": p.weights})
            outputs.append(e)
            trace.append({"tool": "get_listing_evidence", "args": {"listing_id": r["id"]}, "result": _summary("get_listing_evidence", e)})
            evid.append(e)
        answer = compose_answer(query, ranked, evid, p)
        return {"mode": "offline", "model": None, "answer": answer,
                "plan": {"args": args, "weights_used": ranked["weights_used"], "filters": ranked["filters"], "notes": p.notes},
                "ranked": ranked["results"], "count_matching": ranked["count_matching"], "tool_trace": trace,
                "grounding": grounding.check(answer, outputs, query)}


    def _offline_info(self, query: str) -> Optional[dict]:
        """Non-search questions the offline mode can still answer from tools."""
        q = query.lower()
        if re.search(r"median|average rent|typical rent|each (neighbou?rhood|area)|rent by area", q):
            out = tools.call(self.store, "area_overview", {})
            lines = [f"**Median asking rent by area** (active listings, data as of {out['data_as_of']}):\n"]
            lines += [f"- {a['area']} ({a['zip']}): ${a['median_price']:,} median across {a['listings']} listings"
                      f" ({a['stale_listings']} of them older backups, {config.FRESH_DAYS}-{config.BACKUP_DAYS} days)" for a in out["areas"]]
            name = "area_overview"
        elif re.search(r"how .*scor|scor(e|ing) .*(calculated|computed|work|mean)|weights? (mean|work)", q):
            out = tools.call(self.store, "explain_factors", {})
            lines = ["**How the score works:** a weighted average of 0-100 factor scores. "
                     "Factors with no data are left out, not guessed.\n"]
            lines += [f"- **{f['label']}** (default weight {out['default_weights'][k]:g}): {f['how']}" for k, f in out["factors"].items()]
            name = "explain_factors"
        else:
            return None
        out = dict(out, stale_days=config.STALE_DAYS, backup_days=config.BACKUP_DAYS)
        answer = "\n".join(lines)
        return {"mode": "offline", "model": None, "answer": answer, "plan": None, "ranked": [], "count_matching": None,
                "tool_trace": [{"tool": name, "args": {}, "result": "ok"}],
                "grounding": grounding.check(answer, [out], query)}


def _fmt_beds(b) -> str:
    if b is None:
        return "? bd"
    return "studio" if b == 0 else f"{b:g} bd"


def compose_answer(query: str, ranked: dict, evid: List[dict], p: planner.Plan) -> str:
    lines = []
    f = ranked["filters"]
    read = []
    if f.get("max_price"):
        read.append(f"rent <= ${f['max_price']:,.0f}")
    if f.get("min_beds") is not None:
        read.append(_fmt_beds(f["min_beds"]) + ("+" if f.get("max_beds") is None else ""))
    if f.get("areas"):
        read.append("areas " + ", ".join(f["areas"]))
    if f.get("max_bike_min"):
        read.append(f"bike <= {f['max_bike_min']:g} min")
    changed = [f"{k}={v:g}" for k, v in ranked["weights_used"].items() if v != tools.DEFAULT_WEIGHTS.get(k)]
    lines.append(f"**How I read this:** campus = {ranked['campus']}; " + ("; ".join(read) if read else "no hard filters")
                 + (f"; weights changed: {', '.join(changed)}" if changed else "")
                 + ("; Boston only (Cambridge: listing data only)" if f.get("cities") not in ("as areas", None) else "")
                 + ("" if f.get("include_stale") else f". Showing listings up to {f['stale_days']} days on market."))
    if not ranked["results"]:
        msg = "\nNo fresh listing matches all of these."
        if ranked.get("stale_hidden"):
            msg += f" {ranked['stale_hidden']} older backup listings ({f['stale_days']}-{f['backup_days']} days on market) do match; they may already be rented. Ask me to include them."
        lines.append(msg + " Otherwise try a higher budget, fewer bedrooms, or more areas.")
        return "\n".join(lines)
    extra = f" ({ranked['stale_hidden']} older backup listings hidden)" if ranked.get("stale_hidden") else ""
    lines.append(f"\n{ranked['count_matching']} listings match{extra}. Top picks:\n")
    for i, e in enumerate(evid, 1):
        c = e.get("commute") or {}
        bits = [f"${e['price']:,}/mo, {_fmt_beds(e['bedrooms'])}",
                f"score {e['score']['total']}/100 (based on {e['score']['weight_coverage_pct']}% of the weights)"]
        line = f"{i}. **{e['address']}** [L:{e['id']}] — " + ", ".join(bits)
        sub = []
        sub.append(f"~{c.get('bike_min')} min by bike / ~{c.get('walk_min')} min walk to campus (estimate)")
        b = e.get("building") or {}
        if b.get("available"):
            if b["records_window"]:
                top = ", ".join(f"{k.replace('_', ' ')} x{v}" for k, v in list(b["by_signal"].items())[:3])
                cite = b["recent"][0]["record_id"] if b.get("recent") else None
                sub.append(f"building: {b['records_window']} city records in last {b['window_years']} yrs ({top})" + (f" [R:{cite}]" if cite else ""))
            else:
                if b.get("evidence") == "unmatched":
                    sub.append("building: address not found in city data")
                else:
                    sub.append(f"building: no city records since {b.get('window_start', '')[:7]} (limited evidence, not proof of no problems)")
        else:
            sub.append("building record: no data (" + b.get("reason", "n/a") + ")")
        s = e.get("street") or {}
        if s.get("available"):
            sub.append(f"crash history: {s['injury_crashes']} injury crashes, {s['ped_bike_crashes']} pedestrian/bike crashes within {s['radius_m']} m" + (f" ({s['years']})" if s.get("years") else ""))
        o = e.get("owner") or {}
        if o.get("available"):
            occ = "owner-occupied" if o.get("owner_occupied") else "not owner-occupied" if o.get("owner_occupied") is False else "occupancy unknown"
            sub.append(f"owner of record: {o['owner']} ({occ}; {o['portfolio_serious_records_window']} serious records across their properties) — verify before paying a deposit")
        t = e.get("transit") or {}
        if t.get("station"):
            sub.append(f"T: {t['station']} ({t.get('lines') or 'rapid transit'}), ~{t['station_walk_min']} min walk")
        lines.append(line)
        lines.extend(f"   - {x}" for x in sub)
    lines.append("\n_Commute times are straight-line estimates; RentSmart and owner data cover Boston only. Click a pin to see every record._")
    return "\n".join(lines)
