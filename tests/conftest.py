"""Shared pytest setup.

Tests run fully offline: LLM API keys are removed from the environment and
every LLM entry point is patched, so no network calls are made.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(ROOT, "backend", "pipeline")
for path in (ROOT, PIPELINE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

# Strip keys before any module calls load_dotenv(), and stop dotenv from
# re-adding them from a local .env file.
for key in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
    os.environ[key] = ""


class LLMUnavailable(RuntimeError):
    pass


def _no_llm(*_args, **_kwargs):
    raise LLMUnavailable("LLM disabled in tests")


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """Make every LLM call fail fast unless a test overrides it."""
    import classify
    import ask_rivyu
    import llm_client

    monkeypatch.setattr(llm_client, "call_llm", _no_llm)
    monkeypatch.setattr(classify, "call_llm", _no_llm)
    monkeypatch.setattr(ask_rivyu, "call_llm", _no_llm)
    monkeypatch.setattr(classify.time, "sleep", lambda *_: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point persistence at a temp dir and start every test with an empty store."""
    import backend.store as store

    monkeypatch.setattr(store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "STORE_FILE", str(tmp_path / "store.json"))
    store.clear_store()
    yield store
    store.clear_store()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as c:
        yield c


def make_item(item_id, text, date="2026-03-10T10:00:00Z", source="google_play", **extra):
    item = {"id": item_id, "text": text, "date": date, "source": source, "author": "tester"}
    item.update(extra)
    return item


def make_processed(item_id, bucket, sentiment=-0.6, urgency=4, risk_tag="stability_risk",
                   date="2026-03-10T10:00:00Z", source="google_play", text=None):
    """A classified item in the shape classify_items() produces."""
    return {
        "id": item_id,
        "text": text or f"{bucket} feedback {item_id}",
        "author": "tester",
        "date": date,
        "source": source,
        "rating": None,
        "metadata": {},
        "core_bucket": bucket,
        "dynamic_bucket": None,
        "issue_type": "other",
        "risk_tag": risk_tag,
        "category": ["other"],
        "sentiment": sentiment,
        "urgency": urgency,
        "summary": f"{bucket} summary",
        "entities": [],
    }
