@echo off
echo ========================================
echo 洛克王国繁育规划器 - 本地服务器
echo ========================================
echo.
echo 正在启动本地HTTP服务器...
echo 服务器将运行在: http://localhost:8000
echo.
echo 请在浏览器中打开以下地址:
echo http://localhost:8000/roco_shiny_breeding_planner.html
echo.
echo 按 Ctrl+C 停止服务器
echo ========================================
echo.

cd /d "%~dp0"
python -m http.server 8000

pause
