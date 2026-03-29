# Rivyu Deployment

## Option A: Deploy on Render (recommended quick path)

1. Push this repo to GitHub.
2. In Render, create a new **Web Service** from the repo.
3. Render will detect `render.yaml` and build with Docker.
4. Set env vars in Render dashboard:
   - `GEMINI_API_KEY` (optional if using OpenAI only)
   - `OPENAI_API_KEY` (optional if using Gemini only)
5. Deploy.
6. Verify:
   - `GET /api/health` should return `{"status":"ok"}`
   - Open site root `/`

## Option B: Docker locally / any VM

```bash
docker build -t rivyu .
docker run --rm -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e OPENAI_API_KEY=your_key \
  rivyu
```

Then open: `http://localhost:8000`

## Notes

- App serves both frontend and API from one process.
- Store is file-based (`data/store.json`).
- If your platform filesystem is ephemeral, data resets on container restart.
- Ask Rivyu may return deterministic fallback text if LLM provider quotas are exhausted.

