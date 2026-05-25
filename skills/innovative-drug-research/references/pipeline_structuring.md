# Pipeline Structuring Module

Use this module to build the innovative-drug factual base.

## Workflow

```text
输入行业资料
→ 识别公司
→ 识别药物/管线
→ 提取靶点
→ 判断技术路线
→ 识别适应症
→ 判断临床阶段
→ 整理最新进展
→ 提取后续催化剂
→ 对比竞争格局
→ 标注风险点
→ 输出结构化表格
→ 形成待确认清单
→ 定期更新
```

## Recommended First Pass

1. Build company pool from lists and reports.
2. Select priority scope by modality, target, or company.
3. Extract pipeline facts from higher-confidence sources.
4. Extract catalysts from research decks and announcements.
5. Create verification queue for missing facts.

## Field Extraction Rules

- One company can have many pipeline rows.
- One drug with multiple indications should be split into multiple rows when data is available.
- Preserve original names and aliases when possible.
- Use `待确认` for missing target, stage, indication, or progress.
- Distinguish company facts from analyst interpretation.

## Suggested First Scope

For broad innovative-drug tasks, do not start with all companies. Pick 5-10 companies or one theme:

- PD-1/VEGF
- ADC
- bispecific/multispecific antibodies
- GLP-1
- BTK
- small nucleic acid drugs

