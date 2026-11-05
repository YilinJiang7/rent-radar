# Data sources

| Source | Used for | Access | Refresh | Notes |
|---|---|---|---|---|
| RentCast long-term rental listings — `GET https://api.rentcast.io/v1/listings/rental/long-term` | active listings (price, beds, baths, sqft, coordinates, days on market, agent if MLS) | API key; free Developer plan = 50 requests/month | weekly, about 8–12 requests (one per zip page) | No photos, descriptions or listing URLs. About 16% of rows carry an MLSPIN agent. Raw files are git-ignored. |
| RentSmart Boston — <https://data.boston.gov/dataset/rentsmart> | building complaints and violations per address, with owner | public CSV | city updates daily | Combines BOS:311 and Inspectional Services: housing complaints, housing and building violations, sanitation and civic maintenance requests. Recommended by the instructors on 10/29. |
| Boston Property Assessment (latest FY) — <https://data.boston.gov/dataset/property-assessment> | owner of record, owner-occupied flag, mailing address, owner portfolio | public CSV | yearly | Used for the landlord check suggested in instructor feedback #5 and #7. |
| MassDOT crash records 2021–2025 (Boston, Cambridge, Somerville) | street safety, after-dark bike crashes on the route, AADT noise proxy | public; reused from PSet1 | — | `data/vendor/crashes/` |
| MBTA GTFS — <https://cdn.mbta.com/MBTA_GTFS.zip> | stations, lines, bus stops | public | as needed | Only `stops.txt` is kept. `vehicle_type` 0/1 = Green Line, Mattapan and subway; 3 = bus. |

## Considered and rejected

- **Zillow / Apartments.com / Craigslist**: no open API, and their terms of service forbid scraping.
- **Redfin rentals** (instructor tip #2): current listings only, and the terms of service need checking before any use. Not used in v1.
- **Full MLS history** (tip #3): needs broker access.
- **Crime data**: deliberately not used. "Safety" in this app means crash and building records, which keeps the app clear of demographic proxies and Fair Housing problems.

## Coverage report

`python -m rentradar.build` prints, and stores in `meta.build`:

- rows per source
- Boston listings with at least one matched RentSmart record
- Boston listings with an owner of record
- listings whose zip was corrected from coordinates (RentCast returned 02720 for some Cambridge rows)
- the listing snapshot funnel: retrieved, dropped by each rule (inactive, outside scope, not seen recently, > 180 days), shown (≤ 90 days) and older backups (91–180 days)
- coverage of Boston listings: matched to a parcel, owner found, occupancy known, with records, no records (limited evidence), unmatched
- when an earlier snapshot exists: how many of its listings are gone in the new pull (likely rented)

The "About the data" dialog in the UI shows these tables.
