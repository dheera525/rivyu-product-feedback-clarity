"""
Rivyu — AI Product Feedback Analyst
FastAPI backend serving ingestion, analysis, and dashboard APIs.
"""

import os
import sys
from contextlib import asynccontextmanager
import secrets
import re
from datetime import datetime, timezone
import uuid
import io
import csv
from urllib.parse import urlencode

import requests

# Ensure project root and pipeline dir are on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(__file__), "pipeline")
for p in [PROJECT_ROOT, PIPELINE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend.store import (
    get_store, append_raw_items, set_raw_items, set_pipeline_results,
    get_dashboard_data, get_theme_by_id, add_source, clear_store, save_to_disk, load_from_disk
)
from backend.ingest.playstore import fetch_playstore_reviews
from backend.ingest.reddit import fetch_reddit_posts
from backend.ingest.csv_upload import parse_csv_feedback
from backend.ingest.x_posts import fetch_x_posts
from backend.ingest.youtube_comments import fetch_youtube_comments
from backend.ingest.gmail import fetch_gmail_messages, fetch_gmail_messages_oauth
from backend.demo_data import get_demo_items

# Import existing pipeline (these use intra-pipeline imports like "from classify import ...")
from run_pipeline import run_pipeline
from ask_rivyu import ask_rivyu


# --- Auth ---

USERS = {
    "admin": "rivyu2026",
    "demo": "demo123"
}

# Active sessions: token -> username
_sessions = {}

# Google OAuth state store (ephemeral).
_google_oauth_states = {}  # state -> {"session_token": "...", "created_ts": float}
_google_tokens = {}  # session_token -> {"access_token","refresh_token","expires_at","email"}
GOOGLE_STATE_TTL_SEC = 15 * 60


def verify_session(session_token: str = Cookie(None)):
    """Dependency: require valid session cookie for protected routes."""
    if not session_token or session_token not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")
    return _sessions[session_token]


def _ensure_session_token(request: Request):
    """Ensure we have a session token for OAuth linking (guest allowed)."""
    session_token = request.cookies.get("session_token")
    if session_token and session_token in _sessions:
        return session_token, False

    session_token = secrets.token_hex(24)
    _sessions[session_token] = "guest"
    return session_token, True


def _google_client_credentials():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    return client_id, client_secret


def _google_redirect_uri(request: Request):
    env_redirect = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if env_redirect:
        return env_redirect
    return str(request.url_for("google_oauth_callback"))


def _cleanup_google_states():
    now_ts = datetime.now(timezone.utc).timestamp()
    expired = [
        k for k, v in _google_oauth_states.items()
        if now_ts - float(v.get("created_ts", 0)) > GOOGLE_STATE_TTL_SEC
    ]
    for key in expired:
        _google_oauth_states.pop(key, None)


def _get_valid_google_access_token(session_token: str):
    if not session_token:
        return ""

    token_info = _google_tokens.get(session_token)
    if not token_info:
        return ""

    now_ts = datetime.now(timezone.utc).timestamp()
    access_token = token_info.get("access_token", "")
    expires_at = float(token_info.get("expires_at", 0) or 0)
    if access_token and expires_at - now_ts > 60:
        return access_token

    refresh_token = token_info.get("refresh_token", "")
    client_id, client_secret = _google_client_credentials()
    if not refresh_token or not client_id or not client_secret:
        return access_token if expires_at > now_ts else ""

    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            },
            timeout=20
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return ""

        new_access_token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 3600) or 3600)
        if not new_access_token:
            return ""

        token_info["access_token"] = new_access_token
        token_info["expires_at"] = now_ts + max(120, expires_in - 30)
        return new_access_token
    except Exception:
        return ""


def _normalize_bucket_key(raw_bucket: str):
    bucket = (raw_bucket or "").strip().lower()
    if not bucket:
        return ""
    bucket = re.sub(r"[^a-z0-9_-]+", "-", bucket)
    bucket = re.sub(r"-{2,}", "-", bucket).strip("-_")
    return bucket[:64]


def _build_plus_alias(email_addr: str, bucket_key: str):
    email_addr = (email_addr or "").strip()
    bucket_key = _normalize_bucket_key(bucket_key)
    if not email_addr or "@" not in email_addr or not bucket_key:
        return ""
    local, domain = email_addr.split("@", 1)
    local = local.split("+", 1)[0]
    return f"{local}+{bucket_key}@{domain}"


def _merge_gmail_query(forward_alias: str, extra_query: str):
    alias = (forward_alias or "").strip()
    query = (extra_query or "").strip()
    if alias and query:
        return f"to:{alias} ({query})"
    if alias:
        return f"to:{alias}"
    return query


# --- Pydantic models ---

class LoginRequest(BaseModel):
    username: str
    password: str

class PlayStoreRequest(BaseModel):
    app_id: str
    count: int = 100

class RedditRequest(BaseModel):
    subreddit: str
    query: str = ""
    count: int = 50

class XRequest(BaseModel):
    username: str = ""
    query: str = ""
    count: int = 80
    bearer_token: str = ""

class XMentionsRequest(BaseModel):
    company_name: str
    handle: str = ""
    count: int = 80
    bearer_token: str = ""

class YouTubeRequest(BaseModel):
    video_id: str
    count: int = 80
    api_key: str = ""

class GmailRequest(BaseModel):
    email: str = ""
    app_password: str = ""
    company_bucket: str = ""
    forward_alias: str = ""
    query: str = ""
    folder: str = "INBOX"
    count: int = 80

class AskRequest(BaseModel):
    question: str

class AnalyzeRequest(BaseModel):
    use_demo: bool = False

# Runtime caps (raised for realistic demos while keeping latency bounded).
MAX_PLAYSTORE_COUNT = 300
MAX_REDDIT_COUNT = 300
MAX_X_COUNT = 300
MAX_YOUTUBE_COUNT = 300
MAX_GMAIL_COUNT = 300
MAX_ANALYZE_ITEMS = 220


# --- App setup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Rivyu backend starting...")
    restored = load_from_disk()
    if restored:
        print("💾 Restored store from disk")
    yield
    print("👋 Rivyu backend shutting down")

app = FastAPI(title="Rivyu", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auth endpoints ---

@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    if req.username not in USERS or USERS[req.username] != req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_hex(24)
    _sessions[token] = req.username
    response.set_cookie(key="session_token", value=token, httponly=True, samesite="lax", max_age=86400)
    return {"status": "ok", "username": req.username}


@app.post("/api/logout")
async def logout(response: Response, session_token: str = Cookie(None)):
    if session_token and session_token in _sessions:
        del _sessions[session_token]
    if session_token and session_token in _google_tokens:
        del _google_tokens[session_token]
    response.delete_cookie("session_token")
    return {"status": "ok"}


@app.get("/api/me")
async def me(user: str = Depends(verify_session)):
    return {"username": user}


@app.get("/api/auth/google/start")
async def google_oauth_start(request: Request):
    client_id, client_secret = _google_client_credentials()
    if not client_id or not client_secret:
        return RedirectResponse(url="/?gmail_oauth=error_config", status_code=302)

    _cleanup_google_states()
    session_token, created_new = _ensure_session_token(request)
    state = secrets.token_urlsafe(24)
    _google_oauth_states[state] = {
        "session_token": session_token,
        "created_ts": datetime.now(timezone.utc).timestamp()
    }

    redirect_uri = _google_redirect_uri(request)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join([
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/userinfo.email"
        ]),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    resp = RedirectResponse(url=url, status_code=302)
    if created_new:
        resp.set_cookie(key="session_token", value=session_token, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/api/auth/google/callback")
async def google_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

    _cleanup_google_states()
    state_info = _google_oauth_states.pop(state, None)
    if not state_info or not code:
        return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

    session_token = state_info.get("session_token", "")
    if not session_token:
        return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

    client_id, client_secret = _google_client_credentials()
    redirect_uri = _google_redirect_uri(request)

    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            },
            timeout=20
        )
        token_data = token_resp.json() if token_resp.content else {}
        if token_resp.status_code >= 400:
            return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = int(token_data.get("expires_in", 3600) or 3600)
        if not access_token:
            return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

        email_addr = ""
        user_resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20
        )
        if user_resp.status_code < 400 and user_resp.content:
            email_addr = (user_resp.json() or {}).get("email", "")

        prev = _google_tokens.get(session_token, {})
        _google_tokens[session_token] = {
            "access_token": access_token,
            "refresh_token": refresh_token or prev.get("refresh_token", ""),
            "expires_at": datetime.now(timezone.utc).timestamp() + max(120, expires_in - 30),
            "email": email_addr or prev.get("email", "")
        }
    except Exception:
        return RedirectResponse(url="/?gmail_oauth=error", status_code=302)

    resp = RedirectResponse(url="/?gmail_oauth=success", status_code=302)
    resp.set_cookie(key="session_token", value=session_token, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.get("/api/auth/google/status")
async def google_oauth_status(request: Request):
    session_token = request.cookies.get("session_token")
    token_info = _google_tokens.get(session_token or "", {})
    if not token_info:
        return {"connected": False}
    return {
        "connected": bool(_get_valid_google_access_token(session_token or "")),
        "email": token_info.get("email", "")
    }


@app.post("/api/auth/google/disconnect")
async def google_oauth_disconnect(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        return {"status": "ok", "connected": False}

    token_info = _google_tokens.pop(session_token, None)
    if token_info and token_info.get("access_token"):
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token_info.get("access_token", "")},
                timeout=15
            )
        except Exception:
            pass
    return {"status": "ok", "connected": False}


# --- Ingestion endpoints (protected) ---

@app.post("/api/ingest/playstore")
async def ingest_playstore(req: PlayStoreRequest):
    safe_count = max(10, min(req.count, MAX_PLAYSTORE_COUNT))
    items = fetch_playstore_reviews(req.app_id, count=safe_count)
    if not items:
        raise HTTPException(status_code=400, detail="No reviews fetched. Check the app ID.")
    append_raw_items(items)
    add_source({"type": "google_play", "id": req.app_id, "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "google_play", "total_raw": len(get_store()["raw_items"])}


@app.post("/api/ingest/reddit")
async def ingest_reddit(req: RedditRequest):
    safe_count = max(10, min(req.count, MAX_REDDIT_COUNT))
    items = fetch_reddit_posts(req.subreddit, query=req.query, count=safe_count)
    if not items:
        raise HTTPException(status_code=400, detail="No posts fetched. Check the subreddit name.")
    append_raw_items(items)
    add_source({"type": "reddit", "id": f"r/{req.subreddit}", "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "reddit", "total_raw": len(get_store()["raw_items"])}


@app.post("/api/ingest/x")
async def ingest_x(req: XRequest):
    if not (req.username or req.query):
        raise HTTPException(status_code=400, detail="Provide username or query for X ingestion.")

    safe_count = max(10, min(req.count, MAX_X_COUNT))
    items = fetch_x_posts(
        username=req.username,
        query=req.query,
        count=safe_count,
        bearer_token=req.bearer_token
    )
    if not items:
        raise HTTPException(
            status_code=400,
            detail="No X posts fetched. Check username/query and X bearer token."
        )

    source_id = f"@{req.username.lstrip('@')}" if req.username else req.query[:60]
    append_raw_items(items)
    add_source({"type": "x", "id": source_id, "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "x", "total_raw": len(get_store()["raw_items"])}


@app.post("/api/ingest/x/mentions")
async def ingest_x_mentions(req: XMentionsRequest):
    company_name = (req.company_name or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required.")

    safe_count = max(10, min(req.count, MAX_X_COUNT))
    handle = (req.handle or "").strip().lstrip("@")
    parts = [f"\"{company_name}\""]
    if handle:
        parts.append(f"@{handle}")
    query = " OR ".join(parts) + " -is:retweet"

    items = fetch_x_posts(
        query=query,
        count=safe_count,
        bearer_token=req.bearer_token
    )
    if not items:
        raise HTTPException(
            status_code=400,
            detail="No X mentions found. Check company name/handle and X bearer token."
        )

    append_raw_items(items)
    source_id = f"{company_name}{' @' + handle if handle else ''}"
    add_source({"type": "x", "id": source_id, "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "x", "total_raw": len(get_store()["raw_items"])}


@app.post("/api/ingest/youtube")
async def ingest_youtube(req: YouTubeRequest):
    safe_count = max(10, min(req.count, MAX_YOUTUBE_COUNT))
    items = fetch_youtube_comments(req.video_id, count=safe_count, api_key=req.api_key)
    if not items:
        raise HTTPException(
            status_code=400,
            detail="No YouTube comments fetched. Check video ID/URL and API key."
        )

    detected_video_id = (
        items[0].get("metadata", {}).get("video_id", "") if items else ""
    ) or req.video_id

    append_raw_items(items)
    add_source({"type": "youtube_comments", "id": detected_video_id, "count": len(items)})
    save_to_disk()
    return {
        "status": "ok",
        "count": len(items),
        "source": "youtube_comments",
        "total_raw": len(get_store()["raw_items"])
    }


@app.post("/api/ingest/gmail")
async def ingest_gmail(req: GmailRequest, request: Request):
    safe_count = max(10, min(req.count, MAX_GMAIL_COUNT))
    session_token = request.cookies.get("session_token")
    oauth_access_token = _get_valid_google_access_token(session_token or "")

    intake_email = (req.email or os.getenv("GMAIL_INTAKE_EMAIL", "")).strip()
    intake_password = (req.app_password or os.getenv("GMAIL_APP_PASSWORD", "")).strip()
    bucket_key = _normalize_bucket_key(req.company_bucket)
    connected_email = (_google_tokens.get(session_token or "", {}) or {}).get("email", "")
    source_email = connected_email or intake_email
    forward_alias = (req.forward_alias or "").strip() or _build_plus_alias(source_email, bucket_key)
    if bucket_key and not forward_alias:
        raise HTTPException(
            status_code=400,
            detail="Bucket mode needs an intake email (or explicit forward_alias) to build to:alias filter."
        )
    effective_query = _merge_gmail_query(forward_alias if bucket_key or req.forward_alias else "", req.query)

    source_id = ""
    if oauth_access_token:
        items = fetch_gmail_messages_oauth(
            access_token=oauth_access_token,
            query=effective_query,
            folder=req.folder,
            count=safe_count
        )
        source_id = connected_email or "gmail_oauth"
    elif intake_email and intake_password:
        # Backward-compatible fallback for local testing.
        items = fetch_gmail_messages(
            email_address=intake_email,
            app_password=intake_password,
            query=effective_query,
            folder=req.folder,
            count=safe_count
        )
        source_id = intake_email
    else:
        raise HTTPException(
            status_code=400,
            detail="Connect Gmail via OAuth, or provide intake email + app_password (or set GMAIL_INTAKE_EMAIL/GMAIL_APP_PASSWORD)."
        )

    if not items:
        raise HTTPException(
            status_code=400,
            detail="No Gmail messages fetched. Check mailbox permissions, bucket alias, query, folder, and token validity."
        )

    source_label = source_id or "gmail"
    if bucket_key:
        source_label = f"{source_label}::{bucket_key}"

    append_raw_items(items)
    add_source({"type": "gmail", "id": source_label, "count": len(items)})
    save_to_disk()
    return {
        "status": "ok",
        "count": len(items),
        "source": "gmail",
        "bucket_id": bucket_key,
        "forward_alias": forward_alias,
        "query_used": effective_query,
        "total_raw": len(get_store()["raw_items"])
    }


@app.post("/api/ingest/csv")
async def ingest_csv(file: UploadFile = File(...)):
    content = await file.read()
    items = parse_csv_feedback(content)
    if not items:
        raise HTTPException(status_code=400, detail="No feedback found in CSV. Needs a 'text' column.")
    append_raw_items(items)
    add_source({"type": "csv", "id": file.filename or "upload.csv", "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "csv", "total_raw": len(get_store()["raw_items"])}


@app.post("/api/ingest/demo")
async def ingest_demo():
    items = get_demo_items()
    clear_store()
    set_raw_items(items)
    add_source({"type": "demo", "id": "demo_dataset", "count": len(items)})
    save_to_disk()
    return {"status": "ok", "count": len(items), "source": "demo"}


# --- Analysis endpoint ---

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest = AnalyzeRequest()):
    store = get_store()

    if req.use_demo or not store["raw_items"]:
        print("📦 Loading demo data for analysis...")
        items = get_demo_items()
        clear_store()
        set_raw_items(items)
        add_source({"type": "demo", "id": "demo_dataset", "count": len(items)})
        store = get_store()

    raw_items = store["raw_items"]
    if not raw_items:
        raise HTTPException(status_code=400, detail="No feedback data available. Ingest data first.")

    analysis_input = raw_items[:MAX_ANALYZE_ITEMS]

    print(f"🔬 Running analysis on {len(analysis_input)} items...")
    results = run_pipeline(analysis_input)
    results["run_meta"] = {
        "analysis_id": f"run_{uuid.uuid4().hex[:10]}",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "demo" if req.use_demo else "live"
    }
    set_pipeline_results(results)
    save_to_disk()

    return {
        "status": "ok",
        "stats": results["stats"],
        "alert_count": len(results["alerts"]),
        "theme_count": len(results["themes"]),
        "analyzed_count": len(analysis_input),
        "ingested_count": len(raw_items)
    }


# --- Dashboard endpoint ---

@app.get("/api/dashboard")
async def dashboard(time_filter: str = "all"):
    data = get_dashboard_data(time_filter=time_filter)
    if not data.get("has_results"):
        raise HTTPException(status_code=404, detail="No analysis results yet. Run /api/analyze first.")
    return JSONResponse(content=data, headers={"Cache-Control": "no-store"})


# --- Ask Rivyu ---

@app.post("/api/ask")
async def ask(req: AskRequest):
    store = get_store()
    if not store["processed_items"]:
        if store["raw_items"]:
            # Auto-analyze if raw items exist so Ask works in demo and live flows.
            analysis_input = store["raw_items"][:MAX_ANALYZE_ITEMS]
            auto_results = run_pipeline(analysis_input)
            auto_results["run_meta"] = {
                "analysis_id": f"run_{uuid.uuid4().hex[:10]}",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "mode": "auto_for_ask"
            }
            set_pipeline_results(auto_results)
            save_to_disk()
            store = get_store()
        else:
            # Demo-safe behavior: if user lands on Ask first, auto-bootstrap with demo data.
            print("📦 No data loaded for Ask. Auto-loading demo dataset...")
            demo_items = get_demo_items()
            clear_store()
            set_raw_items(demo_items)
            add_source({"type": "demo", "id": "demo_dataset", "count": len(demo_items)})

            analysis_input = demo_items[:MAX_ANALYZE_ITEMS]
            auto_results = run_pipeline(analysis_input)
            auto_results["run_meta"] = {
                "analysis_id": f"run_{uuid.uuid4().hex[:10]}",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "mode": "auto_demo_for_ask"
            }
            set_pipeline_results(auto_results)
            save_to_disk()
            store = get_store()

    answer = ask_rivyu(
        question=req.question,
        themes=store["themes"],
        alerts=store["alerts"],
        processed_items=store["processed_items"]
    )
    return {"question": req.question, "answer": answer}


# --- Theme detail ---

@app.get("/api/theme/{theme_id}")
async def theme_detail(theme_id: str):
    theme = get_theme_by_id(theme_id)
    if not theme:
        raise HTTPException(status_code=404, detail=f"Theme '{theme_id}' not found.")
    return theme


# --- Store status ---

@app.get("/api/status")
async def status():
    store = get_store()
    return JSONResponse(content={
        "raw_count": len(store["raw_items"]),
        "processed_count": len(store["processed_items"]),
        "theme_count": len(store["themes"]),
        "alert_count": len(store["alerts"]),
        "sources": store["sources_connected"],
        "has_results": bool(store["stats"])
    }, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/reset")
async def reset():
    clear_store()
    save_to_disk()
    return {"status": "ok", "message": "Store cleared"}


@app.get("/api/export/complaints.csv")
async def export_complaints():
    store = get_store()
    if not store["processed_items"]:
        raise HTTPException(status_code=400, detail="No analyzed data available to export.")

    complaints = [
        item for item in store["processed_items"]
        if item.get("sentiment", 0) < 0 or item.get("urgency", 3) >= 4
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "date", "source", "author", "rating", "core_bucket", "risk_tag", "urgency", "sentiment", "summary", "text"]
    )
    writer.writeheader()
    for item in complaints:
        writer.writerow({
            "id": item.get("id", ""),
            "date": item.get("date", ""),
            "source": item.get("source", ""),
            "author": item.get("author", ""),
            "rating": item.get("rating", ""),
            "core_bucket": item.get("core_bucket", "Other"),
            "risk_tag": item.get("risk_tag", "none"),
            "urgency": item.get("urgency", ""),
            "sentiment": item.get("sentiment", ""),
            "summary": item.get("summary", ""),
            "text": item.get("text", "")
        })

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=complaints.csv", "Cache-Control": "no-store"}
    )


# --- Serve frontend ---

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Rivyu API is running. Frontend not found."}
else:
    @app.get("/")
    async def root():
        return {"message": "Rivyu API is running", "docs": "/docs"}
