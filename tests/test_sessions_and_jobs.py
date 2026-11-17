"""Per-visitor sessions, background analysis jobs, and deployment capabilities."""

import time

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.ingest import reddit
from run_pipeline import STAGES, run_pipeline

from conftest import make_item


def _wait_for_job(client, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get("/api/analyze/progress").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("analysis job did not finish")


# --- Sessions ---------------------------------------------------------------

def test_each_browser_gets_its_own_session():
    with TestClient(main.app) as alice, TestClient(main.app) as bob:
        alice.post("/api/ingest/demo")
        assert alice.get("/api/status").json()["raw_count"] == 30
        assert bob.get("/api/status").json()["state"] == "empty"

        bob.post("/api/ingest/csv", files={"file": ("b.csv", b"text\nslow app\n")})
        assert alice.get("/api/status").json()["raw_count"] == 30
        assert bob.get("/api/status").json()["raw_count"] == 1

        bob.post("/api/reset")
        assert alice.get("/api/status").json()["raw_count"] == 30


def test_session_cookie_is_http_only():
    with TestClient(main.app) as c:
        res = c.get("/api/status")
        cookie = res.headers["set-cookie"]
        assert cookie.startswith("rivyu_sid=")
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        # Not re-issued once the browser has it.
        assert "set-cookie" not in c.get("/api/status").headers


def test_invalid_session_cookie_is_replaced():
    with TestClient(main.app) as c:
        c.cookies.set("rivyu_sid", "../../etc/passwd")
        res = c.get("/api/status")
        assert res.status_code == 200
        assert "set-cookie" in res.headers


def test_session_survives_restart_via_disk(isolated_store):
    with TestClient(main.app) as c:
        c.post("/api/ingest/demo")
        c.post("/api/analyze", json={})
        isolated_store.reset_all_sessions()  # simulate a process restart
        status = c.get("/api/status").json()
        assert status["state"] == "analyzed"
        assert status["processed_count"] == 30


def test_expired_session_files_are_purged(isolated_store):
    import os

    with TestClient(main.app) as c:
        c.post("/api/ingest/demo")
    [name] = os.listdir(isolated_store.sessions_dir())
    path = os.path.join(isolated_store.sessions_dir(), name)
    old = time.time() - 72 * 3600
    os.utime(path, (old, old))

    assert isolated_store.purge_expired_sessions() == 1
    assert not os.path.exists(path)


# --- Removed and gated endpoints ---------------------------------------------

@pytest.mark.parametrize("method, path", [
    ("post", "/api/login"),
    ("post", "/api/logout"),
    ("get", "/api/me"),
])
def test_hardcoded_login_endpoints_are_gone(client, method, path):
    assert getattr(client, method)(path).status_code in (404, 405)


@pytest.mark.parametrize("method, path", [
    ("post", "/api/ingest/gmail"),
    ("post", "/api/ingest/x"),
    ("post", "/api/ingest/youtube"),
    ("get", "/api/auth/google/start"),
])
def test_experimental_sources_disabled_by_default(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 404
    assert "coming soon" in res.json()["detail"].lower()


def test_no_cors_headers_by_default(client):
    res = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


# --- Background analysis -----------------------------------------------------

def test_background_analysis_reports_progress_and_finishes(client):
    client.post("/api/ingest/demo")

    start = client.post("/api/analyze/start", json={})
    assert start.status_code == 202
    assert start.json()["status"] == "running"
    assert start.json()["stages"] == STAGES

    job = _wait_for_job(client)

    assert job["status"] == "done"
    assert job["percent"] == 100
    assert job["result"]["analyzed_count"] == 30
    assert client.get("/api/status").json()["state"] == "analyzed"


def test_progress_is_idle_before_any_job(client):
    assert client.get("/api/analyze/progress").json() == {"status": "idle"}


def test_background_analysis_error_is_reported(client, monkeypatch):
    client.post("/api/ingest/demo")
    monkeypatch.setattr(main, "run_pipeline", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    client.post("/api/analyze/start", json={})
    job = _wait_for_job(client)

    assert job["status"] == "error"
    assert "still loaded" in job["error"]
    assert client.get("/api/status").json()["state"] == "ingested"


def test_ingest_is_blocked_while_analysis_runs(client, monkeypatch):
    import threading

    release = threading.Event()

    def slow_pipeline(items, progress=None):
        release.wait(5)
        return run_pipeline(items, progress=progress)

    client.post("/api/ingest/demo")
    monkeypatch.setattr(main, "run_pipeline", slow_pipeline)
    client.post("/api/analyze/start", json={})
    try:
        assert client.get("/api/status").json()["analyzing"] is True
        assert client.post("/api/ingest/demo").status_code == 409
        assert client.post("/api/reset").status_code == 409
        # A second start returns the running job instead of starting another.
        assert client.post("/api/analyze/start", json={}).json()["status"] == "running"
    finally:
        release.set()
    assert _wait_for_job(client)["status"] == "done"


def test_pipeline_reports_stages_in_order():
    seen = []
    items = [make_item(str(i), f"App crashes on launch {i}") for i in range(20)]

    run_pipeline(items, progress=lambda stage, fraction: seen.append((stage, fraction)))

    stages = [s for s, _ in seen]
    assert [s for i, s in enumerate(stages) if s not in stages[:i]] == STAGES
    classify_fractions = [f for s, f in seen if s == "classify"]
    assert classify_fractions == sorted(classify_fractions)


# --- Capabilities and Reddit -------------------------------------------------

def test_capabilities_report_fallback_without_keys(client):
    caps = client.get("/api/status").json()["capabilities"]
    assert caps["llm"] == "fallback"
    assert caps["llm_providers"] == []
    health = client.get("/api/health").json()
    assert health["llm"] == "fallback"
    assert "reddit_api" in health


def test_capabilities_detect_keys(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert client.get("/api/status").json()["capabilities"]["llm"] == "openai"
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    caps = client.get("/api/status").json()["capabilities"]
    assert caps["llm"] == "gemini"
    assert caps["llm_providers"] == ["gemini", "openai"]


def test_reddit_blocked_returns_actionable_503(client, monkeypatch):
    def blocked(*_a, **_k):
        raise reddit.RedditAccessError("HTTP 403")

    monkeypatch.setattr(main, "fetch_reddit_posts", blocked)
    res = client.post("/api/ingest/reddit", json={"subreddit": "spotify"})
    assert res.status_code == 503
    assert "REDDIT_CLIENT_ID" in res.json()["detail"]


class _FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_reddit_uses_oauth_api_when_configured(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    reddit._token.update(value="", expires_at=0)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("POST", url))
        return _FakeResponse(200, {"access_token": "tok", "expires_in": 3600})

    def fake_get(url, headers=None, **kwargs):
        calls.append(("GET", url, headers.get("Authorization")))
        post = {"data": {"id": "abc", "title": "App keeps crashing after update", "selftext": "",
                         "created_utc": 1700000000, "author": "u1", "ups": 3}}
        return _FakeResponse(200, {"data": {"children": [post], "after": None}})

    monkeypatch.setattr(reddit.requests, "post", fake_post)
    monkeypatch.setattr(reddit.requests, "get", fake_get)

    items = reddit.fetch_reddit_posts("spotify", count=10)

    assert [i["id"] for i in items] == ["rd_abc"]
    assert calls[0] == ("POST", "https://www.reddit.com/api/v1/access_token")
    assert calls[1] == ("GET", "https://oauth.reddit.com/r/spotify/new", "Bearer tok")


def test_reddit_403_raises_access_error(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.setattr(reddit.requests, "get", lambda *a, **k: _FakeResponse(403, {"message": "Blocked"}))
    with pytest.raises(reddit.RedditAccessError):
        reddit.fetch_reddit_posts("spotify", count=10)


def test_reddit_missing_subreddit_returns_empty(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.setattr(reddit.requests, "get", lambda *a, **k: _FakeResponse(404, {}))
    assert reddit.fetch_reddit_posts("doesnotexist12345", count=10) == []
