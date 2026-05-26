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


def markdown_table(rows: list[dict[str, Any]], limit: int = 20) -> str:
    header = "| 股票 | 行业 | 涨跌幅 | 成交额(亿) | 量比/20日 | 主力净流入(亿) | 异动类型 | 置信度 |\n"
    sep = "|---|---|---:|---:|---:|---:|---|---|\n"
    body = []
    for row in rows[:limit]:
        amount_ratio = "" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}x"
        body.append(
            "| {code} {name} | {industry} | {pct_chg} | {amount_yi} | {amount_ratio} | {main_net_yi} | {abnormal_type} | {confidence} |".format(
                code=row["code"],
                name=row["name"],
                industry=row["industry"],
                pct_chg=pct(row["pct_chg"]),
                amount_yi=row["amount_yi"],
                amount_ratio=amount_ratio,
                main_net_yi=row["main_net_yi"],
                abnormal_type=row["abnormal_type"],
                confidence=row["confidence"],
            )
        )
    return header + sep + "\n".join(body)


def write_report(rows: list[dict[str, Any]], path: Path, generated_at: str) -> None:
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
        "- 说明：本报告用于投研 workflow 测试，不构成投资建议；原因分析为待核验线索。",
        "",
        "## 一、今日重点异动",
        "",
        markdown_table(abnormal if abnormal else rows),
        "",
        "## 二、个股异动分析",
        "",
    ]
    for row in top:
        amount_ratio_text = "" if math.isnan(row["amount_ratio"]) else f"{row['amount_ratio']:.2f}"
        lines.extend(
            [
                f"### {row['code']} {row['name']}",
                "",
                f"- 今日表现：涨跌幅 {pct(row['pct_chg'])}，成交额 {row['amount_yi']} 亿，约为近20日均额 {amount_ratio_text} 倍。",
                f"- 异动类型：{row['abnormal_type']}，置信度：{row['confidence']}。",
                f"- 初步原因线索：{row['reason_hint']}",
                f"- 后续跟踪事项：{row['next_action']}",
                f"- 关键词：{row['keywords']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 三、明日重点关注",
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
                "## 四、数据质量提示",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_date = datetime.now().strftime("%Y-%m-%d")
    stocks = load_watchlist(args.watchlist)
    rows = build_rows(stocks)
    csv_path = args.output_dir / f"daily_monitor_{run_date}.csv"
    report_path = args.output_dir / f"daily_report_{run_date}.md"
    write_csv(rows, csv_path)
    write_report(rows, report_path, generated_at)
    print(f"CSV: {csv_path}")
    print(f"REPORT: {report_path}")


if __name__ == "__main__":
    main()
