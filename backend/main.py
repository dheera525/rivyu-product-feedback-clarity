"""
Rivyu — AI Product Feedback Analyst
FastAPI backend serving ingestion, analysis, and dashboard APIs.
"""

import os
import sys
from contextlib import asynccontextmanager
import secrets
from datetime import datetime, timezone
import uuid
import io
import csv

# Ensure project root and pipeline dir are on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(__file__), "pipeline")
for p in [PROJECT_ROOT, PIPELINE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.store import (
    get_store, append_raw_items, set_raw_items, set_pipeline_results,
    get_dashboard_data, get_theme_by_id, add_source, clear_store, save_to_disk, load_from_disk
)
from backend.ingest.playstore import fetch_playstore_reviews
from backend.ingest.reddit import fetch_reddit_posts
from backend.ingest.csv_upload import parse_csv_feedback
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


def verify_session(session_token: str = Cookie(None)):
    """Dependency: require valid session cookie for protected routes."""
    if not session_token or session_token not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")
    return _sessions[session_token]


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

class AskRequest(BaseModel):
    question: str

class AnalyzeRequest(BaseModel):
    use_demo: bool = False

# Runtime caps (raised for realistic demos while keeping latency bounded).
MAX_PLAYSTORE_COUNT = 300
MAX_REDDIT_COUNT = 300
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
    response.delete_cookie("session_token")
    return {"status": "ok"}


@app.get("/api/me")
async def me(user: str = Depends(verify_session)):
    return {"username": user}


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
