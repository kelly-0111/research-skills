#!/usr/bin/env python3
"""Build first-pass innovative-drug structuring tables from a Markdown company list."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from pathlib import Path


MODALITY_KEYWORDS = [
    "ADC",
    "双抗",
    "多抗",
    "GLP-1",
    "GLP-1RA",
    "小核酸",
    "CAR-T",
    "TCE",
    "PD-1",
    "BTK",
    "生物类似药",
    "抗体",
]

DISEASE_KEYWORDS = [
    "肿瘤",
    "自免",
    "代谢",
    "眼科",
    "神经",
    "中枢神经",
    "糖尿病",
    "减重",
    "血液",
    "乙肝",
    "肝病",
    "罕见病",
    "心血管",
    "肺癌",
]

COMPANY_TYPE_BY_HEADING = {
    "创新药龙头": "Big Pharma",
    "转型创新药企": "转型创新药企",
    "Biotech": "Biotech",
    "Pharma": "Big Pharma",
    "18A Biotech": "18A Biotech",
    "其他港股18A": "18A Biotech/创新药相关",
    "其他A股创新药相关公司": "创新药相关",
}

# High-confidence seed examples from common industry shorthand and the provided list/deck themes.
# These are only a seed; source_confidence is not "高" unless the row is directly supported by source text.
PIPELINE_SEEDS = {
    "百济神州": [
        ("泽布替尼", "BTK", "小分子", "肿瘤/血液瘤", "已上市", "列表提及泽布替尼为全球重磅产品", "销售/适应症拓展进展", "BTK 抑制剂竞争格局待补充", "海外销售、竞争、专利与适应症拓展风险"),
    ],
    "荣昌生物": [
        ("维迪西妥单抗", "HER2", "ADC", "肿瘤", "已上市/待细分", "列表提及 ADC 代表产品维迪西妥单抗", "适应症拓展/BD/临床数据", "HER2 ADC 竞品待补充", "同靶点竞争、商业化和出海不确定性"),
        ("泰它西普", "BLyS/APRIL", "融合蛋白", "自免", "已上市/待细分", "列表提及泰它西普", "适应症拓展/国际合作", "自免领域竞品待补充", "适应症拓展和海外合作不确定性"),
    ],
    "康方生物": [
        ("依沃西单抗", "PD-1/VEGF", "双抗", "肿瘤", "待确认", "列表提及双抗代表产品；复盘材料重点讨论 ASCO/ESMO 数据催化", "ASCO/ESMO 数据披露", "PD-1/VEGF 双抗竞品包括三生、荣昌、君实等待确认", "临床数据不及预期、竞争加剧"),
        ("卡度尼利", "PD-1/CTLA-4", "双抗", "肿瘤", "已上市/待细分", "列表提及卡度尼利", "适应症拓展", "肿瘤免疫双抗竞品待补充", "商业化和适应症竞争风险"),
    ],
    "信达生物": [
        ("IBI363", "PD-1/IL-2α-bias", "融合蛋白/免疫疗法", "肿瘤", "待确认", "复盘材料列为 2026 年重要数据验证品种", "临床数据读出", "同类 IL-2/免疫疗法竞品待补充", "数据证伪风险"),
        ("IBI343", "CLDN18.2", "ADC", "肿瘤", "待确认", "复盘材料提及与武田 BD 合作组合", "BD 后续/临床数据", "CLDN18.2 ADC 竞品待补充", "适应症竞争和数据风险"),
        ("IBI3001", "EGFR/B7H3", "ADC", "肿瘤", "待确认", "复盘材料提及与武田 BD 合作组合", "BD 后续/临床数据", "EGFR/B7H3 ADC 竞品待补充", "早期项目不确定性"),
    ],
    "百利天恒": [
        ("BL-B01D1", "EGFR/HER3", "ADC/双抗ADC", "肿瘤", "待确认", "列表提及 BL-B01D1 全球重磅 BD", "临床数据/BD 后续", "EGFR/HER3 ADC 竞品待补充", "数据兑现与合作推进风险"),
    ],
    "诺诚健华": [
        ("奥布替尼", "BTK", "小分子", "肿瘤/自免待确认", "已上市/待细分", "列表提及 BTK 抑制剂奥布替尼", "适应症拓展", "BTK 抑制剂竞品待补充", "竞争和商业化风险"),
    ],
    "君实生物": [
        ("特瑞普利单抗", "PD-1", "抗体", "肿瘤", "已上市/待细分", "列表提及 PD-1 特瑞普利单抗", "海外/适应症拓展", "PD-1 竞争拥挤", "价格、商业化和海外推进风险"),
    ],
    "艾力斯": [
        ("伏美替尼", "EGFR", "小分子", "肺癌", "已上市/待细分", "列表提及肺癌三代 EGFR-TKI", "适应症拓展", "EGFR-TKI 竞品待补充", "竞争和生命周期管理风险"),
    ],
}

BD_DEAL_SEEDS = {
    "康诺亚": [
        {
            "drug_or_pipeline": "CM326",
            "target": "TSLP",
            "modality": "单抗",
            "partner": "石药集团",
            "territory": "待确认",
            "deal_type": "commercialization partnership/待确认",
            "announcement_date": "待确认",
            "signing_date": "待确认",
            "effective_date": "待确认",
            "closing_date": "待确认",
            "upfront_payment": "待确认",
            "milestone_value": "待确认",
            "equity_or_option_terms": "待确认",
            "covered_indications": "中重度哮喘; 慢性鼻窦炎伴鼻息肉; 特应性皮炎",
            "latest_progress": "AlphaPai旧样例提及CM326与石药集团合作；需用公告或公司材料核验交易条款",
            "latest_update_date": "待确认",
            "next_milestone": "合作后续进展/适应症推进",
            "next_milestone_date_or_window": "待确认",
            "source_confidence": "低",
            "verification_notes": "核验合作公告、授权区域、付款结构和覆盖适应症",
        },
        {
            "drug_or_pipeline": "CM512",
            "target": "TSLP×IL-13",
            "modality": "双抗",
            "partner": "Belenos Biosciences",
            "territory": "海外/待确认",
            "deal_type": "out-license/待确认",
            "announcement_date": "待确认",
            "signing_date": "待确认",
            "effective_date": "待确认",
            "closing_date": "待确认",
            "upfront_payment": "1500万美元",
            "milestone_value": "1.7亿美元",
            "equity_or_option_terms": "Belenos约30%股权",
            "covered_indications": "慢性鼻窦炎伴鼻息肉; 特应性皮炎; 哮喘; COPD; 慢性自发性荨麻疹",
            "latest_progress": "AlphaPai旧样例提及首付款、里程碑和股权安排；需用公告核验",
            "latest_update_date": "待确认",
            "next_milestone": "临床进展/海外合作推进/里程碑触发",
            "next_milestone_date_or_window": "待确认",
            "source_confidence": "低",
            "verification_notes": "核验公告日期、授权区域、里程碑口径和股权安排",
        },
        {
            "drug_or_pipeline": "CM336",
            "target": "BCMA×CD3",
            "modality": "双抗",
            "partner": "Ouro Medicines",
            "territory": "海外/待确认",
            "deal_type": "out-license/待确认",
            "announcement_date": "待确认",
            "signing_date": "待确认",
            "effective_date": "待确认",
            "closing_date": "待确认",
            "upfront_payment": "1600万美元",
            "milestone_value": "最高6.1亿美元",
            "equity_or_option_terms": "待确认",
            "covered_indications": "复发/难治性多发性骨髓瘤; AIHA; ITP; 轻链型淀粉样变性; 自免血细胞减少症; 干燥综合征/炎症性肌病",
            "latest_progress": "AlphaPai旧样例提及首付款和里程碑；需用公告核验",
            "latest_update_date": "待确认",
            "next_milestone": "临床进展/合作推进/里程碑触发",
            "next_milestone_date_or_window": "待确认",
            "source_confidence": "低",
            "verification_notes": "核验公告日期、授权区域和覆盖适应症",
        },
    ],
    "信达生物": [
        {
            "drug_or_pipeline": "IBI343; IBI3001",
            "target": "CLDN18.2; EGFR/B7H3",
            "modality": "ADC",
            "partner": "武田/待确认",
            "territory": "待确认",
            "deal_type": "BD合作/待确认",
            "announcement_date": "待确认",
            "signing_date": "待确认",
            "effective_date": "待确认",
            "closing_date": "待确认",
            "upfront_payment": "待确认",
            "milestone_value": "待确认",
            "equity_or_option_terms": "待确认",
            "covered_indications": "肿瘤",
            "latest_progress": "复盘材料提及与武田BD合作组合；需用公告核验",
            "latest_update_date": "待确认",
            "next_milestone": "BD后续/临床数据",
            "next_milestone_date_or_window": "待确认",
            "source_confidence": "低",
            "verification_notes": "核验合作方、交易金额、授权区域和具体资产",
        }
    ],
}


def clean_cell(cell: str) -> str:
    cell = re.sub(r"<[^>]+>", "", cell)
    return re.sub(r"\s+", " ", cell.replace("&nbsp;", " ")).strip()


def parse_markdown_tables(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current_type = "待确认"
    current_section = ""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("###"):
            current_section = stripped.lstrip("#").strip()
            for key, value in COMPANY_TYPE_BY_HEADING.items():
                if key in current_section:
                    current_type = value
                    break
        if not stripped.startswith("|"):
            continue
        cells = [clean_cell(c) for c in stripped.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in {"序号", "---"} or set(cells[0]) <= {"-", " "}:
            continue
        if not cells[0].isdigit():
            continue
        company = cells[1]
        ticker = cells[2]
        if len(cells) >= 5:
            core = cells[4]
        else:
            core = cells[3]
        rows.append(
            {
                "company_name": company,
                "tickers_raw": ticker,
                "company_type": current_type,
                "section": current_section,
                "core_fields_raw": core,
            }
        )
    return rows


def market_from_ticker(ticker: str) -> str:
    markets = []
    if ".SH" in ticker or ".SZ" in ticker:
        markets.append("A股")
    if ".HK" in ticker:
        markets.append("港股")
    if "美股" in ticker or "BGNE" in ticker:
        markets.append("美股")
    if not markets:
        return "待确认"
    return "/".join(dict.fromkeys(markets))


def tags_from_text(text: str, keywords: list[str]) -> str:
    found = [kw for kw in keywords if kw.lower() in text.lower()]
    return ";".join(dict.fromkeys(found)) if found else "待确认"


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-list", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-name", default="")
    args = parser.parse_args()

    today = dt.date.today().isoformat()
    source_name = args.source_name.strip() or f"上传公司列表：{args.company_list.name}"
    text = args.company_list.read_text(encoding="utf-8")
    parsed = parse_markdown_tables(text)

    company_rows = []
    seen = set()
    for row in parsed:
        key = (row["company_name"], row["tickers_raw"])
        if key in seen:
            continue
        seen.add(key)
        company_rows.append(
            {
                "company_name": row["company_name"],
                "tickers_raw": row["tickers_raw"],
                "market": market_from_ticker(row["tickers_raw"]),
                "company_type": row["company_type"],
                "core_fields_raw": row["core_fields_raw"],
                "modality_tags": tags_from_text(row["core_fields_raw"], MODALITY_KEYWORDS),
                "disease_area_tags": tags_from_text(row["core_fields_raw"], DISEASE_KEYWORDS),
                "priority_reason": "来自创新药上市公司列表；需按管线进一步核验",
                "first_seen_date": today,
                "last_checked_at": today,
                "source": source_name,
                "updated_at": today,
            }
        )

    pipeline_rows = []
    company_names = {row["company_name"] for row in company_rows}
    for company, seeds in PIPELINE_SEEDS.items():
        if company not in company_names:
            continue
        for drug, target, modality, indication, stage, progress, catalyst, landscape, risks in seeds:
            pipeline_rows.append(
                {
                    "company_name": company,
                    "drug_or_pipeline": drug,
                    "target": target,
                    "modality": modality,
                    "indication": indication,
                    "clinical_stage": stage,
                    "latest_progress": progress,
                    "progress_date": "待确认",
                    "next_catalyst": catalyst,
                    "next_catalyst_date_or_window": "待确认",
                    "competitive_landscape": landscape,
                    "risks": risks,
                    "source": source_name,
                    "source_confidence": "中",
                    "last_verified_at": today,
                    "verification_notes": "用公告/官网/临床登记/研报继续核验阶段、适应症和最新进展",
                    "updated_at": today,
                }
            )

    verification_rows = []
    seeded_companies = set(PIPELINE_SEEDS)
    for row in company_rows:
        if row["company_name"] not in seeded_companies:
            verification_rows.append(
                {
                    "company_name": row["company_name"],
                    "missing_item": "药物/管线、靶点、适应症、临床阶段、最新进展",
                    "suggested_next_source": "公司官网/年报/公告/临床试验登记/券商深度报告",
                    "opened_at": today,
                    "target_check_date": "待确认",
                    "resolved_at": "待确认",
                    "source": source_name,
                    "updated_at": today,
                }
            )

    catalyst_rows = []
    for row in pipeline_rows:
        catalyst = row["next_catalyst"]
        if catalyst and catalyst != "待确认":
            catalyst_rows.append(
                {
                    "date_or_window": "待确认",
                    "announced_date": "待确认",
                    "expected_date_or_window": "待确认",
                    "actual_date": "待确认",
                    "company_name": row["company_name"],
                    "drug_or_pipeline": row["drug_or_pipeline"],
                    "catalyst_type": "临床数据/BD/会议/适应症拓展",
                    "event_summary": catalyst,
                    "status": "待确认",
                    "result": "待确认",
                    "expected_impact": "用于后续管线进展更新和竞争格局判断",
                    "source": source_name,
                    "updated_at": today,
                }
            )

    bd_rows = []
    for company, seeds in BD_DEAL_SEEDS.items():
        if company not in company_names:
            continue
        for seed in seeds:
            bd_rows.append(
                {
                    "company_name": company,
                    **seed,
                    "source": source_name,
                    "last_verified_at": today,
                    "updated_at": today,
                }
            )

    write_csv(
        args.out_dir / "company_master.csv",
        company_rows,
        [
            "company_name",
            "tickers_raw",
            "market",
            "company_type",
            "core_fields_raw",
            "modality_tags",
            "disease_area_tags",
            "priority_reason",
            "first_seen_date",
            "last_checked_at",
            "source",
            "updated_at",
        ],
    )
    write_csv(
        args.out_dir / "pipeline_progress_seed.csv",
        pipeline_rows,
        [
            "company_name",
            "drug_or_pipeline",
            "target",
            "modality",
            "indication",
            "clinical_stage",
            "latest_progress",
            "progress_date",
            "next_catalyst",
            "next_catalyst_date_or_window",
            "competitive_landscape",
            "risks",
            "source",
            "source_confidence",
            "last_verified_at",
            "verification_notes",
            "updated_at",
        ],
    )
    write_csv(
        args.out_dir / "catalyst_tracker_seed.csv",
        catalyst_rows,
        [
            "date_or_window",
            "announced_date",
            "expected_date_or_window",
            "actual_date",
            "company_name",
            "drug_or_pipeline",
            "catalyst_type",
            "event_summary",
            "status",
            "result",
            "expected_impact",
            "source",
            "updated_at",
        ],
    )
    write_csv(
        args.out_dir / "bd_deal_tracker_seed.csv",
        bd_rows,
        [
            "company_name",
            "drug_or_pipeline",
            "target",
            "modality",
            "partner",
            "territory",
            "deal_type",
            "announcement_date",
            "signing_date",
            "effective_date",
            "closing_date",
            "upfront_payment",
            "milestone_value",
            "equity_or_option_terms",
            "covered_indications",
            "latest_progress",
            "latest_update_date",
            "next_milestone",
            "next_milestone_date_or_window",
            "source",
            "source_confidence",
            "last_verified_at",
            "verification_notes",
            "updated_at",
        ],
    )
    write_csv(
        args.out_dir / "verification_queue.csv",
        verification_rows,
        [
            "company_name",
            "missing_item",
            "suggested_next_source",
            "opened_at",
            "target_check_date",
            "resolved_at",
            "source",
            "updated_at",
        ],
    )

    print(f"company_master rows: {len(company_rows)}")
    print(f"pipeline_progress_seed rows: {len(pipeline_rows)}")
    print(f"catalyst_tracker_seed rows: {len(catalyst_rows)}")
    print(f"bd_deal_tracker_seed rows: {len(bd_rows)}")
    print(f"verification_queue rows: {len(verification_rows)}")
    print(f"out_dir: {args.out_dir}")


if __name__ == "__main__":
    main()
