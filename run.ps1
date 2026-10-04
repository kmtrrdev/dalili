# Dalili 2.0 - development copy. Runs on port 8001 so the original (port 8000) can run at the same time.
Set-Location $PSScriptRoot
.\.venv\Scripts\python -m uvicorn travel_agent.api:app --port 8001 --reload
