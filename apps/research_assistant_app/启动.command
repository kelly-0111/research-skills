#!/bin/bash
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "未找到 Python 3。请先安装 Python 3.10+，然后再双击启动。" buttons {"好"} default button "好" with icon caution'
  exit 1
fi

python3 app.py
