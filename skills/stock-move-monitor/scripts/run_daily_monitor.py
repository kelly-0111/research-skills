#!/usr/bin/env python3
"""
Daily A-share abnormal-move monitor.

Data source: Eastmoney public quote/K-line endpoints, with optional local
efinance/akshare K-line fallbacks when those packages are installed.
This is a research workflow demo, not investment advice.
"""

from __future__ import annotations

import csv
import json
import math
import os
import ssl
import sys
import time
import argparse
import concurrent.futures
import importlib.util
import socket
import html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.client import RemoteDisconnected
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
QUOTE_SINGLE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"
KLINE_CACHE_ROOT = Path(os.environ.get("STOCK_MONITOR_CACHE_DIR", Path.cwd() / ".cache" / "stock_move_monitor"))
NEWS_LOOKBACK_DAYS = int(os.environ.get("STOCK_MONITOR_NEWS_LOOKBACK_DAYS", "14"))
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Connection": "close",
}

DEFAULT_KLINE_PROVIDERS = ("eastmoney", "efinance")

CAUSE_SOURCE_PRIORITY = [
    "公司公告/交易所公告",
    "权威财经新闻/公司官方新闻",
    "行业或板块事件",
    "研报观点/市场评论",
]

PHARMA_KEYWORDS = ["医药", "创新药", "临床", "BD", "获批", "NDA", "BLA", "ASCO", "ESMO", "AACR"]
CAUSE_POSITIVE_TERMS = ["公告", "中标", "订单", "合同", "业绩", "预增", "回购", "增持", "获批", "临床", "BD", "合作", "政策", "涨停", "上涨"]
CAUSE_NEGATIVE_TERMS = ["减持", "亏损", "下滑", "处罚", "问询", "终止", "下跌", "利空", "风险", "解禁"]
CAUSE_SIGNAL_TERMS = CAUSE_POSITIVE_TERMS + CAUSE_NEGATIVE_TERMS + [
    "创新药",
    "临床",
    "获批",
    "BD",
    "合作",
    "授权",
    "减持",
    "问询函",
    "监管",
    "盈利",
    "营收",
    "销售",
]

SOURCE_OFFICIAL_TERMS = ["公告", "交易所", "上交所", "深交所", "港交所", "披露", "公司公告", "临时公告"]
SOURCE_NEWS_TERMS = ["证券", "财联社", "证券时报", "中国基金报", "上海证券报", "中证报", "每日经济新闻", "界面", "财新"]
SOURCE_COMMENTARY_TERMS = ["研报", "评级", "券商", "观点", "点评", "机构"]

CAUSE_CATEGORY_RULES = [
    ("医药临床/BD/获批", ["临床", "获批", "NDA", "BLA", "IND", "BD", "授权", "license", "适应症", "管线"]),
    ("业绩催化", ["业绩", "预增", "利润", "盈利", "营收", "亏损", "财报"]),
    ("订单/合同", ["订单", "合同", "中标", "采购", "合作协议"]),
    ("并购/重组", ["并购", "收购", "重组", "资产注入", "股权转让"]),
    ("政策催化", ["政策", "医保", "集采", "监管", "审批", "指导意见"]),
    ("产品/技术进展", ["产品", "技术", "研发", "上市", "新品", "商业化"]),
    ("资金轮动", ["资金", "主力", "净流入", "北向", "放量", "涨停"]),
    ("利空释放", ["减持", "处罚", "问询", "终止", "解禁", "风险"]),
]


@dataclass
class Stock:
    code: str
    name: str
    market: str
    industry: str
    theme: str
    watch_reason: str
    tracking_points: str
    keywords: str
    pct_threshold: float
    amount_ratio_threshold: float
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def secid(self) -> str:
        market = (self.market or "").strip().upper()
        if market in {"HK", "HKG", "港股"}:
            return f"116.{self.code.zfill(5)}"
        if market in {"SH", "SSE", "上海", "沪市"}:
            return f"1.{self.code}"
        if market in {"SZ", "SZSE", "深圳", "深市"}:
            return f"0.{self.code}"
        if market in {"BJ", "BSE", "北京", "北交所"}:
            return f"0.{self.code}"
        if market in {"1", "0", "116"}:
            return f"{market}.{self.code}"
        if self.code.startswith(("5", "6", "9")):
            return f"1.{self.code}"
        return f"0.{self.code}"


def fetch_json(
    url: str,
    params: dict[str, Any],
    *,
    attempts: int = 3,
    timeout: int = 15,
    base_sleep: float = 1.5,
) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    req = Request(
        full_url,
        headers=BROWSER_HEADERS,
    )
    # The local Python install may lack system CA roots. Limit this to public market-data pulls.
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(req, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            socket.timeout,
            RemoteDisconnected,
            BrokenPipeError,
            ConnectionResetError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(base_sleep * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def fetch_text(url: str, *, attempts: int = 2, timeout: int = 10, base_sleep: float = 1.0) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 research-workflow/0.1",
            "Accept": "application/rss+xml,application/xml,text/xml,text/html",
        },
    )
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(req, timeout=timeout, context=context) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (
            HTTPError,
            URLError,
            TimeoutError,
            socket.timeout,
            RemoteDisconnected,
            BrokenPipeError,
            ConnectionResetError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(base_sleep * (attempt + 1))
    raise RuntimeError(f"Failed to fetch text {url}: {last_error}") from last_error


def load_watchlist(path: Path) -> list[Stock]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    stocks: list[Stock] = []
    for row in rows:
        pct_threshold = as_threshold(row.get("pct_threshold"), 5.0)
        amount_ratio_threshold = as_threshold(row.get("amount_ratio_threshold"), 2.0)
        stocks.append(
            Stock(
                code=row["code"],
                name=row["name"],
                market=row["market"],
                industry=row["industry"],
                theme=row["theme"],
                watch_reason=row["watch_reason"],
                tracking_points=row["tracking_points"],
                keywords=row["keywords"],
                pct_threshold=pct_threshold,
                amount_ratio_threshold=amount_ratio_threshold,
                raw=dict(row),
            )
        )
    return stocks


def as_threshold(value: Any, default: float) -> float:
    try:
        if value in ("-", None, ""):
            return default
        return float(str(value).replace("%", "").strip())
    except Exception:
        return default


def fetch_quotes(stocks: list[Stock]) -> dict[str, dict[str, Any]]:
    if os.environ.get("STOCK_MONITOR_FAST_MODE") == "1":
        return fetch_single_quotes_concurrent(stocks)

    quotes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(stocks), 5):
        batch = stocks[start : start + 5]
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f12,f14,f2,f3,f4,f5,f6,f10,f20,f21,f62,f184",
            "secids": ",".join(stock.secid for stock in batch),
        }
        try:
            data = fetch_json(QUOTE_URL, params, attempts=1, timeout=6, base_sleep=0.5)
        except RuntimeError as exc:
            progress(f"quote batch failed, fallback to single quote: {exc}")
            quotes.update(fetch_single_quotes_concurrent(batch))
            continue
        diff = (data.get("data") or {}).get("diff") or []
        quotes.update({item["f12"]: item for item in diff})
        time.sleep(0.2)
    return quotes


def fetch_single_quotes_concurrent(stocks: list[Stock]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    if not stocks:
        return quotes
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(stocks))) as executor:
        futures = {executor.submit(fetch_single_quote, stock): stock for stock in stocks}
        for future in concurrent.futures.as_completed(futures):
            stock = futures[future]
            try:
                quote = future.result()
            except Exception as exc:
                progress(f"single quote failed for {stock.code} {stock.name}: {exc}")
                continue
            if quote:
                quotes[stock.code] = quote
    return quotes


def scale_quote_number(value: Any, precision: Any) -> float:
    raw = as_float(value)
    decimals = as_float(precision)
    if math.isnan(raw):
        return math.nan
    if math.isnan(decimals):
        decimals = 2
    return raw / (10 ** int(decimals))


def fetch_single_quote(stock: Stock) -> dict[str, Any]:
    params = {
        "secid": stock.secid,
        "fields": "f57,f58,f43,f169,f170,f47,f48,f50,f59,f60,f62,f184",
    }
    try:
        data = fetch_json(QUOTE_SINGLE_URL, params, attempts=1, timeout=5, base_sleep=0.5)
    except RuntimeError as exc:
        progress(f"single quote failed for {stock.code} {stock.name}: {exc}")
        return {}
    raw = data.get("data") or {}
    if not raw:
        return {}
    precision = raw.get("f59")
    return {
        "f12": raw.get("f57") or stock.code,
        "f14": raw.get("f58") or stock.name,
        "f2": scale_quote_number(raw.get("f43"), precision),
        "f3": as_float(raw.get("f170")) / 100 if not math.isnan(as_float(raw.get("f170"))) else math.nan,
        "f4": scale_quote_number(raw.get("f169"), precision),
        "f5": raw.get("f47"),
        "f6": raw.get("f48"),
        "f10": as_float(raw.get("f50")) / 100 if not math.isnan(as_float(raw.get("f50"))) else math.nan,
        "f20": "",
        "f21": "",
        "f62": math.nan,
        "f184": raw.get("f184"),
    }


def first_raw_value(raw: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = raw.get(name)
        if value not in ("", None, "-"):
            return value
    return ""


def fallback_quote_from_watchlist(stock: Stock) -> dict[str, Any]:
    raw = stock.raw or {}
    price = as_float(first_raw_value(raw, ["price", "close", "latest_price", "last_price", "收盘价", "最新价"]))
    pct_chg = as_float(first_raw_value(raw, ["pct_chg", "chg_pct", "change_pct", "涨跌幅", "涨跌幅%"]))
    amount = as_float(first_raw_value(raw, ["amount", "成交额"]))
    amount_yi = as_float(first_raw_value(raw, ["amount_yi", "成交额_亿", "成交额(亿)"]))
    if math.isnan(amount) and not math.isnan(amount_yi):
        amount = amount_yi * 100000000
    amount_ratio = as_float(first_raw_value(raw, ["amount_ratio", "volume_ratio", "量比"]))
    chg = as_float(first_raw_value(raw, ["chg", "change", "涨跌额"]))
    if math.isnan(chg) and not math.isnan(price) and not math.isnan(pct_chg) and pct_chg != -100:
        previous = price / (1 + pct_chg / 100)
        chg = price - previous
    if math.isnan(price) and math.isnan(pct_chg) and math.isnan(amount_ratio):
        return {}
    return {
        "f12": stock.code,
        "f14": stock.name,
        "f2": price,
        "f3": pct_chg,
        "f4": chg,
        "f5": "",
        "f6": amount,
        "f10": amount_ratio,
        "f20": "",
        "f21": "",
        "f62": math.nan,
        "f184": math.nan,
        "__source": "uploaded_watchlist",
    }


def fetch_klines(stock: Stock) -> list[dict[str, Any]]:
    if os.environ.get("STOCK_MONITOR_FAST_MODE") == "1":
        raise RuntimeError("K-line skipped in fast web mode; using quote data when available")
    cached = load_kline_cache(stock)
    if cached:
        for row in cached:
            row.setdefault("provider", "cache")
        return cached
    if stock.secid.startswith("116.") and os.environ.get("STOCK_MONITOR_ENABLE_HK_KLINE") != "1":
        raise RuntimeError("HK K-line skipped by default for web stability; set STOCK_MONITOR_ENABLE_HK_KLINE=1 to enable")

    errors: list[str] = []
    for provider in kline_providers_for(stock):
        try:
            rows = fetch_klines_from_provider(stock, provider)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            continue
        if rows:
            for row in rows:
                row.setdefault("provider", provider)
            save_kline_cache(stock, rows, provider=provider)
            return rows
    raise RuntimeError("; ".join(errors) or "No K-line provider returned data")


def kline_providers_for(stock: Stock) -> tuple[str, ...]:
    providers = list(DEFAULT_KLINE_PROVIDERS)
    if stock.secid.startswith("116."):
        # efinance/akshare HK endpoints are more likely to hang or disconnect in local tests.
        providers = ["eastmoney", "tencent_hk"]
    if os.environ.get("STOCK_MONITOR_ENABLE_AKSHARE") == "1":
        providers.append("akshare")
    return tuple(dict.fromkeys(providers))


def fetch_klines_from_provider(stock: Stock, provider: str) -> list[dict[str, Any]]:
    if provider == "eastmoney":
        return fetch_klines_eastmoney(stock)
    if provider == "efinance":
        return fetch_klines_efinance(stock)
    if provider == "tencent_hk":
        return fetch_klines_tencent_hk(stock)
    if provider == "akshare":
        return fetch_klines_akshare(stock)
    raise RuntimeError(f"Unknown K-line provider: {provider}")


def fetch_klines_eastmoney(stock: Stock) -> list[dict[str, Any]]:
    data: dict[str, Any] = {}
    last_error: RuntimeError | None = None
    for fqt in (1,):
        params = {
            "secid": stock.secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": fqt,
            "beg": "20240101",
            "end": "20500101",
        }
        try:
            data = fetch_json(KLINE_URL, params, attempts=1, timeout=4, base_sleep=0.5)
        except RuntimeError as exc:
            last_error = exc
            continue
        if ((data.get("data") or {}).get("klines")):
            break
    else:
        if last_error:
            raise last_error
    raw = ((data.get("data") or {}).get("klines")) or []
    out: list[dict[str, Any]] = []
    for line in raw:
        fields = line.split(",")
        if len(fields) < 11:
            continue
        out.append(
            {
                "date": fields[0],
                "open": as_float(fields[1]),
                "close": as_float(fields[2]),
                "high": as_float(fields[3]),
                "low": as_float(fields[4]),
                "volume": as_float(fields[5]),
                "amount": as_float(fields[6]),
                "amplitude": as_float(fields[7]),
                "pct_chg": as_float(fields[8]),
                "chg": as_float(fields[9]),
                "turnover": as_float(fields[10]),
                "provider": "eastmoney",
            }
        )
    return out


def fetch_klines_tencent_hk(stock: Stock) -> list[dict[str, Any]]:
    if not stock.secid.startswith("116."):
        raise RuntimeError("Tencent HK K-line provider only supports HK stocks")
    symbol = f"hk{stock.code.zfill(5)}"
    data = fetch_json(
        TENCENT_KLINE_URL,
        {"param": f"{symbol},day,,,180,qfq"},
        attempts=2,
        timeout=8,
        base_sleep=0.8,
    )
    raw = (((data.get("data") or {}).get(symbol) or {}).get("qfqday")) or (((data.get("data") or {}).get(symbol) or {}).get("day")) or []
    out: list[dict[str, Any]] = []
    prev_close = math.nan
    for item in raw:
        if not isinstance(item, list) or len(item) < 6:
            continue
        date = as_date_text(item[0])
        open_price = as_float(item[1])
        close = as_float(item[2])
        high = as_float(item[3])
        low = as_float(item[4])
        volume = as_float(item[5])
        if not date or math.isnan(close):
            continue
        chg = close - prev_close if not math.isnan(prev_close) else math.nan
        pct_chg = chg / prev_close * 100 if not math.isnan(chg) and prev_close else math.nan
        amplitude = (high - low) / prev_close * 100 if not math.isnan(prev_close) and prev_close else math.nan
        out.append(
            {
                "date": date,
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": math.nan,
                "amplitude": amplitude,
                "pct_chg": pct_chg,
                "chg": chg,
                "turnover": math.nan,
                "provider": "tencent_hk",
            }
        )
        prev_close = close
    out.sort(key=lambda row: row["date"])
    return out


def optional_module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def normalized_stock_code(stock: Stock) -> str:
    if stock.secid.startswith("116."):
        return stock.code.zfill(5)
    return stock.code


def as_date_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if " " in text:
        text = text.split(" ", 1)[0]
    if "T" in text:
        text = text.split("T", 1)[0]
    return text.replace("/", "-")


def pick_value(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and row.get(name) not in ("", None):
            return row.get(name)
    return ""


def normalize_kline_records(records: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        date = as_date_text(pick_value(record, ["日期", "date", "Date", "时间"]))
        close = as_float(pick_value(record, ["收盘", "close", "收盘价", "Close"]))
        if not date or math.isnan(close):
            continue
        out.append(
            {
                "date": date,
                "open": as_float(pick_value(record, ["开盘", "open", "开盘价", "Open"])),
                "close": close,
                "high": as_float(pick_value(record, ["最高", "high", "最高价", "High"])),
                "low": as_float(pick_value(record, ["最低", "low", "最低价", "Low"])),
                "volume": as_float(pick_value(record, ["成交量", "volume", "Volume"])),
                "amount": as_float(pick_value(record, ["成交额", "amount", "成交金额", "Amount"])),
                "amplitude": as_float(pick_value(record, ["振幅", "amplitude"])),
                "pct_chg": as_float(pick_value(record, ["涨跌幅", "pct_chg", "涨跌幅%", "ChangePercent"])),
                "chg": as_float(pick_value(record, ["涨跌额", "chg", "涨跌", "Change"])),
                "turnover": as_float(pick_value(record, ["换手率", "turnover", "换手率%"])),
                "provider": provider,
            }
        )
    out.sort(key=lambda item: item["date"])
    return out


def fetch_klines_efinance(stock: Stock) -> list[dict[str, Any]]:
    if not optional_module_available("efinance"):
        raise RuntimeError("efinance not installed")
    import efinance as ef  # type: ignore

    df = ef.stock.get_quote_history(
        normalized_stock_code(stock),
        beg="20240101",
        end="20500101",
        klt=101,
        fqt=1,
    )
    if df is None or getattr(df, "empty", True):
        raise RuntimeError("efinance returned empty K-line data")
    return normalize_kline_records(df.to_dict("records"), "efinance")


def fetch_klines_akshare(stock: Stock) -> list[dict[str, Any]]:
    if not optional_module_available("akshare"):
        raise RuntimeError("akshare not installed")
    import akshare as ak  # type: ignore

    code = normalized_stock_code(stock)
    if stock.secid.startswith("116."):
        df = ak.stock_hk_hist(symbol=code, period="daily", start_date="20240101", end_date="20500101", adjust="qfq")
    else:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20240101", end_date="20500101", adjust="qfq")
    if df is None or getattr(df, "empty", True):
        raise RuntimeError("akshare returned empty K-line data")
    return normalize_kline_records(df.to_dict("records"), "akshare")


def kline_cache_path(stock: Stock, cache_date: str | None = None) -> Path:
    day = cache_date or datetime.now().strftime("%Y-%m-%d")
    safe_secid = stock.secid.replace(".", "_")
    return KLINE_CACHE_ROOT / "kline" / day / f"{safe_secid}.json"


def load_kline_cache(stock: Stock) -> list[dict[str, Any]]:
    path = kline_cache_path(stock)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("rows") or []
        if rows:
            return rows
    except Exception:
        return []
    return []


def save_kline_cache(stock: Stock, rows: list[dict[str, Any]], provider: str = "") -> None:
    path = kline_cache_path(stock)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "secid": stock.secid,
        "code": stock.code,
        "name": stock.name,
        "provider": provider or (rows[-1].get("provider") if rows else ""),
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def as_float(value: Any) -> float:
    try:
        if value in ("-", None, ""):
            return math.nan
        return float(str(value).replace(",", "").strip())
    except Exception:
        return math.nan


def money_yi(value: float) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value / 100000000:.2f}"


def pct(value: float) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value:.2f}%"


def md_cell(value: Any) -> str:
    return str(value).replace("|", "｜").replace("\n", " ").strip()


def progress(message: str) -> None:
    try:
        print(message, file=sys.stderr)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


def calculate_streak(klines: list[dict[str, Any]]) -> int:
    if not klines:
        return 0
    streak = 0
    direction = 0
    for row in reversed(klines[-10:]):
        p = row["pct_chg"]
        if math.isnan(p) or abs(p) < 0.01:
            break
        d = 1 if p > 0 else -1
        if direction == 0:
            direction = d
        if d != direction:
            break
        streak += d
    return streak


def classify(row: dict[str, Any], stock: Stock) -> tuple[list[str], str, str, str]:
    flags: list[str] = []
    pct_chg = row["pct_chg"]
    amount_ratio = row["amount_ratio"]
    main_pct = row["main_net_pct"]
    streak = row["streak"]

    if not math.isnan(pct_chg) and abs(pct_chg) >= stock.pct_threshold:
        flags.append("价格异动")
    if not math.isnan(amount_ratio) and amount_ratio >= stock.amount_ratio_threshold:
        flags.append("放量异动")
    if abs(streak) >= 3:
        flags.append("连续上涨" if streak > 0 else "连续下跌")
    if not math.isnan(main_pct) and abs(main_pct) >= 8:
        flags.append("资金异动")

    if not flags:
        flags.append("常规跟踪")

    if "价格异动" in flags and "放量异动" in flags:
        confidence = "高"
    elif "价格异动" in flags or "放量异动" in flags or "资金异动" in flags:
        confidence = "中"
    else:
        confidence = "低"

    if "价格异动" in flags or "放量异动" in flags:
        reason = f"已触发价格/量能异动，进入自动新闻与公告线索核验；重点关键词：{stock.keywords}。"
    elif "资金异动" in flags:
        reason = "已触发资金异动，进入自动新闻与公告线索核验；需判断是否有公告、政策、行业事件或资金轮动。"
    elif "连续上涨" in flags or "连续下跌" in flags:
        reason = "已触发连续涨跌信号，进入自动新闻与公告线索核验；需区分趋势延续、基本面变化和交易性波动。"
    else:
        reason = "未触发异动阈值，不自动检索新闻；保留在日常观察池。"

    next_action = f"跟踪：{stock.tracking_points}"
    return flags, confidence, reason, next_action


def infer_cause_categories(stock: Stock, row: dict[str, Any]) -> str:
    text = f"{stock.industry} {stock.theme} {stock.watch_reason} {stock.keywords}".lower()
    categories: list[str] = []
    if "价格异动" in row["abnormal_type"] or "放量异动" in row["abnormal_type"]:
        categories.extend(["公告催化", "业绩催化", "行业景气", "资金轮动"])
    if "资金异动" in row["abnormal_type"]:
        categories.append("资金流向")
    if any(word.lower() in text for word in PHARMA_KEYWORDS):
        categories.extend(["医药临床/BD/获批", "管线进展", "会议数据"])
    if "半导体" in text or "芯片" in text:
        categories.extend(["订单/合同", "国产替代", "产业链催化"])
    if "ai" in text or "算力" in text:
        categories.extend(["AI主题", "算力需求", "订单/合同"])
    if not categories:
        categories.append("待核验")
    return ";".join(dict.fromkeys(categories))


def build_search_queries(stock: Stock, row: dict[str, Any], run_date: str) -> str:
    watch_terms = [
        term.strip()
        for term in stock.keywords.replace("；", ";").split(";")
        if term.strip() and term.strip() not in {stock.name, stock.code}
    ]
    standard_terms = ["公告", "新闻", "股价异动", "业绩", "订单", "资金流入"]
    if any(word in f"{stock.industry} {stock.theme} {stock.keywords}" for word in PHARMA_KEYWORDS):
        standard_terms.extend(["创新药", "临床", "BD", "获批", "ASCO", "ESMO"])

    queries = []
    for term in list(dict.fromkeys(watch_terms + standard_terms))[:10]:
        queries.append(f"{stock.name} {term} {run_date}")
    queries.append(f"{stock.name} 股价上涨 原因 {run_date}")
    if not math.isnan(row["pct_chg"]) and row["pct_chg"] < 0:
        queries.append(f"{stock.name} 股价下跌 原因 {run_date}")
    return " | ".join(dict.fromkeys(queries))


def primary_news_query(stock: Stock, row: dict[str, Any], run_date: str) -> str:
    direction = "上涨" if not math.isnan(row["pct_chg"]) and row["pct_chg"] >= 0 else "下跌"
    terms = [term.strip() for term in stock.keywords.replace("；", ";").split(";") if term.strip()]
    selected_terms = " ".join([term for term in terms if term not in {stock.name, stock.code}][:3])
    return f"{stock.name} {stock.code} {direction} 原因 公告 新闻 {selected_terms}".strip()


def parse_bing_news_rss(xml_text: str, stock: Stock, limit: int = 3) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = html.unescape((item.findtext("link") or "").strip())
        published_at = html.unescape((item.findtext("pubDate") or "").strip())
        source = html.unescape((item.findtext("source") or "").strip())
        description = html.unescape((item.findtext("description") or "").strip())
        haystack = f"{title} {description}"
        if stock.name not in haystack and stock.code not in haystack:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "published_at": published_at,
                "source": source,
                "description": re_space(description),
            }
        )
        if len(items) >= limit:
            break
    return items


def re_space(value: str) -> str:
    return " ".join(value.split())


def fetch_bing_news_items(query: str, stock: Stock, max_results: int) -> list[dict[str, str]]:
    url = f"{BING_NEWS_RSS_URL}?{urlencode({'q': query, 'format': 'RSS'})}"
    xml_text = fetch_text(url, attempts=2, timeout=12, base_sleep=1.0)
    return parse_bing_news_rss(xml_text, stock, limit=max_results)


def parse_run_date(run_date: str) -> datetime:
    try:
        return datetime.strptime(run_date, "%Y-%m-%d")
    except ValueError:
        return datetime.now()


def parse_news_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def is_recent_news_item(item: dict[str, str], run_date: str, lookback_days: int = NEWS_LOOKBACK_DAYS) -> bool:
    published = parse_news_date(item.get("published_at", ""))
    target_date = parse_run_date(run_date)
    if published is None:
        text = f"{item.get('title', '')} {item.get('description', '')}"
        return run_date in text
    earliest = target_date - timedelta(days=lookback_days)
    latest = target_date + timedelta(days=1)
    return earliest <= published <= latest


def search_news_for_cause(stock: Stock, row: dict[str, Any], run_date: str, max_results: int = 5) -> tuple[list[dict[str, str]], str]:
    earliest = (parse_run_date(run_date) - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    queries = [
        f"{stock.name} {stock.code} 公告 披露 {run_date}",
        f"{primary_news_query(stock, row, run_date)} after:{earliest}",
        f"{stock.name} {stock.code} 业绩 合作 临床 获批 after:{earliest}",
        f"{stock.name} 新闻 after:{earliest}",
        f"{stock.name} 公告 after:{earliest}",
    ]
    last_error = ""
    collected: list[dict[str, str]] = []
    seen_links: set[str] = set()
    stale_count = 0
    try:
        for query in dict.fromkeys(queries):
            items = fetch_bing_news_items(query, stock, max_results)
            for item in items:
                if not is_recent_news_item(item, run_date):
                    stale_count += 1
                    continue
                link = item.get("link", "")
                key = link or item.get("title", "")
                if key in seen_links:
                    continue
                seen_links.add(key)
                collected.append(item)
            if len(collected) >= max_results:
                break
    except RuntimeError as exc:
        last_error = f"新闻检索失败：{exc}"
    if last_error:
        return collected, last_error
    if stale_count and not collected:
        return [], f"新闻检索只返回旧闻或无日期结果，已过滤 {stale_count} 条超过近 {NEWS_LOOKBACK_DAYS} 天的材料。"
    return collected[:max_results], ""


def classify_source_type(item: dict[str, str]) -> str:
    text = f"{item.get('title', '')} {item.get('source', '')} {item.get('link', '')}"
    if any(term.lower() in text.lower() for term in SOURCE_OFFICIAL_TERMS):
        return "公告/交易所披露"
    if any(term.lower() in text.lower() for term in SOURCE_COMMENTARY_TERMS):
        return "研报/市场评论"
    if any(term.lower() in text.lower() for term in SOURCE_NEWS_TERMS):
        return "财经新闻"
    return "新闻/网页线索"


def infer_matched_cause_categories(text: str) -> list[str]:
    matched: list[str] = []
    lowered = text.lower()
    for category, terms in CAUSE_CATEGORY_RULES:
        if any(term.lower() in lowered for term in terms):
            matched.append(category)
    return matched


def score_news_relevance(stock: Stock, row: dict[str, Any], item: dict[str, str]) -> tuple[int, str, list[str]]:
    text = f"{item.get('title', '')} {item.get('description', '')} {item.get('source', '')}"
    score = 0
    reasons: list[str] = []
    if stock.name in text:
        score += 35
        reasons.append("匹配股票名称")
    if stock.code in text:
        score += 20
        reasons.append("匹配股票代码")

    source_type = classify_source_type(item)
    if source_type == "公告/交易所披露":
        score += 25
        reasons.append("公告/披露来源")
    elif source_type == "财经新闻":
        score += 15
        reasons.append("财经新闻来源")

    categories = infer_matched_cause_categories(text)
    if categories:
        score += min(30, 10 * len(categories))
        reasons.append("匹配原因类型：" + "/".join(categories[:3]))

    if not math.isnan(row.get("pct_chg", math.nan)):
        if row["pct_chg"] > 0 and any(term in text for term in CAUSE_POSITIVE_TERMS):
            score += 10
            reasons.append("方向偏正向")
        if row["pct_chg"] < 0 and any(term in text for term in CAUSE_NEGATIVE_TERMS):
            score += 10
            reasons.append("方向偏负向")

    return min(score, 100), source_type, categories


def enrich_news_items(stock: Stock, row: dict[str, Any], news_items: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for item in news_items:
        score, source_type, categories = score_news_relevance(stock, row, item)
        item = dict(item)
        item["relevance_score"] = str(score)
        item["source_type"] = source_type
        item["matched_categories"] = ";".join(categories)
        enriched.append(item)
    enriched.sort(key=lambda item: int(item.get("relevance_score") or 0), reverse=True)
    return enriched


def build_analyst_judgement(
    stock: Stock,
    row: dict[str, Any],
    news_items: list[dict[str, str]],
    evidence_status: str,
    cause_judgement: str,
) -> str:
    direction = "上涨" if not math.isnan(row["pct_chg"]) and row["pct_chg"] > 0 else "下跌" if not math.isnan(row["pct_chg"]) and row["pct_chg"] < 0 else "波动"
    if not news_items:
        return f"初步判断：{stock.name}今日{direction}暂无直接新闻/公告证据，先按技术性或板块性波动处理，需人工核验公告。"
    top = news_items[0]
    categories = top.get("matched_categories") or "待核验"
    source_type = top.get("source_type") or "来源"
    score = top.get("relevance_score") or ""
    qualifier = "较可能" if cause_judgement in {"已确认原因", "高相关线索"} else "可能"
    return (
        f"初步判断：{stock.name}今日{direction}{qualifier}与{categories}有关；"
        f"最高相关来源为{source_type}，相关性{score}/100。"
        f"仍需核验原文发布时间、正文细节与股价反应是否同日匹配。"
    )


def judge_news_cause(stock: Stock, row: dict[str, Any], news_items: list[dict[str, str]], news_error: str) -> tuple[str, str, str, str, str, str]:
    if news_error:
        if "旧闻" in news_error:
            judgement = build_analyst_judgement(stock, row, [], "未发现近期来源", "无明显新闻")
            return "未发现近期来源", "无明显新闻", "低", "", news_error, judgement
        judgement = build_analyst_judgement(stock, row, news_items, "检索失败", "待核验线索")
        return "检索失败", "待核验线索", "低", "", news_error, judgement
    if not news_items:
        judgement = build_analyst_judgement(stock, row, news_items, "未发现明确来源", "无明显新闻")
        return "未发现明确来源", "无明显新闻", "低", "", "新闻 RSS 未返回与股票名称/代码直接匹配的结果。", judgement

    news_items = enrich_news_items(stock, row, news_items)
    title_blob = " ".join(f"{item.get('title', '')} {item.get('description', '')}" for item in news_items).lower()
    matched_terms = [term for term in CAUSE_POSITIVE_TERMS + CAUSE_NEGATIVE_TERMS if term.lower() in title_blob]
    evidence_summary = summarize_news_items(news_items)
    best_score = int(news_items[0].get("relevance_score") or 0)
    best_source_type = news_items[0].get("source_type", "")
    if best_source_type == "公告/交易所披露" and best_score >= 70:
        note = "检索到公告/披露类高相关来源；需核对公告原文是否直接对应今日股价异动。"
        judgement = build_analyst_judgement(stock, row, news_items, "已检索", "已确认原因")
        return "已检索", "已确认原因", "高", evidence_summary, note, judgement
    if matched_terms or best_score >= 60:
        note = f"新闻标题匹配关键词：{';'.join(dict.fromkeys(matched_terms))}。仍需核对正文和公告原文。"
        judgement = build_analyst_judgement(stock, row, news_items, "已检索", "高相关线索")
        return "已检索", "高相关线索", "中", evidence_summary, note, judgement
    note = "检索到相关新闻，但标题未直接指向公告、业绩、订单、政策、临床/BD等明确催化。"
    judgement = build_analyst_judgement(stock, row, news_items, "已检索", "待核验线索")
    return "已检索", "待核验线索", "低", evidence_summary, note, judgement


def summarize_news_items(news_items: list[dict[str, str]], limit: int = 3) -> str:
    summaries = []
    for item in news_items[:limit]:
        title = item.get("title", "")
        source = item.get("source") or "新闻源"
        source_type = item.get("source_type") or classify_source_type(item)
        categories = item.get("matched_categories") or ";".join(infer_matched_cause_categories(title))
        score = item.get("relevance_score", "")
        if categories:
            point = f"{source_type}，线索={categories.replace(';', '/')}"
        else:
            matched = [term for term in CAUSE_SIGNAL_TERMS if term.lower() in title.lower()]
            point = "关键词：" + "/".join(dict.fromkeys(matched[:4])) if matched else "相关新闻，需核验正文"
        score_text = f"，相关性{score}/100" if score else ""
        summaries.append(f"{source}：{point}{score_text}")
    return "；".join(summaries)


def first_link_markdown(cause: dict[str, Any]) -> str:
    urls = [url for url in str(cause.get("source_url_or_path", "")).split("；") if url.strip()]
    if not urls:
        return ""
    return f"[来源链接]({urls[0]})"


def compact_cause_summary(cause: dict[str, Any], max_len: int = 90) -> str:
    summary = cause.get("analyst_judgement") or cause.get("evidence_summary") or cause.get("notes") or ""
    summary = re_space(str(summary))
    if len(summary) > max_len:
        summary = summary[:max_len] + "..."
    link = first_link_markdown(cause)
    source = cause.get("top_source_type", "")
    score = cause.get("top_relevance_score", "")
    source_text = f"{source}/{score}" if source or score else ""
    parts = [
        f"{cause.get('evidence_status', '')}/{cause.get('cause_judgement', '')}".strip("/"),
        source_text,
        summary,
        link,
    ]
    return "：".join(part for part in parts if part)


def build_cause_checks(
    rows: list[dict[str, Any]],
    stocks_by_code: dict[str, Stock],
    run_date: str,
    *,
    enable_news_search: bool = True,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in rows:
        if row["is_abnormal"] != "是":
            continue
        stock = stocks_by_code[row["code"]]
        news_items: list[dict[str, str]] = []
        news_error = ""
        if enable_news_search:
            news_items, news_error = search_news_for_cause(stock, row, run_date)
        else:
            news_error = "新闻检索已关闭"
        news_items = enrich_news_items(stock, row, news_items)
        evidence_status, cause_judgement, cause_confidence, evidence_summary, news_notes, analyst_judgement = judge_news_cause(
            stock, row, news_items, news_error
        )
        top_item = news_items[0] if news_items else {}
        checks.append(
            {
                "date": run_date,
                "code": row["code"],
                "name": row["name"],
                "industry": row["industry"],
                "theme": row["theme"],
                "abnormal_type": row["abnormal_type"],
                "pct_chg": row["pct_chg"],
                "amount_ratio": row["amount_ratio"],
                "cause_categories": infer_cause_categories(stock, row),
                "source_priority": " > ".join(CAUSE_SOURCE_PRIORITY),
                "search_queries": build_search_queries(stock, row, run_date),
                "news_search_query": primary_news_query(stock, row, run_date),
                "matched_news_count": str(len(news_items)),
                "top_source_type": top_item.get("source_type", ""),
                "top_relevance_score": top_item.get("relevance_score", ""),
                "matched_cause_categories": top_item.get("matched_categories", ""),
                "evidence_status": evidence_status,
                "cause_judgement": cause_judgement,
                "confidence": cause_confidence,
                "evidence_summary": evidence_summary,
                "analyst_judgement": analyst_judgement,
                "source_title": "；".join(item.get("title", "") for item in news_items[:3]),
                "source_url_or_path": "；".join(item.get("link", "") for item in news_items[:3]),
                "published_at": "；".join(item.get("published_at", "") for item in news_items[:3]),
                "notes": f"{news_notes} 先查公告/交易所披露，再查权威新闻和行业事件；无来源前不要写成确认原因。",
            }
        )
        if enable_news_search:
            time.sleep(0.4)
    return checks


def build_rows(stocks: list[Stock]) -> list[dict[str, Any]]:
    quotes = fetch_quotes(stocks)
    rows: list[dict[str, Any]] = []
    for i, stock in enumerate(stocks, 1):
        quote = quotes.get(stock.code, {})
        if not quote:
            quote = fallback_quote_from_watchlist(stock)
        kline_status = "ok"
        kline_error = ""
        try:
            klines = fetch_klines(stock)
        except RuntimeError as exc:
            progress(f"kline failed for {stock.code} {stock.name}: {exc}")
            klines = []
            kline_status = "failed"
            kline_error = str(exc)
        recent = klines[-21:]
        amounts = [r["amount"] for r in recent[:-1] if not math.isnan(r["amount"])]
        ma20_amount = sum(amounts) / len(amounts) if amounts else math.nan
        latest_kline_date = klines[-1]["date"] if klines else ""
        kline_provider = klines[-1].get("provider", "") if klines else ""

        amount = as_float(quote.get("f6"))
        if math.isnan(amount) and klines:
            amount = klines[-1]["amount"]
        quote_amount_ratio = as_float(quote.get("f10"))
        amount_ratio = amount / ma20_amount if ma20_amount and not math.isnan(ma20_amount) else quote_amount_ratio
        if math.isnan(amount_ratio):
            amount_ratio_source = ""
        elif ma20_amount and not math.isnan(ma20_amount):
            amount_ratio_source = "K线计算"
        else:
            amount_ratio_source = "实时行情"

        if kline_status == "ok":
            data_quality = "完整"
        elif not math.isnan(amount_ratio):
            data_quality = "K线缺失：使用实时量比；连续涨跌不可用"
        elif quote:
            if quote.get("__source") == "uploaded_watchlist":
                data_quality = "使用上传表快照；K线缺失；量比/连续涨跌可能不可用"
            else:
                data_quality = "K线缺失：涨跌幅可用；量比/连续涨跌不可用"
        else:
            data_quality = "行情与K线均缺失"

        row = {
            "code": stock.code,
            "name": quote.get("f14") or stock.name,
            "industry": stock.industry,
            "theme": stock.theme,
            "price": as_float(quote.get("f2")) if quote else (klines[-1]["close"] if klines else math.nan),
            "pct_chg": as_float(quote.get("f3")) if quote else (klines[-1]["pct_chg"] if klines else math.nan),
            "chg": as_float(quote.get("f4")) if quote else (klines[-1]["chg"] if klines else math.nan),
            "amount": amount,
            "amount_yi": money_yi(amount),
            "ma20_amount_yi": money_yi(ma20_amount),
            "amount_ratio": amount_ratio,
            "amount_ratio_source": amount_ratio_source,
            "main_net_yi": money_yi(as_float(quote.get("f62"))),
            "main_net_pct": as_float(quote.get("f184")),
            "streak": calculate_streak(klines),
            "latest_kline_date": latest_kline_date,
            "kline_status": kline_status,
            "kline_provider": kline_provider,
            "data_quality": data_quality,
            "kline_error": kline_error,
            "keywords": stock.keywords,
        }
        flags, confidence, reason, next_action = classify(row, stock)
        row["abnormal_type"] = ";".join(flags)
        row["confidence"] = confidence
        row["reason_hint"] = reason
        row["next_action"] = next_action
        row["is_abnormal"] = "是" if flags != ["常规跟踪"] else "否"
        rows.append(row)
        time.sleep(0.2)
        progress(f"[{i:02d}/{len(stocks)}] {stock.code} {stock.name} done")
    rows.sort(
        key=lambda r: (
            r["is_abnormal"] != "是",
            -abs(r["pct_chg"]) if not math.isnan(r["pct_chg"]) else 0,
            -r["amount_ratio"] if not math.isnan(r["amount_ratio"]) else 0,
        )
    )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "code",
        "name",
        "industry",
        "theme",
        "price",
        "pct_chg",
        "chg",
        "amount_yi",
        "ma20_amount_yi",
        "amount_ratio",
        "amount_ratio_source",
        "main_net_yi",
        "main_net_pct",
        "streak",
        "latest_kline_date",
        "kline_status",
        "kline_provider",
        "data_quality",
        "is_abnormal",
        "abnormal_type",
        "confidence",
        "reason_hint",
        "next_action",
        "keywords",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            clean = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, float):
                    clean[key] = "" if math.isnan(value) else round(value, 4)
                else:
                    clean[key] = value
            writer.writerow(clean)


def write_cause_checks(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "date",
        "code",
        "name",
        "industry",
        "theme",
        "abnormal_type",
        "pct_chg",
        "amount_ratio",
        "cause_categories",
        "source_priority",
        "search_queries",
        "news_search_query",
        "matched_news_count",
        "top_source_type",
        "top_relevance_score",
        "matched_cause_categories",
        "evidence_status",
        "cause_judgement",
        "confidence",
        "evidence_summary",
        "analyst_judgement",
        "source_title",
        "source_url_or_path",
        "published_at",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            clean = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, float):
                    clean[key] = "" if math.isnan(value) else round(value, 4)
                else:
                    clean[key] = value
            writer.writerow(clean)


def markdown_table(rows: list[dict[str, Any]], limit: int = 20) -> str:
    header = "| 股票 | 行业 | 涨跌幅 | 成交额(亿) | 量比/20日 | 主力净流入(亿) | 异动类型 | 置信度 |\n"
    sep = "|---|---|---:|---:|---:|---:|---|---|\n"
    body = []
    for row in rows[:limit]:
        amount_ratio = "" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}x"
        body.append(
            "| {code} {name} | {industry} | {pct_chg} | {amount_yi} | {amount_ratio} | {main_net_yi} | {abnormal_type} | {confidence} |".format(
                code=md_cell(row["code"]),
                name=md_cell(row["name"]),
                industry=md_cell(row["industry"]),
                pct_chg=pct(row["pct_chg"]),
                amount_yi=md_cell(row["amount_yi"]),
                amount_ratio=amount_ratio,
                main_net_yi=md_cell(row["main_net_yi"]),
                abnormal_type=md_cell(row["abnormal_type"]),
                confidence=md_cell(row["confidence"]),
            )
        )
    return header + sep + "\n".join(body)


def cause_markdown_table(cause_checks: list[dict[str, Any]], limit: int = 12) -> str:
    if not cause_checks:
        return "今日无异动股票需要原因核验。"
    header = "| 股票 | 异动类型 | 最高相关来源 | 相关性 | 判断 | 初步结论 | 链接 |\n"
    sep = "|---|---|---|---:|---|---|---|\n"
    body = []
    for row in cause_checks[:limit]:
        summary = row.get("analyst_judgement") or row.get("evidence_summary") or row.get("notes", "")
        if len(summary) > 110:
            summary = summary[:110] + "..."
        link = first_link_markdown(row)
        body.append(
            f"| {md_cell(row['code'])} {md_cell(row['name'])} | {md_cell(row['abnormal_type'])} | {md_cell(row.get('top_source_type', '') or '无')} | {md_cell(row.get('top_relevance_score', '') or '0')} | {md_cell(row['evidence_status'] + '/' + row['cause_judgement'])} | {md_cell(summary)} | {link} |"
        )
    return header + sep + "\n".join(body)


def html_cell(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def kline_annotation_text(row: dict[str, Any], cause: dict[str, Any] | None) -> str:
    parts = [
        row.get("abnormal_type", ""),
        f"涨跌幅 {pct(row['pct_chg'])}" if not math.isnan(row["pct_chg"]) else "",
        f"量比 {row['amount_ratio']:.2f}x" if not math.isnan(row["amount_ratio"]) else "",
    ]
    if cause:
        parts.append(cause.get("analyst_judgement") or cause.get("evidence_summary") or cause.get("cause_judgement") or "")
    return "；".join(part for part in parts if part)


def render_kline_svg(klines: list[dict[str, Any]], row: dict[str, Any], cause: dict[str, Any] | None) -> str:
    recent = [item for item in klines[-60:] if not math.isnan(item["high"]) and not math.isnan(item["low"])]
    if not recent:
        return "<p class=\"empty\">本次没有可用 K 线，无法画图。</p>"

    width, height = 900, 320
    pad_l, pad_r, pad_t, pad_b = 58, 24, 28, 54
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b
    high = max(item["high"] for item in recent)
    low = min(item["low"] for item in recent)
    if high <= low:
        high = low + 1

    def x_at(index: int) -> float:
        if len(recent) == 1:
            return pad_l + chart_w / 2
        return pad_l + chart_w * index / (len(recent) - 1)

    def y_at(price: float) -> float:
        return pad_t + (high - price) * chart_h / (high - low)

    candle_w = max(4, min(12, chart_w / max(len(recent), 1) * 0.55))
    parts = [
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{html_cell(row['code'])} {html_cell(row['name'])} K线标注\">",
        "<rect x=\"0\" y=\"0\" width=\"900\" height=\"320\" fill=\"#fff\"/>",
        f"<line x1=\"{pad_l}\" y1=\"{pad_t}\" x2=\"{pad_l}\" y2=\"{pad_t + chart_h}\" stroke=\"#d7dde8\"/>",
        f"<line x1=\"{pad_l}\" y1=\"{pad_t + chart_h}\" x2=\"{pad_l + chart_w}\" y2=\"{pad_t + chart_h}\" stroke=\"#d7dde8\"/>",
    ]

    for ratio in (0, 0.25, 0.5, 0.75, 1):
        price = high - (high - low) * ratio
        y = pad_t + chart_h * ratio
        parts.append(f"<line x1=\"{pad_l}\" y1=\"{y:.1f}\" x2=\"{pad_l + chart_w}\" y2=\"{y:.1f}\" stroke=\"#eef2f7\"/>")
        parts.append(f"<text x=\"8\" y=\"{y + 4:.1f}\" font-size=\"12\" fill=\"#667085\">{price:.2f}</text>")

    for idx, item in enumerate(recent):
        x = x_at(idx)
        open_price = item["open"]
        close_price = item["close"]
        color = "#d64545" if close_price >= open_price else "#16845f"
        y_high = y_at(item["high"])
        y_low = y_at(item["low"])
        y_open = y_at(open_price)
        y_close = y_at(close_price)
        body_y = min(y_open, y_close)
        body_h = max(2, abs(y_close - y_open))
        parts.append(f"<line x1=\"{x:.1f}\" y1=\"{y_high:.1f}\" x2=\"{x:.1f}\" y2=\"{y_low:.1f}\" stroke=\"{color}\" stroke-width=\"1.3\"/>")
        parts.append(
            f"<rect x=\"{x - candle_w / 2:.1f}\" y=\"{body_y:.1f}\" width=\"{candle_w:.1f}\" height=\"{body_h:.1f}\" fill=\"{color}\" opacity=\"0.82\"/>"
        )

    annotation_idx = len(recent) - 1
    latest_date = row.get("latest_kline_date")
    for idx, item in enumerate(recent):
        if latest_date and item.get("date") == latest_date:
            annotation_idx = idx
            break
    mark = recent[annotation_idx]
    mx = x_at(annotation_idx)
    my = y_at(mark["high"])
    label = html_cell(kline_annotation_text(row, cause))
    if len(label) > 86:
        label = label[:86] + "..."
    label_y = max(24, my - 34)
    parts.extend(
        [
            f"<line x1=\"{mx:.1f}\" y1=\"{pad_t}\" x2=\"{mx:.1f}\" y2=\"{pad_t + chart_h}\" stroke=\"#2f66e8\" stroke-dasharray=\"4 4\"/>",
            f"<circle cx=\"{mx:.1f}\" cy=\"{my:.1f}\" r=\"5\" fill=\"#2f66e8\"/>",
            f"<rect x=\"{min(mx + 8, width - 430):.1f}\" y=\"{label_y:.1f}\" width=\"410\" height=\"42\" rx=\"6\" fill=\"#eef4ff\" stroke=\"#b9cdfd\"/>",
            f"<text x=\"{min(mx + 20, width - 418):.1f}\" y=\"{label_y + 17:.1f}\" font-size=\"12\" fill=\"#1b3f94\">{html_cell(mark.get('date', ''))}</text>",
            f"<text x=\"{min(mx + 20, width - 418):.1f}\" y=\"{label_y + 34:.1f}\" font-size=\"12\" fill=\"#1f2937\">{label}</text>",
            f"<text x=\"{pad_l}\" y=\"{height - 18}\" font-size=\"12\" fill=\"#667085\">{html_cell(recent[0].get('date', ''))}</text>",
            f"<text x=\"{width - 96}\" y=\"{height - 18}\" font-size=\"12\" fill=\"#667085\">{html_cell(recent[-1].get('date', ''))}</text>",
            "</svg>",
        ]
    )
    return "\n".join(parts)


def write_kline_annotations(
    rows: list[dict[str, Any]],
    stocks_by_code: dict[str, Stock],
    cause_checks: list[dict[str, Any]],
    path: Path,
    *,
    limit: int = 12,
) -> None:
    cause_by_code = {row["code"]: row for row in cause_checks}
    selected = [row for row in rows if row.get("is_abnormal") == "是"] or rows
    selected = selected[:limit]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards: list[str] = []
    for row in selected:
        stock = stocks_by_code.get(row["code"])
        cause = cause_by_code.get(row["code"])
        try:
            klines = fetch_klines(stock) if stock else []
            chart = render_kline_svg(klines, row, cause)
            chart_note = f"K线来源：{html_cell((klines[-1].get('provider') if klines else '') or row.get('kline_provider') or '无')}"
        except Exception as exc:
            chart = f"<p class=\"empty\">本次没有可用 K 线，无法画图。原因：{html_cell(exc)}</p>"
            chart_note = "K线来源：无"
        cause_text = compact_cause_summary(cause, max_len=180) if cause else "未进入原因核验。"
        cards.append(
            "\n".join(
                [
                    "<section class=\"card\">",
                    f"<h2>{html_cell(row['code'])} {html_cell(row['name'])}</h2>",
                    f"<div class=\"meta\">{html_cell(row.get('industry', ''))} / {html_cell(row.get('theme', ''))} / {chart_note}</div>",
                    chart,
                    "<div class=\"summary\">",
                    f"<b>异动：</b>{html_cell(row.get('abnormal_type', ''))}　",
                    f"<b>置信度：</b>{html_cell(row.get('confidence', ''))}　",
                    f"<b>原因线索：</b>{html_cell(cause_text)}",
                    "</div>",
                    "</section>",
                ]
            )
        )

    html_text = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <title>K线异动标注</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #1f2937; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    .intro {{ color: #667085; margin-bottom: 18px; }}
    .card {{ background: #fff; border: 1px solid #d9e0ea; border-radius: 10px; padding: 18px; margin-bottom: 18px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
    h2 {{ margin: 0 0 4px; font-size: 20px; }}
    .meta {{ color: #667085; font-size: 13px; margin-bottom: 10px; }}
    .summary {{ border-top: 1px solid #edf1f7; margin-top: 10px; padding-top: 10px; line-height: 1.7; }}
    .empty {{ padding: 42px 16px; background: #f8fafc; border: 1px dashed #c8d2e1; border-radius: 8px; color: #667085; }}
    svg {{ width: 100%; height: auto; border: 1px solid #edf1f7; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>K线异动标注</h1>
  <div class=\"intro\">生成时间：{html_cell(generated_at)}。蓝色虚线标注本次用于复盘的异动日期；图表仅用于快速复盘，具体原因仍需看公告、新闻和原始数据。</div>
  {''.join(cards)}
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def count_by(rows: list[dict[str, Any]], key: str) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "未分类")
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def avg(values: list[float]) -> float:
    clean = [value for value in values if not math.isnan(value)]
    return sum(clean) / len(clean) if clean else math.nan


def signed(value: float, suffix: str = "") -> str:
    if math.isnan(value):
        return ""
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.2f}{suffix}"


def theme_summary_table(rows: list[dict[str, Any]]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get("theme") or row.get("industry") or "未分类", []).append(row)
    header = "| 主题 | 覆盖股票 | 平均涨跌幅 | 上涨/下跌 | 异动数 | 资金净流入合计(亿) |\n"
    sep = "|---|---:|---:|---:|---:|---:|\n"
    body = []
    for theme, items in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        pct_avg = avg([item["pct_chg"] for item in items])
        up = sum(1 for item in items if not math.isnan(item["pct_chg"]) and item["pct_chg"] > 0)
        down = sum(1 for item in items if not math.isnan(item["pct_chg"]) and item["pct_chg"] < 0)
        abnormal_count = sum(1 for item in items if item["is_abnormal"] == "是")
        main_sum = sum(item["main_net_pct"] for item in items if not math.isnan(item["main_net_pct"]))
        body.append(
            f"| {md_cell(theme)} | {len(items)} | {signed(pct_avg, '%')} | {up}/{down} | {abnormal_count} | {signed(main_sum)} |"
        )
    return header + sep + "\n".join(body)


def ranking_table(rows: list[dict[str, Any]], *, reverse: bool, limit: int = 8) -> str:
    filtered = [row for row in rows if not math.isnan(row["pct_chg"])]
    filtered.sort(key=lambda row: row["pct_chg"], reverse=reverse)
    header = "| 排名 | 股票 | 主题 | 涨跌幅 | 成交额(亿) | 量比 | 主力净流入(亿) | 备注 |\n"
    sep = "|---:|---|---|---:|---:|---:|---:|---|\n"
    body = []
    for idx, row in enumerate(filtered[:limit], 1):
        amount_ratio = "" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}x"
        note = row["abnormal_type"] if row["is_abnormal"] == "是" else "未触发阈值"
        body.append(
            f"| {idx} | {md_cell(row['code'])} {md_cell(row['name'])} | {md_cell(row['theme'])} | {pct(row['pct_chg'])} | {md_cell(row['amount_yi'])} | {amount_ratio} | {md_cell(row['main_net_yi'])} | {md_cell(note)} |"
        )
    return header + sep + "\n".join(body)


def watch_queue_table(rows: list[dict[str, Any]], limit: int = 12) -> str:
    def score(row: dict[str, Any]) -> tuple[int, float]:
        points = 0
        if row["is_abnormal"] == "是":
            points += 4
        if not math.isnan(row["pct_chg"]) and abs(row["pct_chg"]) >= 2:
            points += 2
        if not math.isnan(row["amount_ratio"]) and row["amount_ratio"] >= 1:
            points += 1
        if not math.isnan(row["main_net_pct"]) and abs(row["main_net_pct"]) >= 5:
            points += 1
        return points, abs(row["pct_chg"]) if not math.isnan(row["pct_chg"]) else 0

    ranked = sorted(rows, key=score, reverse=True)
    header = "| 优先级 | 股票 | 今日变化 | 关注理由 | 下一步动作 |\n"
    sep = "|---|---|---|---|---|\n"
    body = []
    for row in ranked[:limit]:
        points, _ = score(row)
        priority = "高" if points >= 5 else "中" if points >= 3 else "低"
        change = f"{pct(row['pct_chg'])}，量比 " + ("" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}x")
        body.append(
            f"| {priority} | {md_cell(row['code'])} {md_cell(row['name'])} | {md_cell(change)} | {md_cell(row['reason_hint'])} | {md_cell(row['next_action'])} |"
        )
    return header + sep + "\n".join(body)


def cause_summary_for_row(row: dict[str, Any], cause_by_code: dict[str, dict[str, Any]]) -> str:
    cause = cause_by_code.get(row["code"])
    if cause:
        return compact_cause_summary(cause, max_len=100)
    if row.get("is_abnormal") == "是":
        return "已触发异动，但本次自动检索未返回有效新闻线索；需人工核验公告和新闻。"
    return "未触发异动阈值，未自动检索新闻。"


def detailed_stock_block(row: dict[str, Any], cause_by_code: dict[str, dict[str, Any]]) -> list[str]:
    amount_ratio_text = "数据缺失" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f} 倍"
    price_signal = "上涨" if not math.isnan(row["pct_chg"]) and row["pct_chg"] > 0 else "下跌" if not math.isnan(row["pct_chg"]) and row["pct_chg"] < 0 else "持平/缺失"
    volume_signal = "放量" if not math.isnan(row["amount_ratio"]) and row["amount_ratio"] >= 1.2 else "缩量/未放量" if not math.isnan(row["amount_ratio"]) else "量能缺失"
    cause = cause_by_code.get(row["code"])
    evidence = "未进入自动原因核验；如人工关注，可先查公告、新闻和研报更新。"
    judgement = "未检索"
    if cause:
        evidence = compact_cause_summary(cause, max_len=160)
        judgement = f"{cause.get('evidence_status', '')}/{cause.get('cause_judgement', '')}".strip("/")
    return [
        f"### {row['code']} {row['name']}",
        "",
        f"- 交易表现：{price_signal}，涨跌幅 {pct(row['pct_chg'])}，成交额 {row['amount_yi']} 亿，量比 {amount_ratio_text}（{row.get('amount_ratio_source') or '无'}）。",
        f"- 异动判断：{row['abnormal_type']}；系统置信度：{row['confidence']}；数据质量：{row.get('data_quality', '')}。",
        f"- 异动线索：{row['reason_hint']}",
        f"- 量价结构：{volume_signal}；主力净流入 {row.get('main_net_yi', '')} 亿，主力净占比 {signed(row['main_net_pct'], '%')}。",
        f"- 原因核验：{judgement}。{evidence}",
        f"- 明日跟踪：{row['next_action']}",
        f"- 关键词：{row['keywords']}",
        "",
    ]


def write_report(
    rows: list[dict[str, Any]],
    cause_checks: list[dict[str, Any]],
    path: Path,
    generated_at: str,
) -> None:
    abnormal = [r for r in rows if r["is_abnormal"] == "是"]
    top = sorted(rows, key=lambda r: (r["is_abnormal"] != "是", -(abs(r["pct_chg"]) if not math.isnan(r["pct_chg"]) else 0)))[:10]
    incomplete = [r for r in rows if r.get("kline_status") != "ok"]
    quote_ok = [r for r in rows if not math.isnan(r["pct_chg"]) or not math.isnan(r["price"])]
    kline_ok = [r for r in rows if r.get("kline_status") == "ok"]
    amount_ratio_ok = [r for r in rows if not math.isnan(r["amount_ratio"])]
    up_count = sum(1 for r in rows if not math.isnan(r["pct_chg"]) and r["pct_chg"] > 0)
    down_count = sum(1 for r in rows if not math.isnan(r["pct_chg"]) and r["pct_chg"] < 0)
    cause_by_code = {row["code"]: row for row in cause_checks}
    theme_counts = "；".join(f"{name} {count}" for name, count in count_by(rows, "theme")[:6])
    kline_sources = "；".join(f"{name} {count}" for name, count in count_by(kline_ok, "kline_provider"))
    optional_sources = []
    optional_sources.append(f"efinance={'已安装' if optional_module_available('efinance') else '未安装'}")
    akshare_status = "已安装/未默认启用" if optional_module_available("akshare") else "未安装"
    if os.environ.get("STOCK_MONITOR_ENABLE_AKSHARE") == "1" and optional_module_available("akshare"):
        akshare_status = "已启用"
    optional_sources.append(f"akshare={akshare_status}")
    lines = [
        "# 每日异动监控简报",
        "",
        f"- 生成时间：{generated_at}",
        f"- 股票池数量：{len(rows)}",
        f"- 触发异动数量：{len(abnormal)}",
        f"- 行情成功数量：{len(quote_ok)}/{len(rows)}",
        f"- 量比可用数量：{len(amount_ratio_ok)}/{len(rows)}",
        f"- K线成功数量：{len(kline_ok)}/{len(rows)}（仅影响连续涨跌和20日均额；若实时量比可用，不影响基础异动扫描）",
        f"- K线来源分布：{kline_sources or '无'}",
        f"- 上涨/下跌数量：{up_count}/{down_count}",
        f"- 主要主题分布：{theme_counts}",
        "- 数据源：东方财富公开行情/K线接口；A股 K线失败时会尝试 efinance 兜底；akshare 可通过环境变量 STOCK_MONITOR_ENABLE_AKSHARE=1 启用",
        f"- 可选数据包状态：{'；'.join(optional_sources)}",
        "- 说明：本报告用于投研 workflow 测试，不构成投资建议；无来源支持的原因分析均为待核验线索。",
        "",
        "## 一、盘面概览",
        "",
        theme_summary_table(rows),
        "",
        "## 二、今日重点异动",
        "",
        markdown_table(abnormal if abnormal else rows),
        "",
        "## 三、涨跌幅排序",
        "",
        "### 涨幅靠前",
        "",
        ranking_table(rows, reverse=True),
        "",
        "### 跌幅靠前",
        "",
        ranking_table(rows, reverse=False),
        "",
        "## 四、重点跟踪队列",
        "",
        watch_queue_table(rows),
        "",
        "## 五、自动新闻原因分析",
        "",
        "| 股票 | 是否异动 | 异动类型 | 自动检索结论 | 下一步 |\n|---|---|---|---|---|",
    ]
    for row in top:
        lines.append(
            f"| {md_cell(row['code'])} {md_cell(row['name'])} | {row['is_abnormal']} | {md_cell(row['abnormal_type'])} | {md_cell(cause_summary_for_row(row, cause_by_code))} | {md_cell(row['next_action'])} |"
        )
    lines.extend(
        [
        "",
        "## 六、个股复盘",
        "",
        ]
    )
    for row in top:
        lines.extend(detailed_stock_block(row, cause_by_code))
    lines.extend(
        [
            "## 七、异动原因核验",
            "",
            cause_markdown_table(cause_checks),
            "",
            "核验顺序：先看公司公告/交易所公告，再看权威财经新闻和公司官方新闻，最后参考行业事件、研报观点和市场评论。",
            "",
            "脚本会自动检索新闻 RSS，并把搜索词、匹配新闻、来源标题/链接和判断写入 `cause_check_YYYY-MM-DD.csv`。即使检索到新闻，也只能先标为线索，需继续核验公告原文和正文。",
            "",
            "## 八、明日重点关注",
            "",
            "1. 对高优先级股票补公告原文、交易所披露和公司新闻，区分确认原因和待核验线索。",
            "2. 对涨跌幅靠前但未触发异动阈值的股票，检查是否需要调整阈值或加入人工关注。",
            "3. 对资金异动个股，继续看次日成交额、主力净流入是否延续，避免单日噪声。",
            "4. 对创新药标的，单独补临床数据、BD/license-out、医保、ASCO/ESMO/AACR/WCLC 会议线索。",
            "5. 如果 K线成功率低，优先用备用行情源或本地历史行情缓存补齐量比和连续涨跌。",
            "",
        ]
    )
    if incomplete:
        lines.extend(
            [
                "## 九、数据质量提示",
                "",
                "以下股票本次 K 线接口请求失败；若有实时量比则已用于兜底，但连续涨跌和20日均额仍不完整：",
                "",
                "| 股票 | 行业 | 今日涨跌幅 | 量比 | 量比来源 | 说明 |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for row in incomplete:
            amount_ratio = "" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}x"
            lines.append(
                f"| {row['code']} {row['name']} | {row['industry']} | {pct(row['pct_chg'])} | {amount_ratio} | {row.get('amount_ratio_source', '')} | {row.get('data_quality', '')} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    cwd = Path.cwd()
    parser = argparse.ArgumentParser(description="Run A-share daily abnormal-move monitoring.")
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=cwd / "data" / "watchlist.csv",
        help="Path to watchlist CSV. Default: ./data/watchlist.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=cwd / "outputs",
        help="Directory for generated report and CSV. Default: ./outputs",
    )
    parser.add_argument(
        "--skip-news-search",
        action="store_true",
        help="Disable automatic news RSS search and only generate cause-check queries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_date = datetime.now().strftime("%Y-%m-%d")
    stocks = load_watchlist(args.watchlist)
    stocks_by_code = {stock.code: stock for stock in stocks}
    rows = build_rows(stocks)
    csv_path = args.output_dir / f"daily_monitor_{run_date}.csv"
    cause_path = args.output_dir / f"cause_check_{run_date}.csv"
    report_path = args.output_dir / f"daily_report_{run_date}.md"
    kline_path = args.output_dir / f"kline_annotations_{run_date}.html"
    cause_checks = build_cause_checks(
        rows,
        stocks_by_code,
        run_date,
        enable_news_search=not args.skip_news_search,
    )
    write_csv(rows, csv_path)
    write_cause_checks(cause_checks, cause_path)
    write_report(rows, cause_checks, report_path, generated_at)
    write_kline_annotations(rows, stocks_by_code, cause_checks, kline_path)
    print(f"CSV: {csv_path}")
    print(f"CAUSE_CHECK: {cause_path}")
    print(f"REPORT: {report_path}")
    print(f"KLINE_ANNOTATIONS: {kline_path}")


if __name__ == "__main__":
    main()
