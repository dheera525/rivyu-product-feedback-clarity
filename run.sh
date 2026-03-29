#!/bin/bash
# Start Rivyu server
cd "$(dirname "$0")"
echo "🚀 Starting Rivyu on http://localhost:8000"
echo "   Open in browser: http://localhost:8000"
echo ""
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
