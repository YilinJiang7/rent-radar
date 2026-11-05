"""Generate the small SYNTHETIC dataset in data/fixtures/.

The fixtures mimic the real schemas (RentCast JSON, RentSmart CSV, Property
Assessment CSV, MassDOT crash CSV, MBTA GTFS stops.txt) so tests and the
offline demo run without any download. Addresses, owners and records are
invented; coordinates are near real places so distances look realistic.

    python scripts/make_fixtures.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "fixtures"
random.seed(1125)


def listing(i, line1, unit, city, zip_, lat, lon, price, beds, baths, dom, agent=None):
    r = {
        "id": f"FX-{i}", "formattedAddress": f"{line1}{', ' + unit if unit else ''}, {city}, MA {zip_}",
        "addressLine1": line1, "addressLine2": unit, "city": city, "state": "MA", "zipCode": zip_,
        "latitude": lat, "longitude": lon, "propertyType": "Apartment", "bedrooms": beds,
        "bathrooms": baths, "squareFootage": 500 + 250 * beds, "status": "Active", "price": price,
        "listingType": "Standard", "listedDate": "2026-10-01T00:00:00.000Z",
        "lastSeenDate": "2026-10-27T00:00:00.000Z", "daysOnMarket": dom,
    }
    if agent:
        r["listingAgent"] = {"name": agent}
        r["listingOffice"] = {"name": "Example Realty"}
        r["mlsName"] = "MLSPIN"
    return r


LISTINGS = [
    listing(1, "12 Example St", "Apt 2", "Boston", "02134", 42.3535, -71.1320, 2400, 1, 1, 12, "A. Agent"),
    listing(2, "40-42 Sample Ave", "Unit 3", "Boston", "02134", 42.3550, -71.1290, 2900, 2, 1, 30),
    listing(3, "7 Fixture Rd", None, "Boston", "02135", 42.3490, -71.1560, 2100, 1, 1, 150),  # "older" tier
    listing(4, "88 Testing Ter", "# 5", "Boston", "02215", 42.3470, -71.1000, 3300, 2, 1, 5),
    listing(5, "3 Placeholder Pl", "Apt 1", "Boston", "02135", 42.3500, -71.1500, 1950, 0, 1, 45),
    listing(6, "200 Mock Street", "Apt 4", "Cambridge", "02139", 42.3640, -71.1030, 3100, 1, 1, 8),
    listing(7, "15 Demo Way", None, "Cambridge", "02138", 42.3790, -71.1230, 3600, 2, 1, 20),
    listing(8, "151 N Sample St", "# 727", "Cambridge", "02720", 42.3720, -71.0760, 3161, 0, 1, 2),  # wrong zip on purpose
    listing(9, "1 Faraway Ln", None, "Boston", "02124", 42.29, -71.07, 2000, 1, 1, 10),  # outside scope
    listing(10, "2 Ancient Way", None, "Boston", "02134", 42.3545, -71.1300, 1800, 1, 1, 400),  # dropped: > 180 days
    listing(11, "50 Quiet St", "Apt 1", "Boston", "02134", 42.3560, -71.1250, 2300, 1, 1, 20),  # in parcels, no records
    listing(12, "9 Nowhere Ln", None, "Boston", "02135", 42.3470, -71.1650, 2250, 1, 1, 15),  # not in city data
]

RENTSMART = [
    # date, violation_type, description, address, zip, parcel, owner, lat, lon
    ("2025-01-15", "Housing Complaints", "Heat - Excessive Insufficient", "12 Example St, 02134", "02134", "P1", "EXAMPLE HOLDINGS LLC", 42.3535, -71.1320),
    ("2025-02-02", "Housing Complaints", "Rodent Activity", "12 Example St, 02134", "02134", "P1", "EXAMPLE HOLDINGS LLC", 42.3535, -71.1320),
    ("2024-11-20", "Housing Violations", "Failure to maintain smoke detectors", "12 Example St, 02134", "02134", "P1", "EXAMPLE HOLDINGS LLC", 42.3535, -71.1320),
    ("2019-05-01", "Housing Complaints", "Mice Infestation - Residential", "12 Example St, 02134", "02134", "P1", "EXAMPLE HOLDINGS LLC", 42.3535, -71.1320),
    ("2025-06-10", "Sanitation Requests", "Improper storage of trash (barrels)", "41 Sample Ave, 02134", "02134", "P2", "JANE DOE", 42.3550, -71.1290),
    ("2025-08-08", "Civic Maintenance Requests", "Street Light Outages", "41 Sample Ave, 02134", "02134", "P2", "JANE DOE", 42.3550, -71.1290),
    ("2026-03-03", "Building Violations", "Unsafe and Dangerous - porch", "7 Fixture Road, 02135", "02135", "P3", "EXAMPLE HOLDINGS LLC", 42.3490, -71.1560),
    ("2026-04-04", "Housing Complaints", "Water leak from ceiling, mold", "99 Other St, 02135", "02135", "P9", "EXAMPLE HOLDINGS LLC", 42.3400, -71.1600),
    ("2025-09-09", "Housing Complaints", "Loud party noise", "88 Testing Terrace, 02215", "02215", "0000000004", "SMITH JOHN", 42.3470, -71.1000),
    # same parcel as 3 Placeholder Pl, but filed under a corner address -> only the parcel route finds it
    ("2026-01-20", "Housing Complaints", "No heat in unit", "1 Corner Rd, 02135", "02135", "5.0", "PLACE OWNER", 42.3600, -71.1700),
]

ASSESSMENT = [
    # PID, ST_NUM, ST_NUM2, ST_NAME, UNIT_NUM, ZIP_CODE, OWNER, OWN_OCC, MAIL_CITY, MAIL_STATE, LU_DESC, YR_BUILT, RES_UNITS
    ("P1", "12", "", "EXAMPLE ST", "", "2134", "EXAMPLE HOLDINGS LLC", "N", "WILMINGTON", "DE", "THREE-FAM DWELLING", "1910", "3"),
    ("P2", "40", "42", "SAMPLE AVE", "", "2134", "JANE DOE", "Y", "BOSTON", "MA", "TWO-FAM DWELLING", "1925", "2"),
    ("P3", "7", "", "FIXTURE RD", "", "02135", "EXAMPLE HOLDINGS LLC", "N", "WILMINGTON", "DE", "SINGLE FAM DWELLING", "1950", "1"),
    ("P9", "99", "", "OTHER ST", "", "02135", "EXAMPLE HOLDINGS LLC", "N", "WILMINGTON", "DE", "THREE-FAM DWELLING", "1900", "3"),
    ("4", "88", "", "TESTING TER", "5", "02215", "SMITH JOHN", "N", "BOSTON", "MA", "CONDO UNIT", "1999", "1"),
    ("0000000050", "50", "", "QUIET ST", "", "02134", "QUIET OWNER", "N", "BOSTON", "MA", "TWO-FAM DWELLING", "1915", "2"),
    ("0000000005", "3", "", "PLACEHOLDER PL", "", "02135", "PLACE OWNER", "Y", "BOSTON", "MA", "TWO-FAM DWELLING", "1920", "2"),
]

STOPS = [
    ("place-harsq", "Harvard", "", 42.373362, -71.118956, "1", "", ""),
    ("70067", "Harvard", "Harvard - Red Line - Alewife", 42.373362, -71.118956, "0", "place-harsq", "1"),
    ("place-cntsq", "Central", "", 42.365486, -71.103802, "1", "", ""),
    ("70069", "Central", "Central - Red Line - Ashmont/Braintree", 42.365486, -71.103802, "0", "place-cntsq", "1"),
    ("place-harvd", "Harvard Avenue", "", 42.350243, -71.131355, "1", "", ""),
    ("70130", "Harvard Avenue", "Harvard Avenue - Green Line - (B) Boston College", 42.350243, -71.131355, "0", "place-harvd", "0"),
    ("place-kencl", "Kenmore", "", 42.348949, -71.095169, "1", "", ""),
    ("71151", "Kenmore", "Kenmore - Green Line - Park Street & North", 42.348949, -71.095169, "0", "place-kencl", "0"),
    ("1001", "Brighton Ave @ Linden St", "", 42.3530, -71.1318, "0", "", "3"),
    ("1002", "Western Ave @ Soldiers Field", "", 42.3640, -71.1250, "0", "", "3"),
]


def crashes():
    rows = []
    hot = [(42.3536, -71.1318, 15000, "BRIGHTON AVENUE"), (42.3470, -71.1002, 30000, "BEACON STREET"),
           (42.3640, -71.1032, 25000, "MASSACHUSETTS AVENUE"), (42.3560, -71.1150, 40000, "CAMBRIDGE STREET")]
    n = 0
    for lat, lon, aadt, street in hot:
        for k in range(8):
            n += 1
            sev = "Non-fatal injury" if k % 3 == 0 else "Property damage only (none injured)"
            non_m = "Cyclist" if k % 4 == 0 else ("Pedestrian" if k % 5 == 0 else "")
            rows.append({
                "CRASH_NUMB": f"FXC{n:03d}", "CITY_TOWN_NAME": "BOSTON", "YEAR": 2021 + k % 5,
                "CRASH_DATETIME_ISO": f"{2021 + k % 5}-0{1 + k % 9}-15 18:00:00",
                "LAT": round(lat + random.uniform(-0.0006, 0.0006), 6), "LON": round(lon + random.uniform(-0.0006, 0.0006), 6),
                "CRASH_SEVERITY_DESCR": sev, "NUMB_FATAL_INJR": 0, "NUMB_NONFATAL_INJR": 1 if k % 3 == 0 else 0,
                "NON_MTRST_TYPE_CL": non_m, "AMBNT_LIGHT_DESCR": "Dark - lighted roadway" if k % 2 else "Daylight",
                "AADT": aadt, "STREETNAME": street,
            })
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "listings_fixture.json").write_text(json.dumps({"_note": "SYNTHETIC test data", "listings": LISTINGS}, indent=1))
    with open(OUT / "rentsmart_fixture.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "violation_type", "description", "address", "zip_code", "parcel", "owner", "latitude", "longitude"])
        w.writerows(RENTSMART)
    with open(OUT / "assessment_fixture.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PID", "ST_NUM", "ST_NUM2", "ST_NAME", "UNIT_NUM", "ZIP_CODE", "OWNER", "OWN_OCC", "MAIL_CITY", "MAIL_STATE", "LU_DESC", "YR_BUILT", "RES_UNITS"])
        w.writerows(ASSESSMENT)
    with open(OUT / "stops_fixture.txt", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stop_id", "stop_name", "stop_desc", "stop_lat", "stop_lon", "location_type", "parent_station", "vehicle_type"])
        w.writerows(STOPS)
    rows = crashes()
    with open(OUT / "crashes_fixture.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
