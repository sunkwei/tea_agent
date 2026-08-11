@echo off
rem ============================================
rem  nginx HTTPS Server 停止脚本
rem ============================================
cd /d "%~dp0"
echo 正在停止 nginx ...
nginx -p nginx -s stop
if errorlevel 1 (
    echo [提示] 可能未在运行，或需确认进程。
)
timeout /t 1 >nul
tasklist | findstr /i nginx.exe >nul
if errorlevel 1 (
    echo ✅ nginx 已完全停止。
) else (
    echo [提示] 仍有 nginx 进程: 
    tasklist | findstr /i nginx.exe
)
