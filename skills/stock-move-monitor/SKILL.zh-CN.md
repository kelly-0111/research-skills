---
name: stock-move-monitor
description: 构建并运行 A 股每日股票异动监控投研 workflow。适用于创建或更新自选股池、拉取 A 股实时行情和历史 K 线、检测价格/成交额/资金流/连续涨跌异动、生成 Markdown 每日简报和 CSV 明细表。
---

# 股票异动监控 Skill

## 简介

这个 skill 用来把一份 A 股自选股列表变成每日异动监控简报。默认流程使用东方财富公开行情和 K 线接口，计算简单异动信号，并输出 Markdown 日报和 CSV 明细表。

所有输出都只用于投研 workflow 测试，不构成投资建议。没有来源验证的新闻、传闻或原因判断，不要写成事实；应写成“待核验线索”。

## 快速开始

1. 在当前项目中创建或更新 `data/watchlist.csv`。
2. 使用 `scripts/run_daily_monitor.py` 脚本。
3. 运行：

```bash
python3 scripts/run_daily_monitor.py \
  --watchlist templates/watchlist_template.csv \
  --output-dir outputs/stock_move_monitor
```

4. 查看 `outputs/` 目录下生成的文件：

- `daily_report_YYYY-MM-DD.md`：每日异动监控简报
- `daily_monitor_YYYY-MM-DD.csv`：异动明细表
- `cause_check_YYYY-MM-DD.csv`：异动原因核验队列

如果网络访问被限制，或 Python 本地证书校验失败，需要允许访问公开行情接口。脚本只在访问公开行情/K 线/新闻 RSS 数据时使用非校验证书上下文，这是为了兼容部分本地 Python 缺少 CA 根证书的环境。这个设置只用于公开数据拉取，不应用于登录、私有接口、付费数据库或含 token 的请求。

默认脚本不依赖 `adata`，也不依赖其他第三方行情 SDK。以后如果接入 `adata`，也只能作为可选增强，必须保留当前这个无 SDK 备份路径。调整数据源前先看 `references/data_providers.md`。

## 自选股表格式

默认文件路径：

```text
data/watchlist.csv
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `code` | 是 | 6 位 A 股代码，例如 `600519`、`300750` |
| `name` | 是 | 股票名称 |
| `market` | 是 | 东方财富市场前缀：上交所填 `1`，深交所填 `0` |
| `industry` | 是 | 行业标签 |
| `theme` | 是 | 投资主题或跟踪主题 |
| `watch_reason` | 是 | 为什么把这只股票放进池子 |
| `tracking_points` | 是 | 后续跟踪点，用英文分号或中文分号分隔 |
| `keywords` | 是 | 后续查新闻、公告、研报时用的关键词 |
| `pct_threshold` | 是 | 单日涨跌幅异动阈值，默认可填 `5` |
| `amount_ratio_threshold` | 是 | 当日成交额 / 近 20 日均成交额阈值，默认可填 `2` |

## 当前异动规则

默认检测四类信号：

1. 单日涨跌幅绝对值大于等于 `pct_threshold`
2. 当日成交额 / 近 20 日均成交额大于等于 `amount_ratio_threshold`
3. 连续 3 日或以上上涨/下跌
4. 主力资金占比绝对值大于等于 8%

输出中的 `confidence` 是一个简单启发式判断：

- `高`：价格异动和放量异动同时触发
- `中`：价格异动、放量异动或资金异动至少触发一个
- `低`：主要是连续涨跌等弱信号

## 数据源策略

基础版使用脚本内置的东方财富公开行情/K 线接口，不要求安装 `adata`。这样同事拿到 share package 后，只要本地 Python 可联网，就能先跑起来。

`adata` 可以作为后续可选增强，用于实时行情交叉验证、指数/概念行情和板块联动分析。但不要把它写成必装依赖；如果 `adata` 不可用、返回空表或网络失败，脚本应回退到无 SDK 路径，并在日报里标注数据质量。

## 输出文件

### Markdown 日报

默认路径：

```text
outputs/daily_report_YYYY-MM-DD.md
```

日报包括：

1. 生成时间、股票池数量、触发异动数量、数据源和免责声明
2. 今日重点异动表
3. 个股异动分析
4. 异动原因核验
5. 明日重点关注清单

### CSV 明细表

默认路径：

```text
outputs/daily_monitor_YYYY-MM-DD.csv
```

重点字段：

| 字段 | 说明 |
|---|---|
| `price` | 最新价或最近 K 线收盘价 |
| `pct_chg` | 涨跌幅 |
| `amount_yi` | 成交额，单位：亿元 |
| `ma20_amount_yi` | 近 20 日均成交额，单位：亿元 |
| `amount_ratio` | 当日成交额 / 近 20 日均成交额 |
| `main_net_yi` | 主力净流入，单位：亿元 |
| `main_net_pct` | 主力净流入占比 |
| `streak` | 连续涨跌天数，正数代表连续上涨，负数代表连续下跌 |
| `is_abnormal` | 是否触发异动 |
| `abnormal_type` | 异动类型 |
| `confidence` | 信号置信度 |
| `reason_hint` | 初步原因线索，不是确认原因 |
| `next_action` | 后续跟踪事项 |

### 原因核验表

默认路径：

```text
outputs/cause_check_YYYY-MM-DD.csv
```

这张表用于承接“自动搜索新闻/公告并分析原因”的第 2 步。当前版本先自动生成：

- 异动股票
- 原因分类
- 优先查证来源
- 搜索关键词
- 新闻 RSS 检索词
- 匹配新闻标题、链接、发布时间
- 证据状态
- 原因判断

默认会自动检索新闻 RSS；如果网络不可用，会标注 `检索失败`，但不会中断日报生成。在没有公告、新闻标题、链接或文件路径前，`cause_judgement` 只能写 `待核验线索`。即使检索到新闻，也优先写成 `高相关线索`，不要直接写成确认原因，除非来源和时间都能对应。

## URL 说明

脚本中的两个 URL 不是网页，而是程序接口：

```python
QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
```

- `QUOTE_URL` 用来获取实时行情，例如最新价、涨跌幅、成交额、主力资金等。
- `KLINE_URL` 用来获取历史 K 线，例如每日开盘价、收盘价、成交额、涨跌幅等。

浏览器直接打开这两个基础 URL 通常不会显示正常网页，因为脚本实际访问时会拼接参数，例如股票代码、字段列表、起止日期等。

## 常见调整

- 想换股票池：编辑 `data/watchlist.csv`
- 想改异动敏感度：调整每只股票的 `pct_threshold` 和 `amount_ratio_threshold`
- 想加行业相对表现：给自选股表增加行业指数或 ETF 字段，再扩展脚本
- 想自动解释原因：先使用 `cause_check_YYYY-MM-DD.csv` 生成核验队列，再接入公告、新闻、研报搜索，并给每条解释附来源
- 想跳过新闻检索：运行脚本时加 `--skip-news-search`

## 运行时注意

东方财富公开接口有时会返回 `502` 或远端断开。脚本已经包含：

- 请求重试
- 小批量拉取报价
- 实时报价失败时回退到 K 线
- 单只股票 K 线失败时跳过该股票并继续生成报告

如果当天数据源持续不可用，日报仍可能生成，但部分股票字段会为空，需要在报告中说明数据不完整。
