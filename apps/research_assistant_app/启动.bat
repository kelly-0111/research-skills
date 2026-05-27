@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [错误] 未找到 Python，请先安装 Python 3.10+
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

python app.py
pause
