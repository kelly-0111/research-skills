# Stock Move Monitor Schema

## Watchlist

Required file: `data/watchlist.csv`

Columns:

| Column | Required | Description |
|---|---|---|
| `code` | yes | Six-digit A-share code, e.g. `600519`, `300750` |
| `name` | yes | Security name |
| `market` | yes | Eastmoney market prefix: `1` for SSE, `0` for SZSE |
| `industry` | yes | Analyst-facing sector label |
| `theme` | yes | Investment theme or factor label |
| `watch_reason` | yes | Why the stock belongs in the research pool |
| `tracking_points` | yes | Semicolon-separated items to watch |
| `keywords` | yes | Semicolon-separated terms for future news/announcement search |
| `pct_threshold` | yes | Absolute daily percent-change threshold, default `5` |
| `amount_ratio_threshold` | yes | Current amount / trailing 20-day average threshold, default `2` |

## Output Detail Table

Default file: `outputs/daily_monitor_YYYY-MM-DD.csv`

Important fields:

| Column | Meaning |
|---|---|
| `price` | Latest quote price |
| `pct_chg` | Latest quote percent change |
| `amount_yi` | Current trading amount in RMB 100m |
| `ma20_amount_yi` | Trailing 20-day average amount in RMB 100m |
| `amount_ratio` | Current amount divided by trailing 20-day average amount |
| `main_net_yi` | Main net inflow in RMB 100m, as reported by data source |
| `main_net_pct` | Main net inflow percentage, as reported by data source |
| `streak` | Positive for consecutive up days, negative for consecutive down days |
| `is_abnormal` | `是` when any abnormal signal triggers |
| `abnormal_type` | Semicolon-separated signal labels |
| `confidence` | Simple heuristic confidence: `高`, `中`, or `低` |
| `reason_hint` | Verification lead, not a confirmed cause |
| `next_action` | Analyst follow-up items |

## Report Standard

The Markdown brief should include:

1. Run metadata: generated time, stock count, abnormal count, data source, disclaimer.
2. Today's key abnormal moves table.
3. Individual stock notes for the top abnormal rows.
4. Tomorrow's follow-up checklist.
