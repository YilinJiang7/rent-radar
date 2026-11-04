import json

import pytest

from rentradar import config
from rentradar.ingest import SchemaError, resolve, rentsmart
from rentradar.ingest import listings as listings_mod


def test_listings_scope_dedupe_and_zip_correction():
    rows = listings_mod.load([config.FIXTURE_DIR / "listings_fixture.json"])
    ids = {r["id"] for r in rows}
    assert "FX-9" not in ids  # 02124 is outside v1 scope
    fx8 = next(r for r in rows if r["id"] == "FX-8")
    assert fx8["zip_corrected"] == 1 and fx8["area_zip"] in config.CAMBRIDGE_ZIPS
    fx3 = next(r for r in rows if r["id"] == "FX-3")
    assert fx3["stale"] == 1  # 260 days on market


def test_resolve_aliases_and_error_message():
    cols = resolve(["OPEN_DT", "Type", "Description", "Address"], rentsmart.ALIASES,
                   ["date", "violation_type", "description", "address"], "t")
    assert cols["date"] == "OPEN_DT" and cols["violation_type"] == "Type"
    with pytest.raises(SchemaError) as e:
        resolve(["foo"], rentsmart.ALIASES, ["address"], "RentSmart x")
    assert "Columns found" in str(e.value)


def test_build_report(store):
    src = store.meta["sources"]
    assert src["listings"]["rows"] == 8
    assert src["rentsmart"]["rows"] == 10
    assert store.meta["fixtures"] is True
    link = src["linking"]
    assert link["zip_corrected"] == 1 and link["stale_listings"] == 1


def test_building_match_exact_range_and_window(store):
    f1 = store.features["FX-1"]["building"]  # 12 Example St
    assert f1["available"] and f1["match_type"] == "address"
    assert f1["records_total"] == 4           # 2019 record included in all-years total
    assert f1["records_window"] == 3          # ...but not in the 3-year window
    assert set(f1["by_signal"]) == {"heat_hot_water", "pests", "fire_life_safety"}
    f2 = store.features["FX-2"]["building"]  # 40-42 Sample Ave matches "41 Sample Ave"
    assert f2["match_type"] == "address_range"
    assert f2["records_window"] == 1          # trash; the street light is not building-level


def test_parcel_route_finds_record_filed_under_other_address(store):
    b = store.features["FX-5"]["building"]  # 3 Placeholder Pl; record filed as "1 Corner Rd" on its parcel
    assert b["match_type"] == "parcel" and b["by_signal"] == {"heat_hot_water": 1}


def test_cambridge_has_no_rentsmart(store):
    b = store.features["FX-6"]["building"]
    assert b["available"] is False and "Boston" in b["reason"]


def test_owner_portfolio(store):
    o = store.features["FX-1"]["owner"]
    assert o["owner"] == "EXAMPLE HOLDINGS LLC" and o["is_entity"] and o["out_of_state"]
    assert o["portfolio_properties"] == 3
    # heat + pests + smoke detectors at 12 Example, porch at 7 Fixture, leak/mold at 99 Other
    assert o["portfolio_serious_records_window"] == 5
    assert store.features["FX-2"]["owner"]["owner_occupied"] is True


def test_street_commute_transit(store):
    f = store.features["FX-1"]
    assert f["street"]["crashes"] >= 1 and f["street"]["injury_crashes"] >= 1
    assert f["transit"]["station"] == "Harvard Avenue"
    assert "Green Line B" in f["transit"]["lines"]
    assert f["commute"]["seas"]["bike_min"] < f["commute"]["mit"]["bike_min"]
    assert json.dumps(f)  # JSON-safe


def test_signal_rules():
    from rentradar.signals import classify_rule
    assert classify_rule("Heat - Excessive Insufficient") == "heat_hot_water"
    assert classify_rule("Mice Infestation - Residential") == "pests"
    assert classify_rule("Water leak from ceiling, mold") == "water_mold"
    assert classify_rule("Street Light Outages", "Civic Maintenance Requests") == "street_public"
    assert classify_rule("something odd", "Housing Complaints") == "living_conditions"
    assert classify_rule("something odd", "") == "other"
