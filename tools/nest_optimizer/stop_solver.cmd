@echo off
setlocal
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>nul
)
endlocal
