@echo off
REM Z-Image MCP Server 启动器
REM 依赖（diffusers ZImagePipeline + torchao 量化 + hf_xet）已装入 venv_work，
REM 故优先用它；缺失时依次回退到系统 Python311 / PATH 上的 python。
REM 用法: zimage_mcp.cmd            （stdio，由 MCP 客户端拉起）
setlocal
set "PY=%USERPROFILE%\venv_work\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
set "ZIMAGE_MODEL_DIR=%USERPROFILE%\models\Z-Image-Turbo"
"%PY%" "%~dp0..\tea_agent\mcp_servers\zimage_server.py" %*
