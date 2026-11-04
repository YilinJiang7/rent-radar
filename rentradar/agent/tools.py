"""Agent tools: the only way the LLM can see data.

Each tool is a plain Python function over the Store that returns JSON-safe
dicts. The same functions back the offline agent, the HTTP API and the tests,
so there is one source of truth for every number the agent may say.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .. import config
from ..scoring import DEFAULT_WEIGHTS, FACTORS
from ..store import Store


def _brief(l: dict, f: dict, score: dict, campus: str) -> dict:
    c = f["commute"].get(campus, {})
    b = f.get("building") or {}
    s = f.get("street") or {}
    return {
        "id": l["id"],
        "address": l["address"],
        "area": l["area"],
        "price": l["price"],
        "bedrooms": l["bedrooms"],
        "bathrooms": l["bathrooms"],
        "sqft": l.get("sqft"),
        "days_on_market": l.get("days_on_market"),
        "score": score["total"],
        "score_coverage_pct": score["weight_coverage_pct"],
        "bike_min": c.get("bike_min"),
        "walk_min": c.get("walk_min"),
        "building_records_3y": b.get("records_window") if b.get("available") else None,
        "injury_crashes_150m": s.get("injury_crashes") if s.get("available") else None,
        "nearest_station": (f.get("transit") or {}).get("station"),
        "missing_factors": [x["factor"] for x in score["breakdown"] if x.get("missing")],
    }


def rank_listings(store: Store, campus: str = config.DEFAULT_CAMPUS, max_price: Optional[float] = None,
                  min_beds: Optional[float] = None, max_beds: Optional[float] = None,
                  areas: Optional[List[str]] = None, max_bike_min: Optional[float] = None,
                  include_stale: bool = False, weights: Optional[Dict[str, float]] = None,
                  budget: Optional[float] = None, limit: int = 5) -> dict:
    campus = campus if campus in config.CAMPUSES else config.DEFAULT_CAMPUS
    rows = store.filter(max_price=max_price, min_beds=min_beds, max_beds=max_beds, areas=areas,
                        campus=campus, max_bike_min=max_bike_min, include_stale=include_stale)
    stale_hidden = 0
    if not include_stale:
        stale_hidden = len(store.filter(max_price=max_price, min_beds=min_beds, max_beds=max_beds, areas=areas,
                                        campus=campus, max_bike_min=max_bike_min, include_stale=True)) - len(rows)
    ranked = store.scored(rows, campus, weights, budget or max_price)
    limit = max(1, min(int(limit or 5), 20))
    w = dict(DEFAULT_WEIGHTS)
    w.update({k: v for k, v in (weights or {}).items() if k in w})
    return {
        "campus": config.CAMPUSES[campus]["name"],
        "filters": {"max_price": max_price, "min_beds": min_beds, "max_beds": max_beds, "areas": areas,
                    "max_bike_min": max_bike_min, "include_stale": include_stale,
                    "stale_days": config.STALE_DAYS},
        "weights_used": w,
        "count_matching": len(rows),
        "stale_hidden": stale_hidden,
        "results": [_brief(r["listing"], store.features[r["listing"]["id"]], r["score"], campus) for r in ranked[:limit]],
    }


def get_listing_evidence(store: Store, listing_id: str, campus: str = config.DEFAULT_CAMPUS,
                         weights: Optional[Dict[str, float]] = None, budget: Optional[float] = None) -> dict:
    l = store.listings.get(listing_id)
    if not l:
        return {"error": f"unknown listing_id {listing_id}"}
    campus = campus if campus in config.CAMPUSES else config.DEFAULT_CAMPUS
    f = store.features[listing_id]
    score = store.scorer.score(l, f, campus, weights, budget)
    return {
        "id": l["id"],
        "address": l["address"], "area": l["area"], "city": l["city"],
        "price": l["price"], "bedrooms": l["bedrooms"], "bathrooms": l["bathrooms"], "sqft": l.get("sqft"),
        "property_type": l.get("property_type"), "listed_date": l.get("listed_date"),
        "days_on_market": l.get("days_on_market"), "stale": bool(l["stale"]),
        "score": score,
        "commute": f["commute"].get(campus),
        "transit": f.get("transit"),
        "building": f.get("building"),
        "owner": f.get("owner"),
        "street": f.get("street"),
        "noise": f.get("noise"),
    }


def compare_listings(store: Store, listing_ids: List[str], campus: str = config.DEFAULT_CAMPUS,
                     weights: Optional[Dict[str, float]] = None, budget: Optional[float] = None) -> dict:
    out = []
    for lid in (listing_ids or [])[:5]:
        l = store.listings.get(lid)
        if not l:
            out.append({"id": lid, "error": "unknown listing_id"})
            continue
        f = store.features[lid]
        s = store.scorer.score(l, f, campus, weights, budget)
        item = _brief(l, f, s, campus)
        item["factor_scores"] = {x["factor"]: x["score"] for x in s["breakdown"]}
        out.append(item)
    return {"campus": config.CAMPUSES.get(campus, {}).get("name"), "listings": out}


def area_overview(store: Store) -> dict:
    return {"areas": store.area_stats(), "data_as_of": store.meta.get("as_of")}


def explain_factors(store: Store) -> dict:
    return {"factors": FACTORS, "default_weights": DEFAULT_WEIGHTS,
            "note": "Weights are 0-5. A factor with no data is left out of the average, not guessed."}


WEIGHT_SCHEMA = {
    "type": "object",
    "description": "Optional factor weights 0-5. Keys: " + ", ".join(DEFAULT_WEIGHTS),
    "properties": {k: {"type": "number"} for k in DEFAULT_WEIGHTS},
}
CAMPUS_SCHEMA = {"type": "string", "enum": list(config.CAMPUSES), "description": "mit, harvard (Yard) or seas (Allston)"}

# Gemini / OpenAPI-subset function declarations.
DECLARATIONS = [
    {
        "name": "rank_listings",
        "description": "Filter active rental listings and rank them with the transparent weighted score. Use this first.",
        "parameters": {
            "type": "object",
            "properties": {
                "campus": CAMPUS_SCHEMA,
                "max_price": {"type": "number", "description": "Monthly rent ceiling in USD"},
                "min_beds": {"type": "number", "description": "Minimum bedrooms (0 = studio)"},
                "max_beds": {"type": "number"},
                "areas": {"type": "array", "items": {"type": "string"}, "description": "Area names or zip codes, e.g. Allston, 02139"},
                "max_bike_min": {"type": "number", "description": "Maximum estimated bike minutes to campus"},
                "include_stale": {"type": "boolean", "description": "Include listings on market > 180 days (default false)"},
                "weights": WEIGHT_SCHEMA,
                "limit": {"type": "integer", "description": "How many results (default 5, max 20)"},
            },
        },
    },
    {
        "name": "get_listing_evidence",
        "description": "Full evidence card for one listing: score breakdown, building complaints/violations with record ids, owner of record, crashes, commute, transit, traffic noise.",
        "parameters": {
            "type": "object",
            "properties": {"listing_id": {"type": "string"}, "campus": CAMPUS_SCHEMA, "weights": WEIGHT_SCHEMA},
            "required": ["listing_id"],
        },
    },
    {
        "name": "compare_listings",
        "description": "Side-by-side factor scores for up to 5 listings.",
        "parameters": {
            "type": "object",
            "properties": {"listing_ids": {"type": "array", "items": {"type": "string"}}, "campus": CAMPUS_SCHEMA, "weights": WEIGHT_SCHEMA},
            "required": ["listing_ids"],
        },
    },
    {"name": "area_overview", "description": "Listing counts and median rent per neighborhood.", "parameters": {"type": "object", "properties": {}}},
    {"name": "explain_factors", "description": "How each score factor is computed and the default weights.", "parameters": {"type": "object", "properties": {}}},
]

REGISTRY: Dict[str, Callable[..., Any]] = {
    "rank_listings": rank_listings,
    "get_listing_evidence": get_listing_evidence,
    "compare_listings": compare_listings,
    "area_overview": area_overview,
    "explain_factors": explain_factors,
}


def call(store: Store, name: str, args: Optional[dict] = None, **defaults) -> dict:
    fn = REGISTRY.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    kwargs = dict(args or {})
    import inspect
    params = inspect.signature(fn).parameters
    for k, v in defaults.items():
        if k in params and kwargs.get(k) is None:
            kwargs[k] = v
    kwargs = {k: v for k, v in kwargs.items() if k in params}
    try:
        return fn(store, **kwargs)
    except Exception as e:  # tool errors go back to the model, not up the stack
        return {"error": f"{type(e).__name__}: {e}"}
