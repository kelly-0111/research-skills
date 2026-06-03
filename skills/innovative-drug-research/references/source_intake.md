# Source Intake Module

Use this module before updating pipeline facts or rally logic from new materials.

## Source Folder

Recommended local folder:

```text
data/innovative_drug_sources/
├── announcements/
├── company_pipeline_pages/
├── company_ir_pages/
├── annual_reports/
├── clinical_trials/
├── conference_abstracts/
└── research_reports/
```

Use `templates/innovative_drug_source_manifest_template.csv` to log every input. When AlphaPai API is available, first save or register AlphaPai retrieval results as sources, then extract fields from those registered materials.

Use `templates/company_ir_sources_template.csv` to maintain official investor-relations entry points for each tracked company.

## Source Priority

| Priority | Source type | Use for |
| --- | --- | --- |
| 1 | Company announcements, exchange filings | confirmed events, approvals, BD, financing, material progress |
| 1 | Company official IR pages | official reports, announcements/circulars, presentations, IR monthly reports, calendars |
| 1 | Clinical trial registries | trial phase, indication, enrollment, endpoints, completion window |
| 2 | Company pipeline pages and investor decks | pipeline names, targets, stage, modality, strategic focus |
| 2 | Conference abstracts | clinical data, efficacy/safety signals, readout timing |
| 3 | Research reports and replay decks | competitive framing, catalysts, rally logic, verification leads |
| 3 | News and market commentary | sentiment clues; treat as `待核验线索` |
| 3 | AlphaPai generated agent output | first-pass context; verify facts against underlying sources |

## Intake Workflow

```text
collect source files/URLs, company IR pages, or AlphaPai recall/image outputs
→ add rows to source_manifest
→ classify source priority and confidence
→ extract pipeline facts into pipeline_progress
→ extract events into catalyst_tracker
→ extract BD terms into bd_deal_tracker
→ extract market interpretation into rally review
→ add missing or conflicting items to verification_queue
```

## Confidence Rules

- `高`: directly from company announcement, exchange filing, clinical registry, regulator database, or official conference abstract.
- `中`: company presentation, investor deck, reputable research report, or source that cites official materials.
- `低`: news, market commentary, unsourced summaries, or model-generated lists.
- `待确认`: incomplete source metadata or unclear provenance.

Do not upgrade a research-report opinion to a high-confidence clinical fact unless it is cross-checked against an official source.

## Company IR Search

For every priority company, build an official-source search pack before relying on third-party reports:

1. Investor relations home page
2. Financial reports or annual/interim reports
3. Announcements and circulars
4. Investor presentations
5. IR monthly reports, weekly reports, newsletters, or operation updates if the company publishes them
6. IR calendar
7. Product/pipeline page and global collaboration page
8. News/media center
9. Company-news listing and media-coverage pages

Example for 康方生物:

| Source | URL | Use |
| --- | --- | --- |
| 财务报告 | `https://www.akesobio.com/cn/investor-relations/financial-reports/` | annual/interim reports, pipeline and financial updates |
| 公司新闻 | `https://www.akesobio.com/cn/media/akeso-news/` | dated clinical data releases, conference presentations, guideline recommendations, product progress, collaboration news |
| 演示材料 | company IR presentation page | pipeline progress, strategy, catalysts |
| 投资者关系月报 | company IR monthly report page | frequent operating or event updates |
| 公告与通函 | company IR announcements page | official announcements, circulars, BD/financing/approval events |

For each company IR page, record the page itself in `source_manifest.csv`, then record each downloaded annual report, announcement, presentation, or monthly report as a separate source row with its own `publish_date` and `retrieved_at`.

For news/media pages, each dated article should become a separate source row when it contains pipeline, clinical, conference, guideline, approval, commercial, or BD information. Use the article date as `publish_date`; do not treat the listing-page retrieval date as the event date.

## Time Rules

- `publish_date`: source publication date from AlphaPai or the original material.
- `retrieved_at`: date when this workflow pulled or registered the source.
- `progress_date`: date/month of the pipeline event, approval, NDA, clinical readout, or latest sourced progress.
- `expected_date_or_window`: future event timing such as ASCO 2026、2026H2、2026年内.
- `actual_date`: actual event date when the event has happened.
- BD rows should separately capture `announcement_date`, `signing_date`, `effective_date`, `closing_date`, `latest_update_date`, and `next_milestone_date_or_window` when disclosed.

If the source has a date but the event date is unclear, fill the source date and mark the event date as `待确认`; do not reuse the source date as the event date without evidence.

## AlphaPai API

If `alphapai-research` is installed, use it as the preferred retrieval adapter for paid/private research materials and AlphaPai-native sources:

- `recall`: retrieve underlying source chunks for announcements, reports, roadshows, social media, tables, EDB, and Q&A.
- `image`: find report or announcement charts, tables, and pipeline images.
- `agent`: generate first-pass context such as company one-pagers or investment logic; verify facts before writing final tables.
- `watchlist`: import AlphaPai watchlists when connecting pipeline facts to stock monitoring.

Read `references/alphapai_adapter.md` for command patterns and source-type mapping.

## Other API Candidates

Start without APIs if the source folder is still small. Add APIs only when the same field is repeatedly updated.

Useful public candidates:

- ClinicalTrials.gov API: trial phase, indication, sponsor, endpoints, completion windows.
- NCBI/PubMed E-utilities: publications and abstracts.
- openFDA: FDA drug labels, adverse events, approvals-related data.
- SEC EDGAR APIs: US-listed company filings.
- Exchange/company announcement sources: A/H stock filings and official announcements.
- NMPA/CDE official databases: China approval, acceptance, and clinical trial registration clues.

When an API is added, save its raw pull or normalized export under `data/innovative_drug_sources/` and add it to the manifest.
