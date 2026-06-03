# Schema

## source_manifest.csv

| Field | Meaning |
| --- | --- |
| source_id | Stable source ID, such as `SRC-001` |
| source_type | company_announcement、clinical_registry、company_pipeline_page、annual_report、conference_abstract、research_report、news、other |
| source_title | Source title |
| source_path_or_url | Local path or URL |
| publish_date | Source publication date or `待确认` |
| retrieved_at | Date when the source was retrieved or registered |
| source_period | Period covered by the source, such as FY2025、2026Q1、ASCO 2026、待确认 |
| company_name | Related company or `待确认` |
| drug_or_pipeline | Related drug/pipeline or `待确认` |
| target | Related target or `待确认` |
| indication | Related indication or `待确认` |
| source_confidence | 高、中、低、待确认 |
| extract_priority | 高、中、低 |
| fields_to_extract | Semicolon-separated target fields |
| notes | Intake and verification notes |

## company_ir_sources.csv

| Field | Meaning |
| --- | --- |
| company_name | Company |
| ticker | Primary ticker |
| market | A股、港股、美股、跨市场、待确认 |
| ir_home_url | Official investor-relations home page |
| financial_reports_url | Official financial reports page |
| announcements_url | Official announcements/circulars page |
| presentations_url | Official investor presentations page |
| monthly_reports_url | Official monthly/weekly IR updates page, or `待确认` |
| ir_calendar_url | Official IR calendar page, or `待确认` |
| pipeline_url | Official product/pipeline page, or `待确认` |
| global_collaboration_url | Official partnership/global collaboration page, or `待确认` |
| news_center_url | Official news/media center page, or `待确认` |
| company_news_url | Official company-news listing page, or `待确认` |
| media_coverage_url | Official media coverage page, or `待确认` |
| last_crawled_at | Last date these pages were checked |
| crawl_frequency | daily、weekly、monthly、quarterly、event-driven |
| priority | 高、中、低 |
| notes | Search and extraction notes |

## company_master.csv

| Field | Meaning |
| --- | --- |
| company_name | Company name in Chinese or official source language |
| tickers_raw | Raw ticker string from source |
| market | A股、港股、美股、跨市场、待确认 |
| company_type | Big Pharma、转型创新药企、Biotech、18A Biotech、产业链、其他 |
| core_fields_raw | Source-provided core fields |
| modality_tags | Extracted tags such as ADC、双抗、GLP-1、小核酸、CAR-T、TCE |
| disease_area_tags | Extracted disease areas such as 肿瘤、自免、代谢、眼科、神经 |
| priority_reason | Why the company is worth tracking |
| first_seen_date | Date when the company first entered the tracking pool |
| last_checked_at | Date when the company row was last reviewed |
| source | Source file |
| updated_at | Output date |

## pipeline_progress.csv

| Field | Meaning |
| --- | --- |
| company_name | Company |
| drug_or_pipeline | Drug name or R&D code |
| target | Molecular target |
| modality | ADC、双抗、小分子、抗体、细胞治疗、小核酸、融合蛋白等 |
| indication | Disease/indication |
| clinical_stage | 临床前、I期、II期、III期、NDA/BLA、已上市、待确认 |
| latest_progress | Latest sourced progress |
| progress_date | Date/month of the latest progress, such as YYYY-MM-DD、YYYY-MM、待确认 |
| next_catalyst | Future catalyst |
| next_catalyst_date_or_window | Expected date or time window for the next catalyst |
| competitive_landscape | Same-target or same-indication comparison |
| risks | Specific risk notes |
| source | Source file |
| source_confidence | 高、中、低、待确认 |
| last_verified_at | Date when the row was last verified against a source |
| verification_notes | Missing fields or next verification step |
| updated_at | Output date |

## catalyst_tracker.csv

| Field | Meaning |
| --- | --- |
| date_or_window | Primary exact date or expected time window |
| announced_date | Date when the catalyst/event was announced or first reported |
| expected_date_or_window | Expected date/window if the event has not happened |
| actual_date | Actual event date if it has happened |
| company_name | Company |
| drug_or_pipeline | Drug/pipeline |
| catalyst_type | 学术会议、临床数据、BD、NDA/BLA、获批、医保/商保、政策、其他 |
| event_summary | Short event description |
| status | 已发生、未发生、待确认 |
| result | Event result if known |
| expected_impact | Research significance |
| source | Source file |
| updated_at | Output date |

## bd_deal_tracker.csv

| Field | Meaning |
| --- | --- |
| company_name | Licensing company or listed company to track |
| drug_or_pipeline | Drug/pipeline covered by the deal |
| target | Molecular target or `待确认` |
| modality | ADC、双抗、小分子、抗体、细胞治疗、小核酸、融合蛋白等 |
| partner | BD partner or licensee |
| territory | 授权区域, such as 全球、海外、中国区、待确认 |
| deal_type | out-license、in-license、co-development、equity investment、option、commercialization partnership、待确认 |
| announcement_date | Date when the deal was announced |
| signing_date | Date when the agreement was signed, if disclosed |
| effective_date | Date when the deal became effective, if disclosed |
| closing_date | Date when transaction closing occurred, if applicable |
| upfront_payment | Upfront or near-term payment, preserving original currency |
| milestone_value | Total milestone value, preserving original currency |
| equity_or_option_terms | Equity stake, option rights, profit share, royalties, or `待确认` |
| covered_indications | Semicolon-separated indications or `待确认` |
| latest_progress | Sourced deal/progress description |
| latest_update_date | Date/month of latest deal-related update |
| next_milestone | Next deal or asset milestone |
| next_milestone_date_or_window | Expected date/window for next milestone |
| source | Source file, AlphaPai source title, or URL |
| source_confidence | 高、中、低、待确认 |
| last_verified_at | Date when the deal row was last verified against a source |
| verification_notes | Missing fields or next verification step |
| updated_at | Output date |

## verification_queue.csv

| Field | Meaning |
| --- | --- |
| company_name | Company |
| missing_item | Missing or conflicting field/fact |
| suggested_next_source | Next source to check |
| opened_at | Date when the verification item was created |
| target_check_date | Planned check date or review window |
| resolved_at | Date when the item was resolved, or `待确认` |
| source | Source file, AlphaPai source title, or URL that raised the issue |
| updated_at | Output date |
