@echo off
rem ============================================
rem  nginx HTTPS Server 启动脚本 (port 9443)
rem  用法: 双击运行 或 命令行 start_nginx.cmd
rem ============================================
cd /d "%~dp0"
echo [1/2] 检查配置...
nginx -p nginx -t
if errorlevel 1 (
    echo [错误] 配置测试失败，请检查 nginx\conf\nginx.conf
    pause
    exit /b 1
)
echo [2/2] 启动 nginx (https://localhost:9443) ...
start "nginx-9443" cmd /c "nginx -p nginx"
echo.
echo ✅ 已启动。访问: https://localhost:9443
echo    停止: 运行 stop_nginx.cmd
timeout /t 3 >nul
