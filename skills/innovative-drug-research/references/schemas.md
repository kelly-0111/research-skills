# Schema

## source_manifest.csv

| Field | Meaning |
| --- | --- |
| source_id | Stable source ID, such as `SRC-001` |
| source_type | company_announcement、clinical_registry、company_pipeline_page、annual_report、conference_abstract、research_report、news、other |
| source_title | Source title |
| source_path_or_url | Local path or URL |
| publish_date | Source publication date or `待确认` |
| company_name | Related company or `待确认` |
| drug_or_pipeline | Related drug/pipeline or `待确认` |
| target | Related target or `待确认` |
| indication | Related indication or `待确认` |
| source_confidence | 高、中、低、待确认 |
| extract_priority | 高、中、低 |
| fields_to_extract | Semicolon-separated target fields |
| notes | Intake and verification notes |

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
| next_catalyst | Future catalyst |
| competitive_landscape | Same-target or same-indication comparison |
| risks | Specific risk notes |
| source | Source file |
| source_confidence | 高、中、低、待确认 |
| verification_notes | Missing fields or next verification step |
| updated_at | Output date |

## catalyst_tracker.csv

| Field | Meaning |
| --- | --- |
| date_or_window | Exact date or expected time window |
| company_name | Company |
| drug_or_pipeline | Drug/pipeline |
| catalyst_type | 学术会议、临床数据、BD、NDA/BLA、获批、医保/商保、政策、其他 |
| event_summary | Short event description |
| status | 已发生、未发生、待确认 |
| result | Event result if known |
| expected_impact | Research significance |
| source | Source file |
| updated_at | Output date |
