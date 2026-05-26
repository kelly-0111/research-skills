#!/usr/bin/env python3
"""Score sell-side analyst call logs and generate profile tables."""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


FIELDS_OUT = [
    "analyst_name",
    "broker",
    "sector",
    "call_count",
    "avg_excess_return_pct",
    "avg_directional_return_pct",
    "hit_rate",
    "avg_event_lag_days",
    "avg_depth_score",
    "avg_evidence_score",
    "avg_originality_score",
    "momentum_score",
    "depth_research_score",
    "overall_score",
    "profile_type",
    "confidence",
    "caveat",
]


def as_float(value: Any) -> float:
    try:
        if value in (None, "", "NA", "N/A", "待确认"):
            return math.nan
        return float(value)
    except Exception:
        return math.nan


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            clean = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, float):
                    clean[field] = "" if math.isnan(value) else round(value, 4)
                else:
                    clean[field] = value
            writer.writerow(clean)


def avg(values: list[float]) -> float:
    vals = [v for v in values if not math.isnan(v)]
    return sum(vals) / len(vals) if vals else math.nan


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if math.isnan(value):
        return math.nan
    return min(high, max(low, value))


def score_timeliness(avg_lag: float) -> float:
    if math.isnan(avg_lag):
        return 40.0
    return clamp(100 - max(avg_lag, 0) * 10)


def score_excess(avg_excess: float) -> float:
    if math.isnan(avg_excess):
        return 40.0
    return clamp(50 + avg_excess * 5)


def score_hit_rate(hit_rate: float) -> float:
    if math.isnan(hit_rate):
        return 40.0
    return clamp(hit_rate * 100)


def score_qualitative(value: float) -> float:
    if math.isnan(value):
        return 40.0
    return clamp((value - 1) / 4 * 100)


def profile_type(
    call_count: int,
    momentum_score: float,
    depth_score: float,
    avg_lag: float,
    avg_originality: float,
) -> str:
    if call_count < 3:
        return "样本不足"
    if momentum_score >= 70 and depth_score >= 70:
        return "均衡型"
    if depth_score >= 62 and not math.isnan(avg_originality) and avg_originality >= 3.5 and avg_lag >= 2:
        return "框架驱动型"
    if momentum_score >= 70:
        return "动量快反型"
    if depth_score >= 62:
        return "深度研究型"
    return "跟随型"


def confidence(call_count: int) -> str:
    if call_count >= 10:
        return "高"
    if call_count >= 5:
        return "中"
    return "低"


def add_excess_return(row: dict[str, str]) -> float:
    explicit = as_float(row.get("excess_return_pct"))
    if not math.isnan(explicit):
        return explicit
    fwd = as_float(row.get("forward_return_pct"))
    bench = as_float(row.get("benchmark_return_pct"))
    if math.isnan(fwd) or math.isnan(bench):
        return math.nan
    return fwd - bench


def normalized_call_text(row: dict[str, str]) -> str:
    return " ".join(
        str(row.get(key, "") or "").strip().lower()
        for key in ["call_direction", "rating_action", "notes"]
    )


def call_polarity(row: dict[str, str]) -> str:
    text = normalized_call_text(row)
    bullish_terms = [
        "buy",
        "overweight",
        "outperform",
        "upgrade",
        "positive",
        "bullish",
        "initiate",
        "target_up",
        "看多",
        "买入",
        "增持",
        "推荐",
        "上调",
        "正面",
    ]
    bearish_terms = [
        "sell",
        "underweight",
        "underperform",
        "downgrade",
        "negative",
        "bearish",
        "target_down",
        "看空",
        "卖出",
        "减持",
        "下调",
        "负面",
        "风险提示",
    ]
    neutral_terms = ["neutral", "hold", "maintain", "中性", "持有", "维持"]
    if any(term in text for term in bearish_terms):
        return "bearish"
    if any(term in text for term in bullish_terms):
        return "bullish"
    if any(term in text for term in neutral_terms):
        return "neutral"
    return "unknown"


def directional_return(row: dict[str, str], excess: float) -> float:
    if math.isnan(excess):
        return math.nan
    polarity = call_polarity(row)
    if polarity == "bullish":
        return excess
    if polarity == "bearish":
        return -excess
    if polarity == "neutral":
        return -abs(excess)
    return math.nan


def calc_hit(row: dict[str, str], excess: float) -> float:
    if math.isnan(excess):
        return math.nan
    polarity = call_polarity(row)
    if polarity == "bullish":
        return 1.0 if excess > 0 else 0.0
    if polarity == "bearish":
        return 1.0 if excess < 0 else 0.0
    if polarity == "neutral":
        return 1.0 if abs(excess) <= 2 else 0.0
    return math.nan


def build_scorecards(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        analyst = row.get("analyst_name", "").strip()
        analyst_id = row.get("analyst_id", "").strip()
        group_key = analyst_id or analyst
        if not group_key:
            continue
        broker = row.get("broker", "").strip() or "待确认"
        item = dict(row)
        item["excess_return_pct_calc"] = add_excess_return(row)
        item["directional_return_pct_calc"] = directional_return(row, item["excess_return_pct_calc"])
        item["hit"] = calc_hit(row, item["excess_return_pct_calc"])
        enriched.append(item)
        groups[group_key].append(item)

    scorecards: list[dict[str, Any]] = []
    for group_key, items in groups.items():
        analysts = Counter(item.get("analyst_name", group_key) or group_key for item in items)
        brokers = Counter(item.get("broker", "待确认") for item in items)
        sectors = Counter(item.get("sector", "待确认") for item in items)
        call_count = len(items)
        excess_values = [as_float(item.get("excess_return_pct_calc")) for item in items]
        avg_excess = avg(excess_values)
        directional_values = [as_float(item.get("directional_return_pct_calc")) for item in items]
        avg_directional = avg(directional_values)
        hit_values = [as_float(item.get("hit")) for item in items if not math.isnan(as_float(item.get("hit")))]
        hit_rate = sum(hit_values) / len(hit_values) if hit_values else math.nan
        avg_lag = avg([as_float(item.get("event_lag_days")) for item in items])
        avg_depth = avg([as_float(item.get("depth_score")) for item in items])
        avg_evidence = avg([as_float(item.get("evidence_score")) for item in items])
        avg_originality = avg([as_float(item.get("originality_score")) for item in items])

        momentum = (
            score_timeliness(avg_lag) * 0.35
            + score_excess(avg_directional) * 0.4
            + score_hit_rate(hit_rate) * 0.25
        )
        depth_research = (
            score_qualitative(avg_depth) * 0.45
            + score_qualitative(avg_evidence) * 0.30
            + score_qualitative(avg_originality) * 0.25
        )
        overall = momentum * 0.45 + depth_research * 0.55
        ptype = profile_type(call_count, momentum, depth_research, avg_lag, avg_originality)
        caveat = "样本少，仅作初步画像" if call_count < 5 else "需按行业和市场阶段继续跟踪"

        scorecards.append(
            {
                "analyst_name": analysts.most_common(1)[0][0],
                "broker": brokers.most_common(1)[0][0],
                "sector": sectors.most_common(1)[0][0],
                "call_count": call_count,
                "avg_excess_return_pct": avg_excess,
                "avg_directional_return_pct": avg_directional,
                "hit_rate": hit_rate,
                "avg_event_lag_days": avg_lag,
                "avg_depth_score": avg_depth,
                "avg_evidence_score": avg_evidence,
                "avg_originality_score": avg_originality,
                "momentum_score": momentum,
                "depth_research_score": depth_research,
                "overall_score": overall,
                "profile_type": ptype,
                "confidence": confidence(call_count),
                "caveat": caveat,
            }
        )

    scorecards.sort(key=lambda r: (-as_float(r["overall_score"]), r["analyst_name"]))
    return enriched, scorecards


def write_report(path: Path, scorecards: list[dict[str, Any]], enriched: list[dict[str, Any]]) -> None:
    profile_counts = Counter(row["profile_type"] for row in scorecards)
    lines = [
        "# 卖方研究员画像跟踪报告",
        "",
        f"- 生成日期：{date.today().isoformat()}",
        f"- 研究员数量：{len(scorecards)}",
        f"- 样本数量：{len(enriched)}",
        "- 说明：画像仅用于内部投研 workflow，不作为公开个人评价；样本少时结论需谨慎。",
        "",
        "## 一、画像分布",
        "",
        "| 画像类型 | 数量 |",
        "|---|---:|",
    ]
    for ptype, count in profile_counts.most_common():
        lines.append(f"| {ptype} | {count} |")

    lines.extend(["", "## 二、研究员评分卡", "", "| 研究员 | 券商 | 行业 | 样本 | 动量 | 深度 | 综合 | 画像 | 置信度 |", "|---|---|---|---:|---:|---:|---:|---|---|"])
    for row in scorecards:
        lines.append(
            "| {analyst_name} | {broker} | {sector} | {call_count} | {momentum_score:.1f} | {depth_research_score:.1f} | {overall_score:.1f} | {profile_type} | {confidence} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## 三、后续跟踪",
            "",
            "1. 给样本不足的研究员继续补充历史研报和后验表现。",
            "2. 对同一行业内研究员做横向比较，避免跨行业误判。",
            "3. 对重大事件前后的报告单独复盘，区分快反和事后跟随。",
            "4. 每次新增研报后更新 call log，并保留来源标题或路径。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score sell-side analyst profiles.")
    parser.add_argument("--input", required=True, type=Path, help="Path to analyst_call_log.csv")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    enriched, scorecards = build_scorecards(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "analyst_call_log_scored.csv", enriched, list(enriched[0].keys()) if enriched else [])
    write_csv(args.out_dir / "analyst_scorecard.csv", scorecards, FIELDS_OUT)
    write_report(args.out_dir / "analyst_profile_report.md", scorecards, enriched)
    print(f"call rows: {len(enriched)}")
    print(f"analysts: {len(scorecards)}")
    print(f"out_dir: {args.out_dir}")


if __name__ == "__main__":
    main()
