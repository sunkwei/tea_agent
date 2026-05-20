@echo off
REM setup_scheduled_task.bat
REM 为 csi300_predictor.py 创建 Windows 计划任务（周一到周五 15:10 执行）
REM 需要以管理员身份运行

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%..\..\venv_work\Scripts\python.exe"
set "PREDICTOR=%SCRIPT_DIR%csi300_predictor.py"
set "TASK_NAME=CSI300_Predictor_Daily"
set "LOG_DIR=%SCRIPT_DIR%logs"

REM 如果 venv 不存在，回退到系统 python
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

REM 创建日志目录
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ========================================
echo   CSI300 Predictor 计划任务安装
echo ========================================
echo.
echo Python: %PYTHON_EXE%
echo 任务名称: %TASK_NAME%
echo 执行时间: 周一到周五 15:10
echo 脚本路径: %PREDICTOR%
echo 日志目录: %LOG_DIR%
echo.

REM 删除旧任务（如果存在）
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM 创建新任务
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "cmd /c \"cd /d %SCRIPT_DIR% && \"%PYTHON_EXE%\" %PREDICTOR% --task >> %LOG_DIR%\task_%%date:~0,4%%%-%%date:~5,2%%%-%%date:~8,2%%%.log 2>&1\"" ^
    /sc weekly ^
    /d MON,TUE,WED,THU,FRI ^
    /st 15:10 ^
    /ru "%USERNAME%" ^
    /f

if %errorlevel% equ 0 (
    echo.
    echo [OK] 计划任务创建成功！
    echo.
    echo 管理命令:
    echo   查看任务:   schtasks /query /tn "%TASK_NAME%" /v
    echo   手动运行:   schtasks /run /tn "%TASK_NAME%"
    echo   删除任务:   schtasks /delete /tn "%TASK_NAME%" /f
    echo   查看日志:   dir %LOG_DIR%
    echo.
    echo 日志文件: %LOG_DIR%\task_YYYY-MM-DD.log
) else (
    echo.
    echo [FAIL] 创建失败！请以管理员身份运行此脚本。
)

pause
