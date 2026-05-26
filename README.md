# Investment Research Skills Share Package

Author: Kelly S.  
Status: draft / internal testing  
Created: 2026-05-25

这是一个可分享的投研 skills 包，包含两个可复用 skill；其中 `innovative-drug-research` 内含「管线结构化」和「上涨逻辑复盘」两个子模块：

| Skill | 中文名 | 用途 |
| --- | --- | --- |
| `stock-move-monitor` | 股票异动监控 | 根据自选股列表生成每日异动监控 CSV 和 Markdown 日报 |
| `innovative-drug-research` | 创新药投研助手 | 结构化创新药管线，并复盘医药股上涨逻辑、资金轮动、事件催化和风险信号 |

## 目录

```text
investment_research_skills_share_package/
├── README.md
├── data/
├── skills/
│   ├── stock-move-monitor/
│   └── innovative-drug-research/
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

### 创新药投研助手

准备 Markdown 公司列表或行业资料，运行：

```bash
python3 skills/innovative-drug-research/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/innovative_drug_research
```

使用 `skills/innovative-drug-research/` 中的两个子模块，既可以整理创新药靶点和进展，也可以分析医药股上涨逻辑：

```text
管线结构化：公司/药物/靶点/阶段/进展/催化剂
上涨逻辑复盘：事件催化/资金轮动/行情阶段/风险信号
```

如果要持续跟踪靶向创新药发展，先把资料放入：

```text
data/innovative_drug_sources/
```

再用这个模板登记来源、可信度和要抽取的字段：

```text
templates/innovative_drug_source_manifest_template.csv
```

## 分享注意

这个包不包含原始研报、PDF、公司内部资料或带教材料。建议只分享 skills、模板和示例分析，不要把版权材料或敏感数据一起上传到 GitHub。

## Notes

This package is an early draft for internal workflow testing. It is not a finished product.

The outputs are for research workflow prototyping only and do not constitute investment advice, medical advice, or a recommendation to buy or sell any security.

Please avoid uploading proprietary research reports, copyrighted PDFs, internal materials, or paid database exports together with this package.
