# Scripts

`scripts/` contains project-level entrypoints: commands you run from this 投研 folder.

Skill-specific reusable scripts live under each skill folder:

```text
skills/stock-move-monitor/scripts/
skills/innovative-drug-research/scripts/
```

Current project entrypoint:

```bash
python3 scripts/run_daily_monitor.py
```

It delegates to `skills/stock-move-monitor/scripts/run_daily_monitor.py` and writes outputs to `outputs/stock_move_monitor/`.
