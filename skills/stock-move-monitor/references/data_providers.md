# Data Provider Strategy

The base stock monitor must run without `adata` or any other third-party market-data SDK.

## Default Provider

Use the bundled no-SDK provider by default:

- Quote endpoint: Eastmoney public quote API.
- K-line endpoint: Eastmoney public K-line API.
- Python dependencies: standard library only.

This is the share-package baseline because teammates can run it without installing extra data packages or using a paid database.

## Optional Provider

`adata` can be used as an optional enhancement when it is already installed and reachable.

Use it for:

- current quote backup
- cross-checking price, percent change, volume, and amount
- future index/concept/sector features

Do not make `adata` a required dependency for the base skill. If an `adata` integration is added later, keep a fallback path:

```text
try adata
→ if unavailable or empty
→ fallback to bundled Eastmoney public endpoints
→ still generate report with data_quality notes
```

## Failure Handling

- If quote data fails, continue with available K-line data.
- If K-line data fails, still generate quote-driven abnormal signals and mark `data_quality`.
- If optional SDK data fails, do not stop the run; record the provider failure and use the no-SDK provider.

## Sharing Rule

Do not add `adata` to required installation instructions unless the script truly cannot run without it. Prefer "optional enhancement" wording.
