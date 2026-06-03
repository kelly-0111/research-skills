# General Innovative-Drug Pipeline Workflow

This workflow is the general version of the older AlphaPai pipeline-tracker skill and the康诺亚 workbook example supplied during development.

Use it when building or updating innovative-drug company pipeline workbooks for one or many companies. The goal is to produce an updateable research base, not a one-off summary.

## Core Principle

Do not let raw retrieval results directly overwrite final facts. Build the workbook through:

```text
company universe -> source discovery -> project-level retrieval -> evidence scoring
-> entity-level extraction -> conflict audit -> Excel workbook -> verification queue
```

For companies with a known high-quality workbook, use that workbook as an optional canonical baseline. For companies without a baseline, generate a candidate table and mark low-confidence fields for verification.

## 1. Company Input

Accept either:

- selected companies from the built-in company pool
- uploaded company list
- user-specified company names/tickers

Normalize each company to:

- `company_name`
- `ticker`
- `market`
- `company_aliases`
- `company_source_url`

## 2. Source Discovery

For each company, collect source candidates from:

- company official pipeline/product pages
- investor relations pages
- financial reports/annual reports/interim reports
- announcements and circulars
- investor presentations and earnings materials
- company news/media center
- AlphaPai recall: `ann`, `report`, `roadShow`, `roadShow_ir`, `social_media`
- Eastmoney public market data and announcement pages for K-line, turnover, announcement discovery, and financial statement entry points
- clinical trial registries when available
- major medical conferences when relevant

AlphaPai source discovery must not use only one broad query. For each selected company, run a small set of high-value recall queries from `2025-01-01` onward, then deduplicate by source id:

- company aliases + ticker + core pipeline keywords + `创新药 管线 靶点 适应症 研发阶段 最新进展 年报 研报 路演`
- company aliases + ticker + `2025年报 2024年报 年度报告 业绩会 管理层 路演 商业化 销售 医保`
- company aliases + core projects + partners + `BD license-out NewCo 授权 合作 首付款 里程碑`
- company aliases + core projects + `临床数据 读出 NDA BLA IND 催化剂 2026`
- company aliases + core projects + `估值 盈利预测 DCF 目标价 收入 毛利率 销售费用`

For single-company deep dives, run AlphaPai `qa --mode Think` as an analysis layer and save the full output as a separate deep-research attachment. This file can capture platform-style investment logic, financial assumptions, valuation context, and integrated source reasoning. The Excel fact rows still come from recall/source-index-backed evidence.

All recalled AlphaPai items should be written to the source manifest first. Structured pipeline/BD/catalyst rows are then extracted from matching project windows. This prevents useful reports, roadshows, or annual reports from disappearing merely because they do not yet match a specific project extraction rule.

Record all sources in `source_manifest.csv` with:

- `source_id`
- `source_type`
- `source_title`
- `source_path_or_url`
- `publish_date`
- `retrieved_at`
- `company_name`
- `source_confidence`
- `fields_to_extract`
- `notes`

## 3. Project-Level Retrieval

Avoid one broad query such as `company + all pipelines`. It causes cross-project contamination.

Prefer per-project queries:

```text
{company} {project_code} {drug_name} {target} {indications} 研发阶段 最新进展 BD 合作 {current_year}
```

Examples:

```text
康诺亚 CMG901 AZD0901 CLDN18.2 胃癌 三期 BLA 阿斯利康 2026
康诺亚 CM512 TSLP IL-13 CRSwNP II期 Belenos 2026
康方生物 AK112 依沃西 PD-1 VEGF 肺癌 BLA Summit 2026
```

If no project list exists, first retrieve company pipeline tables from official materials and high-quality reports, then use the discovered project codes as the next retrieval keys.

## 4. Evidence Scoring

Classify evidence before updating fields.

| Confidence | Source types | Usage |
| --- | --- | --- |
| 高 | official announcement, annual/interim report, official pipeline page, official IR material, official clinical registry | May update factual fields |
| 中 | broker report, official roadshow/earnings transcript, investor meeting notes | May update when consistent with another medium/high source |
| 低 | social media, news summary, reposted commentary, unsupported article | Leads only; cannot independently update current stage or BD amount |

Field-specific thresholds:

- `clinical_stage`: requires one high-confidence source or two consistent medium-confidence sources.
- `bd_deal_value`: requires official source, annual report, announcement, or explicit high-quality report citation.
- `latest_progress`: may use medium-confidence reports; mark low-confidence if sourced only from social media/news.
- `next_milestone`: may use broker reports or roadshows, but must not overwrite current stage.

## 5. Entity Extraction

Every final row must bind facts to a specific entity chain:

```text
company -> drug/project -> target -> indication -> stage -> source
```

Required row granularity:

- one drug/project × one indication per row
- split multi-indication products into independent rows
- never output vague rows such as `公司有多个创新药管线`

Recommended detail fields:

- `company_name`
- `ticker`
- `market`
- `drug_name`
- `project_code`
- `target`
- `modality`
- `indication`
- `clinical_stage`
- `latest_progress`
- `progress_date`
- `source_type`
- `source_title`
- `source_date`
- `source_confidence`
- `source_note`
- `next_milestone`
- `next_milestone_date_or_window`
- `update_needed`
- `last_verified_at`

## 6. Anti-Contamination Rules

Only extract facts from windows near the project alias, drug name, or target. Do not infer from the whole article.

Rules:

- Stage terms such as `已上市`, `NDA`, `III期` must appear in the same project window.
- BD amounts must appear near both the project and partner, or be explicitly linked in a table.
- If a paragraph mentions multiple assets, split evidence by project window before extraction.
- `预计递交NDA/BLA`, `有望申报上市`, and `计划获批` are next milestones, not current stages.
- If a stage belongs to a competing product, do not assign it to the company project.
- Treat AlphaPai as a usable research retrieval layer, not as raw web noise. AlphaPai `ann`/official IR sources are high confidence; AlphaPai `report`, `roadShow`, and curated social/media recall are medium-confidence leads unless contradicted. Only unsupported automatic summaries or reposted news should be downgraded to low confidence.
- Explicit contamination checks must flag common mistakes, including CM326 rows carrying CM350 descriptions, CM336 multi-indication rows being mislabeled as NDA/BLA, CMG901/AZD0901 future BLA/NDA expectations being treated as current stage, and CM310 indication-level approval status being generalized across all indications.

## 7. Stage Standardization

Use these standard stages:

| Standard stage | Common expressions |
| --- | --- |
| 临床前 | 临床前研究, preclinical |
| IND申报 | 申报临床, IND申请, 临床试验申请 |
| I期 | Phase I, Ia, Ib |
| I/II期 | Phase I/II, I/II |
| II期 | Phase II, IIa, IIb |
| III期 | Phase III, 注册性临床, 关键性临床 |
| NDA/BLA | 上市申请, NDA/BLA申报, 获受理, 审评中 |
| 已上市 | 获批上市, 商业化, 纳入医保 after approval |

For mixed stages:

- If `I/II期` is explicitly stated, keep `I/II期`.
- If a report says `II/III期`, use the lower active stage unless the official source clearly says pivotal/Phase III.
- If a product has different stages by indication, keep separate rows.

## 8. BD Extraction

BD facts must be bound to:

```text
project/drug -> target -> partner -> territory -> deal terms -> source
```

Track separately:

- `partner`
- `territory`
- `deal_type`
- `upfront_payment`
- `milestone_value`
- `equity_or_option_terms`
- `royalty_or_profit_share`
- `covered_indications`
- `announcement_date`
- `latest_update_date`
- `source_confidence`

Column order should place differentiated investment information early:

```text
公司名称, 靶点, 药物/项目编号, 药物类型, 合作方, BD交易金额/结构,
授权区域, 覆盖适应症, 交易类型/关键日期, 最新进展/下一节点,
置信度, 来源/核验
```

For readability, merge detailed term fields into compact cells:

- `BD交易金额/结构`: upfront + milestone + equity/option/royalty/profit-share terms.
- `交易类型/关键日期`: deal type plus announcement/signing/effective/closing dates.
- `最新进展/下一节点`: latest progress plus next milestone and milestone window.
- Deduplicate semicolon-separated covered indications.
- Split BD rows by `project × partner × transaction`. If one automatic extraction contains multiple partners, split the partners into separate rows and mark deal terms as `待按单笔交易核验` until the announcement confirms each partner's amount/territory/rights.

Never guess BD values. If the amount is not clearly linked to the project, leave it blank and add a verification note.

## 9. Workbook Output

Generate `.xlsx`, not CSV, for final deliverables.

Required sheets:

- `汇总`
- `靶点全景总览`
- `靶点-适应症明细`
- `阶段分布统计`
- `BD合作一览`
- `催化剂追踪`
- `待核验清单`
- `附件索引`
- `收入利润假设`
- `行情验证`

When multiple companies are selected, add one company-specific detail sheet per company. When only one company is selected, do not add a duplicate company sheet because it repeats `靶点-适应症明细`.

Sheet definitions:

- `汇总`: project-level summary, one row per company × target × drug/project, including treatment area, indication count, highest stage, latest progress date, BD partner/value, and next milestone window.
- `靶点全景总览`: target-level panoramic view with treatment area, target, drug name, project code, modality, indication count, highest stage, BD partner, and BD value.
- `靶点-适应症明细`: indication-level detail table, one row per drug/project × indication.
- Company-specific sheets: same structure as `靶点-适应症明细`, filtered to one company only.
- `附件索引`: source attachment index, including source type, title, publish date, source ID/link/file path, confidence, original excerpt/report summary, and extracted fields.
- `收入利润假设`: assumption template at least for the main commercial product. It should not be blank: include initial assumption ranges or research placeholders for indication, reimbursement, patient pool, treatable share, penetration, annual treatment cost, peak sales formula, 2026E/2027E/2028E ramp, gross margin, selling expense ratio, profit contribution, and suggested sources.
- `行情验证`: market validation template with date, stock return, turnover/value traded, relative index return, same-day event, judgement, and data status.

Data-source split:

- Use Eastmoney/public quote APIs for market validation: 1/5/20/60 day returns, traded amount, turnover, and event-date market reaction.
- Use Eastmoney announcement pages as discovery entry points for exchange/company announcements, annual reports, and interim reports.
- Use company official IR/news pages and annual/interim reports as primary sources for pipeline stages, commercial progress, BD announcements, and financial disclosures.
- Use AlphaPai to retrieve and summarize announcements, reports, roadshows, and media leads, then register the underlying source in `附件索引`.
- Do not use Eastmoney alone for patient pool, reimbursement price, penetration rate, or indication-level sales assumptions; these require official filings, reimbursement/price data, epidemiology, or broker deep reports.

Progress and event text policy:

- Main sheets should contain concise research summaries, not long copied paragraphs.
- `最新进展` and `最新进展/下一节点` should be reduced to one or two high-signal sentences with date, stage, milestone, BD, approval, enrollment, or data-readout facts.
- In `催化剂追踪`, keep `事件内容` complete enough for direct reading in Excel; do not truncate it merely to fit a short cell.
- Put full source titles, links/source IDs, file paths, and original excerpts in `附件索引`.
- Main-sheet source columns should point readers to `附件索引` instead of repeating full report text.

Detail ordering and grouping:

- Sort `靶点-适应症明细` by `公司名称 -> 靶点 -> 药物/项目编号 -> 适应症`.
- Insert a blank row between groups keyed by `公司名称 + 靶点 + 药物/项目编号`.
- Omit `竞争格局` and `风险点` from the final workbook unless a later workflow has real differentiated, source-backed content for them. Do not keep generic placeholder columns.
- In `催化剂追踪`, apply bold text to the `药物/管线` column and use wrapped text with expanded row heights for long event/date/progress cells so researchers do not need to double-click each cell.

Formatting rules:

- the first two rows of every sheet are merged intro rows:
  - row 1: `{公司名称（ticker）}创新药管线 — {sheet_name}`
  - row 2: only the `汇总` sheet writes `数据更新日期：YYYY-MM-DD | 来源：...`; all other sheets keep row 2 blank.
- freeze header rows
- enable autofilter
- adaptive column widths with caps
- wrap long text
- stage color coding:
  - 已上市: green
  - NDA/BLA: light blue
  - III期: blue
  - II期: yellow
  - I/Ib/Ia/I/II期: orange/peach
  - IND/临床前/研究者发起: gray

## 10. Audit Before Final Output

Run an audit before presenting a workbook as final.

Audit checks:

- project count unexpectedly lower than baseline or source-derived project list
- missing known project codes
- high stage supported only by low-confidence source
- `NDA/BLA` assigned from a future milestone phrase
- BD amount appears without project/partner binding
- duplicate indication rows
- company/product aliases mismatched
- source dates older than the requested freshness window
- empty `source_note` or missing `source_confidence`

If audit fails, still output the workbook if useful, but mark questionable rows:

- `update_needed=是`
- `source_confidence=低`
- `source_note=待核验: ...`

## 11. Markdown Research Report Output

The Markdown report is not a dump of retrieved text. Treat it as a coached research deliverable.

Required structure:

- one-page conclusion: company positioning, key assets, why it matters, and why it is not yet investment-ready
- key watchlist table: company, core assets, target/technology, near-term catalysts, and verification focus
- core asset base: company × drug/project × target × modality × indication × stage × concise progress × confidence × verification flag
- standard BD table: company, project, target, partner, territory, deal terms, covered indications, announcement date, confidence, verification action
- revenue/profit assumption gap: product, indication, reimbursement/commercialization status, patient pool, penetration, annual treatment cost, revenue forecast fields, COGS/expense assumptions
- stock-move logic validation framework: event catalyst, narrative diffusion, performance delivery, fund behavior; include required market data such as 1/5/20/60 day returns, turnover, amount, relative index return, and event timeline
- fact/inference/verification matrix: distinguish confirmed facts, medium-confidence facts, research inference, and verification leads
- prioritized verification queue with owner-style next action and field to update
- cross-project contamination warning for assets appearing across multiple companies or BD/NewCo structures

Writing rules:

- Do not paste AlphaPai/raw retrieval paragraphs into the report body.
- Use one or two concise research sentences for `最新进展`; keep `催化剂追踪.事件内容` sufficiently complete and readable in the cell.
- For AlphaPai leads, write concise research summaries and point to `附件索引`; do not overstate them as untrustworthy. Use `待来源复核` only when the source type is unsupported, automatically summarized, or contradicted.
- Put full source titles, source IDs/links, file paths, and original excerpts in `附件索引`.
- A conclusion must be tagged by type: confirmed fact, medium-confidence fact, inference, or verification lead.

## 12. Baseline And Incremental Update Policy

Baseline is optional, not required.

Use baseline when:

- the company has a prior manually reviewed workbook
- the user provides a trusted old AlphaPai result
- the company is a monthly focus/priority tracking company

Without baseline:

- generate a candidate table
- mark uncertain fields for verification
- do not hide low confidence

With baseline:

- lock core identifiers and known BD terms unless high-confidence evidence updates them
- only update changed fields
- append update notes to `source_note`
- preserve previous verified facts when new retrieval is ambiguous

Fields usually locked by baseline:

- `project_code`
- `drug_name`
- `target`
- `modality`
- `baseline indications`
- `verified clinical_stage`
- `verified BD terms`

Fields usually updated incrementally:

- `latest_progress`
- `progress_date`
- `next_milestone`
- `next_milestone_date_or_window`
- `source_note`
- `last_verified_at`
- `update_needed`

## 12. Output Status

Each row should make its verification status visible:

- `verified`: high-confidence field support exists
- `candidate`: plausible but not fully verified
- `conflict`: sources disagree
- `needs_update`: stale or missing recent progress

Do not present a candidate table as a verified table without disclosing the status.
