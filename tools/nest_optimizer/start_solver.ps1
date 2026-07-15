$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m uvicorn tools.nest_optimizer.app:app --host 127.0.0.1 --port 8765
