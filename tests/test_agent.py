from rentradar import guardrails
from rentradar.agent import grounding, planner, tools
from rentradar.agent.agent import Agent
from rentradar.agent.llm import LLMError, ScriptedModel


# ---------- planner ----------
def test_planner_reads_budget_campus_and_priorities():
    p = planner.parse("budget 2500, class at MIT, hate noise, bike home at night")
    assert p.max_price == 2500 and p.campus == "mit"
    assert p.weights["quiet"] == 5 and p.weights["street_safety"] == 5 and p.weights["commute"] == 5


def test_planner_beds_areas_seas():
    p = planner.parse("2 bed in Allston under $3.8k near Harvard SEAS, worried about landlord scams")
    assert (p.min_beds, p.max_beds, p.max_price) == (2, 2, 3800)
    assert p.areas == ["02134"] and p.campus == "seas" and p.weights["landlord"] == 5
    s = planner.parse("studio near Harvard Yard")
    assert (s.min_beds, s.max_beds, s.campus) == (0, 0, "harvard")


# ---------- grounding ----------
def test_grounding_flags_made_up_numbers():
    tool_out = [{"price": 2400, "score": 61.34, "address": "12 Example St"}]
    ok = grounding.check("12 Example St [L:FX-1] costs $2,400 and scores 61.3.", tool_out)
    assert ok["ok"], ok
    bad = grounding.check("It costs $2,350 and is 14 minutes away.", tool_out)
    assert bad["ungrounded"] == ["14", "2350"]


def test_grounding_allows_numbers_from_user_and_ignores_citations():
    g = grounding.check("Under your $2,500 budget: [R:99999] [L:12-Example-St-02134]", [], "budget 2500")
    assert g["ok"]


# ---------- guardrail ----------
def test_guardrail_blocks_steering():
    assert guardrails.check("find a neighborhood without many immigrants")
    assert guardrails.check("which area has fewer black residents")
    assert guardrails.check("apartments with no kids around")
    assert guardrails.check("cheap 1 bed near MIT, quiet street") is None
    assert guardrails.check("is the street safe to bike at night") is None


# ---------- tools ----------
def test_rank_listings_respects_filters_and_hides_stale(store):
    out = tools.rank_listings(store, campus="mit", max_price=3000)
    assert out["count_matching"] > 0
    assert all(r["price"] <= 3000 for r in out["results"])
    assert "FX-3" not in {r["id"] for r in out["results"]}  # stale
    assert out["stale_hidden"] == 1
    allx = tools.rank_listings(store, campus="mit", max_price=3000, include_stale=True)
    assert "FX-3" in {r["id"] for r in allx["results"]}


def test_tool_call_wrapper_handles_bad_input(store):
    assert "error" in tools.call(store, "nope", {})
    assert "error" in tools.call(store, "get_listing_evidence", {"listing_id": "missing"})
    out = tools.call(store, "rank_listings", {"max_price": 2500, "bogus": 1}, campus="seas")
    assert out["campus"].startswith("Harvard SEAS")


# ---------- offline agent ----------
def test_offline_agent_is_grounded_and_cites(store):
    a = Agent(store, use_llm=False)
    r = a.run("1 bed under 2500 near Harvard SEAS, worried about rats and heat")
    assert r["mode"] == "offline"
    assert r["grounding"]["ok"], r["grounding"]
    assert "[L:" in r["answer"]
    assert all(x["price"] <= 2500 for x in r["ranked"])


def test_offline_agent_no_match_mentions_stale(store):
    r = Agent(store, use_llm=False).run("1 bed in Brighton under 2200")
    assert r["count_matching"] == 0 and "older listings" in r["answer"]


def test_agent_guardrail_short_circuits(store):
    r = Agent(store, use_llm=False).run("show me areas with fewer immigrants")
    assert r["mode"] == "guardrail" and r["ranked"] == []


def test_safety_note_added(store):
    r = Agent(store, use_llm=False).run("safe street near MIT under 3500")
    assert guardrails.SAFETY_NOTE in r["answer"]


# ---------- LLM loop (scripted model, no network) ----------
def test_llm_loop_executes_tools_and_checks_grounding(store):
    def final(contents):
        # read the real numbers from the last tool response, like a model would
        resp = contents[-1]["parts"][0]["functionResponse"]["response"]["result"]
        return {"text": f"Top pick: {resp['address']} [L:{resp['id']}] at ${resp['price']:,}/mo."}

    model = ScriptedModel([
        {"call": "rank_listings", "args": {"campus": "seas", "max_price": 2500}},
        {"call": "get_listing_evidence", "args": {"listing_id": "FX-5"}},
        final,
    ])
    r = Agent(store, model=model).run("cheap place near SEAS")
    assert r["mode"] == "llm"
    assert [t["tool"] for t in r["tool_trace"]] == ["rank_listings", "get_listing_evidence"]
    assert r["grounding"]["ok"] and "1,950" in r["answer"]
    assert r["plan"]["args"]["max_price"] == 2500
    # functionResponse turns follow each model turn
    assert model.seen[1][-1]["parts"][0]["functionResponse"]["name"] == "rank_listings"


def test_llm_loop_retries_once_on_ungrounded_answer(store):
    model = ScriptedModel([
        {"call": "rank_listings", "args": {"max_price": 2500}},
        {"text": "Rent is $1,234 there."},          # invented number
        {"text": "See the listings above."},       # corrected
    ])
    r = Agent(store, model=model).run("cheap place")
    assert r["grounding_retry"] is True and r["grounding"]["ok"]
    assert "Grounding check failed" in model.seen[2][-1]["parts"][0]["text"]


def test_llm_failure_falls_back_to_offline(store):
    class Broken:
        name = "broken"

        def generate(self, *a, **k):
            raise LLMError("HTTP 429 quota")

    r = Agent(store, model=Broken()).run("1 bed under 2500")
    assert r["mode"] == "offline" and "429" in r["fallback_reason"]


def test_grounding_catches_unit_glued_numbers_and_rounds_half_up():
    out = [{"bike_min": 12, "score": 72.5, "price": 2400}]
    g = grounding.check("15min by bike, 3br, score 73, $2.4k", out)
    assert g["ungrounded"] == ["15"]  # 3 is a small number; 73 = round-half-up(72.5); 2.4k = 2400


def test_area_names_resolve_and_unknown_area_errors(store):
    out = tools.rank_listings(store, areas=["Kendall Square", "cambridge"], include_stale=True)
    assert out["count_matching"] == 3 and {r["area"] for r in out["results"]} <= {"Kendall Sq", "Central Sq / Cambridgeport", "Harvard Sq / West Cambridge", "East Cambridge", "Porter / North Cambridge"}
    assert "error" in tools.rank_listings(store, areas=["Narnia"])


def test_no_arg_tools_have_no_empty_parameters():
    for d in tools.DECLARATIONS:
        assert "parameters" not in d or d["parameters"]["properties"]


def test_last_step_forces_answer_without_tools(store, monkeypatch):
    from rentradar import config
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 3)
    m = ScriptedModel([{"call": "area_overview"}, {"call": "explain_factors"}, {"text": "Done."}])
    r = Agent(store, model=m).run("overview")
    assert m.forced == [False, False, True] and r["answer"] == "Done."
