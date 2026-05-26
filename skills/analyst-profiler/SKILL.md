---
name: analyst-profiler
description: Sell-side analyst profiling and tracking workflow for investment research. Use when Codex needs to structure sell-side research calls, evaluate analyst quality from sourced evidence, distinguish momentum fast-reaction analysts from deep-research analysts, generate analyst scorecards, or maintain a continuous analyst tracking database.
---

# Analyst Profiler

## Purpose

Use this skill to build evidence-based profiles of sell-side analysts. The goal is not to label people subjectively, but to track how useful their research is for investment work.

Core question:

```text
Who reacts quickly?
Who does deep original work?
Who has useful forward-looking calls?
Who is good only in specific sectors or market regimes?
```

## Inputs

Use sourced rows from research reports, morning calls, roadshow notes, rating changes, target-price changes, or manually reviewed notes.

Minimum viable input:

- analyst name
- broker
- sector
- report date
- stock
- call direction / rating action
- thesis type
- event lag
- evidence/depth/originality scores
- post-report stock performance
- source title/path

Read `references/schema.md` for fields.

## Workflow

1. Build `analyst_call_log.csv` from sourced reports and notes.
2. Normalize analyst, broker, sector, stock, date, and call fields.
3. Score each call across:
   - timeliness
   - forward performance
   - evidence quality
   - depth and originality
   - revision discipline
4. Aggregate by analyst, sector, and horizon.
5. Assign profile type:
   - `动量快反型`
   - `深度研究型`
   - `框架驱动型`
   - `均衡型`
   - `跟随型`
   - `样本不足`
6. Write scorecards, profile summary, and a tracking report.
7. Keep verification notes for small samples and missing sources.

## Running The Scorer

If the input is an Alpha Pai exported analyst dataset, convert it first:

```bash
python3 skills/analyst-profiler/scripts/convert_alpha_pai_dataset.py \
  --input /path/to/analyst_call_log_template.csv \
  --output outputs/analyst_profiler/analyst_call_log_converted.csv
```

Then run:

```bash
python3 skills/analyst-profiler/scripts/score_analysts.py \
  --input outputs/analyst_profiler/analyst_call_log_converted.csv \
  --out-dir outputs/analyst_profiler
```

## Quality Rules

- Do not profile an analyst without sourced rows.
- Do not overstate results when sample size is small.
- Keep source titles or paths in the input.
- Separate `事实表现`, `推断画像`, and `待补样本`.
- Use profiles as internal research workflow signals, not public personal judgements.
- Compare analysts within similar sectors and time windows when possible.
