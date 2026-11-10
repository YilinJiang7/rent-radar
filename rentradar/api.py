"""HTTP API + static web UI.

    uvicorn rentradar.api:app --reload        # http://127.0.0.1:8000

Endpoints
  GET  /api/meta                 build info, areas, campuses, factors, default weights, LLM mode
  GET  /api/listings             all in-scope listings with score (query: campus, weights JSON, filters)
  GET  /api/listings/{id}        full evidence card + linked city records
  GET  /api/records/{record_id}  one city record
  POST /api/agent                {"query": "...", "campus": "mit", "weights": {...}}
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

from . import config, summary
from .agent.agent import Agent
from .agent.tools import get_listing_evidence
from .scoring import DEFAULT_WEIGHTS, FACTORS
from .store import Store

WEB_DIR = config.ROOT / "web"
app = FastAPI(title="Rent Radar", version="0.2.0")


@lru_cache(maxsize=1)
def get_store() -> Store:
    return Store(Path(os.getenv("RENTRADAR_DB", config.DB_PATH)))


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    use_llm = os.getenv("RENTRADAR_OFFLINE", "0") != "1"
    return Agent(get_store(), use_llm=use_llm)


def _weights(raw: Optional[str]) -> Optional[Dict[str, float]]:
    if not raw:
        return None
    try:
        w = json.loads(raw)
        return {k: float(v) for k, v in w.items() if k in DEFAULT_WEIGHTS}
    except (ValueError, AttributeError):
        raise HTTPException(400, "weights must be a JSON object, e.g. {\"quiet\": 5}")


@app.get("/api/meta")
def meta():
    s = get_store()
    a = get_agent()
    return {
        "build": s.meta,
        "areas": s.area_stats(),
        "campuses": config.CAMPUSES,
        "factors": FACTORS,
        "default_weights": DEFAULT_WEIGHTS,
        "llm": getattr(a.model, "name", None) if a.model else None,
        "listing_count": len(s.listings),
    }


@app.get("/api/listings")
def listings(campus: str = config.DEFAULT_CAMPUS, weights: Optional[str] = None,
             max_price: Optional[float] = None, min_beds: Optional[float] = None,
             max_beds: Optional[float] = None, include_stale: bool = False, cambridge: bool = False,
             owner_occ: str = "plus",
             area: Optional[str] = Query(None, description="comma-separated area names or zips")):
    s = get_store()
    rows = s.filter(max_price=max_price, min_beds=min_beds, max_beds=max_beds,
                    areas=area.split(",") if area else None, include_stale=include_stale,
                    cities=None if cambridge else config.DEFAULT_CITIES)
    ranked = s.scored(rows, campus, _weights(weights), max_price, owner_occ if owner_occ in ("plus", "neutral", "minus") else "plus")
    out = []
    for r in ranked:
        l, sc = r["listing"], r["score"]
        f = s.features[l["id"]]
        out.append({
            "id": l["id"], "address": l["address"], "area": l["area"], "city": l["city"],
            "lat": l["lat"], "lon": l["lon"], "price": l["price"], "bedrooms": l["bedrooms"],
            "bathrooms": l["bathrooms"], "days_on_market": l["days_on_market"], "stale": bool(l["stale"]), "tier": l.get("tier"),
            "score": sc["total"], "coverage": sc["weight_coverage_pct"],
            "factors": {b["factor"]: b["score"] for b in sc["breakdown"]},
            "bike_min": (f["commute"].get(campus) or {}).get("bike_min"),
            "records_3y": (f.get("building") or {}).get("records_window"),
            # staleness is shown as its own tag on the card, so keep the 3 flag slots for the place itself
            "flags": summary.top_flags([x for x in summary.flags(l, f, campus) if x["topic"] != "listing"], 3),
        })
    return {"count": len(out), "campus": campus, "listings": out}


@app.get("/api/listings/{listing_id:path}")
def listing(listing_id: str, campus: str = config.DEFAULT_CAMPUS, weights: Optional[str] = None,
            budget: Optional[float] = None, owner_occ: str = "plus"):
    s = get_store()
    e = get_listing_evidence(s, listing_id, campus, _weights(weights), budget, owner_occ)
    if "error" in e:
        raise HTTPException(404, e["error"])
    recs = s.records_for(listing_id)
    for r in recs:  # renter-language label + how much it matters
        r["label"] = summary.SIGNAL_WORDS.get(r["signal"], ("record",))[0]
        r["serious"] = summary.serious(r["signal"])
    e["records"] = recs
    return e


@app.get("/api/records/{record_id}")
def record(record_id: str):
    r = get_store().record(record_id)
    if not r:
        raise HTTPException(404, "unknown record")
    return r


class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    campus: Optional[str] = None
    weights: Optional[Dict[str, float]] = None
    owner_occ: Optional[str] = None


@app.post("/api/agent")
def agent(req: AgentRequest):
    return get_agent().run(req.query, req.campus, req.weights, req.owner_occ)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
