"""
Per-session data store with JSON file persistence.

Every visitor gets their own session (identified by a cookie, see
backend/main.py). The active session is carried in a context variable, so
callers just use get_store() and friends without passing an id around.
Sessions live in memory (LRU-capped) and are persisted one file per
session under data/sessions/, which are purged after SESSION_TTL_HOURS.
"""

import contextvars
import json
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

DEFAULT_SESSION = "local"
MAX_SESSIONS_IN_MEMORY = 200
SESSION_TTL_HOURS = 48
_SID_RE = re.compile(r"^[a-z0-9]{1,64}$")

_lock = threading.RLock()
_sessions = OrderedDict()  # sid -> store dict
_current_sid = contextvars.ContextVar("rivyu_session", default=DEFAULT_SESSION)


def _empty_store():
    return {
        "raw_items": [],
        "processed_items": [],
        "themes": [],
        "alerts": [],
        "stats": {},
        "sources_connected": [],
        "run_meta": {"analysis_id": "", "analyzed_at": "", "mode": ""},
    }


def is_valid_session_id(sid):
    return bool(sid) and bool(_SID_RE.match(sid))


def current_session_id():
    return _current_sid.get()


def set_session(sid):
    """Make `sid` the active session for this context. Returns a reset token."""
    if not is_valid_session_id(sid):
        raise ValueError("invalid session id")
    return _current_sid.set(sid)


def reset_session(token):
    _current_sid.reset(token)


@contextmanager
def use_session(sid):
    token = set_session(sid)
    try:
        yield
    finally:
        reset_session(token)


def sessions_dir():
    return os.path.join(DATA_DIR, "sessions")


def session_file(sid=None):
    return os.path.join(sessions_dir(), f"{sid or current_session_id()}.json")


def _s():
    """The store dict for the active session (loaded from disk if needed)."""
    sid = current_session_id()
    with _lock:
        store = _sessions.get(sid)
        if store is None:
            store = _read_session_file(sid) or _empty_store()
            _sessions[sid] = store
            while len(_sessions) > MAX_SESSIONS_IN_MEMORY:
                _sessions.popitem(last=False)  # evict least recently used (file stays)
        else:
            _sessions.move_to_end(sid)
        return store


# Evidence rows sent to the dashboard (searched and filtered client-side).
RECENT_ITEMS_LIMIT = 150

RISK_PRIORITY = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "none": 0
}


def _is_mixed_theme(theme):
    label = str(theme.get("label", "") or "").strip().lower()
    category = str(theme.get("category", "") or "").strip().lower()
    core_bucket = str(theme.get("core_bucket", "") or "").strip().lower()
    return (
        category == "other"
        or label.startswith("mixed feedback")
        or core_bucket in {"other", "mixed feedback", "general feedback"}
    )


def _theme_sort_key(theme):
    is_mixed = 1 if _is_mixed_theme(theme) else 0
    is_pattern = 1 if theme.get("parent_theme_id") else 0
    risk = RISK_PRIORITY.get(str(theme.get("risk_tag", "none")).lower(), 0)
    urgency = float(theme.get("avg_urgency", 0) or 0)
    count = int(theme.get("count", 0) or 0)
    return (
        is_mixed,          # mixed/general themes last
        is_pattern,        # primary themes before phrase subthemes
        -risk,             # higher risk first
        -urgency,          # higher urgency first
        -count,            # then mention count
        str(theme.get("label", "") or "").lower()
    )


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_store():
    return _s()


def set_raw_items(items):
    with _lock:
        # Replacing raw input invalidates all derived analysis state.
        _s()["raw_items"] = items
        _s()["processed_items"] = []
        _s()["themes"] = []
        _s()["alerts"] = []
        _s()["stats"] = {}
        _s()["run_meta"] = {"analysis_id": "", "analyzed_at": "", "mode": ""}


def append_raw_items(items):
    with _lock:
        # Merge by id to avoid duplicate ingestion when same source is fetched repeatedly.
        existing_ids = {str(item.get("id", "")) for item in _s()["raw_items"]}
        for item in items:
            item_id = str(item.get("id", ""))
            if item_id and item_id in existing_ids:
                continue
            _s()["raw_items"].append(item)
            if item_id:
                existing_ids.add(item_id)
        # Any raw mutation invalidates derived state.
        _s()["processed_items"] = []
        _s()["themes"] = []
        _s()["alerts"] = []
        _s()["stats"] = {}
        _s()["run_meta"] = {"analysis_id": "", "analyzed_at": "", "mode": ""}


def set_pipeline_results(results):
    """Store results from run_pipeline()."""
    with _lock:
        _s()["processed_items"] = results.get("processed_items", [])
        _s()["themes"] = results.get("themes", [])
        _s()["alerts"] = results.get("alerts", [])
        _s()["stats"] = results.get("stats", {})
        _s()["run_meta"] = results.get("run_meta", _s().get("run_meta", {}))


def _parse_date(date_str):
    """Parse ISO date string to datetime, returns None on failure."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00+00:00", "+00:00"))
    except (ValueError, TypeError):
        return None


def _filter_items_by_time(items, time_filter):
    """Filter items by time window: '24h', '7d', or 'all'."""
    if time_filter == "all" or not time_filter:
        return items

    now = datetime.now(timezone.utc)
    if time_filter == "24h":
        cutoff = now - timedelta(hours=24)
    elif time_filter == "7d":
        cutoff = now - timedelta(days=7)
    else:
        return items

    filtered = []
    for item in items:
        dt = _parse_date(item.get("date", ""))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            filtered.append(item)
    return filtered


def _time_window_counts(items):
    """Return lightweight mention counts for demo readability."""
    now = datetime.now(timezone.utc)
    c24, c7 = 0, 0

    for item in items:
        dt = _parse_date(item.get("date", ""))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        if delta <= timedelta(hours=24):
            c24 += 1
        if delta <= timedelta(days=7):
            c7 += 1

    return {"mentions_24h": c24, "mentions_7d": c7, "mentions_total": len(items)}


def get_dashboard_data(time_filter="all"):
    """Return dashboard-ready data, optionally filtered by time window."""
    processed = _s()["processed_items"]
    filtered = _filter_items_by_time(processed, time_filter)

    themes_summary = []
    theme_map = {}
    for t in _s()["themes"]:
        # Filter theme items by time too
        theme_items = t.get("items", [])
        theme_filtered = _filter_items_by_time(theme_items, time_filter)
        if not theme_filtered and time_filter != "all":
            continue  # Skip themes with no items in this time window

        count = len(theme_filtered) if time_filter != "all" else t.get("count", 0)
        windows = _time_window_counts(theme_items)
        theme_id = t.get("theme_id", "")
        theme_map[theme_id] = t

        themes_summary.append({
            "theme_id": theme_id,
            "label": t.get("label", ""),
            "core_bucket": t.get("core_bucket", "Other"),
            "category": t.get("category", "other"),
            "risk_tag": t.get("risk_tag", "none"),
            "parent_theme_id": t.get("parent_theme_id"),
            "dynamic_bucket": t.get("dynamic_bucket"),
            "phrase": t.get("phrase", ""),
            "count": count,
            "avg_sentiment": t.get("avg_sentiment", 0),
            "avg_urgency": t.get("avg_urgency", 0),
            "trend": t.get("trend", "stable"),
            "trend_pct": t.get("trend_pct", 0),
            "time_buckets": t.get("time_buckets", {}),
            "top_entities": t.get("top_entities", []),
            "window_counts": windows
        })

    # Prioritize actionable themes first; keep mixed/general feedback at the end.
    themes_summary.sort(key=_theme_sort_key)

    source_breakdown = {}
    for item in filtered:
        source = item.get("source", "unknown")
        source_breakdown[source] = source_breakdown.get(source, 0) + 1

    complaint_count = 0
    for item in filtered:
        sentiment = item.get("sentiment", 0)
        urgency = item.get("urgency", 3)
        if sentiment < 0 or urgency >= 4:
            complaint_count += 1

    enriched_alerts = []
    for a in _s()["alerts"]:
        theme = theme_map.get(a.get("theme_id", ""))
        theme_items = theme.get("items", []) if theme else []
        enriched = dict(a)
        enriched["window_counts"] = _time_window_counts(theme_items)
        enriched_alerts.append(enriched)

    return {
        "has_results": bool(_s().get("stats")),
        "stats": {
            **_s().get("stats", {}),
            "filtered_items": len(filtered),
            "time_filter": time_filter,
            "window_counts": _time_window_counts(processed),
            "complaint_count": complaint_count
        },
        "alerts": enriched_alerts,
        "themes": themes_summary,
        "sources_connected": _s()["sources_connected"],
        "recent_items": filtered[:RECENT_ITEMS_LIMIT],
        "run_meta": _s().get("run_meta", {}),
        "source_breakdown": source_breakdown
    }


def get_theme_by_id(theme_id):
    for t in _s()["themes"]:
        if t.get("theme_id") == theme_id:
            return t
    return None


def add_source(source_info):
    with _lock:
        src_type = source_info.get("type")
        src_id = source_info.get("id")
        src_count = int(source_info.get("count", 0) or 0)

        for existing in _s()["sources_connected"]:
            if existing.get("type") == src_type and existing.get("id") == src_id:
                existing["count"] = int(existing.get("count", 0) or 0) + src_count
                return

        _s()["sources_connected"].append(source_info)


def clear_store():
    with _lock:
        _s()["raw_items"] = []
        _s()["processed_items"] = []
        _s()["themes"] = []
        _s()["alerts"] = []
        _s()["stats"] = {}
        _s()["sources_connected"] = []
        _s()["run_meta"] = {"analysis_id": "", "analyzed_at": "", "mode": ""}


def _is_consistent(data):
    """Analysis results are only valid if all derived parts exist together."""
    has_stats = bool(data.get("stats"))
    has_processed = bool(data.get("processed_items"))
    if has_stats != has_processed:
        return False
    if has_processed and not data.get("raw_items"):
        return False
    return True


def _drop_derived(data):
    data["processed_items"] = []
    data["themes"] = []
    data["alerts"] = []
    data["stats"] = {}
    data["run_meta"] = {"analysis_id": "", "analyzed_at": "", "mode": ""}


def session_state():
    """Single source of truth for what the UI should say about the session.

    Returns one of: "empty" (nothing loaded), "ingested" (raw data loaded,
    not analyzed yet), "analyzed" (results available).
    """
    if _s().get("stats") and _s().get("processed_items"):
        return "analyzed"
    if _s().get("raw_items"):
        return "ingested"
    return "empty"


def _read_session_file(sid):
    path = session_file(sid)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("store file is not a JSON object")
    except Exception as e:
        print(f"⚠️  Failed to load session {sid}, starting empty: {e}")
        return None
    store = _empty_store()
    for key in store:
        if key in data:
            store[key] = data[key]
    if not _is_consistent(store):
        print(f"⚠️  Session {sid} had an incomplete analysis; keeping raw items only.")
        _drop_derived(store)
    return store


def save_to_disk():
    """Persist the active session atomically (or delete its file if empty)."""
    path = session_file()
    try:
        os.makedirs(sessions_dir(), exist_ok=True)
        with _lock:
            store = _s()
            if not store["raw_items"] and not store["sources_connected"]:
                if os.path.exists(path):
                    os.remove(path)
                return
            tmp_path = f"{path}.{threading.get_ident()}.tmp"
            with open(tmp_path, "w") as f:
                json.dump(store, f, default=str)
            os.replace(tmp_path, path)
    except OSError as e:
        # Persistence is best-effort; the in-memory store stays authoritative.
        print(f"⚠️  Failed to save session to disk: {e}")


def load_from_disk():
    """Reload the active session from disk. Returns True if a file was loaded."""
    sid = current_session_id()
    store = _read_session_file(sid)
    with _lock:
        _sessions[sid] = store or _empty_store()
    return store is not None


def purge_expired_sessions(max_age_hours=SESSION_TTL_HOURS):
    """Delete session files untouched for longer than max_age_hours."""
    directory = sessions_dir()
    if not os.path.isdir(directory):
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def reset_all_sessions():
    """Forget every in-memory session (used by tests)."""
    with _lock:
        _sessions.clear()
