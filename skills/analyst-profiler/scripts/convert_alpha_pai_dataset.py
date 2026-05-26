#!/usr/bin/env python3
"""Convert Alpha Pai analyst-profiler datasets into analyst_call_log.csv."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any


OUTPUT_FIELDS = [
    "analyst_id",
    "analyst_name",
    "broker",
    "sector",
    "report_date",
    "stock_code",
    "stock_name",
    "rating_action",
    "call_direction",
    "thesis_type",
    "event_lag_days",
    "horizon_days",
    "forward_return_pct",
    "benchmark_return_pct",
    "excess_return_pct",
    "forecast_revision_direction",
    "depth_score",
    "evidence_score",
    "originality_score",
    "source_title",
    "source_path_or_url",
    "notes",
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def map_rating_action(source_type: str) -> str:
    text = source_type.lower()
    if "深度" in text or "推荐" in text:
        return "initiate"
    if "年报" in text or "业绩" in text:
        return "maintain"
    if "点评" in text or "事件" in text:
        return "positive_comment"
    if "周报" in text:
        return "positive_comment"
    return "positive_comment"


def map_thesis_type(row: dict[str, str]) -> str:
    text = " ".join(clean(row.get(key)) for key in ["source_type", "time_sensitivity", "core_thesis", "event_context"])
    if any(word in text for word in ["事件", "获批", "ASCO", "ESMO", "审评", "会议", "BD"]):
        return "event"
    if any(word in text for word in ["年报", "业绩", "收入", "利润", "指引"]):
        return "earnings_revision"
    if any(word in text for word in ["深度", "平台", "估值", "峰值", "市值", "空间"]):
        return "deep_dive"
    if any(word in text for word in ["行业", "赛道", "主题"]):
        return "thematic"
    return "industry_cycle"


def map_event_lag(value: str) -> int:
    text = clean(value)
    if any(word in text for word in ["催化前", "事件前"]):
        return -3
    if any(word in text for word in ["当天", "极近"]):
        return 0
    if "市场主题早期" in text:
        return 3
    if any(word in text for word in ["逆向", "承压"]):
        return 5
    if "趋势形成中" in text:
        return 8
    if any(word in text for word in ["市场反应后", "已有反应", "明显反应", "跟随"]):
        return 12
    return 7


def map_horizon_days(value: str) -> int:
    text = clean(value)
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if not nums:
        return 60
    if "个月" in text:
        return max(nums) * 20
    return max(nums)


def map_score(value: str) -> str:
    text = clean(value)
    if not text:
        return ""
    if any(word in text for word in ["极强", "很强"]):
        return "5"
    if any(word in text for word in ["高", "强"]):
        return "4"
    if any(word in text for word in ["中高", "中强"]):
        return "4"
    if "中低" in text:
        return "2"
    if "中" in text:
        return "3"
    if "低" in text or "弱" in text:
        return "1"
    if "原创" in text and "部分" not in text:
        return "4"
    if "部分原创" in text:
        return "3"
    if "市场共识" in text:
        return "2"
    return "3"


def score_from_originality(row: dict[str, str]) -> str:
    explicit = clean(row.get("originality_score"))
    if explicit:
        return map_score(explicit)
    level = clean(row.get("originality_level"))
    consensus = clean(row.get("consensus_or_contrarian"))
    if "原创" in level and "部分" not in level:
        return "4"
    if "部分原创" in level:
        return "3"
    if "逆向" in consensus:
        return "4"
    if "市场共识" in level:
        return "2"
    return "3"


def score_from_evidence(row: dict[str, str]) -> str:
    explicit = clean(row.get("evidence_quality"))
    if explicit:
        return map_score(explicit)
    if clean(row.get("research_depth")):
        return "3"
    text = " ".join(clean(row.get(key)) for key in ["evidence_used", "core_thesis", "event_context"])
    if any(token in text for token in ["HR", "PFS", "OS", "%", "亿元", "亿美元", "收入", "利润", "市值", "目标"]):
        return "4"
    if len(text) >= 80:
        return "3"
    return "2"


def map_excess_return(row: dict[str, str]) -> str:
    accuracy = clean(row.get("preliminary_accuracy")).lower()
    hindsight = clean(row.get("hindsight_performance"))
    follow = clean(row.get("follow_degree"))

    if accuracy == "correct" or hindsight == "支持":
        base = 8.0
    elif accuracy == "partially correct" or "部分" in hindsight:
        base = 3.0
    elif accuracy == "unclear" or "暂难" in hindsight:
        return ""
    else:
        base = -3.0

    if "领先市场" in follow:
        base += 3
    elif "半步领先" in follow:
        base += 1.5
    elif "明显跟随" in follow:
        base -= 3
    elif "跟随市场" in follow:
        base -= 1.5
    elif "逆向" in follow and "不领先" not in follow:
        base += 0.5
    return f"{base:.1f}"


def map_call_direction(row: dict[str, str]) -> str:
    text = " ".join(clean(row.get(key)) for key in ["original_view", "core_thesis"])
    if any(word in text for word in ["看空", "下调", "承压", "风险"]):
        return "neutral"
    return "bullish"


def map_forecast_revision(row: dict[str, str]) -> str:
    text = " ".join(clean(row.get(key)) for key in ["original_view", "core_thesis"])
    if any(word in text for word in ["上调", "加速", "超预期", "提升", "放量", "盈利"]):
        return "up"
    if any(word in text for word in ["下调", "承压", "下滑"]):
        return "down"
    return "unknown"


def convert_row(row: dict[str, str]) -> dict[str, str]:
    source_type = clean(row.get("source_type"))
    company = clean(row.get("company"))
    date = clean(row.get("date"))
    team_track_id = clean(row.get("team_track_id"))
    analyst_name = clean(row.get("analyst_name")) or "待确认"
    if team_track_id:
        analyst_name = f"{analyst_name} [{team_track_id}]"
    return {
        "analyst_id": team_track_id,
        "analyst_name": analyst_name,
        "broker": clean(row.get("institution")) or "待确认",
        "sector": clean(row.get("sector")) or "待确认",
        "report_date": date,
        "stock_code": clean(row.get("ticker")),
        "stock_name": company,
        "rating_action": map_rating_action(source_type),
        "call_direction": map_call_direction(row),
        "thesis_type": map_thesis_type(row),
        "event_lag_days": str(map_event_lag(clean(row.get("reaction_speed")) or clean(row.get("time_sensitivity")))),
        "horizon_days": str(map_horizon_days(clean(row.get("outcome_window")))),
        "forward_return_pct": "",
        "benchmark_return_pct": "",
        "excess_return_pct": map_excess_return(row),
        "forecast_revision_direction": map_forecast_revision(row),
        "depth_score": map_score(clean(row.get("research_depth"))),
        "evidence_score": score_from_evidence(row),
        "originality_score": score_from_originality(row),
        "source_title": f"{date} {company} {source_type}".strip(),
        "source_path_or_url": clean(row.get("source_link_or_reference")),
        "notes": " | ".join(
            part
            for part in [
                f"原始观点:{clean(row.get('original_view'))}",
                f"核心逻辑:{clean(row.get('core_thesis'))}",
                f"后验:{clean(row.get('subsequent_outcome'))}",
                f"caveat:{clean(row.get('caveat'))}",
                f"AlphaPai标签:{clean(row.get('follow_degree'))}",
            ]
            if part and not part.endswith(":")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Alpha Pai analyst dataset CSV to analyst_call_log.csv.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    raw_text = args.input.read_text(encoding="utf-8-sig")
    lines = [line for line in raw_text.splitlines() if line.strip()]
    rows = list(csv.DictReader(lines))

    converted = [convert_row(row) for row in rows]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(converted)

    print(f"input rows: {len(rows)}")
    print(f"converted rows: {len(converted)}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
