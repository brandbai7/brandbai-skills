@echo off
setlocal
chcp 65001 >nul
set "ASSISTANT_SCRIPT=%~dp0..\..\scripts\recorder_assistant.py"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B "%ASSISTANT_SCRIPT%" install-windows
) else (
  python -B "%ASSISTANT_SCRIPT%" install-windows
)

if errorlevel 1 (
  echo.
  echo 安装未完成。请确认已安装 Python，然后重新运行本安装程序。
  pause
  exit /b 1
)

echo.
echo 现在可以打开抖音直播间，并从浏览器侧边栏开始录制。
pause
