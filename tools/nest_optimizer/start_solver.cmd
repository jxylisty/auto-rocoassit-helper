@echo off
setlocal
pushd "%~dp0..\.."
set "PYTHON=tools\nest_optimizer\.venv\Scripts\python.exe"
"%PYTHON%" -m uvicorn tools.nest_optimizer.app:app --host 127.0.0.1 --port 8765
popd
endlocal
