from rentradar.scoring import DEFAULT_WEIGHTS, FACTORS


def test_every_factor_documented():
    assert set(DEFAULT_WEIGHTS) == set(FACTORS)
    assert all(FACTORS[k]["how"] for k in FACTORS)


def test_missing_factors_are_excluded_not_guessed(store):
    l = store.listings["FX-6"]  # Cambridge -> no building / owner data
    s = store.scorer.score(l, store.features["FX-6"], "mit")
    missing = {b["factor"] for b in s["breakdown"] if b.get("missing")}
    assert {"building", "landlord"} <= missing
    assert s["weight_coverage_pct"] < 100
    used = [b for b in s["breakdown"] if not b.get("missing")]
    expected = sum(b["weight"] * b["score"] for b in used) / sum(b["weight"] for b in used)
    assert abs(s["total"] - round(expected, 1)) < 0.11


def test_bad_building_scores_lower(store):
    s1 = store.scorer.score(store.listings["FX-1"], store.features["FX-1"], "mit")
    s2 = store.scorer.score(store.listings["FX-2"], store.features["FX-2"], "mit")  # one trash record
    s4 = store.scorer.score(store.listings["FX-4"], store.features["FX-4"], "mit")  # one noise record
    b = lambda s: next(x for x in s["breakdown"] if x["factor"] == "building")["score"]  # noqa: E731
    assert b(s1) < b(s2) < 100.0 and b(s4) == b(s2)


def test_weights_change_ranking(store):
    rows = list(store.listings.values())
    cheap_first = store.scored(rows, "mit", {k: 0 for k in DEFAULT_WEIGHTS} | {"price": 5})
    ppb = lambda r: r["price"] / max(1, r["bedrooms"] or 1)  # noqa: E731  rent per bedroom
    assert ppb(cheap_first[0]["listing"]) == min(ppb(r) for r in rows)
    zero = store.scorer.score(rows[0], store.features[rows[0]["id"]], "mit", {k: 0 for k in DEFAULT_WEIGHTS})
    assert zero["total"] is None


def test_budget_price_curve(store):
    l = dict(store.listings["FX-1"])  # $2,400
    f = store.features["FX-1"]
    p = lambda budget: store.scorer.factor_scores(l, f, "mit", budget)["price"]  # noqa: E731
    assert p(4000) == 100.0
    assert p(2400) == 50.0
    assert p(2000) < 50
