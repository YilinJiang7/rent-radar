import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rentradar import config
from rentradar.ingest import SchemaError, resolve, rentsmart
from rentradar.ingest import listings as listings_mod


PULL = datetime(2026, 10, 27, tzinfo=timezone.utc)


def test_listings_scope_tiers_and_funnel():
    rows, funnel = listings_mod.load_snapshot([config.FIXTURE_DIR / "listings_fixture.json"], today=PULL)
    ids = {r["id"] for r in rows}
    assert "FX-9" not in ids   # 02124 is outside v1 scope
    assert "FX-10" not in ids  # 400 days on market: dropped
    fx8 = next(r for r in rows if r["id"] == "FX-8")
    assert fx8["zip_corrected"] == 1 and fx8["area_zip"] in config.CAMBRIDGE_ZIPS
    fx3 = next(r for r in rows if r["id"] == "FX-3")
    assert fx3["tier"] == "older" and fx3["stale"] == 1  # 150 days: kept as a backup
    assert funnel["retrieved"] == 12 and funnel["dropped_outside_scope"] == 1
    assert funnel["dropped_older_than_backup"] == 1 and funnel["kept"] == 10 == funnel["fresh"] + funnel["older"]


def test_not_seen_recently_is_dropped(tmp_path):
    p = tmp_path / "2026-11-10_02134.json"
    p.write_text(json.dumps([{"id": "A", "status": "Active", "price": 2000, "latitude": 42.354, "longitude": -71.13,
                              "zipCode": "02134", "city": "Boston", "addressLine1": "1 A St", "daysOnMarket": 10,
                              "lastSeenDate": "2026-10-01T00:00:00Z"}]))
    rows, funnel = listings_mod.load_snapshot([p], today=datetime(2026, 11, 10, tzinfo=timezone.utc))
    assert rows == [] and funnel["dropped_not_seen_recently"] == 1


def test_snapshot_grouping_uses_newest_dated_pull():
    names = [Path("listings_Boston.json"), Path("2026-11-05_02134.json"), Path("2026-11-12_02134.json"),
             Path("2026-11-12_02135.json")]
    groups = listings_mod.group_snapshots(names)
    assert groups[0][0] == "2026-11-12" and len(groups[0][1]) == 2
    assert [g[0] for g in groups] == ["2026-11-12", "2026-11-05", "undated"]


def test_resolve_aliases_and_error_message():
    cols = resolve(["OPEN_DT", "Type", "Description", "Address"], rentsmart.ALIASES,
                   ["date", "violation_type", "description", "address"], "t")
    assert cols["date"] == "OPEN_DT" and cols["violation_type"] == "Type"
    with pytest.raises(SchemaError) as e:
        resolve(["foo"], rentsmart.ALIASES, ["address"], "RentSmart x")
    assert "Columns found" in str(e.value)


def test_build_report(store):
    src = store.meta["sources"]
    assert src["listings"]["rows"] == 10
    assert src["rentsmart"]["rows"] == 10
    assert store.meta["fixtures"] is True
    link = src["linking"]
    assert link["zip_corrected"] == 1 and link["stale_listings"] == 1
    cov = store.meta["coverage"]
    assert cov["boston_listings"] == 7 and cov["with_city_records"] == 5
    assert cov["no_records_found"] == 1 and cov["unmatched"] == 1 and cov["cambridge_listings_listing_only"] == 3


def test_no_records_is_limited_evidence_not_reassurance(store):
    from rentradar import summary
    b11 = store.features["FX-11"]["building"]
    assert b11["evidence"] == "no_records" and b11["records_window"] == 0
    s = store.scorer.score(store.listings["FX-11"], store.features["FX-11"], "mit")
    assert next(x for x in s["breakdown"] if x["factor"] == "building")["score"] == 90.0  # capped, never 100
    fl = summary.flags(store.listings["FX-11"], store.features["FX-11"], "mit")
    assert not any(f["kind"] == "good" and f["topic"] == "building" for f in fl)
    assert any("not proof" in f["text"] for f in fl)
    # address not in city data at all -> no building score
    assert store.features["FX-12"]["building"]["evidence"] == "unmatched"
    s12 = store.scorer.score(store.listings["FX-12"], store.features["FX-12"], "mit")
    assert next(x for x in s12["breakdown"] if x["factor"] == "building").get("missing")


def test_flags_never_call_a_street_safe(store):
    from rentradar import summary
    for lid in store.listings:
        for f in summary.flags(store.listings[lid], store.features[lid], "mit"):
            assert not (f["topic"] == "street" and f["kind"] == "good")
            assert not re.search(r"\b(safe|unsafe|dangerous)\b", f["text"].lower())


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


def test_city_comes_from_zip_not_rentcast_label(store):
    l = store.listings["FX-2"]  # RentCast says "Allston"
    assert l["city"] == "Boston" and l["city_raw"] == "Allston"
    assert store.features["FX-2"]["building"]["available"] is True
    # and it is inside the Boston-first default scope
    from rentradar.agent import tools
    out = tools.rank_listings(store, campus="mit", limit=20)
    assert "FX-2" in {r["id"] for r in out["results"]}
