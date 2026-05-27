#!/usr/bin/env python3
"""Dependency-free local web portal for investment research workflows."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import math
import mimetypes
import sys
import threading
import traceback
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET


APP_DIR = Path(__file__).resolve().parent
def find_project_root() -> Path:
    candidates = [APP_DIR, APP_DIR.parent, *APP_DIR.parents]
    for candidate in candidates:
        if (candidate / "skills").exists() and (candidate / "templates").exists():
            return candidate
        package = candidate / "investment_research_skills_share_package"
        if (package / "skills").exists() and (package / "templates").exists():
            return package
    raise RuntimeError(
        "没有找到 skills/templates。请确认本工具在 share package 内，或和 "
        "investment_research_skills_share_package 放在同一个总文件夹内。"
    )


ROOT = find_project_root()
SKILLS_DIR = ROOT / "skills"
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = APP_DIR / "outputs"
UPLOAD_DIR = APP_DIR / "uploads"
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    if not spec.loader:
        raise RuntimeError(f"无法加载脚本：{path}")
    spec.loader.exec_module(module)
    return module


stock_monitor = load_module(
    "stock_monitor_skill",
    SKILLS_DIR / "stock-move-monitor" / "scripts" / "run_daily_monitor.py",
)
analyst_converter = load_module(
    "analyst_converter_skill",
    SKILLS_DIR / "analyst-profiler" / "scripts" / "convert_alpha_pai_dataset.py",
)
analyst_scorer = load_module(
    "analyst_scorer_skill",
    SKILLS_DIR / "analyst-profiler" / "scripts" / "score_analysts.py",
)
drug_seed = load_module(
    "drug_seed_skill",
    SKILLS_DIR / "innovative-drug-research" / "scripts" / "build_pipeline_seed.py",
)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_name(filename: str) -> str:
    keep = []
    for ch in filename:
        keep.append(ch if ch.isalnum() or ch in "._-" else "_")
    return "".join(keep) or "upload"


def save_upload(upload: dict[str, Any], prefix: str) -> Path:
    filename = safe_name(upload.get("filename") or f"{prefix}.csv")
    path = UPLOAD_DIR / f"{prefix}_{timestamp()}_{filename}"
    path.write_bytes(upload["content"])
    return path


def xlsx_to_csv_text(path: Path) -> str:
    """Read the first worksheet of a simple .xlsx file using only stdlib."""
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                texts = [node.text or "" for node in si.findall(".//a:t", ns)]
                shared.append("".join(texts))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        first_sheet = workbook.find("a:sheets/a:sheet", ns)
        if first_sheet is None:
            raise ValueError("Excel 文件没有可读取的工作表")
        rel_id = first_sheet.attrib[f"{{{ns['r']}}}id"]
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib["Target"]
                break
        if not target:
            raise ValueError("Excel 文件没有可读取的工作表")
        sheet_path = "xl/" + target.lstrip("/")
        if sheet_path not in zf.namelist():
            sheet_path = "xl/worksheets/sheet1.xml"

        sheet = ET.fromstring(zf.read(sheet_path))
        rows: list[list[str]] = []
        for row in sheet.findall(".//a:sheetData/a:row", ns):
            values: list[str] = []
            last_col = 0
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                col_index = 0
                for ch in col_letters:
                    col_index = col_index * 26 + (ord(ch.upper()) - ord("A") + 1)
                while last_col + 1 < col_index:
                    values.append("")
                    last_col += 1
                raw = cell.findtext("a:v", default="", namespaces=ns)
                if cell.attrib.get("t") == "s" and raw:
                    value = shared[int(raw)]
                elif cell.attrib.get("t") == "inlineStr":
                    texts = [node.text or "" for node in cell.findall(".//a:t", ns)]
                    value = "".join(texts)
                else:
                    value = raw
                values.append(value)
                last_col = col_index
            rows.append(values)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()


def read_tabular_upload(path: Path) -> str:
    if path.suffix.lower() == ".xlsx":
        return xlsx_to_csv_text(path)
    return path.read_text(encoding="utf-8-sig")


def csv_text_to_path(text: str, prefix: str) -> Path:
    path = UPLOAD_DIR / f"{prefix}_{timestamp()}.csv"
    path.write_text(text, encoding="utf-8-sig")
    return path


def output_files(folder: Path) -> list[dict[str, str]]:
    files = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            files.append({"name": path.name, "url": f"/download/{folder.name}/{path.name}"})
    return files


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_tags(value: str) -> list[str]:
    if not value or value == "待确认":
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def count_items(items: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def to_float(value: Any) -> float | None:
    try:
        if value in {"", None, "nan", "NaN"}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def json_safe(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def metric(label: str, value: Any, tone: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "tone": tone}


def compact_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], limit: int = 10) -> dict[str, Any]:
    return {
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": [{key: row.get(key, "") for key, _label in columns} for row in rows[:limit]],
    }


def markdown_preview(path: Path, max_lines: int = 80) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines])


def summarize_cause_for_preview(row: dict[str, Any], cause_by_code: dict[str, dict[str, Any]]) -> str:
    cause = cause_by_code.get(row.get("code", ""))
    if cause:
        status = cause.get("evidence_status", "")
        judgement = cause.get("cause_judgement", "")
        summary = cause.get("evidence_summary") or cause.get("notes") or ""
        if len(summary) > 70:
            summary = summary[:70] + "..."
        return "；".join(part for part in [status, judgement, summary] if part)
    if row.get("is_abnormal") == "是":
        return "已触发异动，但本次未取得有效新闻线索；请查看 cause_check 或人工核验公告。"
    return "未触发异动阈值，未自动搜索新闻。"


def build_stock_preview(rows: list[dict[str, Any]], cause_checks: list[dict[str, Any]], report_path: Path) -> dict[str, Any]:
    abnormal_rows = [row for row in rows if row.get("is_abnormal") == "是"]
    up_rows = [row for row in rows if (to_float(row.get("pct_chg")) or 0) > 0]
    down_rows = [row for row in rows if (to_float(row.get("pct_chg")) or 0) < 0]
    data_rows = [row for row in rows if to_float(row.get("pct_chg")) is not None or to_float(row.get("price")) is not None]
    kline_rows = [row for row in rows if row.get("kline_status") == "ok"]
    amount_ratio_rows = [row for row in rows if to_float(row.get("amount_ratio")) is not None]
    sorted_rows = sorted(rows, key=lambda row: abs(to_float(row.get("pct_chg")) or 0), reverse=True)
    data_tone = "bad" if rows and len(data_rows) == 0 else "warn" if rows and len(data_rows) < len(rows) else "good"
    kline_tone = "bad" if rows and len(kline_rows) == 0 else "warn" if rows and len(kline_rows) < len(rows) else "good"
    amount_tone = "bad" if rows and len(amount_ratio_rows) == 0 else "warn" if rows and len(amount_ratio_rows) < len(rows) else "good"
    cause_by_code = {row.get("code", ""): row for row in cause_checks}
    display_rows = []
    for row in sorted_rows:
        item = dict(row)
        item["cause_summary"] = summarize_cause_for_preview(row, cause_by_code)
        display_rows.append(item)
    return {
        "title": "股票异动监控结果",
        "metrics": [
            metric("自选股", len(rows)),
            metric("行情成功", f"{len(data_rows)}/{len(rows)}", data_tone),
            metric("量比可用", f"{len(amount_ratio_rows)}/{len(rows)}", amount_tone),
            metric("触发异动", len(abnormal_rows), "warn" if abnormal_rows else ""),
            metric("今日上涨", len(up_rows), "good"),
            metric("今日下跌", len(down_rows), "bad"),
        ],
        "secondaryMetrics": [
            metric("K线成功", f"{len(kline_rows)}/{len(rows)}", kline_tone),
            metric("连续涨跌", "可用" if len(kline_rows) == len(rows) else "部分不可用", kline_tone),
        ],
        "tableTitle": "异动明细预览",
        "table": compact_table(
            display_rows,
            [
                ("code", "代码"),
                ("name", "名称"),
                ("pct_chg", "涨跌幅%"),
                ("amount_ratio", "量比"),
                ("amount_ratio_source", "量比来源"),
                ("is_abnormal", "异动"),
                ("abnormal_type", "异动类型"),
                ("confidence", "置信度"),
                ("data_quality", "数据质量"),
                ("cause_summary", "新闻/原因核验"),
            ],
            limit=12,
        ),
        "reportTitle": "日报预览",
        "report": markdown_preview(report_path, 140),
    }


def build_analyst_preview(enriched: list[dict[str, Any]], scorecards: list[dict[str, Any]], report_path: Path) -> dict[str, Any]:
    avg_score_values = [to_float(row.get("overall_score")) for row in scorecards]
    avg_score_values = [value for value in avg_score_values if value is not None]
    profile_types = count_items([row.get("profile_type", "") for row in scorecards if row.get("profile_type")])
    return {
        "title": "卖方研究员画像结果",
        "metrics": [
            metric("观点数", len(enriched)),
            metric("研究员/团队", len(scorecards)),
            metric("平均总分", f"{sum(avg_score_values) / len(avg_score_values):.1f}" if avg_score_values else "NA"),
            metric("主要类型", profile_types[0][0] if profile_types else "NA"),
        ],
        "tableTitle": "研究员评分卡预览",
        "table": compact_table(
            scorecards,
            [
                ("analyst_name", "研究员"),
                ("broker", "券商"),
                ("sector", "行业"),
                ("overall_score", "总分"),
                ("hit_rate", "命中率"),
                ("profile_type", "画像"),
                ("confidence", "置信度"),
                ("caveat", "说明"),
            ],
            limit=12,
        ),
        "reportTitle": "画像报告预览",
        "report": markdown_preview(report_path, 80),
    }


def build_drug_preview(out_dir: Path) -> dict[str, Any]:
    company_rows = read_csv_rows(out_dir / "company_master.csv")
    pipeline_rows = read_csv_rows(out_dir / "pipeline_progress_seed.csv")
    catalyst_rows = read_csv_rows(out_dir / "catalyst_tracker_seed.csv")
    verification_rows = read_csv_rows(out_dir / "verification_queue.csv")
    modality_counts = count_items([tag for row in company_rows for tag in split_tags(row.get("modality_tags", ""))])
    top_modality = modality_counts[0][0] if modality_counts else "待补充"
    display_rows = []
    pipeline_by_company: dict[str, list[dict[str, str]]] = {}
    for row in pipeline_rows:
        pipeline_by_company.setdefault(row.get("company_name", ""), []).append(row)
    for row in company_rows:
        company = row.get("company_name", "")
        pipelines = pipeline_by_company.get(company, [])
        display_rows.append(
            {
                "company_name": company,
                "market": row.get("market", ""),
                "company_type": row.get("company_type", ""),
                "modality_tags": row.get("modality_tags", ""),
                "disease_area_tags": row.get("disease_area_tags", ""),
                "pipeline_count": len(pipelines),
                "next_step": "核验代表管线和催化剂" if not pipelines else "跟踪临床/BD/商业化催化",
            }
        )
    return {
        "title": "创新药分析结果",
        "metrics": [
            metric("覆盖公司", len(company_rows)),
            metric("管线种子", len(pipeline_rows)),
            metric("催化剂线索", len(catalyst_rows)),
            metric("主线标签", top_modality),
        ],
        "tableTitle": "公司池与跟踪优先级预览",
        "table": compact_table(
            display_rows,
            [
                ("company_name", "公司"),
                ("market", "市场"),
                ("company_type", "类型"),
                ("modality_tags", "技术路线"),
                ("disease_area_tags", "适应症"),
                ("pipeline_count", "管线数"),
                ("next_step", "下一步"),
            ],
            limit=12,
        ),
        "reportTitle": "分析报告预览",
        "report": markdown_preview(out_dir / "innovative_drug_analysis_report.md", 90),
        "secondaryMetrics": [metric("待核验事项", len(verification_rows), "warn")],
    }


def write_innovative_drug_analysis(out_dir: Path, source_name: str) -> None:
    company_rows = read_csv_rows(out_dir / "company_master.csv")
    pipeline_rows = read_csv_rows(out_dir / "pipeline_progress_seed.csv")
    catalyst_rows = read_csv_rows(out_dir / "catalyst_tracker_seed.csv")
    verification_rows = read_csv_rows(out_dir / "verification_queue.csv")

    modality_counts = count_items([tag for row in company_rows for tag in split_tags(row.get("modality_tags", ""))])
    disease_counts = count_items([tag for row in company_rows for tag in split_tags(row.get("disease_area_tags", ""))])
    pipeline_by_company: dict[str, list[dict[str, str]]] = {}
    catalyst_by_company: dict[str, list[dict[str, str]]] = {}
    for row in pipeline_rows:
        pipeline_by_company.setdefault(row.get("company_name", ""), []).append(row)
    for row in catalyst_rows:
        catalyst_by_company.setdefault(row.get("company_name", ""), []).append(row)

    hot_modalities = {"ADC", "双抗", "多抗", "GLP-1", "GLP-1RA", "小核酸", "CAR-T", "TCE"}
    watchlist = []
    for row in company_rows:
        company = row.get("company_name", "")
        tags = split_tags(row.get("modality_tags", ""))
        score = 0
        reasons = []
        if company in pipeline_by_company:
            score += 2
            reasons.append("已有可映射管线种子")
        if company in catalyst_by_company:
            score += 2
            reasons.append("已有后续催化剂线索")
        hot_hits = [tag for tag in tags if tag in hot_modalities]
        if hot_hits:
            score += 1
            reasons.append("涉及 " + "/".join(hot_hits))
        if "Biotech" in row.get("company_type", "") or "18A" in row.get("company_type", ""):
            score += 1
            reasons.append("创新药弹性公司")
        watchlist.append((score, company, reasons, row))
    watchlist.sort(key=lambda item: (-item[0], item[1]))

    lines = [
        "# 创新药结构化分析与后续跟踪报告",
        "",
        f"- 生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 输入资料：{source_name}",
        f"- 覆盖公司：{len(company_rows)} 家",
        f"- 已映射管线种子：{len(pipeline_rows)} 条",
        f"- 催化剂线索：{len(catalyst_rows)} 条",
        f"- 待核验公司/事项：{len(verification_rows)} 条",
        "",
        "## 一、核心结论",
        "",
    ]
    if pipeline_rows:
        lines.extend(
            [
                "当前资料已经不只是公司名单，可以初步拆成“公司池、代表管线、靶点/技术路线、后续催化剂、风险点”五层。",
                "但由于输入资料仍偏列表和复盘材料，报告中的上涨逻辑属于基于已输入材料的投研推断，不应视为已验证事实。",
            ]
        )
    else:
        lines.extend(
            [
                "当前资料主要完成公司池识别，缺少足够的药物、靶点、临床阶段和催化剂信息。",
                "这类输出更适合作为资料收集入口，还不能直接支持股价上涨逻辑判断。",
            ]
        )

    lines.extend(["", "## 二、靶点与技术路线分布", ""])
    if modality_counts:
        lines.append("| 技术路线 | 公司数量 | 初步含义 |")
        lines.append("| --- | ---: | --- |")
        for modality, count in modality_counts:
            meaning = "可能对应板块叙事和资金偏好" if modality in hot_modalities else "需结合具体管线质量判断"
            lines.append(f"| {modality} | {count} | {meaning} |")
    else:
        lines.append("输入资料未识别出明确技术路线标签，需要补充管线资料。")

    lines.extend(["", "## 三、适应症方向分布", ""])
    if disease_counts:
        lines.append("| 适应症方向 | 公司数量 | 跟踪重点 |")
        lines.append("| --- | ---: | --- |")
        for disease, count in disease_counts:
            focus = "临床数据、竞争格局、商业化空间"
            lines.append(f"| {disease} | {count} | {focus} |")
    else:
        lines.append("输入资料未识别出明确适应症方向，需要补充药物说明、临床登记或研报。")

    lines.extend(["", "## 四、重点观察公司", ""])
    lines.append("| 优先级 | 公司 | 初步原因 | 代表管线/催化剂 |")
    lines.append("| --- | --- | --- | --- |")
    for score, company, reasons, _row in watchlist[:12]:
        priority = "高" if score >= 4 else "中" if score >= 2 else "待补充"
        pipelines = pipeline_by_company.get(company, [])
        catalysts = catalyst_by_company.get(company, [])
        pipeline_text = "；".join(
            f"{item.get('drug_or_pipeline', '')}({item.get('target', '')})" for item in pipelines[:3]
        )
        catalyst_text = "；".join(item.get("event_summary", "") for item in catalysts[:2])
        combined = " / ".join([part for part in [pipeline_text, catalyst_text] if part]) or "待补充"
        lines.append(f"| {priority} | {company} | {'；'.join(reasons) or '资料不足'} | {combined} |")

    lines.extend(
        [
            "",
            "## 五、医药股上涨逻辑拆解",
            "",
            "| 上涨逻辑 | 当前判断 | 证据/线索 | 后续验证 |",
            "| --- | --- | --- | --- |",
        ]
    )
    event_view = "存在事件催化线索" if catalyst_rows else "暂缺明确催化剂"
    event_evidence = "；".join(
        f"{row.get('company_name', '')}-{row.get('drug_or_pipeline', '')}: {row.get('event_summary', '')}"
        for row in catalyst_rows[:5]
    ) or "需要补充会议、临床读出、BD、NDA/获批等时间表"
    lines.append(f"| 事件催化 | {event_view} | {event_evidence} | 核验公告、临床登记、会议日程、公司交流纪要 |")

    narrative_view = "具备叙事线索" if modality_counts else "待补充"
    narrative_evidence = "；".join(f"{name}({count})" for name, count in modality_counts[:5]) or "未识别"
    lines.append(f"| 叙事变化 | {narrative_view} | 技术路线集中在：{narrative_evidence} | 判断是否对应当期市场主线，如 ADC、双抗、GLP-1、出海 BD |")

    lines.append(
        "| 业绩/商业化兑现 | 待核验 | 已上市或商业化产品需要单独拉销售、医保、放量数据 | 补充收入、适应症放量、海外销售、费用率变化 |"
    )
    lines.append(
        "| 竞争格局改善 | 待核验 | 当前多数竞品信息仍是待补充字段 | 对比同靶点数据、疗效、安全性、入组速度和价格 |"
    )
    lines.append(
        "| 资金轮动 | 暂不能判断 | 当前输入没有行情、成交额、资金流数据 | 需叠加股价、成交额、板块指数和新闻时间线 |"
    )

    lines.extend(
        [
            "",
            "## 六、后续预测与跟踪框架",
            "",
            "| 情景 | 触发条件 | 可能表现 | 跟踪指标 |",
            "| --- | --- | --- | --- |",
            "| 乐观 | 重点管线临床数据超预期、BD/出海落地、商业化放量 | 核心公司先涨，随后扩散到同技术路线或二线标的 | 数据读出、授权金额、销售环比、成交额放大 |",
            "| 中性 | 催化剂兑现但数据普通，板块只有局部主题 | 个股分化，资金更偏确定性管线 | 涨幅持续性、研报上修、机构调仓 |",
            "| 悲观 | 数据不及预期、竞品压制、利好兑现后不涨 | 高弹性标的回撤，板块轮动到其他主题 | 放量滞涨、利好后下跌、同靶点估值下修 |",
            "",
            "## 七、待补充资料",
            "",
        ]
    )
    missing_companies = [row.get("company_name", "") for row in verification_rows[:20]]
    if missing_companies:
        lines.append("- 需要优先补齐管线事实的公司：" + "、".join(missing_companies))
    else:
        lines.append("- 当前输入公司均已有初步管线种子，但仍需逐条核验来源。")
    lines.extend(
        [
            "- 建议补充：公司公告、官网管线页、临床试验登记、最近年报/半年报、卖方深度报告、会议摘要。",
            "- 若要判断“股价上涨逻辑”，还需要叠加行情数据：涨跌幅、成交额、相对医药指数收益、新闻/公告日期。",
            "",
            "## 八、使用边界",
            "",
            "本报告是基于上传材料生成的投研分析框架，已验证事实与推断需要分开使用。没有来源支撑的内容应进入待核验清单，不能直接作为投资结论。",
        ]
    )

    (out_dir / "innovative_drug_analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_multipart(body: bytes, content_type: str) -> dict[str, Any]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("请求格式错误：缺少 boundary")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    boundary_bytes = ("--" + boundary).encode()
    fields: dict[str, Any] = {}
    for part in body.split(boundary_bytes):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip(b"\r\n")
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="replace").split("\r\n")
        disposition = ""
        for header in headers:
            if header.lower().startswith("content-disposition:"):
                disposition = header
                break
        attrs: dict[str, str] = {}
        for chunk in disposition.split(";"):
            if "=" in chunk:
                key, value = chunk.strip().split("=", 1)
                attrs[key] = value.strip().strip('"')
        name = attrs.get("name")
        if not name:
            continue
        if "filename" in attrs:
            fields[name] = {"filename": attrs.get("filename", ""), "content": content}
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields


def run_stock_monitor(fields: dict[str, Any]) -> dict[str, Any]:
    upload = fields.get("file")
    if not upload:
        raise ValueError("请上传自选股 CSV 或 Excel 文件")

    path = save_upload(upload, "stock")
    csv_path = csv_text_to_path(read_tabular_upload(path), "stock_watchlist")
    stocks = stock_monitor.load_watchlist(csv_path)
    if not stocks:
        raise ValueError("自选股文件为空")

    run_date = datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_dir = OUTPUT_DIR / f"stock_{timestamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = stock_monitor.build_rows(stocks)
    stocks_by_code = {stock.code: stock for stock in stocks}
    cause_checks = stock_monitor.build_cause_checks(
        rows,
        stocks_by_code,
        run_date,
        enable_news_search=fields.get("skip_news") != "true",
    )
    report_path = out_dir / f"daily_report_{run_date}.md"
    stock_monitor.write_csv(rows, out_dir / f"daily_monitor_{run_date}.csv")
    stock_monitor.write_cause_checks(cause_checks, out_dir / f"cause_check_{run_date}.csv")
    stock_monitor.write_report(rows, cause_checks, report_path, generated_at)

    abnormal_count = sum(1 for row in rows if row.get("is_abnormal") == "是")
    return {
        "summary": f"已监控 {len(rows)} 只股票，发现 {abnormal_count} 条异动。",
        "files": output_files(out_dir),
        "preview": build_stock_preview(rows, cause_checks, report_path),
    }


def run_analyst_profiler(fields: dict[str, Any]) -> dict[str, Any]:
    upload = fields.get("file")
    if not upload:
        raise ValueError("请上传研究员观点 CSV 或 Excel 文件")

    input_type = fields.get("input_type", "standard")
    path = save_upload(upload, "analyst")
    csv_path = csv_text_to_path(read_tabular_upload(path), "analyst_input")
    out_dir = OUTPUT_DIR / f"analyst_{timestamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if input_type == "alpha":
        converted = out_dir / "analyst_call_log_converted.csv"
        raw_text = csv_path.read_text(encoding="utf-8-sig")
        lines = [line for line in raw_text.splitlines() if line.strip()]
        rows = list(csv.DictReader(lines))
        with converted.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=analyst_converter.OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows([analyst_converter.convert_row(row) for row in rows])
        score_input = converted
    else:
        score_input = csv_path

    rows = analyst_scorer.read_rows(score_input)
    enriched, scorecards = analyst_scorer.build_scorecards(rows)
    analyst_scorer.write_csv(
        out_dir / "analyst_call_log_scored.csv",
        enriched,
        list(enriched[0].keys()) if enriched else [],
    )
    report_path = out_dir / "analyst_profile_report.md"
    analyst_scorer.write_csv(out_dir / "analyst_scorecard.csv", scorecards, analyst_scorer.FIELDS_OUT)
    analyst_scorer.write_report(report_path, scorecards, enriched)

    return {
        "summary": f"已处理 {len(enriched)} 条观点，生成 {len(scorecards)} 个研究员/团队画像。",
        "files": output_files(out_dir),
        "preview": build_analyst_preview(enriched, scorecards, report_path),
    }


def run_drug_research(fields: dict[str, Any]) -> dict[str, Any]:
    upload = fields.get("file")
    if not upload:
        raise ValueError("请上传创新药公司列表 Markdown/TXT 文件")

    path = save_upload(upload, "drug")
    out_dir = OUTPUT_DIR / f"drug_{timestamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    text = path.read_text(encoding="utf-8-sig")
    parsed = drug_seed.parse_markdown_tables(text)
    if not parsed:
        raise ValueError("没有识别到 Markdown 表格，请确认文件格式")

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "build_pipeline_seed.py",
            "--company-list",
            str(path),
            "--out-dir",
            str(out_dir),
        ]
        drug_seed.main()
    finally:
        sys.argv = old_argv

    write_innovative_drug_analysis(out_dir, path.name)

    return {
        "summary": f"已识别 {len(parsed)} 条公司列表记录，并生成结构化表和分析报告。",
        "files": output_files(out_dir),
        "preview": build_drug_preview(out_dir),
    }


class ResearchHandler(BaseHTTPRequestHandler):
    server_version = "ResearchAssistant/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            body = (APP_DIR / "templates" / "index.html").read_bytes()
            self.send_bytes(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/template/"):
            kind = path.rsplit("/", 1)[-1]
            template_path = {
                "stock": TEMPLATE_DIR / "watchlist_template.csv",
                "analyst": TEMPLATE_DIR / "analyst_call_log_template.csv",
                "drug": TEMPLATE_DIR / "company_list_template.md",
            }.get(kind)
            if template_path and template_path.exists():
                self.send_download(template_path)
                return
            self.send_bytes(404, "模板不存在".encode("utf-8"), "text/plain; charset=utf-8")
            return

        if path.startswith("/download/"):
            parts = path.split("/")
            if len(parts) == 4:
                run_id, filename = parts[2], parts[3]
                file_path = OUTPUT_DIR / run_id / filename
                if file_path.exists() and file_path.is_file():
                    self.send_download(file_path)
                    return
            self.send_bytes(404, "文件不存在".encode("utf-8"), "text/plain; charset=utf-8")
            return

        self.send_bytes(404, "页面不存在".encode("utf-8"), "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        try:
            fields = parse_multipart(self.rfile.read(length), content_type)
            if parsed.path == "/api/stock":
                self.send_json(200, run_stock_monitor(fields))
            elif parsed.path == "/api/analyst":
                self.send_json(200, run_analyst_profiler(fields))
            elif parsed.path == "/api/drug":
                self.send_json(200, run_drug_research(fields))
            else:
                self.send_json(404, {"error": "接口不存在"})
        except Exception as exc:
            self.send_json(500, {"error": str(exc), "detail": traceback.format_exc()})

    def send_download(self, path: Path) -> None:
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
        self.send_bytes(200, path.read_bytes(), content_type, headers)


def main() -> None:
    url = "http://127.0.0.1:5199"

    def open_browser() -> None:
        import time

        time.sleep(1)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print("=" * 58)
    print(" 投研助手本地工具已启动")
    print(f" 浏览器将自动打开；如未打开，请访问 {url}")
    print(" 关闭窗口或按 Ctrl+C 即可停止")
    print("=" * 58)
    ThreadingHTTPServer(("127.0.0.1", 5199), ResearchHandler).serve_forever()


if __name__ == "__main__":
    main()
