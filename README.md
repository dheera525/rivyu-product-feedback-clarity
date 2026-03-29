# Rivyu

Rivyu is a FastAPI-based feedback analysis application for aggregating user feedback from Google Play, Reddit, CSV uploads, and demo data.  
It classifies items, groups themes, detects trends, generates alerts, and exposes an Ask interface over the current analyzed dataset.

## Tech Stack

- Backend: FastAPI, Uvicorn
- Frontend: Vanilla HTML/CSS/JS (served by FastAPI)
- LLM Providers: Gemini (primary) with OpenAI fallback
- Storage: In-memory store with JSON persistence (`data/store.json`)
- Deployment: Docker, Render

## Core Capabilities

- Multi-source ingestion:
  - Google Play reviews
  - Reddit posts
  - CSV (`text` column)
  - Demo dataset
- Analysis pipeline:
  - Item classification (LLM + heuristic fallback)
  - Theme grouping and dynamic phrase sub-themes
  - Trend detection
  - Priority alert generation
- Dashboard:
  - Summary metrics
  - Time-window counts (`24h`, `7d`, `total`)
  - Source breakdown and evidence
- Ask Rivyu:
  - Uses analyzed context from current run
  - Auto-bootstrap behavior if no processed data is present
  - Deterministic fallback if live model calls fail

## Repository Structure

```text
backend/
  main.py                 # FastAPI app and API routes
  store.py                # In-memory + JSON persistence layer
  ingest/                 # Source connectors (playstore, reddit, csv)
  pipeline/               # classify, grouping, trend, alerts, llm client, ask
frontend/
  index.html
  style.css
  app.js
data/
  store.json              # Generated at runtime
Dockerfile
render.yaml
run.sh
```

## Environment Variables

Copy `.env.example` to `.env` for local development.

Required (at least one recommended in production):

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

Optional:

- `OPENAI_MODEL` (preferred OpenAI model; fallback chain is still applied)
- `PORT` (default: `8000`)

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Application URLs:

- UI: `http://localhost:8000`
- Health: `http://localhost:8000/api/health`
- API docs: `http://localhost:8000/docs`

## Docker Run

```bash
docker build -t rivyu .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY=your_key \
  -e GEMINI_API_KEY=your_key \
  rivyu
```

## API Overview

- `POST /api/ingest/playstore` - ingest Google Play reviews
- `POST /api/ingest/reddit` - ingest Reddit posts
- `POST /api/ingest/csv` - ingest CSV feedback
- `POST /api/ingest/demo` - load demo dataset
- `POST /api/analyze` - run analysis pipeline
- `GET /api/dashboard` - get dashboard payload (`time_filter=all|7d|24h`)
- `POST /api/ask` - ask questions against current analyzed dataset
- `GET /api/theme/{theme_id}` - theme detail
- `GET /api/status` - store and run status
- `POST /api/reset` - clear store
- `GET /api/export/complaints.csv` - export complaint-like items
- `GET /api/health` - liveness check

## Data Persistence Behavior

- Runtime data is stored in:
  - `raw_items`
  - `processed_items`
  - `themes`
  - `alerts`
  - `stats`
  - `sources_connected`
  - `run_meta`
- State is persisted to `data/store.json`.
- Any raw data mutation invalidates derived analysis state.
- On container restarts with ephemeral disks, prior run state may reset.

## Deployment (Render)

This repository includes `render.yaml` configured for Docker deployment.

1. Push repository to GitHub.
2. Create a Render Web Service from the repository.
3. Confirm Docker environment and health check path `/api/health`.
4. Set environment variables in Render:
   - `OPENAI_API_KEY` and/or `GEMINI_API_KEY`
5. Deploy.

Reference: `DEPLOY.md`

## Security Notes

- Do not commit `.env` or API keys.
- Rotate keys if they are exposed.
- Store secrets in provider-managed environment variables (Render Environment panel).
