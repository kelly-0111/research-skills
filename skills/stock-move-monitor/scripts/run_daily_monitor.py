#!/usr/bin/env python3
"""
Daily A-share abnormal-move monitor.

Data source: Eastmoney public quote and kline endpoints.
This is a research workflow demo, not investment advice.
"""

from __future__ import annotations

import csv
import json
import math
import ssl
import sys
import time
import argparse
import socket
import html
import xml.etree.ElementTree as ET
from http.client import RemoteDisconnected
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"

CAUSE_SOURCE_PRIORITY = [
    "公司公告/交易所公告",
    "权威财经新闻/公司官方新闻",
    "行业或板块事件",
    "研报观点/市场评论",
]

PHARMA_KEYWORDS = ["医药", "创新药", "临床", "BD", "获批", "NDA", "BLA", "ASCO", "ESMO", "AACR"]
CAUSE_POSITIVE_TERMS = ["公告", "中标", "订单", "合同", "业绩", "预增", "回购", "增持", "获批", "临床", "BD", "合作", "政策", "涨停", "上涨"]
CAUSE_NEGATIVE_TERMS = ["减持", "亏损", "下滑", "处罚", "问询", "终止", "下跌", "利空", "风险", "解禁"]


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

    @property
    def secid(self) -> str:
        return f"{self.market}.{self.code}"


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
        headers={
            "User-Agent": "Mozilla/5.0 research-workflow/0.1",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    # The local Python install may lack system CA roots. Limit this to public market-data pulls.
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(req, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, socket.timeout, RemoteDisconnected) as exc:
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
        except (HTTPError, URLError, TimeoutError, socket.timeout, RemoteDisconnected) as exc:
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
                pct_threshold=float(row["pct_threshold"]),
                amount_ratio_threshold=float(row["amount_ratio_threshold"]),
            )
        )
    return stocks


def fetch_quotes(stocks: list[Stock]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(stocks), 5):
        batch = stocks[start : start + 5]
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f12,f14,f2,f3,f4,f5,f6,f20,f21,f62,f184",
            "secids": ",".join(stock.secid for stock in batch),
        }
        try:
            data = fetch_json(QUOTE_URL, params)
        except RuntimeError as exc:
            print(f"quote batch failed, fallback to kline: {exc}", file=sys.stderr)
            continue
        diff = (data.get("data") or {}).get("diff") or []
        quotes.update({item["f12"]: item for item in diff})
        time.sleep(0.2)
    return quotes


def fetch_klines(stock: Stock) -> list[dict[str, Any]]:
    params = {
        "secid": stock.secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 1,
        "beg": "20240101",
        "end": "20500101",
    }
    data = fetch_json(KLINE_URL, params, attempts=5, timeout=25, base_sleep=2.0)
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
            }
        )
    return out


def as_float(value: Any) -> float:
    try:
        if value in ("-", None, ""):
            return math.nan
        return float(value)
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
        reason = f"优先核验：{stock.keywords}；结合公告、新闻、研报和行业价格数据判断是否基本面驱动。"
    elif "资金异动" in flags:
        reason = "主力资金指标波动较大，先核验是否有公告、政策或行业事件。"
    else:
        reason = "未触发核心阈值，保留在日常观察池。"

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


def search_news_for_cause(stock: Stock, row: dict[str, Any], run_date: str, max_results: int = 3) -> tuple[list[dict[str, str]], str]:
    queries = [
        primary_news_query(stock, row, run_date),
        f"{stock.name} 新闻",
        f"{stock.name} 公告",
    ]
    last_error = ""
    try:
        for query in dict.fromkeys(queries):
            items = fetch_bing_news_items(query, stock, max_results)
            if items:
                return items, ""
    except RuntimeError as exc:
        last_error = f"新闻检索失败：{exc}"
    if last_error:
        return [], last_error
    return [], ""


def judge_news_cause(stock: Stock, row: dict[str, Any], news_items: list[dict[str, str]], news_error: str) -> tuple[str, str, str, str, str]:
    if news_error:
        return "检索失败", "待核验线索", "低", "", news_error
    if not news_items:
        return "未发现明确来源", "无明显新闻", "低", "", "新闻 RSS 未返回与股票名称/代码直接匹配的结果。"

    titles = "；".join(item["title"] for item in news_items if item.get("title"))
    title_blob = titles.lower()
    matched_terms = [term for term in CAUSE_POSITIVE_TERMS + CAUSE_NEGATIVE_TERMS if term.lower() in title_blob]
    evidence_summary = "；".join(
        f"{item.get('source') or '新闻源'}:{item.get('title')}" for item in news_items[:3]
    )
    if matched_terms:
        note = f"新闻标题匹配关键词：{';'.join(dict.fromkeys(matched_terms))}。仍需核对正文和公告原文。"
        return "已检索", "高相关线索", "中", evidence_summary, note
    note = "检索到相关新闻，但标题未直接指向公告、业绩、订单、政策、临床/BD等明确催化。"
    return "已检索", "待核验线索", "低", evidence_summary, note


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
        evidence_status, cause_judgement, cause_confidence, evidence_summary, news_notes = judge_news_cause(
            stock, row, news_items, news_error
        )
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
                "evidence_status": evidence_status,
                "cause_judgement": cause_judgement,
                "confidence": cause_confidence,
                "evidence_summary": evidence_summary,
                "source_title": "；".join(item.get("title", "") for item in news_items[:3]),
                "source_url_or_path": "；".join(item.get("link", "") for item in news_items[:3]),
                "published_at": "；".join(item.get("published_at", "") for item in news_items[:3]),
                "notes": f"{news_notes} 先查公告/交易所披露，再查权威新闻和行业事件；无来源前不要写成确认原因。",
            }
        )
        time.sleep(0.4)
    return checks


def build_rows(stocks: list[Stock]) -> list[dict[str, Any]]:
    quotes = fetch_quotes(stocks)
    rows: list[dict[str, Any]] = []
    for i, stock in enumerate(stocks, 1):
        quote = quotes.get(stock.code, {})
        kline_status = "ok"
        kline_error = ""
        try:
            klines = fetch_klines(stock)
        except RuntimeError as exc:
            print(f"kline failed for {stock.code} {stock.name}: {exc}", file=sys.stderr)
            klines = []
            kline_status = "failed"
            kline_error = str(exc)
        recent = klines[-21:]
        amounts = [r["amount"] for r in recent[:-1] if not math.isnan(r["amount"])]
        ma20_amount = sum(amounts) / len(amounts) if amounts else math.nan
        latest_kline_date = klines[-1]["date"] if klines else ""

        amount = as_float(quote.get("f6"))
        if math.isnan(amount) and klines:
            amount = klines[-1]["amount"]
        amount_ratio = amount / ma20_amount if ma20_amount and not math.isnan(ma20_amount) else math.nan

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
            "main_net_yi": money_yi(as_float(quote.get("f62"))),
            "main_net_pct": as_float(quote.get("f184")),
            "streak": calculate_streak(klines),
            "latest_kline_date": latest_kline_date,
            "kline_status": kline_status,
            "data_quality": "完整" if kline_status == "ok" else "K线缺失：量比/连续涨跌不可用",
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
        time.sleep(0.15)
        print(f"[{i:02d}/{len(stocks)}] {stock.code} {stock.name} done", file=sys.stderr)
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
        "main_net_yi",
        "main_net_pct",
        "streak",
        "latest_kline_date",
        "kline_status",
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
        "evidence_status",
        "cause_judgement",
        "confidence",
        "evidence_summary",
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
    header = "| 股票 | 异动类型 | 原因分类 | 新闻匹配 | 证据状态 | 判断 | 证据摘要 |\n"
    sep = "|---|---|---|---:|---|---|---|\n"
    body = []
    for row in cause_checks[:limit]:
        summary = row.get("evidence_summary") or row.get("notes", "")
        if len(summary) > 80:
            summary = summary[:80] + "..."
        body.append(
            f"| {md_cell(row['code'])} {md_cell(row['name'])} | {md_cell(row['abnormal_type'])} | {md_cell(row['cause_categories'])} | {md_cell(row.get('matched_news_count', ''))} | {md_cell(row['evidence_status'])} | {md_cell(row['cause_judgement'])} | {md_cell(summary)} |"
        )
    return header + sep + "\n".join(body)


def write_report(
    rows: list[dict[str, Any]],
    cause_checks: list[dict[str, Any]],
    path: Path,
    generated_at: str,
) -> None:
    abnormal = [r for r in rows if r["is_abnormal"] == "是"]
    top = abnormal[:8] if abnormal else rows[:5]
    incomplete = [r for r in rows if r.get("kline_status") != "ok"]
    lines = [
        "# 每日异动监控简报",
        "",
        f"- 生成时间：{generated_at}",
        f"- 股票池数量：{len(rows)}",
        f"- 触发异动数量：{len(abnormal)}",
        f"- K线数据不完整数量：{len(incomplete)}",
        "- 数据源：东方财富公开行情/K线接口",
        "- 说明：本报告用于投研 workflow 测试，不构成投资建议；无来源支持的原因分析均为待核验线索。",
        "",
        "## 一、今日重点异动",
        "",
        markdown_table(abnormal if abnormal else rows),
        "",
        "## 二、个股异动分析",
        "",
    ]
    for row in top:
        amount_ratio_text = "数据缺失" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f} 倍"
        lines.extend(
            [
                f"### {row['code']} {row['name']}",
                "",
                f"- 今日表现：涨跌幅 {pct(row['pct_chg'])}，成交额 {row['amount_yi']} 亿，约为近20日均额 {amount_ratio_text}。",
                f"- 异动类型：{row['abnormal_type']}，置信度：{row['confidence']}。",
                f"- 初步原因线索：{row['reason_hint']}",
                f"- 后续跟踪事项：{row['next_action']}",
                f"- 关键词：{row['keywords']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 三、异动原因核验",
            "",
            cause_markdown_table(cause_checks),
            "",
            "核验顺序：先看公司公告/交易所公告，再看权威财经新闻和公司官方新闻，最后参考行业事件、研报观点和市场评论。",
            "",
            "脚本会自动检索新闻 RSS，并把搜索词、匹配新闻、来源标题/链接和判断写入 `cause_check_YYYY-MM-DD.csv`。即使检索到新闻，也只能先标为线索，需继续核验公告原文和正文。",
            "",
            "## 四、明日重点关注",
            "",
            "1. 优先核验高置信度异动个股是否有公告、政策、行业价格或研报催化。",
            "2. 对连续上涨/下跌个股检查是否存在基本面变化或纯交易性波动。",
            "3. 对放量但涨跌幅不大的个股，关注是否处于事件前置交易或资金换手阶段。",
            "",
        ]
    )
    if incomplete:
        lines.extend(
            [
                "## 五、数据质量提示",
                "",
                "以下股票本次 K 线接口请求失败，实时报价仍可用，但量比/连续涨跌/最新K线日期字段不完整：",
                "",
                "| 股票 | 行业 | 今日涨跌幅 | 说明 |",
                "|---|---|---:|---|",
            ]
        )
        for row in incomplete:
            lines.append(
                f"| {row['code']} {row['name']} | {row['industry']} | {pct(row['pct_chg'])} | {row.get('data_quality', '')} |"
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
    cause_checks = build_cause_checks(
        rows,
        stocks_by_code,
        run_date,
        enable_news_search=not args.skip_news_search,
    )
    write_csv(rows, csv_path)
    write_cause_checks(cause_checks, cause_path)
    write_report(rows, cause_checks, report_path, generated_at)
    print(f"CSV: {csv_path}")
    print(f"CAUSE_CHECK: {cause_path}")
    print(f"REPORT: {report_path}")


if __name__ == "__main__":
    main()
