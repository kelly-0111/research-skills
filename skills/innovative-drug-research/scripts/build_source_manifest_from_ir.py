#!/usr/bin/env python3
"""Build source_manifest seed rows from official company IR page registry."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


URL_FIELDS = [
    ("ir_home_url", "company_official_ir_page", "投资者关系首页", "company_profile;source_discovery"),
    ("financial_reports_url", "company_financial_reports_page", "财务报告", "annual_report;interim_report;pipeline_progress;financials"),
    ("announcements_url", "company_announcements_page", "公告与通函", "announcements;bd;approval;financing;material_events"),
    ("presentations_url", "company_presentations_page", "演示材料", "pipeline_progress;strategy;catalysts;competition"),
    ("monthly_reports_url", "company_ir_monthly_reports_page", "IR月报/周报", "latest_progress;events;catalysts"),
    ("ir_calendar_url", "company_ir_calendar_page", "IR日历", "event_dates;expected_catalysts"),
    ("pipeline_url", "company_pipeline_page", "产品/管线页", "drug_or_pipeline;target;indication;clinical_stage"),
    ("global_collaboration_url", "company_collaboration_page", "全球合作页", "bd;partner;territory;deal_terms"),
    ("news_center_url", "company_news_center_page", "新闻中心", "source_discovery;latest_progress;events"),
    ("company_news_url", "company_news_page", "公司新闻", "latest_progress;clinical_data;conference;guideline;events;verification_leads"),
    ("media_coverage_url", "company_media_coverage_page", "媒体报道", "sentiment;verification_leads"),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def valid_url(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith("http://") or value.startswith("https://")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ir-sources", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    today = dt.date.today().isoformat()
    rows = []
    counter = 1
    for company in read_csv(args.ir_sources):
        company_name = company.get("company_name", "待确认")
        ticker = company.get("ticker", "待确认")
        for field, source_type, label, fields_to_extract in URL_FIELDS:
            url = company.get(field, "")
            if not valid_url(url):
                continue
            rows.append(
                {
                    "source_id": f"IR-{counter:04d}",
                    "source_type": source_type,
                    "source_title": f"{company_name}{label}",
                    "source_path_or_url": url,
                    "publish_date": "待确认",
                    "retrieved_at": today,
                    "source_period": "持续更新页面",
                    "company_name": company_name,
                    "drug_or_pipeline": "待确认",
                    "target": "待确认",
                    "indication": "待确认",
                    "source_confidence": "高",
                    "extract_priority": company.get("priority", "高") or "高",
                    "fields_to_extract": fields_to_extract,
                    "notes": f"官方IR入口；ticker={ticker}；需定期检查页面新增PDF/公告/演示材料",
                }
            )
            counter += 1

    write_csv(
        args.output,
        rows,
        [
            "source_id",
            "source_type",
            "source_title",
            "source_path_or_url",
            "publish_date",
            "retrieved_at",
            "source_period",
            "company_name",
            "drug_or_pipeline",
            "target",
            "indication",
            "source_confidence",
            "extract_priority",
            "fields_to_extract",
            "notes",
        ],
    )
    print(f"source_manifest rows: {len(rows)}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
