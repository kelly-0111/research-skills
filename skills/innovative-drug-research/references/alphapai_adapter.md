# AlphaPai Adapter

Use AlphaPai as the data entrance and this skill as the research workflow layer.

```text
AlphaPai recall/image/agent output
→ source_manifest.csv
→ pipeline_progress.csv
→ catalyst_tracker.csv
→ bd_deal_tracker.csv
→ verification_queue.csv
→ Excel/Markdown deliverables
```

## Installed Skill

The local AlphaPai skill is expected at:

```text
~/.codex/skills/alphapai-research/
```

Configure the API key outside this repository:

```bash
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py config --set-key YOUR_API_KEY
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py hello
```

Do not commit API keys, full private exports, paid research reports, or proprietary roadshow notes.

## Retrieval Pattern

For pipeline structuring, prefer raw retrieval over generated final answers:

```bash
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py recall \
  --query "康诺亚 CM310 CM326 CM512 管线 靶点 适应症 临床阶段 最新进展 BD" \
  --type ann,report,roadShow,social_media,table \
  --start 2025-01-01 \
  --json
```

Use `--no-cutoff` when the downstream task needs full source text for extraction.

## Company Official-Source Pattern

Before broad AlphaPai retrieval, seed company official pages in `company_ir_sources.csv` and include official-page terms in queries:

```bash
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py recall \
  --query "康方生物 官网 投资者关系 财务报告 演示材料 月报 公告 通函 管线 BD 依沃西 卡度尼利" \
  --type ann,report,roadShow,social_media,table \
  --json
```

For official company materials found through AlphaPai, map them to `company_official_ir_page`, `company_announcement`, `annual_report`, `interim_report`, `investor_presentation`, or `ir_monthly_report` in `source_manifest.csv`.

For company news pages, use queries that include the official media/news wording and the relevant drug/event terms:

```bash
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py recall \
  --query "康方生物 公司新闻 EHA AACR ELCC CSCO 依沃西 卡度尼利 临床数据 指南 推荐 官网" \
  --type ann,report,roadShow,social_media,table \
  --json
```

Map official dated news articles to `company_news_article`; use the article date as `publish_date` and the clinical/conference date as `progress_date` or `actual_date` only when separately stated.

## Source-Type Mapping

| AlphaPai type | Local source_type | Default confidence | Use |
| --- | --- | --- | --- |
| `ann` | company_announcement | 高 | approvals, NDA/BLA, material BD, financing, official progress |
| `report` | research_report | 中 | framework, catalysts, competition, forecasts |
| `foreign_report` | research_report | 中 | global comparison and overseas expectations |
| `roadShow` | roadshow_note | 中 | management tone, operating details, Q&A leads |
| `roadShow_ir` | company_roadshow | 中/高 | official management communication |
| `social_media` | news_or_social | 低/中 | hot events and leads to verify |
| `table` | extracted_table | 中 | tabular pipeline, financial, or clinical data |
| `image` | extracted_image | 中 | pipeline charts, mechanism charts, comparison figures |
| `edb` | market_or_industry_data | 中 | time series and industry indicators |

## Image/Table Search

Use AlphaPai image search when a report likely contains a pipeline chart or BD table:

```bash
python ~/.codex/skills/alphapai-research/scripts/alphapai_client.py image \
  --query "康诺亚 管线图 CM310 CM326 CM512 BD" \
  --files-range 3 6 8 9 \
  --topk 20 \
  --json
```

Record returned titles, dates, URLs, and file identifiers in `source_manifest.csv` before extracting fields.

## Agent Use

Use AlphaPai `agent` outputs for quick first-pass context only. Treat them as generated research artifacts, not as final verified clinical facts. If an agent output says a drug is in a specific phase or has a BD deal, create verification rows unless it cites an announcement, company source, clinical registry, or source table.

## Normalization Rules

- Convert every retrieved material into one `source_manifest.csv` row before extraction.
- Preserve original source title/date/type/path or URL.
- Extract dates explicitly. Put AlphaPai/source publication dates into `publish_date`, retrieval date into `retrieved_at`, pipeline event dates into `progress_date`, catalyst dates into `expected_date_or_window` or `actual_date`, and BD dates into `announcement_date`, `signing_date`, `effective_date`, or `latest_update_date`.
- Extract one row per drug-indication pair when enough detail exists.
- Put partner and deal economics in `bd_deal_tracker.csv`; do not bury them only in `latest_progress`.
- Mark unsupported or conflicting rows as `待确认` and add them to `verification_queue.csv`.
