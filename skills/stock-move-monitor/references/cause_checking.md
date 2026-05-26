# Abnormal Move Cause Checking

Use this module after abnormal stocks are detected.

## Goal

Turn abnormal-move rows into a verification queue:

```text
abnormal stock
→ search queries
→ automatic news RSS search
→ source priority
→ cause categories
→ evidence status
→ confirmed cause / high-related lead / to-verify lead
```

## Current Automation

The bundled script uses a no-key Bing News RSS search for each abnormal stock. It records:

- news search query
- matched news count
- source title
- source URL/path
- publish time
- evidence summary
- cause judgement

If RSS search fails, the script must still generate the daily report and mark `evidence_status=检索失败`.

## Source Priority

| Priority | Source | Judgement |
| --- | --- | --- |
| 1 | Company announcements and exchange filings | Can support `已确认原因` if timing and content match the move |
| 2 | Reputable financial news and company official news | Usually `高相关线索` unless directly citing official disclosure |
| 3 | Industry or sector events | Useful for `板块联动` and `资金轮动` |
| 4 | Research reports and market commentary | Treat as interpretation; keep as `待核验线索` unless cross-checked |
| 5 | Social media or unsourced summaries | Low-confidence lead only |

## Cause Categories

- 公告催化
- 业绩催化
- 订单/合同
- 并购/重组
- 政策催化
- 行业景气
- 产品/技术进展
- 医药临床/BD/获批
- 资金轮动
- 板块联动
- 利空释放
- 无明显新闻
- 待核验

For pharma/innovative-drug stocks, also check:

- 临床数据
- BD/license-out
- NDA/BLA/获批
- 医保/商保
- ASCO/ESMO/AACR/WCLC meetings
- 管线进展

## Evidence Labels

- `已检索`: source title and URL/path are filled.
- `待检索`: queries generated but no source checked yet.
- `未发现明确来源`: searched but no relevant source found.
- `检索失败`: news search failed, but the monitor continued.

## Judgement Labels

- `已确认原因`: official or high-confidence source directly explains the event and timing.
- `高相关线索`: source is relevant and timely, but causality is still an inference.
- `待核验线索`: plausible but not source-backed.
- `无明显新闻`: no relevant news or announcement found in the review window.

Never write "because" as a confirmed cause without a source title, URL/path, and publish date.
