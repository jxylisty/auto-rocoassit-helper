@echo off
chcp 65001 >nul
echo ========================================
echo Microsoft C++ Build Tools 自动安装
echo ========================================
echo.

echo [步骤 1] 检查是否已安装...
where cl >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo ✅ Visual C++ 编译器已存在
    goto :COMPILE
)

echo [步骤 2] 下载 Build Tools 离线安装器...
set DOWNLOAD_URL=https://aka.ms/vs/17/release/vs_buildtools.exe
set INSTALLER_PATH=%TEMP%\vs_buildtools.exe

echo 正在下载 (%DOWNLOAD_URL%)...
powershell -Command "& {Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%INSTALLER_PATH%'}"

if not exist "%INSTALLER_PATH%" (
    echo ❌ 下载失败
    pause
    exit /b 1
)

echo [步骤 3] 静默安装 (仅 C++ 编译器)...
echo 参数：--add Microsoft.VisualStudio.Workload.VCTools --includeOffline --quiet --wait
"%INSTALLER_PATH%" --add Microsoft.VisualStudio.Workload.VCTools --includeOffline --quiet --wait

if %ERRORLEVEL% == 0 (
    echo ✅ 安装成功
) else if %ERRORLEVEL% == 3010 (
    echo ⚠️  安装成功但需要重启电脑
    set NEED_REBOOT=1
) else (
    echo ❌ 安装失败，错误码：%ERRORLEVEL%
    pause
    exit /b 1
)

:COMPILE
echo.
echo [步骤 4] 开始编译 auth_core.py ...
cd /d "%~dp0.."
python tools/build_cython_auth.py

if %NEED_REBOOT%==1 (
    echo.
    echo ⚠️  提示：安装后需要重启电脑才能生效
    pause
)

echo.
echo 完成！
pause
