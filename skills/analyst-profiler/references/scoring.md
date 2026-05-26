# Scoring Rules

## Dimensions

| Dimension | What it measures |
| --- | --- |
| Forward performance | Whether calls outperform sector/benchmark after publication |
| Hit rate | Direction-aware correctness: bullish calls should outperform, bearish calls should underperform, neutral calls should stay near benchmark |
| Timeliness | Whether the analyst reacts before or soon after catalysts |
| Depth | Modeling quality, company detail, industry-chain work, and falsifiable assumptions |
| Evidence | Whether the report cites verifiable data, filings, field research, or channel checks |
| Originality | Whether the view is differentiated rather than consensus-following |

## Profile Types

Use sample-aware labels:

- `动量快反型`: high momentum score, fast event response, useful around catalysts; depth score can be moderate.
- `深度研究型`: high depth/originality/evidence score, useful for framework building and medium-term understanding.
- `框架驱动型`: repeated reports follow a coherent industry/company framework; often strategic rather than event-first.
- `均衡型`: both momentum and depth are above average.
- `跟随型`: weak forward performance and low timeliness/originality; often confirms consensus after the move.
- `样本不足`: fewer than 3 sourced calls.

## Guardrails

- Do not compare analysts across unrelated sectors without caveats.
- Do not infer personal capability from one report.
- Keep manual scores auditable; source files must be available.
- Market returns are noisy. Treat scores as workflow signals, not final truth.
- Score bearish and risk-warning calls directionally; a stock underperforming after a bearish call is a hit.
- Missing `event_lag_days` is allowed; the scorer assigns a neutral-low timeliness score of 40 rather than failing the run.
