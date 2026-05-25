# Investment Research Skills Share Package

Author: Kelly S.  
Status: draft / internal testing  
Created: 2026-05-25

这是一个可分享的投研 skills 包，包含两个可复用 workflow：

| Skill | 中文名 | 用途 |
| --- | --- | --- |
| `stock-move-monitor` | 股票异动监控 | 根据自选股列表生成每日异动监控 CSV 和 Markdown 日报 |
| `drug-pipeline-structuring` | 创新药管线结构化 | 将创新药资料整理成公司池、管线进展表、催化剂表和待确认清单 |

## 目录

```text
investment_research_skills_share_package/
├── README.md
├── skills/
│   ├── stock-move-monitor/
│   └── drug-pipeline-structuring/
├── scripts/
├── templates/
└── examples/
```

## 使用方式

### 股票异动监控

准备自选股模板：

```text
templates/watchlist_template.csv
```

运行：

```bash
python3 scripts/run_daily_monitor.py \
  --watchlist templates/watchlist_template.csv \
  --output-dir outputs/stock_move_monitor
```

### 创新药管线结构化

准备 Markdown 公司列表或行业资料，运行：

```bash
python3 skills/drug-pipeline-structuring/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/innovative_drug_structuring
```

## 分享注意

这个包不包含原始研报、PDF、公司内部资料或带教材料。建议只分享 skills、模板和示例分析，不要把版权材料或敏感数据一起上传到 GitHub。

## Notes

This package is an early draft for internal workflow testing. It is not a finished product.

The outputs are for research workflow prototyping only and do not constitute investment advice, medical advice, or a recommendation to buy or sell any security.

Please avoid uploading proprietary research reports, copyrighted PDFs, internal materials, or paid database exports together with this package.
