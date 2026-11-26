@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "DIR=%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo 没有找到可用的 Python 3。
  echo 请先安装 Python 3.10 以上版本，安装时勾选 Add Python to PATH，再双击本文件。
  echo.
  pause
  exit /b 1
)

echo 启动阅答题，浏览器会自动打开 http://127.0.0.1:8122
echo 关闭这个窗口即停止服务。
echo.
python -X utf8 "%DIR%童阅写稿器.py" --serve
pause
