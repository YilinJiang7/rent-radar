import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(fixture_db):
    os.environ["RENTRADAR_DB"] = str(fixture_db)
    os.environ["RENTRADAR_OFFLINE"] = "1"
    from rentradar import api
    api.get_store.cache_clear()
    api.get_agent.cache_clear()
    return TestClient(api.app)


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["listing_count"] == 8 and m["llm"] is None
    assert set(m["campuses"]) == {"mit", "harvard", "seas"}


def test_listings_and_weights(client):
    r = client.get("/api/listings", params={"campus": "seas", "max_price": 3000}).json()
    assert r["count"] > 0 and all(l["price"] <= 3000 for l in r["listings"])
    assert client.get("/api/listings", params={"weights": "not json"}).status_code == 400


def test_listing_detail_with_records(client):
    e = client.get("/api/listings/FX-1").json()
    assert e["building"]["records_window"] == 3
    assert len(e["records"]) == 4 and e["records"][0]["match_type"] == "address"
    assert client.get("/api/listings/nope").status_code == 404
    rid = e["records"][0]["record_id"]
    assert client.get(f"/api/records/{rid}").json()["record_id"] == rid


def test_agent_endpoint(client):
    r = client.post("/api/agent", json={"query": "1 bed under 2500 near SEAS"}).json()
    assert r["mode"] == "offline" and r["grounding"]["ok"]
    assert client.post("/api/agent", json={"query": ""}).status_code == 422


def test_index_served(client):
    assert "Rent Radar" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
