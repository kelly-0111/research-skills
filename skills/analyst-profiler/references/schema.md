# Schema

## analyst_call_log.csv

One row is one sourced analyst call, report, or material update.

| Field | Meaning |
| --- | --- |
| analyst_id | Optional stable ID for grouping; use this when names are anonymized, duplicated, or teams change broker text |
| analyst_name | Analyst name |
| broker | Broker / research house |
| sector | Coverage sector |
| report_date | `YYYY-MM-DD` |
| stock_code | Stock code |
| stock_name | Stock name |
| rating_action | initiate、upgrade、downgrade、maintain、target_up、target_down、positive_comment、negative_comment |
| call_direction | bullish、bearish、neutral |
| thesis_type | momentum、event、earnings_revision、industry_cycle、deep_dive、thematic、policy、valuation |
| event_lag_days | Days between key event and report; lower is faster |
| horizon_days | Evaluation horizon, such as 20 or 60 |
| forward_return_pct | Stock return after report over the horizon |
| benchmark_return_pct | Benchmark/sector return over same horizon |
| excess_return_pct | Stock return minus benchmark return; can be blank and script will calculate |
| forecast_revision_direction | up、down、none、unknown |
| depth_score | 1-5 manual score for modeling, industry chain, company details, and falsifiable assumptions |
| evidence_score | 1-5 manual score for source quality and factual support |
| originality_score | 1-5 manual score for non-consensus insight |
| source_title | Report/source title |
| source_path_or_url | Local path or URL |
| notes | Reviewer notes |

## analyst_scorecard.csv

| Field | Meaning |
| --- | --- |
| analyst_name | Analyst |
| broker | Broker |
| sector | Most common sector |
| call_count | Number of sourced calls |
| avg_excess_return_pct | Average excess return |
| avg_directional_return_pct | Return adjusted for call direction; bearish calls benefit from negative excess return |
| hit_rate | Share of calls that are correct after adjusting for call direction |
| avg_event_lag_days | Average event lag |
| avg_depth_score | Average depth score |
| avg_evidence_score | Average evidence score |
| avg_originality_score | Average originality score |
| momentum_score | 0-100 score for fast reaction and short-horizon usefulness |
| depth_research_score | 0-100 score for research depth |
| overall_score | 0-100 blended score |
| profile_type | 动量快反型、深度研究型、框架驱动型、均衡型、跟随型、样本不足 |
| confidence | 高、中、低 |
| caveat | Sample and data-quality caveat |
