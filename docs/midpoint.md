# Midpoint check-in (Deliverable 2, Thu 11/19)

The course page asks for three things at the midpoint: a settled direction, the main technical uncertainties investigated, and real progress on the core of the project. The deliverable is a working repo plus a short demo.

## 1. Direction (settled)

Rent Radar is a rental map plus an AI neighborhood check for Harvard and MIT students in Allston, Brighton, Fenway and Cambridge. It is the same direction as the 10/29 proposal. The scope is narrower, and the changes come from instructor feedback:

| Feedback (10/29) | What changed |
|---|---|
| #1 data sources and weights are what matters | The score is a plain weighted average with a published formula for each factor. Sliders change the weights, and the agent states which weights it changed. Factors with no data are left out and labeled. |
| #6 RentSmart Boston | RentSmart replaces the hand-built 311 layer. It is one public file with 311 and inspection records per property. |
| #5, #7 landlord fraud and landlord history | Owner of record from Property Assessment: owner-occupied flag, out-of-state mailing address, portfolio size, and serious records across all of the owner's properties. The detail card also has a "verify before you pay" checklist citing M.G.L. c.186 §15B. |
| #4 more city data | Deferred to the final (fires, building violations outside RentSmart). |
| #9 noise sources | Proxy for now: busiest road (AADT) within 100 m. A POI layer (police, fire stations, ERs) is planned for the final. |
| #2, #3 Redfin / MLS | Not used. The terms of service and access requirements are documented in `docs/data-sources.md`. |

### Proposal feedback received 11/4 and what changed

| Feedback | Change |
|---|---|
| Boston layers and a clearly defined listing snapshot first | Search and map default to Boston. Cambridge is an opt-in "listing only" layer. The snapshot is the newest dated RentCast pull with stated rules (≤ 90 days shown, 91–180 kept as labeled backups, older or not recently seen dropped). |
| Replace "100% of active listings" with measurable coverage | Snapshot funnel plus Boston coverage table (parcel match, owner, occupancy, records / no records / unmatched), shown under About the data and printed by the build. |
| Complaints and crashes need geographic and time context, not personal safety | Every count carries its window and radius. The factor is called "Crash history", and no flag calls a street safe. |
| No complaint records = limited evidence | Neutral note "no city records since …, not proof of no problems". Building score is capped at 90. Unmatched addresses get no building score. |
| Show missing geographic coverage | Cambridge pins are hollow and labeled "LISTING ONLY", and the coverage table counts them. |

## 2. Technical uncertainties: what was tested

| Risk (proposal slide 4) | Status | Evidence |
|---|---|---|
| Joining listings to city records by address | **Built and tested.** Normalized street+zip keys with house-number ranges, plus a geo fallback within 20 m. | `tests/test_ingest_build.py` (exact, range, window and Cambridge "no data" cases). Real match rate: see the build report (§5). |
| Source schemas drift between releases | **Handled.** Column aliases, and a loud `SchemaError` that lists the columns found. The build continues without that layer and reports it. | `tests/test_ingest_build.py::test_resolve_aliases_and_error_message` |
| Network: api.rentcast.io and data.boston.gov are blocked from the dev sandboxes | **Worked around.** The fetch scripts run on the Mac with curl (the key is never written to disk), and the build works from local files. | `scripts/fetch_*.py` |
| LLM inventing numbers | **Measured.** A grounding check runs on every answer, with one corrective retry. | `make eval` → `eval/results/` (offline: 20/20 pass, 0 made-up numbers) |
| LLM unavailable during the demo (quota, wifi) | **Covered.** Automatic fallback to the offline planner over the same tools. | `tests/test_agent.py::test_llm_failure_falls_back_to_offline` |
| Fair Housing | **Guardrail plus a design choice.** No demographic or crime data is stored. Steering requests are refused. "Safe" is defined in the UI. | `tests/test_agent.py::test_guardrail_blocks_steering`, eval cases A17–A19 |
| Stale listings | **Found a real problem.** In the 10/27 RentCast pull, 462 of 1,000 rows were listed more than 180 days earlier, and every Allston, Brighton and Fenway row was. Now: freshness tiers (≤ 90 shown, 91–180 backups, older dropped), newest snapshot only, and a "gone since last pull" count when two pulls exist. | snapshot funnel in the build report |

## 3. What works now

- The data pipeline (fetch → ingest → match → evidence → SQLite), with a coverage report.
- A map of all in-scope listings, colored by score. Each listing opens an evidence card with the score breakdown, building records (with IDs), owner of record, commute, transit, crashes and traffic.
- The agent: Gemini function calling over 5 tools, citations, a grounding check and an offline fallback.
- Tests: 44 pytest cases on synthetic fixtures. The 20-case agent evaluation is scripted.

## 4. Plan to the final (12/3)

| Week | Work |
|---|---|
| 11/19–11/25 | Run `make eval` in LLM mode and fix failures. Hand-label 200 RentSmart descriptions (`eval/signal_agreement.py`) and run the optional LLM classifier. Weekly RentCast refresh by zip. |
| 11/26–11/30 | Cambridge layers (Cambridge open data: inspections, building permits). Real transit times (MBTA V3 API or GTFS routing). POI noise layer. |
| 12/1–12/3 | User test with 5 students (proposal success metric). Polish the UI. Update the README, record a demo video, build the final deck. |

## 5. Numbers to fill in after the real build

Run `make data && make build` on the Mac, then copy these from the printed report:

- Boston listings with ≥1 RentSmart record: ____ / ____
- Boston listings with an owner of record: ____ / ____
- RentSmart rows loaded: ____ · Assessment rows: ____ · MBTA stations: ____
- `make eval` (LLM mode): pass ____/20, made-up numbers ____
