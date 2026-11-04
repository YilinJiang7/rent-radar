# Rent Radar

A rental map with an AI neighborhood check for Harvard and MIT students. It covers Allston, Brighton, Fenway and Cambridge.

You describe what you need in plain language, for example *"budget 2500, class at MIT, hate noise, bike home at night"*. An agent turns that into filters and weights, queries public records with tools, ranks the active listings and explains each pick. Every number in the explanation comes from a record, and every listing and record it mentions is cited. Click any pin to see the evidence behind its score:

- building complaints and violations at the address
- the owner of record and that owner's record across their other properties
- crashes on the street
- the bike commute, including crashes along the way
- distance to the nearest T station
- traffic noise

MIT 1.125 term project · Yilin Jiang (solo) · Midpoint check-in (Deliverable 2), Nov 19 2026.

> **Status:** midpoint build. Midpoint slides: <https://claude.ai/artifact/2HWv3wbV2vvjb1iWXt6VhC> (private until shared). Proposal: `docs/proposal.pdf` (Deliverable 1, PSet6). What changed since the proposal and what's left: [`docs/midpoint.md`](docs/midpoint.md).

---

## Quick start

You need Python 3.10+ (developed on 3.11) and `curl`. Run these from the repo folder:

```bash
make setup                       # creates .venv, installs requirements.txt
cp .env.example .env             # optional: add GEMINI_API_KEY (see below)

# A) demo on synthetic data, no downloads
make fixtures
RENTRADAR_DB=data/fixtures.sqlite make run      # open http://127.0.0.1:8000

# B) real data
python scripts/fetch_rentcast.py --import-snapshot <folder with listings_*.json>   # or a fresh pull (uses RentCast quota)
make data                        # RentSmart + Property Assessment + MBTA stops (public, no key)
make build                       # -> data/rentradar.sqlite, prints a coverage report
make run                         # http://127.0.0.1:8000
```

Tests and evaluation:

```bash
make test           # 44 unit/integration tests on the fixtures, no network
make eval           # 20 fixed agent queries -> eval/results/agent_<mode>_<date>.json
```

If you don't have the `make` command, each target is a one-line command listed in the `Makefile`.

### Gemini API key (optional)

1. Go to <https://aistudio.google.com>, open **Get API key**, then **Create API key**. The free tier is enough.
2. Put the key in `.env` as `GEMINI_API_KEY=...`. The `.env` file is git-ignored.
3. Restart `make run`. The header will show `AI: gemini:gemini-2.5-flash`.

Without a key, or if a Gemini call fails (rate limit, no network), the agent switches to **offline mode**. Offline mode uses a rule-based request parser over the same tools, so the demo always works.

---

## What it does

| Layer | Source | What the user sees |
|---|---|---|
| Listings | RentCast API (active long-term rentals) | Pins colored by score. Listings on the market more than 180 days are faded and flagged as possibly stale. |
| Building record | RentSmart Boston (311 + Inspectional Services) | Complaints and violations matched to the address, each with a renter signal (heat, pests, mold, safety, ...) and a record ID |
| Owner of record | Boston Property Assessment | Owner, whether owner-occupied, out-of-state mailing address, number of Boston properties, serious records across all of them |
| Street safety | MassDOT crashes 2021–2025 (from PSet1) | Injury, pedestrian/bike and after-dark crashes within 150 m |
| Commute | Straight line × 1.3 detour | Bike and walk minutes to MIT, Harvard Yard or SEAS, plus bike crashes along the way |
| Transit | MBTA GTFS | Nearest subway or Green Line station and its lines; bus stops within 400 m |
| Traffic noise | Road traffic volume (AADT) on nearby crash records | Busiest road within 100 m |

Owner and RentSmart data cover **Boston only** for now. Cambridge publishes these on a separate portal (planned for the final). Factors without data are **left out of the score and labeled "no data"**. They are never guessed, and the card shows what share of the weights the score is based on.

### Where the AI is

1. **Agent with tool calling** (`rentradar/agent/`). Gemini receives five tool declarations: `rank_listings`, `get_listing_evidence`, `compare_listings`, `area_overview` and `explain_factors`. It decides which tools to call and with what filters and weights, then writes the answer. It can only see data through those tools.
2. **Grounding check** (`agent/grounding.py`). Every number in the answer must appear in a tool result from that conversation. If the check fails, the model gets one retry with the list of offending numbers. The result of the check is shown under every answer.
3. **Renter-signal classification** (`signals.py`, `classify.py`). Transparent keyword rules sort RentSmart descriptions into renter signals. An optional Gemini pass labels the descriptions the rules leave as "other", and those labels are marked "AI label" in the UI. `eval/signal_agreement.py` scores both against hand labels.
4. **Fair Housing guardrail** (`guardrails.py`). Requests to rank by who lives somewhere (race, religion, national origin, family status, ...) are refused and redirected to the building and street layers. In this app, "safe" means crash and building records only. No demographic data is stored.

### Scoring (transparent and adjustable)

The score is a weighted average of 0–100 factor scores. Weights run from 0 to 5 and can be changed with sliders in the UI or by the agent. Hover a factor to see its formula. The formulas are listed in `rentradar/scoring.py` (`FACTORS`).

| Factor | Default weight | Formula (short) |
|---|---|---|
| Price | 3 | Against a budget: 100 at ≤85% of budget, 50 at budget, 0 at 115%. With no budget: rank of rent per bedroom. |
| Bike commute | 3 | 100 at ≤10 min, 0 at ≥45 min |
| Building record | 3 | Per signal type: severity × (1 + ln count), so repeats add less. Trash tickets weigh 0.3; heat, pests, mold and safety weigh 2.5–3. Score = 100·exp(−total / 6), using the last 3 years. |
| Owner record | 2 | Starts at 70. +20 if owner-occupied, −5 per serious record across the owner's properties (max −60), −10 if mailing address is outside MA. |
| Street safety | 2 | Rank of (injury + 2 × pedestrian/bike crashes within 150 m + after-dark bike crashes along the route) |
| Traffic noise | 1 | Rank of the busiest nearby road's AADT. No traffic count within 100 m counts as no data. |
| T access | 1 | 100 at ≤5 min walk, 0 at ≥20 min |
| Freshness | 1 | 100 at ≤14 days on market, 0 at ≥365 days |

---

## Architecture

```
scripts/fetch_*.py ──► data/raw/ (git-ignored) ─┐
data/vendor/crashes (PSet1) ────────────────────┤
                                                ▼
          rentradar/ingest/*  (pure readers, column-alias tolerant)
                                                ▼
          rentradar/build.py  ── address matching + EvidenceIndex (features.py)
                                                ▼
                         data/rentradar.sqlite  (listings, city_records, parcels,
                                                 crashes, stations, listing_records, features)
                                                ▼
          store.py (in-memory read model) ── scoring.py (weights)
                 ▲                                ▲
   agent/tools.py (one source of truth for every number)
        ▲                     ▲
 agent/agent.py ── llm.py (Gemini REST) / planner.py (offline) ── grounding.py ── guardrails.py
        ▲
 api.py (FastAPI) ──► web/ (Leaflet, vanilla JS)
```

Key design choices. More detail is in [`docs/architecture.md`](docs/architecture.md).

- **Precompute evidence, score at request time.** Matching listings to records and counting crashes is slow, so it runs once at build time. Weights change per user, so scoring runs live and is cheap.
- **Tools are the only data path.** The UI, the offline agent and the LLM agent all call the same functions. That is what makes the grounding check meaningful.
- **Address matching** (`address.py`). Addresses are normalized to `STREET|ZIP` plus a house-number range, so `40-42 Sample Ave` matches `41 Sample Avenue`. When the address doesn't match, the fallback is the nearest record within 20 m, labeled `geo`. The match type is shown on every record.
- **The Gemini REST API is called directly** with `httpx` instead of an SDK, so the request and response shapes are visible in one file (`agent/llm.py`). A `ScriptedModel` replays model turns in tests, so the tool loop is tested without network access.
- **Readers fail loudly on schema drift.** Each reader lists column aliases. If a required column is missing, it raises an error that names the columns it found. The build skips that layer and reports it; it doesn't silently zero it out.

## Repository layout

```
rentradar/      config, address, geo, signals, features, scoring, store, build, api, classify
  ingest/       listings (RentCast), rentsmart, assessment, crashes (MassDOT), mbta (GTFS)
  agent/        tools, agent loop, llm client, offline planner, grounding
web/            index.html, app.js, style.css, vendor/leaflet (BSD-2)
scripts/        fetch_data.py, fetch_rentcast.py, make_fixtures.py
data/fixtures/  synthetic data for tests/demo
data/vendor/    MassDOT crash extracts from PSet1
eval/           agent_cases.json, run_eval.py, signal_agreement.py, results/
tests/          pytest suite
docs/           architecture, data sources, midpoint report, proposal
```

## Testing and evaluation

- `make test` runs **44 tests** on the synthetic fixtures. They cover address parsing and ranges, spatial index, ingest scope and zip correction, schema errors, building/owner/street/transit features, scoring (missing factors excluded, weights change the ranking, budget curve), planner, grounding, guardrail, tools, the offline agent, the LLM tool loop with a scripted model (including the grounding retry and the fallback on a 429), and the HTTP API.
- `make eval` runs **20 fixed queries** and checks hard constraints (budget and bedrooms), made-up numbers, guardrail refusals and the safety note. The proposal target is 0 made-up numbers across the 20 tests. The latest results are in `eval/results/`.
- `eval/signal_agreement.py sample|score` hand-labels 200 RentSmart descriptions and measures agreement for the rules and the LLM. The proposal target is ≥85%.

## Limitations (honest list)

- **Listings go stale.** In the 2026-10-27 RentCast pull, every Allston, Brighton and Fenway listing had been on the market 183 days or more. Stale listings are kept but faded and flagged, and the agent hides them unless asked.
- Commute times are straight-line estimates, not routed. MBTA trip planning is planned for the final.
- RentSmart and owner layers cover Boston only. The Cambridge equivalents are planned.
- The owner of record can differ from the person advertising the listing. The app shows both and tells the student to verify before paying anything. It does not detect fraud.
- RentCast provides no photos or descriptions, and only about 16% of listings name an agent.

## Data and licenses

- RentCast listing data is used under the RentCast API terms. Raw pulls are git-ignored because they include agent contact details. Analyze Boston datasets are public (ODC-BY / PDDL; see each dataset page). MassDOT crash data is public. MBTA GTFS is public.
- Map tiles: © OpenStreetMap contributors, © CARTO. Leaflet 1.9.4: BSD-2-Clause (`web/vendor/leaflet/LICENSE`).
- Sources with URLs are listed in [`docs/data-sources.md`](docs/data-sources.md).

## External resources and AI assistance

- Libraries: FastAPI, Uvicorn, httpx, python-dotenv, pytest, Leaflet.
- Model: Google Gemini (`gemini-2.5-flash` by default) through the Gemini API.
- AI tools: **Claude (Anthropic)** drafted most of the modules, tests and docs in this repo, working from the author's proposal, design decisions and instructor feedback. The project idea, scope and data choices are the author's. Per course policy, the author is responsible for reviewing and running the code and for being able to explain all of it.
