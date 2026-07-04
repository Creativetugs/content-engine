#!/usr/bin/env bash
# Start Content Engine API locally (Git Bash on Windows)
cd "$(dirname "$0")"
source venv/Scripts/activate
pip install -r requirements.txt -q
echo "Starting API at http://127.0.0.1:8001"
echo "Health check: http://127.0.0.1:8001/health"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
