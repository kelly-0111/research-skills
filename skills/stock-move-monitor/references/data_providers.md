# Data Provider Strategy

The base stock monitor must run without `adata`, `efinance`, `akshare`, or any other third-party market-data SDK.

## Default Provider

Use the bundled no-SDK provider by default:

- Quote endpoint: Eastmoney public quote API.
- K-line endpoint: Eastmoney public K-line API.
- Python dependencies: standard library only.

This is the share-package baseline because teammates can run it without installing extra data packages or using a paid database.

## Optional Providers

`efinance` and `akshare` can be used as optional local K-line fallbacks when they are already installed and reachable. They are not required for the baseline share package. `efinance` is the default A-share fallback; `akshare` is opt-in because its public endpoints can occasionally disconnect or hang.

Use it for:

- K-line backup when Eastmoney `push2his` disconnects
- cross-checking price, percent change, volume, and amount
- future index/concept/sector features

The current provider order is:

```text
try Eastmoney direct K-line
→ if unavailable or empty, try efinance when installed
→ if unavailable or empty, try akshare only when STOCK_MONITOR_ENABLE_AKSHARE=1
→ if all fail, still generate report from real-time quote data and mark data_quality
```

`adata` can still be added later as another optional enhancement, but it should follow the same rule: never make it mandatory for CSV/report generation.

## Failure Handling

- If quote data fails, continue with available K-line data.
- If K-line data fails, still generate quote-driven abnormal signals and mark `data_quality`.
- If optional SDK data fails, do not stop the run; record the provider failure and use the next provider.

## Sharing Rule

Do not add `efinance`, `akshare`, or `adata` to required installation instructions unless the script truly cannot run without them. Prefer "optional enhancement" wording.
