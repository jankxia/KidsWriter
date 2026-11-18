@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "DIR=%~dp0"
set "PY="

where python >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
  if exist "%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\fa694f517e5995233c80a9a8db5212c2\python\python.exe" (
    set "PY=%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\fa694f517e5995233c80a9a8db5212c2\python\python.exe"
  )
)

if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\*") do (
    if exist "%%D\python\python.exe" set "PY=%%D\python\python.exe"
  )
)

if not defined PY (
  echo.
  echo 没有找到可用的 Python 3。
  echo 请先安装 Python 3.10 以上版本，安装时勾选 Add Python to PATH，再双击本文件。
  echo.
  pause
  exit /b 1
)

echo 启动童阅写稿器，浏览器会自动打开 http://127.0.0.1:8122
echo 关闭这个窗口即停止服务。
echo.
"%PY%" -X utf8 "%DIR%童阅写稿器.py" --serve
pause
