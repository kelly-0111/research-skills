#!/usr/bin/env python3
"""Project-level entrypoint for the stock-move-monitor skill script."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPT = ROOT / "skills" / "stock-move-monitor" / "scripts" / "run_daily_monitor.py"


def main() -> None:
    if len(sys.argv) == 1:
        sys.argv.extend(
            [
                "--watchlist",
                str(ROOT / "data" / "watchlist.csv"),
                "--output-dir",
                str(ROOT / "outputs" / "stock_move_monitor"),
            ]
        )
    runpy.run_path(str(SKILL_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
