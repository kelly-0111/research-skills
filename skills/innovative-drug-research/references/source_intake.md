# Source Intake Module

Use this module before updating pipeline facts or rally logic from new materials.

## Source Folder

Recommended local folder:

```text
data/innovative_drug_sources/
├── announcements/
├── company_pipeline_pages/
├── annual_reports/
├── clinical_trials/
├── conference_abstracts/
└── research_reports/
```

Use `templates/innovative_drug_source_manifest_template.csv` to log every input.

## Source Priority

| Priority | Source type | Use for |
| --- | --- | --- |
| 1 | Company announcements, exchange filings | confirmed events, approvals, BD, financing, material progress |
| 1 | Clinical trial registries | trial phase, indication, enrollment, endpoints, completion window |
| 2 | Company pipeline pages and investor decks | pipeline names, targets, stage, modality, strategic focus |
| 2 | Conference abstracts | clinical data, efficacy/safety signals, readout timing |
| 3 | Research reports and replay decks | competitive framing, catalysts, rally logic, verification leads |
| 3 | News and market commentary | sentiment clues; treat as `待核验线索` |

## Intake Workflow

```text
collect source files/URLs
→ add rows to source_manifest
→ classify source priority and confidence
→ extract pipeline facts into pipeline_progress
→ extract events into catalyst_tracker
→ extract market interpretation into rally review
→ add missing or conflicting items to verification_queue
```

## Confidence Rules

- `高`: directly from company announcement, exchange filing, clinical registry, regulator database, or official conference abstract.
- `中`: company presentation, investor deck, reputable research report, or source that cites official materials.
- `低`: news, market commentary, unsourced summaries, or model-generated lists.
- `待确认`: incomplete source metadata or unclear provenance.

Do not upgrade a research-report opinion to a high-confidence clinical fact unless it is cross-checked against an official source.

## API Candidates

Start without APIs if the source folder is still small. Add APIs only when the same field is repeatedly updated.

Useful public candidates:

- ClinicalTrials.gov API: trial phase, indication, sponsor, endpoints, completion windows.
- NCBI/PubMed E-utilities: publications and abstracts.
- openFDA: FDA drug labels, adverse events, approvals-related data.
- SEC EDGAR APIs: US-listed company filings.
- Exchange/company announcement sources: A/H stock filings and official announcements.
- NMPA/CDE official databases: China approval, acceptance, and clinical trial registration clues.

When an API is added, save its raw pull or normalized export under `data/innovative_drug_sources/` and add it to the manifest.
