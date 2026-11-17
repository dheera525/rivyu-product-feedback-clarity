import json

import classify
from conftest import make_item

REQUIRED_FIELDS = {
    "id", "text", "source", "core_bucket", "risk_tag", "sentiment",
    "urgency", "summary", "entities", "category", "issue_type",
}

ITEMS = [
    make_item("1", "App crashes every time I open it after the update"),
    make_item("2", "Login OTP never arrives, I can't access my account"),
    make_item("3", "Please add dark mode, my eyes hurt at night"),
    make_item("4", "I was charged twice for my subscription, need a refund"),
]


def _assert_well_formed(results, expected_ids):
    assert [r["id"] for r in results] == expected_ids
    for r in results:
        assert REQUIRED_FIELDS <= r.keys()
        assert r["core_bucket"] in classify.CORE_BUCKETS_SET
        assert -1.0 <= r["sentiment"] <= 1.0
        assert 1 <= r["urgency"] <= 5


def test_heuristic_used_when_no_keys_configured():
    results = classify.classify_items(ITEMS)

    _assert_well_formed(results, ["1", "2", "3", "4"])
    buckets = {r["id"]: r["core_bucket"] for r in results}
    assert buckets["1"] == "Crashes & App Stability"
    assert buckets["2"] == "Login & Account Access"
    assert buckets["3"] == "Feature Requests"
    assert buckets["4"] == "Payments, Refunds & Billing"


def test_falls_back_to_heuristic_when_llm_keeps_failing(monkeypatch):
    calls = []

    def flaky_llm(prompt, expect_json=False):
        calls.append(prompt)
        raise RuntimeError("503 service overloaded")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(classify, "call_llm", flaky_llm)

    results = classify.classify_items(ITEMS)

    assert len(calls) == 2  # retried once, then gave up
    _assert_well_formed(results, ["1", "2", "3", "4"])
    assert results[0]["core_bucket"] == "Crashes & App Stability"


def test_quota_error_switches_to_heuristic_without_retrying(monkeypatch):
    calls = []

    def quota_llm(prompt, expect_json=False):
        calls.append(prompt)
        raise RuntimeError("Gemini quota exceeded and OPENAI_API_KEY is not configured.")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(classify, "call_llm", quota_llm)

    results = classify.classify_items(ITEMS)

    assert len(calls) == 1
    _assert_well_formed(results, ["1", "2", "3", "4"])


def test_malformed_llm_json_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(classify, "call_llm", lambda *a, **k: '{"not": "a list"}')

    results = classify.classify_items(ITEMS)

    _assert_well_formed(results, ["1", "2", "3", "4"])


def test_llm_results_are_used_and_missing_items_filled(monkeypatch):
    def fake_llm(prompt, expect_json=False):
        # Only classify item 1; item 2 is "forgotten" by the model.
        return json.dumps([{
            "id": "1",
            "core_bucket": "Crashes & App Stability",
            "risk_tag": "stability_risk",
            "sentiment": -0.9,
            "urgency": 5,
            "summary": "Crash on launch after update",
            "entities": ["update"],
        }])

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(classify, "call_llm", fake_llm)

    results = classify.classify_items(ITEMS[:2])

    _assert_well_formed(results, ["1", "2"])
    assert results[0]["summary"] == "Crash on launch after update"
    assert results[0]["urgency"] == 5
    assert results[1]["core_bucket"] == "Login & Account Access"


def test_invalid_llm_values_are_clamped(monkeypatch):
    def fake_llm(prompt, expect_json=False):
        return json.dumps([{
            "id": "1", "core_bucket": "Made Up Bucket", "risk_tag": "bogus",
            "sentiment": 7, "urgency": 99, "summary": "x", "entities": "nope",
        }])

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(classify, "call_llm", fake_llm)

    [result] = classify.classify_items(ITEMS[:1])

    # The invalid bucket becomes "Other", so the heuristic rescues the row
    # (it's a crash report) and its own sentiment/urgency are used.
    assert result["core_bucket"] == "Crashes & App Stability"
    assert -1.0 <= result["sentiment"] <= 1.0
    assert 1 <= result["urgency"] <= 5
    assert result["risk_tag"] in classify.RISK_TAGS
    assert isinstance(result["entities"], list)


def test_empty_input_returns_empty_list():
    assert classify.classify_items([]) == []
