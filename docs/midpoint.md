# Midpoint check-in (Deliverable 2, Thu 11/19)

The course page asks for three things at the midpoint: a settled direction, the main technical uncertainties investigated, and real progress on the core of the project. The deliverable is a working repo plus a ~4 minute video: <https://youtu.be/-PX3yZA1AP0>.

## 1. Direction (settled)

Rent Radar is a rental map plus an AI neighborhood check for Harvard and MIT students in Allston, Brighton, Fenway and Cambridge. It is the same direction as the 10/29 proposal. The scope is narrower, and the changes come from instructor feedback:

| Feedback (10/29) | What changed |
|---|---|
| #1 data sources and weights are what matters | The score is a plain weighted average with a published formula for each factor. Sliders change the weights, and the agent states which weights it changed. Missing Boston data is scored at the area average and shown as "unknown"; Cambridge factors with no data are left out ("n/a"). |
| #6 RentSmart Boston | RentSmart replaces the hand-built 311 layer. It is one public file with 311 and inspection records per property. |
| #5, #7 landlord fraud and landlord history | Owner of record from Property Assessment: owner-occupied flag, out-of-state mailing address, portfolio size, and serious records across all of the owner's properties. The detail card also has a "verify before you pay" checklist citing M.G.L. c.186 §15B. |
| #4 more city data | Deferred to the final (fires, building violations outside RentSmart). |
| #9 noise sources | Proxy for now: busiest road (AADT) within 100 m. A POI layer (police, fire stations, ERs) is planned for the final. |
| #2, #3 Redfin / MLS | Not used. The terms of service and access requirements are documented in `docs/data-sources.md`. |

### Proposal feedback received 11/4 and what changed

| Feedback | Change |
|---|---|
| Boston layers and a clearly defined listing snapshot first | Boston has the full evidence. Cambridge listings stay on the map (MIT and Harvard Yard students live there) but are labeled "LISTING ONLY" and can be switched off; the agent leaves them out for SEAS unless asked. The snapshot is the newest dated RentCast pull with stated rules (≤ 90 days shown, 91–180 kept as labeled backups, older or not recently seen dropped). |
| Replace "100% of active listings" with measurable coverage | Snapshot funnel plus Boston coverage table (parcel match, owner, occupancy, records / no records / unmatched), shown under About the data and printed by the build. |
| Complaints and crashes need geographic and time context, not personal safety | Every count carries its window and radius. The factor is called "Crash history", and no flag calls a street safe. |
| No complaint records = limited evidence | Neutral note "no city records since …, not proof of no problems". Building score is capped at 90. An unmatched address gets the area average for that factor, shown as "unknown", so missing data is never a bonus or a penalty. |
| Show missing geographic coverage | Cambridge cards are labeled "LISTING ONLY" ("no city records yet"), and the coverage table counts them. |

## 2. Technical uncertainties: what was tested

| Risk (proposal slide 4) | Status | Evidence |
|---|---|---|
| Joining listings to city records by address | **Built and tested.** Normalized street+zip keys with house-number ranges, then the parcel ID. A 20 m location match is used only for records with no parseable address, so neighbours are never blamed. | `tests/test_ingest_build.py`. Real match rate: 1,829 of 2,130 Boston listings (86%) matched to city data (§5). |
| Source schemas drift between releases | **Handled.** Column aliases, and a loud `SchemaError` that lists the columns found. The build continues without that layer and reports it. | `tests/test_ingest_build.py::test_resolve_aliases_and_error_message` |
| Network: api.rentcast.io and data.boston.gov are blocked from the dev sandboxes | **Worked around.** The fetch scripts run on the Mac with curl (the key is never written to disk), and the build works from local files. | `scripts/fetch_*.py` |
| LLM inventing numbers | **Measured.** A grounding check runs on every answer, with one corrective retry. | `make eval` → `eval/results/agent_llm_2026-11-09.json`: 20/20 pass with Gemini, 0 made-up numbers |
| LLM unavailable during the demo (quota, wifi) | **Covered.** Retries with backoff, a wait on 429 quota errors, a backup model, then the offline planner over the same tools. Gemini 3.8 Flash returned 503 in every run, so Gemini 3.1 Flash-Lite (which passed 20/20) is now the primary model. | `tests/test_agent.py::test_llm_failure_falls_back_to_offline`, README "Model choice" |
| Fair Housing | **Guardrail plus a design choice.** No demographic or crime data is stored. Steering requests are refused. "Safe" is defined in the UI. | `tests/test_agent.py::test_guardrail_blocks_steering`, eval cases A17–A19 |
| Stale listings | **Found a real problem.** In the 10/27 RentCast pull, 462 of 1,000 rows were listed more than 180 days earlier, and every Allston, Brighton and Fenway row was. The cause was the city-level query: the Nov 4 pull per zip code retrieved 4,218 listings and kept 3,011 (2,380 shown, 631 backups); Boston median days on market is 37. Freshness tiers (≤ 90 shown, 91–180 backups, older dropped), newest snapshot only, and a "gone since last pull" count when two pulls exist. | snapshot funnel in the build report |

## 3. What works now

- The data pipeline (fetch → ingest → match → evidence → SQLite), with a coverage report.
- A map of all in-scope listings, colored by score. Each listing opens an evidence card with the score breakdown, building records (with IDs), owner of record, commute, transit, crashes and traffic.
- The agent: Gemini function calling over 5 tools, citations, a grounding check and an offline fallback.
- Tests: 59 pytest cases on synthetic fixtures. The 20-case agent evaluation passes 20/20 with Gemini (Nov 9).
- Video walkthrough: <https://youtu.be/-PX3yZA1AP0>.

## 4. Plan to the final (12/3)

| Week | Work |
|---|---|
| 11/19–11/25 | Second RentCast pull to measure how many listings disappear between pulls. Hand-label 200 RentSmart descriptions (`eval/signal_agreement.py`) and run the optional LLM classifier. Weekly RentCast refresh by zip. |
| 11/26–11/30 | Cambridge layers (Cambridge open data: inspections, building permits). Real transit times (MBTA V3 API or GTFS routing). POI noise layer. |
| 12/1–12/3 | User test with 5 students (proposal success metric). Polish the UI. Update the README, record a demo video, build the final deck. |

## 5. Numbers from the real build (snapshot Nov 4, build Nov 9)

- Listing snapshot: 4,218 retrieved → 3,011 kept (2,380 shown, 631 older backups). Boston 2,130 · Cambridge 881 (listing only).
- Boston listings matched to city data: 1,829 / 2,130 (86%). Found in city parcels: 1,716. With an owner of record: 1,829.
- Boston listings with ≥1 RentSmart record: 1,742 / 2,130. Matched, with no records: 87. Unmatched: 297.
- RentSmart rows loaded: 379,006 (through 2026-11-03) · Assessment rows: 175,314 · Crash records: 35,389 · MBTA stops: 7,227
- `make eval` (LLM mode, Nov 9): pass 20/20, made-up numbers 0, budget or bedroom violations 0, guardrail refusals 2/2.
