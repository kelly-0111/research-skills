---
name: drug-pipeline-structuring
description: Structure innovative-drug industry materials into a reusable research database. Use when Codex needs to process biotech/pharma company lists, research reports, slides, announcements, or AlphaPai-style outputs and extract company, drug/pipeline, target, modality, indication, clinical stage, latest progress, catalysts, competitive landscape, risks, sources, and update status.
---

# Drug Pipeline Structuring

## Purpose

Use this skill to convert scattered innovative-drug industry materials into structured research tables. The primary output is a pipeline progress database, not a stock-price explanation.

Treat source materials as inputs to verify and structure. Do not invent drug facts. Mark uncertain or source-missing fields as `待确认`.

## Default Outputs

Create three tables:

1. `company_master.csv`: company pool and initial tags.
2. `pipeline_progress.csv`: company-drug-target-indication-stage-progress table.
3. `catalyst_tracker.csv`: expected or historical catalysts such as ASCO/ESMO/AACR, clinical readouts, NDA/BLA, approvals, BD, reimbursement, and policy events.

For schemas and field definitions, read `references/schema.md`.

## Workflow

1. **Define the scope**
   Start with a narrow scope if the user says "all innovative drugs". Reasonable first scopes include:
   - company pool only
   - one modality: ADC, bispecific/multispecific antibody, GLP-1, small nucleic acid, CAR-T/TCE
   - one target family: PD-1/VEGF, CLDN18.2, B7-H3, HER2, BTK
   - 5-10 priority companies

2. **Build the company pool**
   Extract company name, ticker, market, company type, core field, and initial modality tags from source lists or reports.

3. **Extract pipeline facts**
   For each company, extract one row per drug-indication pair when available:
   `公司名称 | 药物/管线 | 靶点 | 技术路线 | 适应症 | 临床阶段 | 最新进展 | 后续催化剂 | 竞争格局 | 风险点 | 信息来源 | 更新时间`.

4. **Separate facts from judgment**
   - Fact: sourced announcements, trial status, approvals, BD terms, meeting abstracts.
   - Judgment: market expectation, competitive interpretation, likely catalysts.
   - Unknown: write `待确认`.

5. **Track catalysts**
   Convert dates and events into a catalyst tracker. Include event type, expected/actual date, company, drug, result, and source.

6. **Create a verification queue**
   Add a `待确认项` or `verification_notes` column for missing targets, indications, clinical stage, and unsupported assumptions.

## Running The Seed Builder

When the input is a Markdown company list, use the bundled script:

```bash
python3 skills/drug-pipeline-structuring/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/skill_test/innovative_drug_structuring
```

The script produces a first-pass company master table, a seed pipeline table for facts explicitly inferable from the list or built-in high-confidence examples, and a verification queue.

## Quality Rules

- Prefer `待确认` over guessing.
- Preserve source file names in every output row.
- Split multi-market tickers into separate `tickers_raw` rather than losing information.
- Split multi-drug or multi-indication information into multiple rows when enough detail exists.
- Keep the pipeline table updateable: include `source`, `source_confidence`, and `updated_at`.
- For facts from market-review slides, mark them as `研究员复盘材料` and verify later with announcements, company websites, clinical trial registries, or databases.
