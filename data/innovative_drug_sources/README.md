# 创新药资料池

把用于更新创新药管线和上涨逻辑的原始资料放在这里。先用文件夹半自动管理，后续如果接 API，也把 API 拉取结果落到同样的结构里。

| 子目录 | 放什么 |
| --- | --- |
| `announcements/` | 上交所、深交所、港交所、公司公告 |
| `company_pipeline_pages/` | 公司官网管线页截图、导出文本、网页摘录 |
| `annual_reports/` | 年报、中报、业绩材料、投资者演示 |
| `clinical_trials/` | ClinicalTrials.gov、CDE/药审中心、登记平台资料 |
| `conference_abstracts/` | ASCO、ESMO、AACR、WCLC 等会议摘要 |
| `research_reports/` | 券商研报、行业复盘、带教材料摘录 |

使用 `templates/innovative_drug_source_manifest_template.csv` 记录每份资料的来源、日期、可信度和要抽取的字段。
