@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
pip install -r requirements-local.txt -q
echo Starting API at http://127.0.0.1:8001
echo Health check: http://127.0.0.1:8001/health
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
