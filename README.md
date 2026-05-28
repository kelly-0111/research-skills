# Investment Research Skills Share Package

Author: Kelly S.  
Status: draft / internal testing  
Created: 2026-05-25

这是一个可分享的投研 skills 包，包含三个可复用 skill；其中 `innovative-drug-research` 内含「资料接入」「管线结构化」和「上涨逻辑复盘」三个子模块：

| Skill | 中文名 | 用途 |
| --- | --- | --- |
| `stock-move-monitor` | 股票异动监控 | 根据自选股列表生成每日异动监控 CSV 和 Markdown 日报 |
| `innovative-drug-research` | 创新药投研助手 | 结构化创新药管线，并复盘医药股上涨逻辑、资金轮动、事件催化和风险信号 |
| `analyst-profiler` | 卖方研究员画像 | 结构化卖方研报观点，区分快反型、深度型和持续跟踪价值 |

## 目录

```text
investment_research_skills_share_package/
├── README.md
├── data/
├── examples/
├── apps/
│   └── research_assistant_app/
├── skills/
│   ├── stock-move-monitor/
│   ├── innovative-drug-research/
│   └── analyst-profiler/
├── scripts/
├── templates/
└── examples/
```

## 使用方式

### 本地网页工具

如果不熟悉 GitHub、命令行或 IDE，优先使用本地网页工具：

```bash
cd apps/research_assistant_app
bash 启动.sh
```

Mac 可双击：

```text
apps/research_assistant_app/启动.command
```

Windows 可双击：

```text
apps/research_assistant_app/启动.bat
```

浏览器地址：

```text
http://127.0.0.1:5199
```

网页工具支持上传 Excel/CSV/Markdown，运行后会同时在网页展示结果，并生成可下载文件。

Wind 不是必需项。若需要配置自己的 Wind Key 作为后续增强或兜底数据源，见：

```text
docs/WIND_SETUP.md
```

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

基础版不需要安装任何行情 SDK，默认使用脚本内置的公开行情接口。若本机已经安装 `efinance`，A 股 K 线失败时会自动作为兜底源；`akshare` 因公开接口偶发断连，默认不启用，可通过 `STOCK_MONITOR_ENABLE_AKSHARE=1` 作为深度兜底；`adata` 也可以后续作为本机可选增强，但都不作为 share package 的必装依赖。

示例：

```text
examples/stock_move_monitor/sample_watchlist.csv
examples/stock_move_monitor/sample_daily_report.md
```

### 创新药投研助手

准备 Markdown 公司列表或行业资料，运行：

```bash
python3 skills/innovative-drug-research/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/innovative_drug_research
```

使用 `skills/innovative-drug-research/` 中的三个子模块，既可以登记来源，也可以整理创新药靶点和进展，并分析医药股上涨逻辑：

```text
资料接入：公告/官网管线页/年报/临床登记/会议摘要/研报
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

### 卖方研究员画像

准备研究员观点记录模板：

```text
templates/analyst_call_log_template.csv
```

运行：

```bash
python3 skills/analyst-profiler/scripts/score_analysts.py \
  --input /path/to/analyst_call_log.csv \
  --out-dir outputs/analyst_profiler
```

示例：

```text
examples/analyst_profiler/sample_analyst_call_log.csv
examples/analyst_profiler/analyst_scorecard.csv
examples/analyst_profiler/analyst_profile_report.md
```

## 依赖

基础 workflow 只使用 Python 标准库。可选增强见：

```text
requirements.txt
```

## 测试

```bash
python3 -m unittest discover -s tests
```

## 快速测试命令

```bash
python3 scripts/run_daily_monitor.py \
  --watchlist templates/watchlist_template.csv \
  --output-dir outputs/stock_move_monitor \
  --skip-news-search

python3 skills/innovative-drug-research/scripts/build_pipeline_seed.py \
  --company-list templates/company_list_template.md \
  --out-dir outputs/innovative_drug_research

python3 skills/analyst-profiler/scripts/score_analysts.py \
  --input examples/analyst_profiler/sample_analyst_call_log.csv \
  --out-dir outputs/analyst_profiler
```

## 分享注意

这个包不包含原始研报、PDF、公司内部资料或带教材料。建议只分享 skills、模板和示例分析，不要把版权材料或敏感数据一起上传到 GitHub。

不要把个人 `WIND_API_KEY` 上传到 GitHub 或打包外发。谁配置 Key，谁消耗 Wind 额度。

## Notes

This package is an early draft for internal workflow testing. It is not a finished product.

The outputs are for research workflow prototyping only and do not constitute investment advice, medical advice, or a recommendation to buy or sell any security.

Please avoid uploading proprietary research reports, copyrighted PDFs, internal materials, or paid database exports together with this package.
