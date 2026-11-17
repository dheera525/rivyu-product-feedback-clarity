"""HTTP-level tests for the FastAPI app (LLM calls are mocked out)."""

import json

import ask_rivyu
import backend.main as main


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_status_reflects_real_state(client):
    assert client.get("/api/status").json()["state"] == "empty"

    client.post("/api/ingest/demo")
    status = client.get("/api/status").json()
    assert status["state"] == "ingested"
    assert status["has_results"] is False
    assert status["raw_count"] == 30

    client.post("/api/analyze", json={})
    status = client.get("/api/status").json()
    assert status["state"] == "analyzed"
    assert status["has_results"] is True
    assert status["analyzed_at"]


def test_reset_returns_to_empty(client):
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})
    client.post("/api/reset")
    assert client.get("/api/status").json()["state"] == "empty"
    assert client.get("/api/dashboard").status_code == 404


def test_dashboard_404_before_analysis(client):
    assert client.get("/api/dashboard").status_code == 404


def test_demo_flow_produces_dashboard(client):
    assert client.post("/api/ingest/demo").json()["count"] == 30
    analysis = client.post("/api/analyze", json={}).json()
    assert analysis["analyzed_count"] == 30

    data = client.get("/api/dashboard").json()
    assert data["has_results"]
    assert data["alerts"]
    assert data["themes"]
    # Demo dates are shifted to be recent, so time windows are non-empty.
    assert data["stats"]["window_counts"]["mentions_7d"] > 0

    theme_id = data["themes"][0]["theme_id"]
    theme = client.get(f"/api/theme/{theme_id}").json()
    assert theme["items"]


def test_csv_upload_valid(client):
    res = client.post(
        "/api/ingest/csv",
        files={"file": ("complaints.csv", b"text,rating\nApp keeps crashing,1\nRefund please,2\n", "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["count"] == 2
    assert client.get("/api/status").json()["sources"][0]["id"] == "complaints.csv"


def test_csv_upload_wrong_columns(client):
    res = client.post("/api/ingest/csv", files={"file": ("bad.csv", b"name,score\nbob,3\n", "text/csv")})
    assert res.status_code == 400
    assert "No text column found" in res.json()["detail"]
    assert client.get("/api/status").json()["state"] == "empty"


def test_csv_upload_wrong_extension(client):
    res = client.post("/api/ingest/csv", files={"file": ("data.xlsx", b"text\nhi\n")})
    assert res.status_code == 400


def test_playstore_rejects_bad_app_id(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_playstore_reviews", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")))
    for bad in ["", "   ", "not an id", "whatsapp", "com..x"]:
        res = client.post("/api/ingest/playstore", json={"app_id": bad})
        assert res.status_code == 400, bad


def test_playstore_accepts_store_url(client, monkeypatch):
    seen = {}

    def fake_fetch(app_id, count=100):
        seen["app_id"] = app_id
        return [{"id": "gp_1", "source": "google_play", "text": "Crashes a lot", "date": "2026-03-01T00:00:00Z"}]

    monkeypatch.setattr(main, "fetch_playstore_reviews", fake_fetch)
    res = client.post("/api/ingest/playstore",
                      json={"app_id": "https://play.google.com/store/apps/details?id=com.whatsapp&hl=en"})
    assert res.status_code == 200
    assert seen["app_id"] == "com.whatsapp"


def test_playstore_no_results_is_404(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_playstore_reviews", lambda *a, **k: [])
    res = client.post("/api/ingest/playstore", json={"app_id": "com.example.app"})
    assert res.status_code == 404
    assert "com.example.app" in res.json()["detail"]


def test_reddit_validation(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_reddit_posts", lambda *a, **k: [])
    assert client.post("/api/ingest/reddit", json={"subreddit": ""}).status_code == 400
    assert client.post("/api/ingest/reddit", json={"subreddit": "bad name!"}).status_code == 400
    res = client.post("/api/ingest/reddit", json={"subreddit": "r/whatsapp"})
    assert res.status_code == 404
    assert "r/whatsapp" in res.json()["detail"]


def test_ask_falls_back_to_deterministic_answer(client):
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})

    res = client.post("/api/ask", json={"question": "What are the top issues?"})

    assert res.status_code == 200
    answer = res.json()["answer"]
    assert "## Summary" in answer
    assert "Crashes & App Stability" in answer


def test_ask_recent_question_uses_trend_branch(client):
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})
    answer = client.post("/api/ask", json={"question": "What is new this week?"}).json()["answer"]
    assert "Rising or newly appearing themes" in answer or "Nothing is rising sharply" in answer


def test_ask_fallback_answers_revenue_questions(client):
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})
    answer = client.post("/api/ask", json={"question": "Any revenue risks?"}).json()["answer"]
    assert "Payments, Refunds & Billing" in answer
    assert "charged twice" in answer.lower() or "double charged" in answer.lower()
    assert "_risk" not in answer  # tags are rendered as readable labels


def test_ask_fallback_prioritizes_by_alert_order(client):
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})
    answer = client.post("/api/ask", json={"question": "What should we prioritize this sprint?"}).json()["answer"]
    assert answer.index("1. **Crashes & App Stability") < answer.index("2. **")


def test_ask_uses_llm_when_available(client, monkeypatch):
    monkeypatch.setattr(ask_rivyu, "call_llm", lambda prompt, expect_json=False: "  LLM says hi  ")
    client.post("/api/ingest/demo")
    client.post("/api/analyze", json={})
    assert client.post("/api/ask", json={"question": "hi"}).json()["answer"] == "LLM says hi"


def test_ask_rejects_empty_question(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 400


def test_analyze_failure_keeps_raw_data(client, monkeypatch):
    client.post("/api/ingest/demo")

    def boom(_items):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(main, "run_pipeline", boom)
    res = client.post("/api/analyze", json={})

    assert res.status_code == 500
    status = client.get("/api/status").json()
    assert status["state"] == "ingested"
    assert status["raw_count"] == 30


def test_half_analyzed_store_is_repaired_on_load(isolated_store):
    import os
    os.makedirs(isolated_store.sessions_dir(), exist_ok=True)
    with open(isolated_store.session_file(), "w") as f:
        json.dump({
            "raw_items": [{"id": "1", "text": "hi"}],
            "processed_items": [{"id": "1"}],
            "stats": {},  # results without stats = interrupted run
            "themes": [{"theme_id": "x"}],
        }, f)

    isolated_store.load_from_disk()

    assert isolated_store.session_state() == "ingested"
    assert isolated_store.get_store()["themes"] == []


def test_corrupt_store_file_starts_empty(isolated_store):
    import os
    os.makedirs(isolated_store.sessions_dir(), exist_ok=True)
    with open(isolated_store.session_file(), "w") as f:
        f.write("{not json")

    assert isolated_store.load_from_disk() is False
    assert isolated_store.session_state() == "empty"
