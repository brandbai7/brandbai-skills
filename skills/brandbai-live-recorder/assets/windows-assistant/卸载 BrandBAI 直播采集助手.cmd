@echo off
setlocal
chcp 65001 >nul
set "ASSISTANT_SCRIPT=%~dp0..\..\scripts\recorder_assistant.py"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B "%ASSISTANT_SCRIPT%" uninstall-windows
) else (
  python -B "%ASSISTANT_SCRIPT%" uninstall-windows
)

if errorlevel 1 (
  echo.
  echo 启动入口未能移除，请稍后重试。
  pause
  exit /b 1
)

echo.
echo 已有文件不会被删除。
pause
