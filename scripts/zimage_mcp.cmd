@echo off
REM Z-Image MCP Server 启动器：显式锁定带 torch(cu128)+diffusers+torchao 的解释器
REM 用法: zimage_mcp.cmd            （stdio，由 MCP 客户端拉起）
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
set "ZIMAGE_MODEL_DIR=%USERPROFILE%\models\Z-Image-Turbo"
"%PY%" "%~dp0..\tea_agent\mcp_servers\zimage_server.py" %*
