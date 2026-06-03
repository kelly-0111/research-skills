---
name: innovative-drug-research
description: End-to-end innovative-drug investment research workflow. Use when Codex needs to structure biotech/pharma company and pipeline materials, extract drugs, targets, modalities, indications, clinical stages, latest progress and catalysts, or connect those facts to pharma stock rally logic, event catalysts, fund rotation, sector stage, and risk signals.
---

# Innovative Drug Research

## Purpose

Use this skill as the main workflow for innovative-drug investment research. It has three modules:

1. **Source intake**: collect and classify source materials.
2. **Pipeline structuring**: build the factual base.
3. **Rally logic**: explain stock-price moves using facts, events, sentiment, and liquidity.

Keep these modules connected but distinct:

```text
AlphaPai/API source materials → source manifest → pipeline facts → catalysts/BD/progress → rally logic → risk signals
```

Do not invent drug facts or stock-move causes. Mark uncertain information as `待确认` or `待核验线索`.

## Module Selection

Use **source intake** when the user asks to:

- add more real materials for tracking targeted innovative-drug development
- use AlphaPai, PaiPai, or AlphaPai API as the data entrance for announcements, reports, roadshows, comments, social media, tables, or images
- collect official company investor-relations and news/media pages such as financial reports, announcements and circulars, presentations, IR monthly/weekly reports, calendars, product pages, collaboration pages, news centers, company-news listings, or media coverage
- decide whether to use APIs or manual source folders
- standardize announcements, pipeline pages, annual reports, clinical registries, conference abstracts, or research reports
- create or update a source manifest

Read `references/source_intake.md`, `references/alphapai_adapter.md`, and `references/schemas.md`.

Use **pipeline structuring** when the user asks to:

- 梳理所有创新药靶点和进展
- build a company/pipeline/target database
- extract drug, target, indication, modality, clinical stage, progress, catalyst, competition, or risk fields
- process company lists, research reports, slides, announcements, or AlphaPai-style outputs

Read `references/general_pipeline_workflow.md`, `references/pipeline_structuring.md`, and `references/schemas.md`.

Use `references/general_pipeline_workflow.md` as the controlling workflow when building a reusable Excel workbook, integrating AlphaPai retrieval, auditing data quality, preventing cross-project field contamination, or deciding how to handle companies with or without a baseline workbook.

Use **rally logic** when the user asks to:

- analyze why pharma/innovative-drug stocks rose
- review stock rally logic, market replay, event trading, or sell-the-news risk
- distinguish fundamental catalysts from narrative, liquidity, fund rotation, or sentiment
- identify sector stage and topping/profit-taking signals

Read `references/rally_logic.md`.

Use **both modules** when the user asks to connect drug progress to stock moves:

1. Register source materials in the source manifest.
2. Create or update the pipeline/catalyst facts.
3. Use those facts as inputs for rally-stage and stock-move interpretation.
4. Separate confirmed facts, inference, and verification leads.

## Default Outputs

For pipeline structuring:

- `company_ir_sources.csv`
- `source_manifest.csv`
- `company_master.csv`
- `pipeline_progress.csv`
- `catalyst_tracker.csv`
- `bd_deal_tracker.csv`
- `verification_queue.csv`

For rally logic:

- rally review report
- catalyst map
- representative stock table
- risk/topping signal checklist
- verification checklist

## Running The Seed Builder

When the input is a Markdown company list, run:

```bash
python3 skills/innovative-drug-research/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/innovative_drug_research
```

This creates first-pass company, pipeline seed, catalyst seed, and verification queue tables.

The built-in `PIPELINE_SEEDS` in the script are starter examples only. Treat them as first-pass mapping rows and verification leads, not a complete innovative-drug database or final research conclusion.

When AlphaPai API access is available, use `alphapai-research` for data retrieval and keep this skill responsible for normalization, verification, tracking tables, and final deliverables. Do not store API keys in this repository; configure them in the installed AlphaPai skill or local environment only.

## Quality Rules

- Prefer `待确认` over guessing.
- Keep source names in output rows.
- Keep source confidence and verification status visible.
- Keep event time and maintenance time separate: source publish date, retrieval date, progress date, catalyst window, BD announcement/signing/effective dates, last verified date, and output update date should not be collapsed into one field.
- Do not treat research-deck interpretations as verified clinical facts.
- Split multi-drug or multi-indication rows when enough detail exists.
- Track BD terms separately when available: partner, territory, upfront payment, milestone value, equity/option terms, covered assets, and source confidence.
- For Excel deliverables, follow `general_pipeline_workflow.md`: merge the first two rows as title/source rows, avoid duplicate company tabs for single-company runs, make `汇总` a project-level summary, sort and group `靶点-适应症明细` by company -> target -> drug/project -> indication, use compact core columns for the BD sheet, summarize progress/event cells in the main sheets, and put full sources/original excerpts in `附件索引`.
- For stock-move explanations, label unsupported causes as `待核验线索`.
- Make outputs updateable rather than one-off summaries.
