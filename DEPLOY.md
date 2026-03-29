# Rivyu Deployment

## Recommended: Render (single service)

### 1) Preflight (local)

```bash
./run.sh
```

Check:
- `http://localhost:8000/api/health` returns `{"status":"ok"}`
- UI loads at `http://localhost:8000`

### 2) Push to GitHub

```bash
git add .
git commit -m "Deploy-ready Rivyu"
git push origin main
```

### 3) Create Render service

1. Render dashboard -> **New** -> **Web Service**.
2. Select your GitHub repo.
3. Render auto-detects `render.yaml` and uses Docker.
4. Confirm health check path: `/api/health`.
5. Deploy.

### 4) Set environment variables in Render

Set at least one working provider key:
- `OPENAI_API_KEY` (recommended)
- `GEMINI_API_KEY` (optional fallback/provider choice)

You can set both for safer failover.

### 5) Verify production

After deploy:
- `https://<your-render-url>/api/health`
- Open `https://<your-render-url>/`
- Run a quick ingest -> analyze -> dashboard -> ask flow

## Docker (local or any VM)

```bash
docker build -t rivyu .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY=your_key \
  -e GEMINI_API_KEY=your_key \
  rivyu
```

## Notes

- Frontend and API are served by one FastAPI process.
- Store is JSON-backed (`data/store.json`).
- On ephemeral filesystems, stored runs reset when container restarts.
- If LLM keys are missing/exhausted, parts of the pipeline gracefully fall back to heuristic behavior.
