"""Project-wide configuration: scope, campuses, paths, radii.

Everything that a reviewer might want to change lives here so the rest of the
code has no magic numbers.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("RENTRADAR_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
VENDOR_DIR = DATA_DIR / "vendor"
FIXTURE_DIR = DATA_DIR / "fixtures"
DB_PATH = Path(os.getenv("RENTRADAR_DB", DATA_DIR / "rentradar.sqlite"))

# --- Scope (v1 = student neighborhoods) -------------------------------------
# zip -> (area label, city, approximate centroid lat, lon). Centroids are only
# used to re-assign listings whose zip code is wrong (RentCast returned a few
# Cambridge rows with zip 02720) -- we place those by coordinates instead.
AREAS = {
    "02134": ("Allston", "Boston", 42.3539, -71.1337),
    "02135": ("Brighton", "Boston", 42.3489, -71.1566),
    "02215": ("Fenway / Kenmore", "Boston", 42.3472, -71.1022),
    "02138": ("Harvard Sq / West Cambridge", "Cambridge", 42.3800, -71.1340),
    "02139": ("Central Sq / Cambridgeport", "Cambridge", 42.3640, -71.1040),
    "02140": ("Porter / North Cambridge", "Cambridge", 42.3920, -71.1330),
    "02141": ("East Cambridge", "Cambridge", 42.3700, -71.0830),
    "02142": ("Kendall Sq", "Cambridge", 42.3620, -71.0830),
}
BOSTON_ZIPS = [z for z, a in AREAS.items() if a[1] == "Boston"]
CAMBRIDGE_ZIPS = [z for z, a in AREAS.items() if a[1] == "Cambridge"]

# Campus destinations used for commute estimates.
CAMPUSES = {
    "mit": {"name": "MIT (77 Massachusetts Ave)", "lat": 42.3594, "lon": -71.0928},
    "harvard": {"name": "Harvard Yard", "lat": 42.3744, "lon": -71.1169},
    "seas": {"name": "Harvard SEAS (150 Western Ave, Allston)", "lat": 42.3634, "lon": -71.1257},
}
DEFAULT_CAMPUS = "mit"

# --- Evidence radii / windows -------------------------------------------------
CRASH_RADIUS_M = 150          # crashes "near" a listing
CORRIDOR_WIDTH_M = 75         # crashes "along the way" to campus
BUSY_ROAD_RADIUS_M = 100      # AADT proxy for traffic noise
STATION_SEARCH_M = 1600       # search radius for nearest rapid-transit station
BUS_STOP_RADIUS_M = 400
GEO_MATCH_M = 20              # coordinate fallback when address match fails
BUILDING_RECORD_YEARS = 3     # building record window for scoring
# Listing freshness tiers (days on market). RentCast keeps a listing "Active"
# while some source still shows it, so old listings are often already rented.
FRESH_DAYS = 90               # shown by default
BACKUP_DAYS = 180             # 91-180: kept as "older" backups, hidden by default; >180 dropped
NOT_SEEN_DAYS = 14            # dropped if RentCast has not seen it active for this long
STALE_DAYS = FRESH_DAYS       # older name kept for compatibility: "stale" = older than FRESH_DAYS
DEFAULT_CITIES = ["Boston"]   # v1 scope per feedback: Boston layers first; Cambridge = listings only

# Commute speed assumptions (documented in README). Detour factor turns a
# straight line into a rough street distance.
DETOUR_FACTOR = 1.3
WALK_M_PER_MIN = 80           # ~4.8 km/h
BIKE_M_PER_MIN = 250          # ~15 km/h

# --- LLM ----------------------------------------------------------------------
# gemini-2.5-flash returns 404 for new users (Nov 2026); override in .env if needed
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite")
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "8"))
