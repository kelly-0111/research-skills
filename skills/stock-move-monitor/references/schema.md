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
| `latest_kline_date` | Latest available K-line date |
| `kline_status` | `ok` or `failed` |
| `data_quality` | Whether quote/K-line-derived fields are complete |
| `is_abnormal` | `是` when any abnormal signal triggers |
| `abnormal_type` | Semicolon-separated signal labels |
| `confidence` | Simple heuristic confidence: `高`, `中`, or `低` |
| `reason_hint` | Verification lead, not a confirmed cause |
| `next_action` | Analyst follow-up items |

## Cause Check Table

Default file: `outputs/cause_check_YYYY-MM-DD.csv`

| Column | Meaning |
|---|---|
| `date` | Run date |
| `code` | Stock code |
| `name` | Security name |
| `industry` | Sector label |
| `theme` | Watchlist theme |
| `abnormal_type` | Triggered abnormal signals |
| `pct_chg` | Percent change |
| `amount_ratio` | Current amount / trailing 20-day average |
| `cause_categories` | Candidate cause tags |
| `source_priority` | Source-check order |
| `search_queries` | Generated search queries for news/announcement retrieval |
| `news_search_query` | Query used by automatic news RSS search |
| `matched_news_count` | Number of matched news items |
| `evidence_status` | `待检索`, `已检索`, or `未发现明确来源` |
| `cause_judgement` | `已确认原因`, `高相关线索`, `待核验线索`, or `无明显新闻` |
| `confidence` | Cause confidence after source review |
| `evidence_summary` | Short summary of matched source titles |
| `source_title` | Supporting source title |
| `source_url_or_path` | URL or local path |
| `published_at` | Source publish date/time |
| `notes` | Verification notes |

## Report Standard

The Markdown brief should include:

1. Run metadata: generated time, stock count, abnormal count, data source, disclaimer.
2. Today's key abnormal moves table.
3. Individual stock notes for the top abnormal rows.
4. Abnormal-move cause-check table.
5. Tomorrow's follow-up checklist.

## Dependency Standard

The base monitor should require only Python standard-library modules. Optional providers such as `adata` can be documented or added later, but CSV/report generation must still work without them.
