---
name: stock-move-monitor
description: Build and run an A-share daily stock abnormal-move monitoring workflow for investment research. Use when Codex needs to create or update a watchlist, fetch A-share quotes/K-line data, detect price/volume/fund-flow/streak abnormalities, generate a Markdown daily brief and CSV detail table, or package this workflow as a reusable research assistant skill.
---

# Stock Move Monitor

## Overview

Use this skill to turn an A-share watchlist into a daily abnormal-move research brief. The default workflow uses Eastmoney public quote/K-line endpoints, calculates simple abnormal-move signals, and writes a Markdown report plus CSV detail table.

Treat outputs as research workflow artifacts, not investment advice. Do not state unverified news or causal explanations as facts; label them as leads to verify unless source-backed.

## Quick Start

1. Create or update `data/watchlist.csv` in the current project. Use the schema in `references/schema.md`.
2. Copy or reuse `scripts/run_daily_monitor.py`.
3. Run:

```bash
python3 scripts/run_daily_monitor.py
```

4. Review generated files in `outputs/`:

- `daily_report_YYYY-MM-DD.md`
- `daily_monitor_YYYY-MM-DD.csv`

If network access is blocked or SSL CA verification fails, request permission to access the public market-data endpoint. The bundled script uses an unverified SSL context only for public quote/K-line pulls because some local Python installs lack CA roots.

## Workflow

1. **Define the watchlist**
   Include 10-30 stocks for the first run. Prefer stocks the user can judge. Use `market=1` for SSE and `market=0` for SZSE.

2. **Fetch market data**
   Pull real-time quote fields and daily K-lines. Keep the script's data-source note in the report.

3. **Calculate signals**
   Default signals:
   - absolute daily percent change >= `pct_threshold`
   - amount / trailing 20-trading-day average amount >= `amount_ratio_threshold`
   - 3 or more consecutive up/down days
   - absolute main fund-flow percentage >= 8%

4. **Generate the report**
   Prioritize abnormal rows first. Include table columns for code/name, industry, pct change, amount, amount ratio, main net inflow, abnormal type, and confidence.

5. **Write analyst follow-ups**
   For each abnormal stock, list keywords and tracking points. Phrase suspected causes as "核验线索" unless backed by announcements/news/research citations.

## Customization

- Change thresholds in `data/watchlist.csv` per stock.
- Add stocks by appending rows to the watchlist.
- For industry-relative performance, add a benchmark column and extend the script to fetch index/ETF K-lines.
- For source-backed cause analysis, add a news/announcement retrieval step after abnormal rows are detected.

## Bundled Resources

- `scripts/run_daily_monitor.py`: runnable A-share abnormal-move monitor.
- `references/schema.md`: watchlist and output-field schema.
