@echo off
setlocal
pushd "%~dp0..\.."
set "PYTHON=tools\nest_optimizer\.venv\Scripts\python.exe"
set "SOLVER_UP="
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -Method Get -TimeoutSec 2; if ($r.ok -eq $true) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  set "SOLVER_UP=1"
)
if not defined SOLVER_UP (
  start "Roco Nest Solver" "%PYTHON%" -m uvicorn tools.nest_optimizer.app:app --host 127.0.0.1 --port 8765
  timeout /t 2 /nobreak >nul
)
start "" "docs\roco_shiny_breeding_planner.html"
popd
endlocal
