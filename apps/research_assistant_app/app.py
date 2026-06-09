#!/usr/bin/env python3
"""Dependency-free local web portal for investment research workflows."""

from __future__ import annotations

import csv
import contextlib
import importlib.util
import io
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import zipfile
from collections import Counter
from datetime import datetime
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.sax.saxutils import escape as xml_escape_raw
from xml.etree import ElementTree as ET


APP_DIR = Path(__file__).resolve().parent
def find_project_root() -> Path:
    candidates = [APP_DIR, *APP_DIR.parents]
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
DATA_DIR = ROOT / "data"
OUTPUT_DIR = APP_DIR / "outputs"
UPLOAD_DIR = APP_DIR / "uploads"
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

ALPHAPAI_SKILL_DIR = Path.home() / ".codex" / "skills" / "alphapai-research"
ALPHAPAI_CLIENT = ALPHAPAI_SKILL_DIR / "scripts" / "alphapai_client.py"
ALPHAPAI_CONFIG = ALPHAPAI_SKILL_DIR / "config.json"
ALPHAPAI_RECALL_START_DATE = "2025-01-01"
ALPHAPAI_BD_RECALL_START_DATE = "2000-01-01"
ALPHAPAI_RECALL_TYPES = "ann,report,roadShow,roadShow_ir,social_media"


@contextlib.contextmanager
def temporary_env(key: str, value: str):
    old_value = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


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
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename) or "upload"


def save_upload(upload: dict[str, Any], prefix: str) -> Path:
    filename = safe_name(upload.get("filename") or f"{prefix}.csv")
    path = UPLOAD_DIR / f"{prefix}_{timestamp()}_{filename}"
    path.write_bytes(upload["content"])
    return path


def _read_xlsx_sheets(path: Path, max_rows: int | None = None) -> list[tuple[str, list[list[str]]]]:
    """Read worksheet values from a simple .xlsx file using only stdlib."""
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
        rel_targets = {rel.attrib.get("Id", ""): rel.attrib.get("Target", "") for rel in rels}
        sheets: list[tuple[str, list[list[str]]]] = []
        for sheet_info in workbook.findall("a:sheets/a:sheet", ns):
            sheet_name = sheet_info.attrib.get("name", "Sheet")
            rel_id = sheet_info.attrib.get(f"{{{ns['r']}}}id", "")
            target = rel_targets.get(rel_id, "")
            if not target:
                continue
            sheet_path = "xl/" + target.lstrip("/")
            if sheet_path not in zf.namelist():
                continue
            sheet = ET.fromstring(zf.read(sheet_path))
            rows: list[list[str]] = []
            raw_rows = sheet.findall(".//a:sheetData/a:row", ns)
            for row in raw_rows[:max_rows] if max_rows is not None else raw_rows:
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
            sheets.append((sheet_name, rows))
    return sheets


def xlsx_to_csv_text(path: Path) -> str:
    """Read the first worksheet of a simple .xlsx file using only stdlib."""
    sheets = _read_xlsx_sheets(path)
    if not sheets:
        raise ValueError("Excel 文件没有可读取的工作表")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(sheets[0][1])
    return buf.getvalue()


def xlsx_sheet_rows(path: Path, max_rows: int = 500) -> list[tuple[str, list[list[str]]]]:
    return _read_xlsx_sheets(path, max_rows=max_rows)


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
            item = {"name": path.name, "url": f"/download/{folder.name}/{path.name}"}
            if path.suffix.lower() in {".xlsx", ".csv", ".md", ".txt", ".html"}:
                item["preview_url"] = f"/preview/{folder.name}/{path.name}"
            files.append(item)
    return files


def output_bundle(folder: Path) -> dict[str, str]:
    return {"name": f"{folder.name}.zip", "url": f"/download-zip/{folder.name}"}


def output_folder_for_run(run_id: str) -> Path | None:
    if not re.match(r"^[A-Za-z0-9_\-]+$", run_id or ""):
        return None
    folder = (OUTPUT_DIR / run_id).resolve()
    try:
        folder.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None
    return folder if folder.exists() and folder.is_dir() else None


def build_output_zip(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.iterdir()):
            if path.is_file():
                zf.write(path, arcname=path.name)
    return buffer.getvalue()


def html_table(rows: list[list[str]]) -> str:
    if not rows:
        return '<div class="empty">暂无数据</div>'
    max_cols = max((len(row) for row in rows), default=1)
    body = []
    for row_idx, row in enumerate(rows):
        tag = "th" if row_idx == 0 else "td"
        cells = []
        for col_idx in range(max_cols):
            value = row[col_idx] if col_idx < len(row) else ""
            cells.append(f"<{tag}>{html_escape(str(value))}</{tag}>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(body)}</table>"


def render_file_preview(path: Path) -> bytes:
    suffix = path.suffix.lower()
    title = html_escape(path.name)
    download_url = "#"
    if path.parent.parent == OUTPUT_DIR:
        download_url = f"/download/{path.parent.name}/{path.name}"
    style = """
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#18202f;background:#f6f7f9}
    header{position:sticky;top:0;z-index:2;display:flex;gap:12px;align-items:center;padding:12px 16px;background:#fff;border-bottom:1px solid #d9dee7}
    h1{font-size:16px;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    a{color:#2563eb;text-decoration:none;font-weight:650}
    main{padding:16px}
    .sheet{margin:0 0 18px;background:#fff;border:1px solid #d9dee7;border-radius:8px;overflow:hidden}
    .sheet h2{font-size:14px;margin:0;padding:10px 12px;background:#fbfcfe;border-bottom:1px solid #d9dee7}
    .table-wrap{overflow:auto;max-height:78vh}
    table{border-collapse:collapse;width:max-content;min-width:100%;font-size:13px}
    th,td{border:1px solid #e5e7eb;padding:7px 9px;vertical-align:top;max-width:520px;white-space:pre-wrap;word-break:break-word}
    th{position:sticky;top:0;background:#1f5a95;color:#fff;z-index:1}
    pre{white-space:pre-wrap;word-break:break-word;background:#fff;border:1px solid #d9dee7;border-radius:8px;padding:14px;line-height:1.55}
    .empty{padding:14px;color:#667085}
    """
    if suffix == ".xlsx":
        sections = []
        for sheet_name, rows in xlsx_sheet_rows(path):
            sections.append(
                '<section class="sheet">'
                f"<h2>{html_escape(sheet_name)}</h2>"
                f'<div class="table-wrap">{html_table(rows)}</div>'
                "</section>"
            )
        content = "".join(sections) or '<div class="empty">Excel 文件没有可预览工作表。</div>'
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))[:500]
        content = f'<section class="sheet"><div class="table-wrap">{html_table(rows)}</div></section>'
    elif suffix in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        content = f"<pre>{html_escape(text)}</pre>"
    elif suffix == ".html":
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    else:
        content = '<div class="empty">该文件类型暂不支持网页预览，请下载查看。</div>'
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title><style>{style}</style></head><body>"
        f"<header><h1>{title}</h1><a href=\"{html_escape(download_url)}\">下载原文件</a></header>"
        f"<main>{content}</main></body></html>"
    )
    return html.encode("utf-8")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def company_pool_candidates() -> list[Path]:
    candidates = [DATA_DIR / "innovative_drug_company_pool.md"]
    extra_paths = os.environ.get("INNOVATIVE_DRUG_COMPANY_POOL_PATHS", "")
    for raw_path in extra_paths.split(os.pathsep):
        raw_path = raw_path.strip()
        if raw_path:
            candidates.append(Path(raw_path).expanduser())
    return candidates


def load_drug_company_pool() -> list[dict[str, str]]:
    seen: set[str] = set()
    companies: list[dict[str, str]] = []
    for path in company_pool_candidates():
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
            rows = drug_seed.parse_markdown_tables(text)
        except Exception:
            continue
        for row in rows:
            name = row.get("company_name", "").strip()
            ticker = row.get("tickers_raw", "").strip()
            if not name:
                continue
            key = name
            if key in seen:
                continue
            seen.add(key)
            core = row.get("core_fields_raw", "")
            companies.append(
                {
                    "company_name": name,
                    "ticker": ticker,
                    "market": drug_seed.market_from_ticker(ticker),
                    "company_type": row.get("company_type", "待确认"),
                    "section": row.get("section", ""),
                    "core_fields_raw": core,
                    "modality_tags": drug_seed.tags_from_text(core, drug_seed.MODALITY_KEYWORDS),
                    "disease_area_tags": drug_seed.tags_from_text(core, drug_seed.DISEASE_KEYWORDS),
                    "source": str(path),
                }
            )
    return companies


def normalize_company_name(name: str) -> str:
    return (
        (name or "")
        .replace("-B", "")
        .replace("－B", "")
        .replace("—B", "")
        .replace(" ", "")
        .strip()
    )


def build_company_list_markdown(companies: list[dict[str, str]]) -> str:
    groups: dict[str, list[dict[str, str]]] = {}
    for company in companies:
        market = company.get("market") or "待确认"
        if "港股" in market and "A股" not in market:
            group = "港股创新药公司"
        elif "美股" in market and "A股" not in market and "港股" not in market:
            group = "美股创新药公司"
        elif "A股" in market:
            group = "A股创新药公司"
        else:
            group = "其他创新药公司"
        groups.setdefault(group, []).append(company)

    lines = ["# 内置公司池选择", ""]
    for group in ["A股创新药公司", "港股创新药公司", "美股创新药公司", "其他创新药公司"]:
        rows = groups.get(group, [])
        if not rows:
            continue
        lines.extend([f"## {group}", "", "| 序号 | 公司名称 | 股票代码 | 核心领域 |", "| --- | --- | --- | --- |"])
        for idx, company in enumerate(rows, start=1):
            lines.append(
                "| {idx} | {name} | {ticker} | {core} |".format(
                    idx=idx,
                    name=company.get("company_name", ""),
                    ticker=company.get("ticker", ""),
                    core=(company.get("core_fields_raw", "") or "待确认").replace("|", "/"),
                )
            )
        lines.append("")
    return "\n".join(lines)


def split_tags(value: str) -> list[str]:
    if not value or value == "待确认":
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def count_items(items: list[str]) -> list[tuple[str, int]]:
    return sorted(Counter(item for item in items if item).items(), key=lambda pair: (-pair[1], pair[0]))


def to_float(value: Any) -> float | None:
    try:
        if value in {"", None, "nan", "NaN"}:
            return None
        parsed = float(value)
        if math.isnan(parsed):
            return None
        return parsed
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


def excel_col_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def xml_escape(value: Any) -> str:
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", str(value))
    return xml_escape_raw(text)


_STAGE_LEVELS: list[tuple[tuple[str, ...], int, int]] = [
    (("已上市",), 90, 2),
    (("NDA", "BLA"), 80, 3),
    (("III", "Ⅲ"), 70, 4),
    (("I/II", "Ⅰ/Ⅱ"), 55, 6),
    (("II", "Ⅱ"), 60, 5),
    (("Ib", "Ia", "I期", "Ⅰ期", "I"), 50, 6),
    (("IND",), 30, 7),
    (("研究者",), 20, 7),
    (("临床前",), 10, 7),
]


def _stage_info(value: Any) -> tuple[int, int]:
    text = str(value or "").strip()
    if not text or text == "待确认":
        return 0, 0
    for keywords, rank, style_id in _STAGE_LEVELS:
        for keyword in keywords:
            if (keyword == "I" and text == "I") or (keyword != "I" and keyword in text):
                return rank, style_id
    return 0, 0


def stage_style_id(value: Any) -> int:
    return _stage_info(value)[1]


def sheet_header_row_index(rows: list[list[Any]]) -> int:
    if len(rows) >= 3 and rows[0] and rows[1]:
        first = str(rows[0][0] or "")
        second = str(rows[1][0] or "")
        if "创新药管线" in first and (not second or "数据更新日期" in second):
            return 3
    return 1


def stage_column_indexes(rows: list[list[Any]]) -> set[int]:
    if not rows:
        return set()
    header_idx = sheet_header_row_index(rows) - 1
    if header_idx >= len(rows):
        return set()
    indexes = set()
    for idx, header in enumerate(rows[header_idx]):
        text = str(header or "")
        if "研发阶段" in text or "最高研发阶段" in text:
            indexes.add(idx)
    return indexes


def excel_display_width(value: Any) -> int:
    text = "" if value is None else str(value)
    width = 0
    for ch in text:
        if ch in "\r\n":
            width = max(width, 8)
        elif ord(ch) > 127:
            width += 2
        else:
            width += 1
    return width


def adaptive_column_widths(rows: list[list[Any]]) -> list[float]:
    if not rows:
        return [12.0]
    max_cols = max((len(row) for row in rows), default=1)
    widths: list[float] = []
    long_text_headers = {
        "最新进展", "下一里程碑", "来源", "核验说明",
        "事件内容", "预期影响", "BD交易金额", "股权/期权/分成条款", "覆盖适应症",
        "待核验事项", "建议来源", "代表管线", "来源类型/具体来源", "source_note",
        "最新进展/下一节点", "来源/核验",
    }
    medium_text_headers = {"BD交易金额/结构", "交易类型/关键日期", "最新进展/下一节点", "来源/核验", "覆盖适应症"}
    compact_headers = {"公司名称", "治疗领域", "靶点", "项目编号", "药物类型", "研发阶段", "最高研发阶段", "置信度"}
    for col_idx in range(max_cols):
        header_row = sheet_header_row_index(rows) - 1
        header = str(rows[header_row][col_idx] if rows and header_row < len(rows) and col_idx < len(rows[header_row]) else "")
        observed = [excel_display_width(row[col_idx]) for row in rows[header_row:header_row + 120] if col_idx < len(row)]
        raw = max(observed or [len(header), 8])
        if header in medium_text_headers:
            width = min(max(raw * 0.62 + 2, 16), 32)
        elif header in long_text_headers or raw > 50:
            width = min(max(raw * 0.72 + 2, 20), 58)
        elif header in compact_headers:
            width = min(max(raw * 0.95 + 2, 10), 18)
        else:
            width = min(max(raw * 0.9 + 2, 10), 28)
        widths.append(round(width, 1))
    return widths


def estimated_row_height(row: list[Any], widths: list[float], is_header: bool = False) -> float:
    if is_header:
        return 24.0
    max_lines = 1
    for idx, value in enumerate(row):
        text = "" if value is None else str(value)
        if not text:
            continue
        width_chars = max(int((widths[idx] if idx < len(widths) else 14) * 1.3), 8)
        text_lines = text.count("\n") + 1
        wrapped = max(1, math.ceil(excel_display_width(text) / width_chars))
        line_cap = 14 if excel_display_width(text) > 90 else 8
        max_lines = max(max_lines, min(max(text_lines, wrapped), line_cap))
    return min(18.0 * max_lines, 252.0)


def bold_column_indexes(rows: list[list[Any]], sheet_name: str) -> set[int]:
    if sheet_name != "催化剂追踪":
        return set()
    header_idx = sheet_header_row_index(rows) - 1
    if header_idx >= len(rows):
        return set()
    return {
        idx
        for idx, header in enumerate(rows[header_idx])
        if str(header or "") in {"药物/管线", "药物/项目编号"}
    }


def worksheet_xml(rows: list[list[Any]], sheet_name: str = "", freeze_header: bool = True) -> str:
    stage_cols = stage_column_indexes(rows)
    bold_cols = bold_column_indexes(rows, sheet_name)
    header_row = sheet_header_row_index(rows)
    widths = adaptive_column_widths(rows)
    max_cols = max((len(row) for row in rows), default=1)
    cols_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(widths, start=1)
    )
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            ref = f"{excel_col_name(col_idx)}{row_idx}"
            text = "" if value is None else str(value)
            if header_row == 3 and row_idx in {1, 2} and col_idx > 1:
                continue
            if row_idx == 1 and header_row == 3:
                style_id = 8
            elif row_idx == 2 and header_row == 3:
                style_id = 9
            elif row_idx == header_row:
                style_id = 1
            else:
                if (col_idx - 1) in stage_cols:
                    style_id = stage_style_id(value)
                elif (col_idx - 1) in bold_cols and text:
                    style_id = 10
                else:
                    style_id = 0
            style = f' s="{style_id}"' if style_id else ""
            cells.append(
                f'<c r="{ref}" t="inlineStr"{style}><is><t>{xml_escape(text)}</t></is></c>'
            )
        height = estimated_row_height(row, widths, row_idx == header_row)
        sheet_rows.append(f'<row r="{row_idx}" ht="{height:.1f}" customHeight="1">{"".join(cells)}</row>')
    freeze_split = header_row
    freeze_top_left = f"A{header_row + 1}"
    pane = (
        '<sheetViews><sheetView workbookViewId="0">'
        f'<pane ySplit="{freeze_split}" topLeftCell="{freeze_top_left}" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        if freeze_header and rows
        else '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    )
    max_rows = max(len(rows), 1)
    dimension = f"A1:{excel_col_name(max_cols)}{max_rows}"
    filter_ref = f"A{header_row}:{excel_col_name(max_cols)}{max_rows}"
    merge_xml = ""
    if header_row == 3 and max_cols > 1:
        last_col = excel_col_name(max_cols)
        merge_xml = (
            '<mergeCells count="2">'
            f'<mergeCell ref="A1:{last_col}1"/>'
            f'<mergeCell ref="A2:{last_col}2"/>'
            '</mergeCells>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        f"{pane}"
        '<sheetFormatPr defaultRowHeight="18"/>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        f'<autoFilter ref="{filter_ref}"/>'
        f"{merge_xml}"
        '</worksheet>'
    )


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    safe_sheets = [(name[:31], rows or [["暂无数据"]]) for name, rows in sheets]
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for idx in range(1, len(safe_sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append("</Types>")

    workbook_sheets = []
    workbook_rels = []
    for idx, (name, _rows) in enumerate(safe_sheets, start=1):
        workbook_sheets.append(
            f'<sheet name="{xml_escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        )
        workbook_rels.append(
            f'<Relationship Id="rId{idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
        )
    workbook_rels.append(
        f'<Relationship Id="rId{len(safe_sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheets)}</sheets>'
        '</workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(workbook_rels)}'
        '</Relationships>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="5">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="14"/><color rgb="FF1F5A95"/><name val="Calibri"/></font>'
        '<font><i/><sz val="10"/><color rgb="FF666666"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="9">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F5A95"/><bgColor rgb="FF1F5A95"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/><bgColor rgb="FFC6EFCE"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFB7D7E8"/><bgColor rgb="FFB7D7E8"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFBDD7EE"/><bgColor rgb="FFBDD7EE"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor rgb="FFFFF2CC"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFCE4D6"/><bgColor rgb="FFFCE4D6"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E6E6"/><bgColor rgb="FFE7E6E6"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="11">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="5" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="6" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="7" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="8" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment wrapText="1" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment wrapText="1" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment wrapText="1" vertical="top"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="0"/><tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        for idx, (name, rows) in enumerate(safe_sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", worksheet_xml(rows, name))


def split_drug_project(value: str) -> tuple[str, str]:
    text = (value or "").strip()
    if not text:
        return "", ""
    if "(" in text and text.endswith(")"):
        before, _, after = text.rpartition("(")
        project = after[:-1].strip()
        return before.strip() or text, project or before.strip() or text
    return text, text


def stage_rank(stage: str) -> int:
    return _stage_info(stage)[0]


def choose_highest_stage(stages: list[str]) -> str:
    clean = [stage for stage in stages if stage and stage != "待确认"]
    if not clean:
        return "待确认"
    return sorted(clean, key=lambda item: (-stage_rank(item), item))[0]


PIPELINE_FIELDNAMES = [
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
]

CATALYST_FIELDNAMES = [
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
]

BD_FIELDNAMES = [
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
]

SOURCE_MANIFEST_FIELDNAMES = [
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
]

VERIFICATION_FIELDNAMES = [
    "company_name",
    "missing_item",
    "suggested_next_source",
    "opened_at",
    "target_check_date",
    "resolved_at",
    "source",
    "updated_at",
]

ALPHAPAI_PIPELINE_PATTERNS = [
    {
        "companies": ["康方生物", "康方"],
        "aliases": ["依沃西", "AK112", "ivonescimab", "依达方"],
        "drug": "依沃西单抗(AK112)",
        "target": "PD-1/VEGF",
        "modality": "双抗",
        "indications": ["肺癌/NSCLC", "胃癌/胃食管结合部癌", "结直肠癌"],
        "partners": ["Summit", "GSK"],
    },
    {
        "companies": ["康方生物", "康方"],
        "aliases": ["卡度尼利", "AK104", "开坦尼"],
        "drug": "卡度尼利(AK104)",
        "target": "PD-1/CTLA-4",
        "modality": "双抗",
        "indications": ["宫颈癌", "胃癌/胃食管结合部癌"],
        "partners": [],
    },
    {
        "companies": ["康方生物", "康方"],
        "aliases": ["AK117", "莱法利", "CD47"],
        "drug": "莱法利单抗(AK117)",
        "target": "CD47",
        "modality": "单抗",
        "indications": ["待细分适应症"],
        "partners": [],
    },
    {
        "companies": ["康方生物", "康方"],
        "aliases": ["AK146D1", "Trop2", "Nectin4"],
        "drug": "AK146D1",
        "target": "Trop2/Nectin4",
        "modality": "ADC/双抗ADC",
        "indications": ["待细分适应症"],
        "partners": [],
    },
    {
        "companies": ["康方生物", "康方"],
        "aliases": ["AK138D1", "HER3"],
        "drug": "AK138D1",
        "target": "HER3",
        "modality": "ADC",
        "indications": ["待细分适应症"],
        "partners": [],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM310", "司普奇拜", "康悦达", "IL-4R"],
        "drug": "司普奇拜单抗(CM310)",
        "target": "IL-4Rα",
        "modality": "单抗",
        "indications": ["特应性皮炎", "青少年/儿童特应性皮炎", "慢性鼻窦炎伴鼻息肉", "季节性过敏性鼻炎", "结节性痒疹", "哮喘"],
        "partners": ["石药集团"],
        "listed": True,
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM512", "TSLP/IL-13", "TSLP-IL-13", "TSLP x IL-13", "TSLP×IL-13"],
        "drug": "CM512",
        "target": "TSLP×IL-13",
        "modality": "双抗",
        "indications": ["特应性皮炎", "慢性鼻窦炎伴鼻息肉", "哮喘", "COPD", "慢性自发性荨麻疹"],
        "partners": ["Belenos Biosciences"],
        "deal_upfront": "1500万美元",
        "deal_milestone": "1.7亿美元",
        "deal_equity": "Belenos约30%股权",
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CMG901", "AZD0901", "Claudin 18.2", "CLDN18.2"],
        "drug": "CMG901/AZD0901(CMG901)",
        "target": "CLDN18.2",
        "modality": "ADC",
        "indications": ["胃癌/胃食管结合部癌", "胰腺癌", "胆道癌"],
        "partners": ["阿斯利康(AstraZeneca)"],
        "deal_upfront": "6300万美元",
        "deal_milestone": "最高11.25亿美元",
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM518", "CM518D1", "CDH17"],
        "drug": "CM518D1",
        "target": "CDH17",
        "modality": "ADC",
        "indications": ["胃癌/胃食管结合部癌", "胰腺癌", "待细分适应症"],
        "partners": [],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM336", "BCMA×CD3", "BCMAxCD3", "BCMA x CD3", "BCMA/CD3", "BCMA-CD3"],
        "drug": "CM336",
        "target": "BCMA×CD3",
        "modality": "双抗",
        "indications": ["复发/难治性多发性骨髓瘤(RRMM)", "多发性骨髓瘤", "轻链型淀粉样变性", "干燥综合征", "系统性硬化症", "系统性红斑狼疮"],
        "partners": ["Ouro Medicines", "吉利德科学"],
        "deal_upfront": "1600万美元/二次交易约2.5亿美元",
        "deal_milestone": "最高6.1亿美元/二次交易最高约7000万美元",
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM313", "CD38"],
        "drug": "CM313",
        "target": "CD38",
        "modality": "单抗",
        "indications": ["原发免疫性血小板减少症", "待细分适应症"],
        "partners": ["Timberlyne Therapeutics"],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM355", "ICP-B02", "CD20×CD3", "CD20xCD3", "CD20 x CD3", "CD20/CD3", "CD20-CD3"],
        "drug": "CM355/ICP-B02(CM355)",
        "target": "CD20×CD3",
        "modality": "双抗",
        "indications": ["系统性硬化症", "系统性红斑狼疮", "待细分适应症"],
        "partners": ["Prolium Biosciences"],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM369", "ICP-B05", "CCR8"],
        "drug": "CM369/ICP-B05(CM369)",
        "target": "CCR8",
        "modality": "单抗",
        "indications": ["晚期实体瘤", "非霍奇金淋巴瘤", "待细分适应症"],
        "partners": ["诺诚健华"],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM380", "GPRC5D"],
        "drug": "CM380",
        "target": "GPRC5D×CD3",
        "modality": "双抗",
        "indications": ["多发性骨髓瘤", "待细分适应症"],
        "partners": [],
    },
    {
        "companies": ["康诺亚", "康诺亚-B"],
        "aliases": ["CM326", "TSLP抗体", "TSLP 单抗"],
        "drug": "CM326",
        "target": "TSLP",
        "modality": "单抗",
        "indications": ["哮喘", "COPD", "慢性鼻窦炎伴鼻息肉", "特应性皮炎"],
        "partners": ["石药集团"],
    },
    {
        "companies": ["乐普生物", "乐普生物-B"],
        "aliases": ["CMG901", "AZD0901", "Claudin 18.2", "CLDN18.2"],
        "drug": "CMG901/AZD0901(CMG901)",
        "target": "CLDN18.2",
        "modality": "ADC",
        "indications": ["胃癌/胃食管结合部癌", "胰腺癌", "胆道癌"],
        "partners": ["阿斯利康(AstraZeneca)"],
        "deal_upfront": "6300万美元",
        "deal_milestone": "最高11.25亿美元",
    },
    {
        "companies": ["乐普生物", "乐普生物-B"],
        "aliases": ["普佑恒", "普特利单抗", "PD-1"],
        "drug": "普特利单抗",
        "target": "PD-1",
        "modality": "单抗",
        "indications": ["待细分适应症"],
        "partners": [],
    },
]


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def append_unique_csv(path: Path, new_rows: list[dict[str, Any]], fieldnames: list[str], key_fields: list[str]) -> int:
    existing = read_csv_rows(path)
    seen = {tuple(str(row.get(field, "")) for field in key_fields) for row in existing}
    added = 0
    for row in new_rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        if not any(key) or key in seen:
            continue
        existing.append(row)
        seen.add(key)
        added += 1
    write_dict_csv(path, existing, fieldnames)
    return added


def alphapai_is_configured() -> bool:
    if not ALPHAPAI_CLIENT.exists() or not ALPHAPAI_CONFIG.exists():
        return False
    try:
        config = json.loads(ALPHAPAI_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(config.get("api_key"))


def alphapai_company_context(company: str) -> dict[str, list[str]]:
    context = {
        "aliases": [company],
        "projects": [],
        "partners": [],
        "topics": ["创新药", "管线", "靶点", "适应症", "研发阶段", "最新进展", "BD", "年报", "研报", "路演"],
    }
    if "康方" in company:
        context["aliases"].extend(["康方生物", "康方生物-B", "Akeso", "09926.HK", "9926.HK"])
        context["projects"].extend(["依沃西", "AK112", "卡度尼利", "AK104"])
        context["partners"].extend(["Summit", "GSK", "ASCO", "ESMO"])
    if "康诺亚" in company:
        context["aliases"].extend(["康诺亚", "康诺亚-B", "Keymed", "02162.HK", "2162.HK"])
        context["projects"].extend(["CM310", "康悦达", "司普奇拜单抗", "CM512", "CMG901", "AZD0901", "CM336", "CM313", "CM355", "CM518D1"])
        context["partners"].extend(["阿斯利康", "AstraZeneca", "Ouro", "吉利德", "Gilead", "Belenos", "Timberlyne", "Prolium", "石药"])
    if "乐普" in company:
        context["aliases"].extend(["乐普生物", "乐普生物-B", "Lepu Biopharma", "02157.HK", "2157.HK"])
        context["projects"].extend(["CMG901", "MRG004A", "MRG006A", "普特利单抗", "ADC", "PD-1"])
        context["partners"].extend(["阿斯利康", "AstraZeneca"])
    return {key: list(dict.fromkeys(value)) for key, value in context.items()}


def alphapai_recall_queries(company: str) -> list[dict[str, str]]:
    context = alphapai_company_context(company)
    alias_text = " ".join(context["aliases"][:6])
    project_text = " ".join(context["projects"][:10])
    partner_text = " ".join(context["partners"][:8])
    base = f"{alias_text} {project_text}".strip()
    queries = [
        {
            "label": "pipeline_recent",
            "query": f"{base} 创新药 管线 靶点 适应症 研发阶段 最新进展 年报 研报 路演",
            "start_date": ALPHAPAI_RECALL_START_DATE,
        },
        {
            "label": "commercial_recent",
            "query": f"{base} 2025年报 2024年报 年度报告 业绩会 管理层 路演 商业化 销售 医保",
            "start_date": ALPHAPAI_RECALL_START_DATE,
        },
        {
            "label": "bd_full_history",
            "query": f"{base} {partner_text} 历史BD license-out NewCo 授权 合作 首付款 里程碑 交易金额 权益区域",
            "start_date": ALPHAPAI_BD_RECALL_START_DATE,
        },
        {
            "label": "clinical_catalyst_recent",
            "query": f"{base} 临床数据 读出 NDA BLA IND 催化剂 2026",
            "start_date": ALPHAPAI_RECALL_START_DATE,
        },
        {
            "label": "valuation_recent",
            "query": f"{base} 估值 盈利预测 DCF 目标价 收入 毛利率 销售费用",
            "start_date": ALPHAPAI_RECALL_START_DATE,
        },
    ]
    cleaned = []
    for item in queries:
        query = re.sub(r"\s+", " ", item["query"]).strip()
        if query:
            cleaned.append({**item, "query": query})
    return cleaned


def alphapai_run_recall_query(query: str, start_date: str = ALPHAPAI_RECALL_START_DATE) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ALPHAPAI_CLIENT),
        "recall",
        "--query",
        query,
        "--type",
        ALPHAPAI_RECALL_TYPES,
        "--start",
        start_date,
        "--json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "AlphaPai recall failed").strip())
    json_start = result.stdout.find("{")
    if json_start < 0:
        raise RuntimeError("AlphaPai recall 没有返回 JSON")
    return json.loads(result.stdout[json_start:])


def alphapai_recall_company(company: str, out_dir: Path) -> list[dict[str, Any]]:
    merged_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    query_payloads: list[dict[str, Any]] = []
    for idx, query_spec in enumerate(alphapai_recall_queries(company), start=1):
        query = query_spec["query"]
        start_date = query_spec.get("start_date", ALPHAPAI_RECALL_START_DATE)
        label = query_spec.get("label", "recall")
        payload = alphapai_run_recall_query(query, start_date=start_date)
        raw_path = out_dir / f"alphapai_recall_{safe_name(company)}_{idx:02d}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        data = payload.get("data", [])
        if not isinstance(data, list):
            data = []
        query_payloads.append(
            {
                "query": query,
                "query_label": label,
                "start_date": start_date,
                "types": ALPHAPAI_RECALL_TYPES,
                "item_count": len(data),
                "raw_file": raw_path.name,
            }
        )
        for item in data:
            if not isinstance(item, dict):
                continue
            item["_alphapai_query_label"] = label
            item["_alphapai_query_start_date"] = start_date
            item_id = str(item.get("id") or "")
            key = item_id or f"{item.get('type','')}|{item.get('title','')}|{item.get('time','')}"
            if key in seen:
                continue
            seen.add(key)
            merged_items.append(item)
    combined_payload = {
        "company": company,
        "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query_strategy": query_payloads,
        "data": merged_items,
    }
    raw_path = out_dir / f"alphapai_recall_{safe_name(company)}.json"
    raw_path.write_text(json.dumps(combined_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged_items


def alphapai_deep_research_company(company: str, out_dir: Path) -> dict[str, Any]:
    context = alphapai_company_context(company)
    alias_text = " / ".join(context["aliases"][:6])
    project_text = "、".join(context["projects"][:10]) or "核心创新药管线"
    question = (
        f"请基于AlphaPai可检索到的公告、年报/中报、券商研报、路演纪要和公开新闻，"
        f"生成{alias_text}的创新药管线与投资价值底稿。重点覆盖："
        f"1）{project_text}等核心资产的药物-靶点-适应症-阶段-最新进展；"
        "2）BD/license-out/NewCo交易、合作方、金额和权益，BD需覆盖成立以来/上市以来可检索的全部历史交易，不限近两年；"
        "3）商业化、医保、销售放量、收入利润假设；"
        "4）2026年临床/注册催化剂，以及历史BD交易后的后续里程碑；"
        "5）竞争格局、估值逻辑、行情验证需要关注的数据。"
        "请保留关键时间、数字、来源线索，不要只给泛泛总结。"
    )
    cmd = [
        sys.executable,
        str(ALPHAPAI_CLIENT),
        "qa",
        "--question",
        question,
        "--mode",
        "Think",
        "--start",
        ALPHAPAI_RECALL_START_DATE,
        "--json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "AlphaPai QA Think failed").strip())
    json_start = result.stdout.find("{")
    if json_start < 0:
        raise RuntimeError("AlphaPai QA Think 没有返回 JSON")
    payload = json.loads(result.stdout[json_start:])
    raw_path = out_dir / f"alphapai_deep_research_{safe_name(company)}.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    answer = str(payload.get("answer") or payload.get("data", {}).get("answer") or "")
    references = payload.get("references") or payload.get("data", {}).get("references") or []
    lines = [
        f"# AlphaPai深度投研底稿：{company}",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 检索起始日期：{ALPHAPAI_RECALL_START_DATE}",
        f"- 模式：QA Think",
        "",
        answer or "（AlphaPai未返回正文）",
    ]
    if isinstance(references, list) and references:
        lines.extend(["", "## 引用来源"])
        for idx, ref in enumerate(references, start=1):
            if not isinstance(ref, dict):
                lines.append(f"{idx}. {ref}")
                continue
            title = ref.get("title") or ref.get("sourceTitle") or ref.get("docTitle") or "未命名来源"
            date = ref.get("publishDate") or ref.get("time") or ref.get("date") or ""
            source_type = ref.get("type") or ref.get("sourceType") or ""
            lines.append(f"{idx}. {title} {date} {source_type}".strip())
    md_path = out_dir / f"alphapai_deep_research_{safe_name(company)}.md"
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"raw": raw_path.name, "markdown": md_path.name, "references": len(references) if isinstance(references, list) else 0}


def item_text(item: dict[str, Any]) -> str:
    chunks = item.get("chunks") or []
    if not isinstance(chunks, list):
        chunks = [str(chunks)]
    parts = [item.get("title", ""), item.get("contextInfo", ""), *[str(chunk) for chunk in chunks]]
    return "\n".join(part for part in parts if part)


def pattern_relevant_text(item: dict[str, Any], aliases: list[str]) -> str:
    chunks = item.get("chunks") or []
    if not isinstance(chunks, list):
        chunks = [str(chunks)]
    header = str(item.get("title", ""))
    lower_aliases = [alias.lower() for alias in aliases]
    relevant = []
    for chunk in chunks:
        chunk_text = str(chunk)
        lower_chunk = chunk_text.lower()
        windows = []
        for alias in lower_aliases:
            pos = lower_chunk.find(alias)
            while pos >= 0:
                start = max(0, pos - 180)
                end = min(len(chunk_text), pos + len(alias) + 700)
                windows.append(chunk_text[start:end])
                pos = lower_chunk.find(alias, pos + len(alias))
        if windows:
            relevant.extend(windows[:3])
    if not relevant and any(alias in header.lower() for alias in lower_aliases):
        relevant = [
            str(chunk) for chunk in chunks[:2]
            if any(alias in str(chunk).lower() for alias in lower_aliases)
        ]
    return "\n".join([header, *relevant]).strip()


def project_section_text(item: dict[str, Any], pattern: dict[str, Any]) -> str:
    """Return project-level sections so one drug's indications do not borrow facts from neighbors."""
    chunks = item.get("chunks") or []
    if not isinstance(chunks, list):
        chunks = [str(chunks)]
    aliases = [str(alias) for alias in pattern.get("aliases", []) if str(alias).strip()]
    if not aliases:
        return ""
    lower_aliases = [alias.lower() for alias in aliases]
    section_starts = [
        r"(?:^|\n|\s)[•·●]\s*(?:CM|AK|MRG|ICP|PRO)[A-Za-z0-9/.-]+",
        r"(?:^|\n|\s)(?:截至本報告日期，|截至本报告日期，)?(?:CM|AK|MRG)\d{3,}[A-Za-z0-9/.-]*",
    ]
    sections: list[str] = []
    for chunk in chunks:
        chunk_text = str(chunk)
        lower_chunk = chunk_text.lower()
        positions: list[int] = []
        for alias in lower_aliases:
            pos = lower_chunk.find(alias)
            while pos >= 0:
                positions.append(pos)
                pos = lower_chunk.find(alias, pos + max(1, len(alias)))
        for pos in sorted(set(positions))[:4]:
            start = pos
            marker_matches = [
                match for section_pattern in section_starts
                for match in re.finditer(section_pattern, chunk_text[:pos], flags=re.IGNORECASE)
            ]
            if marker_matches and pos - marker_matches[-1].start() <= 80:
                start = marker_matches[-1].start()
            end = len(chunk_text)
            for section_pattern in section_starts:
                match = re.search(section_pattern, chunk_text[pos + 1:], flags=re.IGNORECASE)
                if match:
                    candidate = pos + 1 + match.start()
                    marker = chunk_text[candidate:candidate + 80].lower()
                    if not any(alias in marker for alias in lower_aliases):
                        end = min(end, candidate)
            section = chunk_text[start:end].strip()
            if section and section not in sections:
                sections.append(section)
    if not sections:
        return pattern_relevant_text(item, aliases)
    return "\n".join([str(item.get("title", "")), *sections]).strip()


def evidence_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return [part.strip() for part in re.split(r"(?<=[。；;.!?？])|\n", clean) if part.strip()]


def evidence_sentence(text: str, aliases: list[str], indication: str = "") -> str:
    sentences = evidence_sentences(text)
    lower_aliases = [alias.lower() for alias in aliases]
    with_alias = [sentence for sentence in sentences if any(alias in sentence.lower() for alias in lower_aliases)]
    if indication:
        exact = [
            sentence for sentence in with_alias
            if any(term.lower() in sentence.lower() for term in indication_terms(indication))
        ]
        if exact:
                return exact[0]
    return with_alias[0] if with_alias else ""


def indication_stage_context(text: str, aliases: list[str], indication: str) -> str:
    sentences = evidence_sentences(text)
    if not sentences:
        return text or ""
    lower_aliases = [alias.lower() for alias in aliases]
    terms = [term.lower() for term in indication_terms(indication)]
    scored: list[tuple[int, int]] = []
    for idx, sentence in enumerate(sentences):
        lower = sentence.lower()
        has_indication = any(term in lower for term in terms)
        if not has_indication:
            continue
        score = 10
        if any(alias in lower for alias in lower_aliases):
            score += 10
        if detect_stage(sentence) != "待确认":
            score += 5
        scored.append((score, idx))
    if not scored:
        return evidence_sentence(text, aliases, indication) or evidence_sentence(text, aliases) or text
    _score, idx = sorted(scored, key=lambda item: (-item[0], item[1]))[0]
    start = max(0, idx - 1)
    end = min(len(sentences), idx + 2)
    return " ".join(sentences[start:end])


def other_pipeline_alias_hits(text: str, current_pattern: dict[str, Any]) -> list[str]:
    lower = (text or "").lower()
    current_aliases = {alias.lower() for alias in current_pattern.get("aliases", [])}
    hits: list[str] = []
    for pattern in ALPHAPAI_PIPELINE_PATTERNS:
        if pattern is current_pattern:
            continue
        for alias in pattern.get("aliases", []):
            alias_text = str(alias).strip()
            alias_lower = alias_text.lower()
            if len(alias_text) < 4 or alias_lower in current_aliases:
                continue
            if alias_lower in lower:
                hits.append(str(pattern.get("drug", alias_text)))
                break
    return list(dict.fromkeys(hits))


def indication_terms(indication: str) -> list[str]:
    mapping = {
        "复发/难治性多发性骨髓瘤(RRMM)": ["复发/难治性多发性骨髓瘤", "复发或难治性多发性骨髓瘤", "復發或難治性多發性骨髓瘤", "RRMM", "R/R MM"],
        "多发性骨髓瘤": ["多发性骨髓瘤", "多發性骨髓瘤", "multiple myeloma", "MM"],
        "胃癌/胃食管结合部癌": ["胃癌", "胃食管", "GC/AEG", "GEJ"],
        "慢性鼻窦炎伴鼻息肉": ["慢性鼻窦炎伴鼻息肉", "慢性鼻竇炎伴鼻息肉", "CRSwNP", "CRSw NP", "鼻息肉"],
        "季节性过敏性鼻炎": ["季节性过敏性鼻炎", "季節性過敏性鼻炎", "SAR"],
        "特应性皮炎": ["特应性皮炎", "特應性皮炎", "atopic dermatitis"],
        "青少年/儿童特应性皮炎": ["青少年中重度AD", "儿童中重度AD", "青少年特应性皮炎", "儿童特应性皮炎"],
        "结节性痒疹": ["结节性痒疹", "結節性癢疹", "PN"],
        "胰腺癌": ["胰腺癌", "胰臟癌"],
        "胆道癌": ["胆道癌", "膽道癌", "胆管癌", "膽管癌"],
        "系统性硬化症": ["系统性硬化症", "系統性硬化症", "SSc"],
        "系统性红斑狼疮": ["系统性红斑狼疮", "系統性紅斑狼瘡", "SLE"],
        "原发免疫性血小板减少症": ["原发免疫性血小板减少症", "原發免疫性血小板減少症", "免疫性血小板减少症", "ITP"],
        "轻链型淀粉样变性": ["轻链型淀粉样变性", "輕鏈型澱粉樣變性", "原發性輕鏈型澱粉樣變性", "AL"],
        "非霍奇金淋巴瘤": ["非霍奇金淋巴瘤", "非霍奇金淋巴瘤", "B-NHL", "NHL"],
        "晚期实体瘤": ["晚期实体瘤", "晚期實體瘤", "实体瘤", "實體瘤"],
    }
    return mapping.get(indication, [indication])


def stage_match_spans(text: str) -> list[tuple[int, int, str]]:
    checks = [
        (r"获批上市|獲批上市|批准上市|已上市|納入醫保|纳入医保|获NMPA批准|獲NMPA批准|上市申请.{0,30}批准|上市申請.{0,30}批准|已获批|已獲批|获批治疗|獲批治療|适应症.{0,20}获批|適應症.{0,20}獲批|获批该适应症|獲批該適應症|獲批", "已上市"),
        (r"BLA|NDA|sNDA|上市申请|新药上市申请|获受理|优先审评|申报上市|递交全球上市申请", "NDA/BLA"),
        (r"(?<!I)III\s*期|Ⅲ\s*期|三期|3\s*期|注册性临床", "III期"),
        (r"I/II\s*期|Ⅰ/Ⅱ\s*期|1/2\s*期", "I/II期"),
        (r"(?<!I)II\s*期|Ⅱ\s*期|二期|2\s*期", "II期"),
        (r"(?<!I)I\s*期|Ⅰ\s*期|一期|1\s*期", "I期"),
        (r"IND|临床试验申请|申报临床", "IND申报"),
        (r"研究者发起|研究者發起|探索性研究|IIT", "研究者发起"),
    ]
    spans: list[tuple[int, int, str]] = []
    for pattern, stage in checks:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            spans.append((match.start(), match.end(), stage))
    return spans


def detect_stage_for_indication(text: str, indication: str) -> str:
    if not text:
        return "待确认"
    sentences = evidence_sentences(text)
    terms = [term.lower() for term in indication_terms(indication)]
    for sentence in sentences:
        lower_sentence = sentence.lower()
        if any(term in lower_sentence for term in terms) and any(word in sentence for word in ["研究者发起", "研究者發起", "探索性研究", "IIT"]):
            return "研究者发起"
    term_positions = [
        match.start()
        for term in indication_terms(indication)
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE)
    ]
    spans = stage_match_spans(text)
    if term_positions and spans:
        ranked: list[tuple[int, int, str]] = []
        for pos in term_positions:
            for span_start, _span_end, stage in spans:
                ranked.append((abs(pos - span_start), span_start, stage))
        distance, _span_start, stage = sorted(ranked, key=lambda item: (item[0], item[1]))[0]
        if distance <= 140:
            return stage
    return detect_stage(text)


def stage_supported_for_indication(text: str, indication: str, stage: str) -> bool:
    if not text or not indication or stage == "待确认":
        return False
    term_positions = [
        match.start()
        for term in indication_terms(indication)
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE)
    ]
    if not term_positions:
        return False
    spans = [span for span in stage_match_spans(text) if span[2] == stage]
    if not spans:
        return False
    if stage == "已上市" and any(word in text for word in ["适应症相继获批", "三大适应症", "获批上市", "批准上市"]):
        return True
    return any(abs(pos - span_start) <= 90 for pos in term_positions for span_start, _span_end, _stage in spans)


def source_confidence(source_type: str) -> str:
    if source_type in {"ann", "roadShow_ir"}:
        return "高"
    if source_type in {"report", "roadShow"}:
        return "中"
    return "低"


def clip_text(text: str, limit: int = 220) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean if len(clean) <= limit else clean[:limit].rstrip() + "..."


def detect_stage(text: str) -> str:
    checks = [
        (r"获批上市|獲批上市|批准上市|已上市|納入醫保|纳入医保|获NMPA批准|獲NMPA批准|上市申请.{0,30}批准|上市申請.{0,30}批准|已获批|已獲批|获批治疗|獲批治療|适应症.{0,20}获批|適應症.{0,20}獲批|获批该适应症|獲批該適應症|獲批", "已上市"),
        (r"BLA|NDA|sNDA|上市申请|新药上市申请|获受理|优先审评|申报上市|递交全球上市申请", "NDA/BLA"),
        (r"(?<!I)III\s*期|Ⅲ\s*期|三期|3\s*期|注册性临床", "III期"),
        (r"I/II\s*期|Ⅰ/Ⅱ\s*期|1/2\s*期", "I/II期"),
        (r"(?<!I)II\s*期|Ⅱ\s*期|二期|2\s*期", "II期"),
        (r"(?<!I)I\s*期|Ⅰ\s*期|一期|1\s*期", "I期"),
        (r"IND|临床试验申请|申报临床", "IND申报"),
    ]
    for pattern, stage in checks:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return stage
    return "待确认"


def refine_stage_for_indication(text: str, indication: str, stage: str) -> str:
    if indication == "复发/难治性多发性骨髓瘤(RRMM)":
        has_i_ii = re.search(r"I/II\s*期|Ⅰ/Ⅱ\s*期|1/2\s*期", text or "", flags=re.IGNORECASE)
        has_iii_enroll = re.search(r"III\s*期|Ⅲ\s*期|三期", text or "", flags=re.IGNORECASE) and any(
            word in (text or "") for word in ["入组", "入組", "患者入组", "患者入組"]
        )
        if has_i_ii and has_iii_enroll:
            return "I/II期；III期入组中"
    return stage


def detect_indications(text: str) -> list[str]:
    mapping = [
        (["非小细胞肺癌", "NSCLC", "肺鳞癌", "sq-NSCLC", "肺癌"], "肺癌/NSCLC"),
        (["胃癌", "胃食管", "GC/AEG", "GC", "GEJ"], "胃癌/胃食管结合部癌"),
        (["宫颈癌"], "宫颈癌"),
        (["实体瘤", "晚期实体瘤"], "晚期实体瘤"),
        (["非霍奇金淋巴瘤", "NHL"], "非霍奇金淋巴瘤"),
        (["结直肠癌", "CRC", "mCRC"], "结直肠癌"),
        (["胰腺癌", "胰臟癌"], "胰腺癌"),
        (["胆道癌", "膽道癌", "胆管癌", "膽管癌"], "胆道癌"),
        (["头颈"], "头颈鳞癌"),
        (["特应性皮炎", "atopic dermatitis"], "特应性皮炎"),
        (["青少年中重度AD", "儿童中重度AD"], "青少年/儿童特应性皮炎"),
        (["慢性鼻窦炎伴鼻息肉", "慢性鼻竇炎伴鼻息肉", "CRSwNP", "CRSw NP", "鼻息肉"], "慢性鼻窦炎伴鼻息肉"),
        (["季节性过敏性鼻炎", "SAR"], "季节性过敏性鼻炎"),
        (["结节性痒疹", "PN"], "结节性痒疹"),
        (["哮喘"], "哮喘"),
        (["COPD", "慢性阻塞性肺疾病"], "COPD"),
        (["荨麻疹", "CSU"], "慢性自发性荨麻疹"),
        (["复发/难治性多发性骨髓瘤", "復發或難治性多發性骨髓瘤", "RRMM", "R/R MM"], "复发/难治性多发性骨髓瘤(RRMM)"),
        (["多发性骨髓瘤", "多發性骨髓瘤"], "多发性骨髓瘤"),
        (["原发免疫性血小板减少症", "免疫性血小板减少症", "ITP"], "原发免疫性血小板减少症"),
        (["轻链型淀粉样变性"], "轻链型淀粉样变性"),
        (["干燥综合征"], "干燥综合征"),
        (["系统性硬化症", "SSc"], "系统性硬化症"),
        (["系统性红斑狼疮", "SLE"], "系统性红斑狼疮"),
    ]
    found = []
    lower = text.lower()
    for keywords, indication in mapping:
        if any(keyword.lower() in lower for keyword in keywords):
            found.append(indication)
    return list(dict.fromkeys(found)) or ["待细分适应症"]


def detect_window(text: str) -> str:
    patterns = [
        r"2026\s*年\s*[上下]半年",
        r"2026\s*H[12]",
        r"26\s*H[12]",
        r"2026\s*年\s*\d{1,2}\s*[-至]\s*\d{1,2}\s*月",
        r"2026\s*年\s*\d{1,2}\s*月",
        r"2026\s*年\s*Q[1-4]",
        r"2H26",
        r"1H26",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(0))
    return "待确认"


def detect_catalyst_type(text: str) -> str:
    if any(word in text for word in ["读出", "数据", "ASCO", "ESMO"]):
        return "临床数据读出/会议"
    if any(word in text for word in ["BLA", "NDA", "上市申请", "获批", "受理"]):
        return "注册/获批"
    if any(word in text for word in ["BD", "合作", "授权", "里程碑"]):
        return "BD/里程碑"
    return "管线进展"


def detect_next_milestone(text: str, stage: str = "", drug: str = "", indication: str = "", window: str = "") -> str:
    clean = re.sub(r"\s+", " ", text or "")
    context = f"{drug} {indication} {stage} {window} {clean}"
    is_listed = "已上市" in stage or any(word in clean for word in ["获批上市", "商业化", "纳入医保", "医保目录"])

    if "CM310" in drug or "司普奇拜" in drug or "康悦达" in drug:
        if indication in {"特应性皮炎", "慢性鼻窦炎伴鼻息肉"} and is_listed:
            return "商业化放量/医保后渗透"
        if "季节性过敏性鼻炎" in indication:
            return "SAR商业化/适应症拓展跟踪" if is_listed else "SAR注册审评/获批跟踪"
        if "青少年" in indication or "儿童" in indication:
            return "青少年/儿童AD注册审评" if ("NDA" in stage or "BLA" in stage or "受理" in clean) else "青少年/儿童AD临床推进"
        if "结节性痒疹" in indication:
            return "结节性痒疹NDA审评" if ("NDA" in stage or "BLA" in stage or "受理" in clean) else "结节性痒疹注册申报"
        if "哮喘" in indication:
            return "哮喘III期推进/数据更新"
        if is_listed:
            return "商业化放量/适应症拓展"

    if "CM512" in drug:
        if "慢性鼻窦炎" in indication:
            return "CRSwNP II期数据读出"
        if "哮喘" in indication:
            return "美国哮喘I/II期入组/数据更新" if "Belenos" in context or "美国" in context else "哮喘II期推进"
        if "COPD" in indication:
            return "COPD II期推进/数据更新"
        if "特应性皮炎" in indication:
            return "AD II期推进/数据更新"
        if "荨麻疹" in indication:
            return "CSU II期推进/数据更新"

    if "CMG901" in drug or "AZD0901" in drug:
        if "胃癌" in indication or "胃食管" in indication:
            if any(word in context for word in ["二线", "2L", "二线及以上"]):
                return "2L+胃癌III期数据/注册推进"
            if any(word in context for word in ["一线", "1L", "联合"]):
                return "1L胃癌III期入组推进"
            return "胃癌III期数据/注册推进"
        if "胰腺癌" in indication or "胆道癌" in indication:
            return "胰腺癌/胆道癌II期探索数据"

    if "CM518D1" in drug or "CM518" in drug:
        if any(word in context for word in ["ESMO", "ASCO", "GI", "数据"]):
            return "ESMO/ASCO GI早期数据披露"
        return "I/II期剂量递增/扩展数据"

    if "CM336" in drug:
        if "多发性骨髓瘤" in indication:
            return "MM III期推进/注册路径确认"
        if "轻链型淀粉样变性" in indication:
            return "AL适应症BLA/NDA进展"
        if any(word in indication for word in ["干燥综合征", "系统性硬化症", "红斑狼疮"]):
            return "自免适应症早期数据更新"

    if "CM326" in drug:
        if "石药" in context:
            return f"{indication or 'TSLP'} II期推进/石药合作进展"
        return f"{indication or 'TSLP'} II期数据更新"

    rules = [
        (["顶线数据", "topline", "Topline"], "顶线数据读出"),
        (["读出", "数据公布", "公布数据", "披露数据", "数据发布"], "临床数据读出/披露"),
        (["完成入组", "入组完成"], "完成入组"),
        (["首例患者给药", "首例受试者给药", "首例给药", "首例入组"], "首例患者入组/给药"),
        (["启动III期", "启动 III期", "III期启动", "三期启动"], "III期启动"),
        (["启动II期", "启动 II期", "II期启动", "二期启动"], "II期启动"),
        (["递交BLA", "提交BLA", "申报BLA"], "BLA递交"),
        (["递交NDA", "提交NDA", "申报NDA"], "NDA递交"),
        (["BLA获受理", "NDA获受理", "上市申请获受理", "获NMPA受理", "获受理"], "上市申请获受理"),
        (["优先审评"], "优先审评/审评进展"),
        (["获批上市", "批准上市", "获NMPA批准"], "获批上市"),
        (["纳入医保", "医保目录"], "医保纳入/执行"),
        (["里程碑付款", "里程碑款", "触发", "付款"], "里程碑付款/触发"),
        (["BD", "授权", "许可协议", "license", "License", "NewCo", "合作"], "BD合作/授权进展"),
        (["IND申报", "申报IND", "申报临床", "临床试验申请"], "IND申报/受理"),
        (["ASCO", "ESMO", "AACR", "ASH", "AAD", "学术大会", "会议"], "学术会议数据披露"),
    ]
    for keywords, label in rules:
        if any(keyword in clean for keyword in keywords):
            return label
    if "已上市" in stage:
        return "商业化放量/适应症拓展"
    if "NDA" in stage or "BLA" in stage:
        return "上市申请审评进展"
    if "III" in stage or "Ⅲ" in stage:
        return "III期数据/注册申报进展"
    if "II" in stage or "Ⅱ" in stage:
        return "II期数据/下一阶段推进"
    if "I" in stage or "Ⅰ" in stage:
        return "I期安全性/剂量递增数据"
    return "待确认"


def milestone_specificity(value: str) -> int:
    text = value or ""
    if not text or text == "待确认":
        return 0
    generic = {
        "注册/获批",
        "管线进展",
        "BD/里程碑",
        "临床数据读出/会议",
        "II期数据/下一阶段推进",
        "III期数据/注册申报进展",
        "商业化放量/适应症拓展",
        "上市申请审评进展",
        "BD合作/授权进展",
    }
    score = 1 if text in generic else 4
    score += sum(1 for word in ["NDA", "BLA", "III", "II", "I期", "数据", "入组", "给药", "医保", "里程碑", "AD", "CRSwNP", "胃癌", "哮喘", "审评", "注册", "商业化", "适应症"] if word in text)
    if "BD" in text or "授权" in text:
        score -= 2
    if "临床推进" in text:
        score -= 1
    return score


def choose_best_milestone(values: list[str]) -> str:
    clean = [value for value in values if value and value != "待确认"]
    if not clean:
        return "待确认"
    return sorted(clean, key=lambda item: (-milestone_specificity(item), item))[0]


def detect_partner_and_terms(text: str) -> tuple[str, str, str, str]:
    partner_map = {
        "Summit": ["Summit"],
        "GSK": ["GSK", "葛兰素史克"],
        "阿斯利康(AstraZeneca)": ["阿斯利康", "AstraZeneca", "AZ"],
        "Belenos Biosciences": ["Belenos"],
        "Ouro Medicines": ["Ouro", "PML", "Platina"],
        "石药集团": ["石药"],
        "诺诚健华": ["诺诚健华"],
        "Prolium Biosciences": ["Prolium"],
        "Timberlyne Therapeutics": ["Timberlyne"],
        "吉利德科学": ["吉利德", "Gilead"],
    }
    partners = [name for name, keys in partner_map.items() if any(key in text for key in keys)]
    amounts = re.findall(r"(?:首付款|预付款)?\s*(?:约|最高|合计|超过|超)?\s*[\d.]+\s*(?:亿|万)?\s*(?:美元|美金|人民币|港元)", text)
    milestones = [amount for amount in amounts if any(word in text[max(0, text.find(amount) - 20): text.find(amount) + 30] for word in ["里程碑", "最高", "总额", "付款"])]
    upfront = [amount for amount in amounts if any(word in text[max(0, text.find(amount) - 20): text.find(amount) + 30] for word in ["首付款", "预付款"])]
    equity = ""
    equity_match = re.search(r"(?:股权|股份|特许权|分成|销售分层)[^。；\n]{0,60}", text)
    if equity_match:
        equity = equity_match.group(0)
    return "；".join(dict.fromkeys(partners)), "；".join(dict.fromkeys(upfront)), "；".join(dict.fromkeys(milestones)), equity


def extract_alphapai_rows(company: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    today = datetime.now().strftime("%Y-%m-%d")
    pipeline_rows: list[dict[str, Any]] = []
    catalyst_rows: list[dict[str, Any]] = []
    bd_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    normalized_company = normalize_company_name(company)

    for item in items:
        text = item_text(item)
        source_type = str(item.get("type", ""))
        source = f"AlphaPai:{source_type}:{item.get('title', '')}"
        publish_date = str(item.get("time", "")).split(" ")[0]
        confidence = source_confidence(source_type)
        source_rows.append(
            {
                "source_id": item.get("id", ""),
                "source_type": source_type,
                "source_title": item.get("title", ""),
                "source_path_or_url": item.get("id", ""),
                "publish_date": publish_date,
                "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source_period": f"{item.get('_alphapai_query_start_date') or ALPHAPAI_RECALL_START_DATE}至今",
                "company_name": company,
                "drug_or_pipeline": "",
                "target": "",
                "indication": "",
                "source_confidence": confidence,
                "extract_priority": "高" if confidence == "高" else "中",
                "fields_to_extract": "来源发现;管线;BD;商业化;估值;催化剂",
                "notes": clip_text(text, 180),
            }
        )
        matched_patterns = [
            pattern for pattern in ALPHAPAI_PIPELINE_PATTERNS
            if any(normalize_company_name(alias) == normalized_company or alias in company for alias in pattern["companies"])
            and any(alias.lower() in text.lower() for alias in pattern["aliases"])
        ]
        for pattern in matched_patterns:
            relevant_text = project_section_text(item, pattern)
            if not relevant_text:
                continue
            detected_indications = detect_indications(relevant_text)
            allowed_indications = pattern.get("indications", [])
            indications = [
                indication for indication in detected_indications
                if not allowed_indications or indication in allowed_indications
            ]
            if not indications and "待细分适应症" in allowed_indications:
                indications = ["待细分适应症"]
            if not indications:
                continue
            window = detect_window(relevant_text)
            for indication in indications:
                row_evidence = evidence_sentence(relevant_text, pattern["aliases"], indication)
                stage_context = indication_stage_context(relevant_text, pattern["aliases"], indication)
                row_text = row_evidence or stage_context or evidence_sentence(relevant_text, pattern["aliases"]) or relevant_text
                row_confidence = confidence
                row_notes = ["AlphaPai投研资料抽取；关键事实以来源索引回溯"]
                if row_evidence:
                    row_notes.append(f"来源句：{clip_text(row_evidence, 160)}")
                    other_hits = other_pipeline_alias_hits(row_evidence, pattern)
                    if other_hits:
                        row_confidence = "低"
                        row_notes.append(f"来源句同时命中其他项目({';'.join(other_hits[:3])})，疑似项目污染，阶段/适应症需人工核验")
                else:
                    row_confidence = "低"
                    row_notes.append("未找到同时命中药物别名和该适应症的来源句，阶段/适应症需人工核验")
                evidence_stage = detect_stage_for_indication(row_evidence, indication) if row_evidence else "待确认"
                stage = evidence_stage if evidence_stage != "待确认" else detect_stage_for_indication(stage_context or row_text, indication)
                stage_evidence_text = stage_context or row_text
                if stage != "待确认" and not stage_supported_for_indication(stage_evidence_text, indication, stage):
                    row_notes.append(f"来源句未能证明 {indication} 对应 {stage}，阶段留待核验")
                    stage = "待确认"
                stage = refine_stage_for_indication(relevant_text, indication, stage)
                has_direct_fact = bool(row_evidence) and stage != "待确认"
                if row_confidence == "低" and has_direct_fact:
                    row_confidence = "中"
                    row_notes.append("AlphaPai召回句同时命中药物、适应症和阶段，按可用线索填表；来源类型低于公告级")
                elif row_confidence == "低" and stage != "待确认":
                    row_notes.append(f"低可信来源未形成直接项目-适应症-阶段证据，原自动抽取阶段为 {stage}")
                    stage = "待确认"
                progress = clip_text(f"{item.get('title', '')}：{row_text}", 240)
                pipeline_rows.append(
                    {
                        "company_name": company,
                        "drug_or_pipeline": pattern["drug"],
                        "target": pattern["target"],
                        "modality": pattern["modality"],
                        "indication": indication,
                        "clinical_stage": stage,
                        "latest_progress": progress,
                        "progress_date": publish_date or "待确认",
                        "next_catalyst": detect_next_milestone(relevant_text, stage, pattern["drug"], indication, window),
                        "next_catalyst_date_or_window": window,
                        "competitive_landscape": "",
                        "risks": "",
                        "source": source,
                        "source_confidence": row_confidence,
                        "last_verified_at": today,
                        "verification_notes": "；".join(dict.fromkeys(row_notes)),
                        "updated_at": today,
                    }
                )
            if window != "待确认" or any(word in relevant_text for word in ["读出", "申报", "获批", "里程碑", "首例"]):
                catalyst_rows.append(
                    {
                        "date_or_window": window,
                        "announced_date": publish_date or "待确认",
                        "expected_date_or_window": window,
                        "actual_date": "待确认",
                        "company_name": company,
                        "drug_or_pipeline": pattern["drug"],
                        "catalyst_type": detect_catalyst_type(text),
                        "event_summary": progress,
                        "status": "待跟踪",
                        "result": "待确认",
                        "expected_impact": "",
                        "source": source,
                        "updated_at": today,
                    }
                )
            partners, upfront, milestone, equity = detect_partner_and_terms(relevant_text)
            allowed_partners = pattern.get("partners", [])
            if partners and allowed_partners:
                partners = "；".join(
                    partner for partner in partners.split("；") if partner in allowed_partners
                )
            elif partners:
                partners = ""
            if partners and any(word in relevant_text for word in ["BD", "合作", "授权", "许可", "里程碑", "NewCo", "收购"]):
                upfront = pattern.get("deal_upfront") or upfront
                milestone = pattern.get("deal_milestone") or milestone
                equity = pattern.get("deal_equity") or equity
                bd_rows.append(
                    {
                        "company_name": company,
                        "drug_or_pipeline": pattern["drug"],
                        "target": pattern["target"],
                        "modality": pattern["modality"],
                        "partner": partners,
                        "territory": "全球/海外/中国权益待细分",
                        "deal_type": "BD合作/授权/NewCo/里程碑",
                        "announcement_date": publish_date or "待确认",
                        "signing_date": "待确认",
                        "effective_date": "待确认",
                        "closing_date": "待确认",
                        "upfront_payment": upfront or "待确认",
                        "milestone_value": milestone or "待确认",
                        "equity_or_option_terms": equity or "待确认",
                        "covered_indications": "；".join(indications),
                        "latest_progress": progress,
                        "latest_update_date": publish_date or "待确认",
                        "next_milestone": detect_next_milestone(relevant_text, stage, pattern["drug"], "；".join(indications), window),
                        "next_milestone_date_or_window": window,
                        "source": source,
                        "source_confidence": confidence,
                        "last_verified_at": today,
                        "verification_notes": "AlphaPai投研资料抽取；交易金额和权益区域以来源索引回溯",
                        "updated_at": today,
                    }
                )
            source_rows.append(
                {
                    "source_id": item.get("id", ""),
                    "source_type": source_type,
                    "source_title": item.get("title", ""),
                    "source_path_or_url": item.get("id", ""),
                    "publish_date": publish_date,
                    "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source_period": f"{item.get('_alphapai_query_start_date') or ALPHAPAI_RECALL_START_DATE}至今",
                    "company_name": company,
                    "drug_or_pipeline": pattern["drug"],
                    "target": pattern["target"],
                    "indication": "；".join(detect_indications(text)),
                    "source_confidence": confidence,
                    "extract_priority": "高" if confidence == "高" else "中",
                    "fields_to_extract": "研发阶段;最新进展;进展时间;下一里程碑;BD合作",
                    "notes": clip_text(relevant_text, 180),
                }
            )
    return pipeline_rows, catalyst_rows, bd_rows, source_rows


def latest_date(values: list[str]) -> str:
    dates = [value for value in values if re.match(r"\d{4}-\d{2}-\d{2}", str(value or ""))]
    if dates:
        return sorted(dates)[-1]
    return next((value for value in values if value and value != "待确认"), "待确认")


def collapse_pipeline_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    buckets: dict[tuple[str, str, str], dict[str, list[str]]] = {}
    for row in rows:
        key = (row.get("company_name", ""), row.get("drug_or_pipeline", ""), row.get("indication", ""))
        if key not in grouped:
            grouped[key] = dict(row)
            buckets[key] = {"stages": [], "dates": [], "progress": [], "sources": [], "windows": [], "milestones": [], "notes": []}
        elif pipeline_row_quality(row) > pipeline_row_quality(grouped[key]):
            grouped[key] = dict(row)
        bucket = buckets[key]
        for field, target in [
            ("clinical_stage", "stages"),
            ("progress_date", "dates"),
            ("latest_progress", "progress"),
            ("source", "sources"),
            ("next_catalyst_date_or_window", "windows"),
            ("next_catalyst", "milestones"),
            ("verification_notes", "notes"),
        ]:
            value = row.get(field, "")
            if value and value not in bucket[target]:
                bucket[target].append(value)
    collapsed = []
    for key, row in grouped.items():
        bucket = buckets[key]
        row["clinical_stage"] = row.get("clinical_stage", "待确认")
        row["progress_date"] = latest_date(bucket["dates"])
        row["source"] = "；".join(bucket["sources"][:3])
        row["next_catalyst_date_or_window"] = latest_date(bucket["windows"])
        chosen_milestone = choose_best_milestone(bucket["milestones"])
        contextual_milestone = detect_next_milestone(
            row.get("latest_progress", ""),
            row.get("clinical_stage", ""),
            row.get("drug_or_pipeline", ""),
            row.get("indication", ""),
            row.get("next_catalyst_date_or_window", ""),
        )
        generic_milestones = {
            "BD合作/授权进展",
            "III期数据/注册申报进展",
            "II期数据/下一阶段推进",
            "上市申请审评进展",
            "商业化放量/适应症拓展",
        }
        if contextual_milestone != "待确认" and (
            chosen_milestone in generic_milestones
            or milestone_specificity(contextual_milestone) > milestone_specificity(chosen_milestone)
        ):
            chosen_milestone = contextual_milestone
        row["next_catalyst"] = chosen_milestone
        row["verification_notes"] = join_unique_values([
            f"AlphaPai投研资料抽取并按药物-适应症聚合；合并来源 {len(bucket['sources'])} 条，可在附件索引回溯",
            *bucket["notes"][:3],
        ])
        collapsed.append(row)
    return collapsed


def collapse_catalyst_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("company_name", ""),
            row.get("drug_or_pipeline", ""),
            row.get("date_or_window", ""),
            row.get("catalyst_type", ""),
        )
        if key not in grouped:
            grouped[key] = dict(row)
        else:
            existing = grouped[key]
            if row.get("announced_date", "") > existing.get("announced_date", ""):
                existing["announced_date"] = row.get("announced_date", "")
                existing["event_summary"] = row.get("event_summary", existing.get("event_summary", ""))
            sources = [source for source in [existing.get("source", ""), row.get("source", "")] if source]
            existing["source"] = "；".join(dict.fromkeys(sources[:3]))
    return list(grouped.values())


def collapse_bd_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("company_name", ""), row.get("drug_or_pipeline", ""), row.get("partner", ""))
        if key not in grouped:
            grouped[key] = dict(row)
        else:
            existing = grouped[key]
            for field in ["upfront_payment", "milestone_value", "equity_or_option_terms", "covered_indications", "source"]:
                values = [value for value in [existing.get(field, ""), row.get(field, "")] if value and value != "待确认"]
                if values:
                    existing[field] = "；".join(dict.fromkeys(values[:4]))
            if row.get("announcement_date", "") > existing.get("announcement_date", ""):
                existing["announcement_date"] = row.get("announcement_date", "")
                existing["latest_update_date"] = row.get("latest_update_date", existing.get("latest_update_date", ""))
                existing["latest_progress"] = row.get("latest_progress", existing.get("latest_progress", ""))
    return list(grouped.values())


def pipeline_row_quality(row: dict[str, Any]) -> int:
    notes = row.get("verification_notes", "")
    score = confidence_rank(row.get("source_confidence", "")) * 300
    score += stage_rank(row.get("clinical_stage", "")) * 5
    if row.get("clinical_stage") and row.get("clinical_stage") != "待确认":
        score += 20
    if "来源句：" in notes:
        score += 40
    if "AlphaPai:ann:" in row.get("source", ""):
        score += 80
    elif "AlphaPai:report:" in row.get("source", ""):
        score += 30
    if any(word in notes for word in ["污染", "未找到同时命中", "未能证明", "低可信来源"]):
        score -= 120
    if row.get("indication") == "待细分适应症":
        score -= 50
    return score


def verification_rows_from_pipeline(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    today = datetime.now().strftime("%Y-%m-%d")
    verification_rows: list[dict[str, str]] = []
    for row in rows:
        notes = row.get("verification_notes", "")
        confidence = row.get("source_confidence", "")
        stage = row.get("clinical_stage", "")
        needs_check = (
            confidence == "低"
            or stage == "待确认"
            or any(word in notes for word in ["污染", "未找到同时命中", "低可信来源", "需人工核验", "需逐适应症核验"])
        )
        if not needs_check:
            continue
        drug = row.get("drug_or_pipeline", "")
        indication = row.get("indication", "")
        verification_rows.append(
            {
                "company_name": row.get("company_name", ""),
                "missing_item": f"{drug} / {indication}：适应症归属、临床阶段、最新进展需核验",
                "suggested_next_source": "公司公告/年报/官网管线页/临床试验登记/NMPA受理或获批信息",
                "opened_at": today,
                "target_check_date": "待确认",
                "resolved_at": "待确认",
                "source": source_brief(row.get("source", ""), max_items=1, include_attachment_suffix=False),
                "updated_at": today,
            }
        )
    return verification_rows


def enrich_drug_tables_with_alphapai(out_dir: Path, companies: list[str]) -> dict[str, Any]:
    if not alphapai_is_configured():
        return {"enabled": False, "message": "AlphaPai API 未配置，已使用本地种子数据。"}
    all_pipeline: list[dict[str, Any]] = []
    all_catalysts: list[dict[str, Any]] = []
    all_bd: list[dict[str, Any]] = []
    all_sources: list[dict[str, Any]] = []
    errors: list[str] = []
    for company in companies[:8]:
        try:
            items = alphapai_recall_company(company, out_dir)
            pipeline_rows, catalyst_rows, bd_rows, source_rows = extract_alphapai_rows(company, items)
            all_pipeline.extend(pipeline_rows)
            all_catalysts.extend(catalyst_rows)
            all_bd.extend(bd_rows)
            all_sources.extend(source_rows)
        except Exception as exc:
            errors.append(f"{company}: {exc}")

    all_pipeline = sanitize_pipeline_rows(collapse_pipeline_rows(all_pipeline))
    all_catalysts = collapse_catalyst_rows(all_catalysts)
    all_bd = collapse_bd_rows(all_bd)
    added_pipeline = append_unique_csv(
        out_dir / "pipeline_progress_seed.csv",
        all_pipeline,
        PIPELINE_FIELDNAMES,
        ["company_name", "drug_or_pipeline", "indication"],
    )
    added_catalysts = append_unique_csv(
        out_dir / "catalyst_tracker_seed.csv",
        all_catalysts,
        CATALYST_FIELDNAMES,
        ["company_name", "drug_or_pipeline", "date_or_window", "catalyst_type"],
    )
    added_bd = append_unique_csv(
        out_dir / "bd_deal_tracker_seed.csv",
        all_bd,
        BD_FIELDNAMES,
        ["company_name", "drug_or_pipeline", "partner"],
    )
    append_unique_csv(
        out_dir / "source_manifest_alphapai.csv",
        all_sources,
        SOURCE_MANIFEST_FIELDNAMES,
        ["source_id", "company_name", "drug_or_pipeline", "target"],
    )
    added_verification = append_unique_csv(
        out_dir / "verification_queue.csv",
        verification_rows_from_pipeline(all_pipeline),
        VERIFICATION_FIELDNAMES,
        ["company_name", "missing_item", "source"],
    )
    return {
        "enabled": True,
        "pipeline": added_pipeline,
        "catalysts": added_catalysts,
        "bd": added_bd,
        "sources": len(all_sources),
        "verification": added_verification,
        "errors": errors,
    }


def therapeutic_area_from_indications(indications: list[str], company_tags: str = "") -> str:
    text = "；".join(indications) + "；" + (company_tags or "")
    areas = []
    if any(word in text for word in ["肿瘤", "癌", "瘤", "实体瘤", "胃癌", "肺癌", "乳腺癌"]):
        areas.append("肿瘤")
    if any(word in text for word in ["自免", "特应性皮炎", "鼻窦炎", "哮喘", "COPD", "荨麻疹", "红斑狼疮", "硬化症", "炎症", "IgA肾病"]):
        areas.append("自免/慢病")
    if any(word in text for word in ["神经", "阿尔茨海默", "中枢"]):
        areas.append("神经退行性")
    if any(word in text for word in ["代谢", "糖尿病", "减重", "GLP"]):
        areas.append("代谢")
    return "/".join(dict.fromkeys(areas)) or "待确认"


def combine_deal_value(row: dict[str, str]) -> str:
    parts = [
        row.get("upfront_payment", ""),
        row.get("milestone_value", ""),
        row.get("equity_or_option_terms", ""),
    ]
    clean = [part for part in parts if part and part != "待确认"]
    return "+".join(dict.fromkeys(clean))


def field_trust_tier(row_or_confidence: dict[str, str] | str) -> str:
    if isinstance(row_or_confidence, dict):
        confidence = row_or_confidence.get("source_confidence", "")
    else:
        confidence = row_or_confidence
    if confidence == "高":
        return "公告级"
    if confidence == "中":
        return "研报推断"
    return "待核验"


def aggregate_trust_tier(values: list[str]) -> str:
    clean = [value for value in values if value and value != "待确认"]
    if not clean or any(value == "低" for value in clean):
        return "待核验"
    if all(value == "高" for value in clean):
        return "公告级"
    return "研报推断"


def display_deal_value(row: dict[str, str]) -> str:
    value = combine_deal_value(row)
    if not value or "待按单笔交易核验" in value or value == "待确认":
        return ""
    return value


def display_milestone_window(row: dict[str, str]) -> str:
    if field_trust_tier(row) != "公告级":
        return ""
    value = row.get("next_catalyst_date_or_window") or row.get("next_milestone_date_or_window") or ""
    return "" if value == "待确认" else value


def clean_company_display_name(company_name: str) -> str:
    return re.sub(r"[-－]B$", "", company_name or "").strip() or "公司"


def company_display(company_rows: list[dict[str, str]], company_name: str | None = None) -> str:
    if company_name:
        row = next((item for item in company_rows if item.get("company_name") == company_name), {})
        ticker = row.get("tickers_raw") or row.get("code") or ""
        name = clean_company_display_name(company_name)
        return f"{name}（{ticker}）" if ticker else name
    non_empty = [row for row in company_rows if row.get("company_name")]
    if len(non_empty) == 1:
        return company_display(company_rows, non_empty[0].get("company_name", ""))
    return "多公司"


def summarize_source_types(*row_groups: list[dict[str, str]]) -> str:
    source_text = " ".join(
        str(row.get("source", "") or row.get("source_type", "") or row.get("source_title", ""))
        for rows in row_groups
        for row in rows
    ).lower()
    labels: list[str] = []
    source_rules = [
        (("ann", "公告", "年报", "annual", "interim", "公司官网"), "公司年报/公告"),
        (("report", "研报", "券商"), "券商研报"),
        (("roadshow", "业绩会", "纪要", "调研"), "业绩会纪要"),
        (("news", "新闻", "social", "media", "社媒"), "公开新闻/社媒"),
        (("alphapai", "alpha派"), "AlphaPai召回数据"),
    ]
    for needles, label in source_rules:
        if any(needle in source_text for needle in needles):
            labels.append(label)
    if not labels:
        labels = ["公司资料", "券商研报", "业绩会纪要", "公开新闻等"]
    return "、".join(dict.fromkeys(labels))


def with_sheet_intro(company_label: str, sheet_title: str, table: list[list[Any]], source_line: str = "") -> list[list[Any]]:
    col_count = max((len(row) for row in table), default=1)
    title = f"{company_label}创新药管线 — {sheet_title}"
    return [
        [title, *[""] * (col_count - 1)],
        [source_line, *[""] * (col_count - 1)],
        *table,
    ]


def group_detail_table(table: list[list[Any]]) -> list[list[Any]]:
    if len(table) <= 2:
        return table
    header = table[0]
    data_rows = [row for row in table[1:] if any(str(cell or "").strip() for cell in row)]
    data_rows.sort(
        key=lambda row: (
            str(row[0] if len(row) > 0 else ""),
            str(row[1] if len(row) > 1 else ""),
            str(row[2] if len(row) > 2 else ""),
            str(row[4] if len(row) > 4 else ""),
        )
    )
    grouped = [header]
    previous_key: tuple[str, str] | None = None
    blank = [""] * len(header)
    for row in data_rows:
        key = (
            str(row[0] if len(row) > 0 else ""),
            str(row[1] if len(row) > 1 else ""),
            str(row[2] if len(row) > 2 else ""),
        )
        if previous_key is not None and key != previous_key:
            grouped.append(blank[:])
        grouped.append(row)
        previous_key = key
    return grouped


def prune_low_signal_columns(table: list[list[Any]], candidate_headers: set[str]) -> list[list[Any]]:
    if not table:
        return table
    header = table[0]
    drop_indexes: set[int] = set()
    for idx, name in enumerate(header):
        if str(name) not in candidate_headers:
            continue
        values = []
        for row in table[1:]:
            value = str(row[idx] if idx < len(row) else "").strip()
            if value and value not in {"待确认", "暂无", "无", "nan", "None"}:
                values.append(value)
        if len(set(values)) <= 1:
            drop_indexes.add(idx)
    if not drop_indexes:
        return table
    return [
        [cell for idx, cell in enumerate(row) if idx not in drop_indexes]
        for row in table
    ]


def join_unique_values(values: list[str], fallback: str = "") -> str:
    clean = [value for value in values if value and value != "待确认"]
    return "；".join(dict.fromkeys(clean)) or fallback


def join_unique_segments(value: str, fallback: str = "") -> str:
    parts = re.split(r"[；;]", value or "")
    clean = [part.strip() for part in parts if part.strip() and part.strip() != "待确认"]
    return "；".join(dict.fromkeys(clean)) or fallback


def concise_research_text(value: str, max_chars: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if "：" in text:
        title, body = text.split("：", 1)
        if (len(title) > 18 and len(body) > 20) or body.strip().startswith(title.strip()):
            text = body.strip()
            if text.startswith(title.strip()):
                text = text[len(title.strip()):].strip(" ：:")
    text = re.sub(r"([A-Za-z0-9])\s+([A-Za-z0-9])", r"\1 \2", text)
    sentences = [part.strip(" ；;。") for part in re.split(r"[。；;\n]", text) if part.strip(" ；;。")]
    keywords = [
        "获批", "上市", "医保", "NDA", "BLA", "IND", "受理", "III期", "II期", "I期",
        "首例", "入组", "读出", "数据", "里程碑", "付款", "合作", "授权", "申报",
        "预计", "完成", "启动", "递交", "获", "发布",
    ]
    scored: list[tuple[int, int, str]] = []
    for idx, sentence in enumerate(sentences[:8]):
        score = sum(1 for word in keywords if word in sentence)
        if re.search(r"\d{4}年|\d{4}-\d{2}|\d+月|\d+例|\d+万|\d+亿", sentence):
            score += 2
        scored.append((score, -idx, sentence))
    selected = [item[2] for item in sorted(scored, reverse=True)[:2] if item[0] > 0]
    if not selected:
        selected = sentences[:2] or [text]
    summary = "；".join(dict.fromkeys(selected))
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip(" ，,；;。") + "…"
    return summary


def source_brief(value: str, max_items: int = 2, include_attachment_suffix: bool = True) -> str:
    sources = [item.strip() for item in re.split(r"[；;]", value or "") if item.strip()]
    brief = []
    for source in sources[:max_items]:
        if source.startswith(("上传公司列表：", "上传材料：")):
            brief.append(source)
            continue
        if re.search(r"(^/Users/|^/private/|^/tmp/|^[A-Za-z]:[\\/])", source):
            brief.append(f"上传材料：{Path(source).name}")
            continue
        parts = source.split(":", 2)
        if len(parts) == 3:
            brief.append(f"{parts[0]}:{parts[1]}")
        else:
            brief.append(clip_text(source, 28))
    suffix = "；详见附件索引" if sources and include_attachment_suffix else ""
    return "；".join(dict.fromkeys(brief)) + suffix


def md_cell(value: Any, max_chars: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("|", "/")
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip(" ，,；;。") + "…"
    return text or "待补充"


def report_progress_summary(row: dict[str, str], max_chars: int = 90) -> str:
    source = row.get("source", "")
    confidence = row.get("source_confidence", "")
    if confidence == "低":
        date = row.get("progress_date", "")
        catalyst = row.get("next_catalyst", "")
        prefix = f"{date} " if date and date != "待确认" else ""
        return f"{prefix}{catalyst or '进展'}线索；详见附件索引，待来源复核"
    text = concise_research_text(row.get("latest_progress", ""), max_chars)
    noisy_terms = ["索平台", "总在研项目", "超50个", "管线规模与国际化"]
    if any(term in text for term in noisy_terms):
        return "管线/平台描述线索；需回到项目级公告、年报或临床登记核验"
    return text


def report_event_summary(row: dict[str, str], max_chars: int = 80) -> str:
    source = row.get("source", "")
    if "social_media" in source:
        event_type = row.get("catalyst_type", "") or "事件"
        window = row.get("date_or_window", "")
        suffix = f"（{window}）" if window and window != "待确认" else ""
        return f"{event_type}{suffix}线索；AlphaPai来源，详见附件索引"
    return concise_research_text(row.get("event_summary", ""), max_chars)


def normalize_confidence(row: dict[str, str]) -> str:
    source = row.get("source", "")
    confidence = row.get("source_confidence", "") or "待确认"
    if "自动摘要" in source or "新闻转载" in source:
        return "低"
    return confidence


def confidence_rank(value: str) -> int:
    return {"高": 3, "中": 2, "低": 1}.get(value or "", 0)


def choose_highest_confidence(values: list[str]) -> str:
    clean = [value for value in values if value and value != "待确认"]
    if not clean:
        return "待确认"
    return sorted(clean, key=lambda item: (-confidence_rank(item), item))[0]


def sanitize_pipeline_row(row: dict[str, str]) -> dict[str, str]:
    clean = dict(row)
    drug = clean.get("drug_or_pipeline", "")
    indication = clean.get("indication", "")
    progress = clean.get("latest_progress", "")
    stage = clean.get("clinical_stage", "")
    notes = [clean.get("verification_notes", "")]
    clean["source_confidence"] = normalize_confidence(clean)

    evidence_text = join_unique_values([progress, clean.get("verification_notes", "")])
    evidence_stage = detect_stage_for_indication(evidence_text, indication)
    if evidence_stage != "待确认" and clean["source_confidence"] != "低":
        refined_stage = refine_stage_for_indication(evidence_text, indication, evidence_stage)
        should_replace_stage = (
            not stage
            or stage == "待确认"
            or stage_rank(refined_stage) >= stage_rank(stage)
            or "来源句未能证明" in clean.get("verification_notes", "")
        )
        if should_replace_stage and refined_stage != stage:
            notes.append(f"按本行适应症附近证据重算研发阶段：{stage or '空'} -> {refined_stage}")
        if should_replace_stage:
            clean["clinical_stage"] = refined_stage
            stage = refined_stage

    if clean["source_confidence"] == "低":
        notes.append("来源线索/待复核")
        if stage and stage != "待确认":
            clean["clinical_stage"] = "待确认"
            notes.append(f"低可信来源不确认研发阶段，原自动抽取阶段为 {stage}")

    if indication == "待细分适应症":
        clean["source_confidence"] = "低"
        notes.append("适应症未拆到具体疾病，不能作为项目级事实，需回公告/临床登记核验")

    clean["verification_notes"] = "；".join(dict.fromkeys(note for note in notes if note))
    return clean


def sanitize_pipeline_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    cleaned = [sanitize_pipeline_row(row) for row in rows]
    specific_mm_keys = {
        (row.get("company_name", ""), row.get("drug_or_pipeline", ""))
        for row in cleaned
        if row.get("indication") == "复发/难治性多发性骨髓瘤(RRMM)"
    }
    return [
        row for row in cleaned
        if not (
            row.get("indication") == "多发性骨髓瘤"
            and (row.get("company_name", ""), row.get("drug_or_pipeline", "")) in specific_mm_keys
        )
    ]


def expand_bd_rows_by_partner(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    expanded: list[dict[str, str]] = []
    for row in rows:
        partners = [item.strip() for item in re.split(r"[；;]", row.get("partner", "")) if item.strip()]
        if len(partners) <= 1:
            expanded.append(row)
            continue
        for partner in partners:
            item = dict(row)
            item["partner"] = partner
            item["upfront_payment"] = "待按单笔交易核验"
            item["milestone_value"] = "待按单笔交易核验"
            item["equity_or_option_terms"] = "待按单笔交易核验"
            item["source_confidence"] = "低"
            item["verification_notes"] = join_unique_values([
                row.get("verification_notes", ""),
                "原始自动抽取包含多个合作方，已按合作方拆行；金额/权益需回公告逐笔核验",
            ])
            expanded.append(item)
    return expanded


def cm310_revenue_template_rows(company_rows: list[dict[str, str]], pipeline_rows: list[dict[str, str]]) -> list[list[Any]]:
    has_cm310 = any("CM310" in row.get("drug_or_pipeline", "") for row in pipeline_rows)
    company = next((row.get("company_name", "") for row in company_rows if row.get("company_name")), "康诺亚-B")
    assumptions = [
        {
            "indication": "成人中重度特应性皮炎(AD)",
            "reimbursed": "是/待核验医保支付范围",
            "patients": "待填: 流行病学/指南/券商深度核验",
            "treatable": "待填",
            "penetration": "待填",
            "cost": "待核价: 医保后年治疗费用",
            "peak": "公式待填: 患者池×可治疗比例×渗透率×年治疗费用",
            "revenue_2026": "待填",
            "revenue_2027": "待填",
            "revenue_2028": "待填",
            "gross_margin": "待填: 公司财报口径",
            "selling_ratio": "待填: 公司财报口径",
        },
        {
            "indication": "成人慢性鼻窦炎伴鼻息肉(CRSwNP)",
            "reimbursed": "是/待核验适应症支付范围",
            "patients": "待填: 流行病学/指南/券商深度核验",
            "treatable": "待填",
            "penetration": "待填",
            "cost": "待核价: 医保后年治疗费用",
            "peak": "公式待填: 患者池×可治疗比例×渗透率×年治疗费用",
            "revenue_2026": "待填",
            "revenue_2027": "待填",
            "revenue_2028": "待填",
            "gross_margin": "待填: 公司财报口径",
            "selling_ratio": "待填: 公司财报口径",
        },
        {
            "indication": "其他适应症/待核验",
            "reimbursed": "待核验",
            "patients": "按单适应症重新拆患者池",
            "treatable": "待填",
            "penetration": "待填",
            "cost": "待核价",
            "peak": "待确认适应症后计算",
            "revenue_2026": "不纳入基准情景",
            "revenue_2027": "可列期权情景",
            "revenue_2028": "可列期权情景",
            "gross_margin": "参考公司财报",
            "selling_ratio": "参考公司财报",
        },
    ]
    if not has_cm310:
        assumptions = [{
            "indication": "商业化产品/待补充",
            "reimbursed": "待核验",
            "patients": "待填",
            "treatable": "待填",
            "penetration": "待填",
            "cost": "待填",
            "peak": "待填",
            "revenue_2026": "待填",
            "revenue_2027": "待填",
            "revenue_2028": "待填",
            "gross_margin": "待填",
            "selling_ratio": "待填",
        }]
    rows = [[
        "公司", "产品", "适应症", "是否医保", "患者池", "可治疗比例", "渗透率",
        "年治疗费用", "峰值销售额", "2026E收入", "2027E收入", "2028E收入",
        "毛利率", "销售费用率", "利润贡献", "数据状态", "建议来源"
    ]]
    for item in assumptions:
        rows.append([
            company,
            "CM310/司普奇拜单抗",
            item["indication"],
            item["reimbursed"],
            item["patients"],
            item["treatable"],
            item["penetration"],
            item["cost"],
            item["peak"],
            item["revenue_2026"],
            item["revenue_2027"],
            item["revenue_2028"],
            item["gross_margin"],
            item["selling_ratio"],
            "收入×毛利率-收入×销售费用率",
            "人工核验后填",
            "医保目录、年报、业绩会、券商深度、流行病学/指南、中标价/支付价",
        ])
    return rows


def parse_primary_ticker(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        return "", ""
    token = re.split(r"[,，;/；\s]+", text)[0].strip()
    upper = token.upper()
    code_match = re.search(r"\d{4,6}", upper)
    code = code_match.group(0) if code_match else ""
    if not code:
        return "", ""
    if upper.endswith(".HK") or len(code) <= 5:
        return code.zfill(5), "HK"
    if upper.endswith(".SH") or code.startswith(("5", "6", "9")):
        return code, "SH"
    if upper.endswith(".SZ") or code.startswith(("0", "2", "3")):
        return code, "SZ"
    return code, "SH" if code.startswith("6") else "SZ"


def pct_return_from_klines(klines: list[dict[str, Any]], days: int) -> float | None:
    if len(klines) < days + 1:
        return None
    latest = stock_monitor.as_float(klines[-1].get("close"))
    previous = stock_monitor.as_float(klines[-days - 1].get("close"))
    if math.isnan(latest) or math.isnan(previous) or previous == 0:
        return None
    return (latest / previous - 1) * 100


def fmt_pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "NA"
    return f"{value:.2f}%"


def fmt_amount(value: Any) -> str:
    amount = stock_monitor.as_float(value)
    if math.isnan(amount):
        return "NA"
    return f"{amount / 100000000:.2f}亿元"


def fetch_company_klines(company_rows: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {}
    with temporary_env("STOCK_MONITOR_ENABLE_HK_KLINE", "1"):
        for row in company_rows:
            company = row.get("company_name", "")
            code, market = parse_primary_ticker(row.get("tickers_raw", "") or row.get("ticker", ""))
            if not company or not code:
                continue
            stock = stock_monitor.Stock(
                code=code,
                name=company,
                market=market,
                industry="医药",
                theme="创新药",
                watch_reason="创新药行情验证",
                tracking_points="事件催化/BD/商业化",
                keywords=f"{company} 创新药 BD 临床 商业化",
                pct_threshold=0,
                amount_ratio_threshold=0,
            )
            try:
                rows = stock_monitor.fetch_klines_eastmoney(stock)
            except Exception:
                rows = []
            if rows:
                results[company] = rows
    return results


def fetch_index_klines_for_market(market: str) -> list[dict[str, Any]]:
    code = "931152" if market == "HK" else "399441"
    sec_market = "SH" if market == "HK" else "SZ"
    stock = stock_monitor.Stock(
        code=code,
        name="创新药/医药指数Proxy",
        market=sec_market,
        industry="指数",
        theme="医药",
        watch_reason="相对收益proxy",
        tracking_points="指数相对收益",
        keywords="创新药 医药 指数",
        pct_threshold=0,
        amount_ratio_threshold=0,
    )
    try:
        return stock_monitor.fetch_klines_eastmoney(stock)
    except Exception:
        return []


def fetch_market_validation_data(company_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    klines_by_company = fetch_company_klines(company_rows)
    index_cache: dict[str, list[dict[str, Any]]] = {}
    output: dict[str, dict[str, str]] = {}
    for row in company_rows:
        company = row.get("company_name", "")
        code, market = parse_primary_ticker(row.get("tickers_raw", "") or row.get("ticker", ""))
        klines = klines_by_company.get(company, [])
        if not klines:
            output[company] = {"status": "行情待接入", "judgement": "人工核验后填"}
            continue
        index_rows = index_cache.setdefault(market, fetch_index_klines_for_market(market))
        returns = {days: pct_return_from_klines(klines, days) for days in (1, 5, 20, 60)}
        index_returns = {days: pct_return_from_klines(index_rows, days) for days in (1, 5, 20, 60)} if index_rows else {}
        rel_returns = {
            days: (returns[days] - index_returns[days])
            for days in returns
            if returns.get(days) is not None and index_returns.get(days) is not None
        }
        latest = klines[-1]
        output[company] = {
            "latest_date": str(latest.get("date", "")),
            "return_summary": "；".join(f"{days}日{fmt_pct(returns[days])}" for days in (1, 5, 20, 60)),
            "amount_summary": f"{fmt_amount(latest.get('amount'))}；换手率{fmt_pct(stock_monitor.as_float(latest.get('turnover')))}",
            "relative_return_summary": "；".join(
                f"{days}日{fmt_pct(rel_returns.get(days))}" for days in (1, 5, 20, 60)
            ) if rel_returns else "指数proxy待拉取",
            "judgement": "仅行情数据已拉取；上涨逻辑仍需结合事件时间线验证",
            "status": f"东方财富K线:{code}.{market}; 指数proxy:{'ok' if index_rows else '待拉取'}",
        }
    return output


def official_source_seed_rows(company_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    today = datetime.now().strftime("%Y-%m-%d")
    known_pages = {
        "康方生物": [
            ("company_financial_reports_page", "康方生物财务报告", "https://www.akesobio.com/cn/investor-relations/financial-reports/", "annual_report;interim_report;financials;pipeline_progress", "高"),
            ("company_news_page", "康方生物新闻中心", "https://www.akesobio.com/cn/media/akeso-news/", "latest_progress;clinical_data;conference;approval;bd", "高"),
        ],
        "乐普生物": [
            ("company_financial_reports_page", "乐普生物财务报告", "https://www.lepubiopharma.com/investor/caiwubaogao", "annual_report;interim_report;financials;pipeline_progress", "高"),
            ("company_official_home_page", "乐普生物官网", "https://www.lepubiopharma.com/", "source_discovery;company_news;pipeline_progress", "高"),
        ],
    }
    rows: list[dict[str, str]] = []
    counter = 1
    for company in company_rows:
        company_name = company.get("company_name", "")
        clean_name = clean_company_display_name(company_name)
        ticker, _market = parse_primary_ticker(company.get("tickers_raw", "") or company.get("ticker", ""))
        if ticker:
            rows.append({
                "source_id": f"OFFICIAL-{counter:04d}",
                "source_type": "eastmoney_announcement_page",
                "source_title": f"{company_name}公告入口（东方财富公告大全）",
                "source_path_or_url": f"https://data.eastmoney.com/notices/stock/{ticker}.html",
                "publish_date": "持续更新",
                "retrieved_at": today,
                "source_period": "持续更新页面",
                "company_name": company_name,
                "drug_or_pipeline": "待确认",
                "target": "待确认",
                "indication": "待确认",
                "source_confidence": "中",
                "extract_priority": "高",
                "fields_to_extract": "announcements;annual_report;interim_report;bd;approval;financials",
                "notes": "公告聚合入口；用于定位交易所公告原文、年度/中期报告和重大BD/审批事件",
            })
            counter += 1
        for key, pages in known_pages.items():
            if key in clean_name or clean_name in key:
                for source_type, title, url, fields, confidence in pages:
                    rows.append({
                        "source_id": f"OFFICIAL-{counter:04d}",
                        "source_type": source_type,
                        "source_title": title,
                        "source_path_or_url": url,
                        "publish_date": "持续更新",
                        "retrieved_at": today,
                        "source_period": "持续更新页面",
                        "company_name": company_name,
                        "drug_or_pipeline": "待确认",
                        "target": "待确认",
                        "indication": "待确认",
                        "source_confidence": confidence,
                        "extract_priority": "高",
                        "fields_to_extract": fields,
                        "notes": "公司官方入口；用于后续抽取年报、公告、新闻和产品进展",
                    })
                    counter += 1
    return rows


def market_validation_template_rows(company_rows: list[dict[str, str]], catalyst_rows: list[dict[str, str]]) -> list[list[Any]]:
    rows = [["日期", "公司", "股价涨跌幅", "成交额", "相对指数收益", "同日事件", "判断", "数据状态"]]
    market_data = fetch_market_validation_data(company_rows)
    companies = [row.get("company_name", "") for row in company_rows if row.get("company_name")]
    if catalyst_rows:
        for catalyst in catalyst_rows[:12]:
            company = catalyst.get("company_name", "")
            data = market_data.get(company, {})
            rows.append([
                data.get("latest_date") or catalyst.get("announced_date", "") or catalyst.get("date_or_window", ""),
                company,
                data.get("return_summary", ""),
                data.get("amount_summary", ""),
                data.get("relative_return_summary", ""),
                report_event_summary(catalyst, 80),
                data.get("judgement", "未验证；禁止写上涨逻辑成立"),
                data.get("status", "行情待接入"),
            ])
    else:
        for company in companies[:8] or ["待补充"]:
            data = market_data.get(company, {})
            rows.append([
                data.get("latest_date", "待填"),
                company,
                data.get("return_summary", ""),
                data.get("amount_summary", ""),
                data.get("relative_return_summary", ""),
                "待填",
                data.get("judgement", "未验证"),
                data.get("status", "行情待接入"),
            ])
    return rows


def write_innovative_drug_excel(out_dir: Path) -> Path:
    company_rows = read_csv_rows(out_dir / "company_master.csv")
    pipeline_rows_all = sanitize_pipeline_rows(read_csv_rows(out_dir / "pipeline_progress_seed.csv"))
    pipeline_rows = [
        row for row in pipeline_rows_all
        if row.get("source_confidence") != "低"
        and row.get("clinical_stage") not in {"", "待确认"}
        and row.get("indication") != "待细分适应症"
    ]
    catalyst_rows = read_csv_rows(out_dir / "catalyst_tracker_seed.csv")
    bd_rows = expand_bd_rows_by_partner(read_csv_rows(out_dir / "bd_deal_tracker_seed.csv"))
    verification_rows = read_csv_rows(out_dir / "verification_queue.csv")
    existing_verification_keys = {
        (row.get("company_name", ""), row.get("missing_item", ""), row.get("source", ""))
        for row in verification_rows
    }
    for row in verification_rows_from_pipeline(pipeline_rows_all):
        key = (row.get("company_name", ""), row.get("missing_item", ""), row.get("source", ""))
        if key not in existing_verification_keys:
            verification_rows.append(row)
            existing_verification_keys.add(key)
    source_manifest_rows = read_csv_rows(out_dir / "source_manifest_alphapai.csv")
    source_manifest_rows.extend(read_csv_rows(out_dir / "source_manifest.csv"))
    source_manifest_rows.extend(official_source_seed_rows(company_rows))

    company_by_name = {row.get("company_name", ""): row for row in company_rows}
    bd_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in bd_rows:
        key = (row.get("company_name", ""), row.get("drug_or_pipeline", ""))
        bd_by_key.setdefault(key, []).append(row)

    overview_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in pipeline_rows:
        key = (row.get("company_name", ""), row.get("target", ""), row.get("drug_or_pipeline", ""))
        drug_name, project_code = split_drug_project(row.get("drug_or_pipeline", ""))
        item = overview_map.setdefault(
            key,
            {
                "company_name": row.get("company_name", ""),
                "market": company_by_name.get(row.get("company_name", ""), {}).get("market", ""),
                "target": row.get("target", ""),
                "drug_name": drug_name,
                "project_code": project_code,
                "modality": row.get("modality", ""),
                "indications": [],
                "stages": [],
                "progress_dates": [],
                "progress": [],
                "catalysts": [],
                "catalyst_windows": [],
                "confidences": [],
            },
        )
        for field, bucket in [
            ("indication", "indications"),
            ("clinical_stage", "stages"),
            ("progress_date", "progress_dates"),
            ("latest_progress", "progress"),
            ("next_catalyst", "catalysts"),
            ("next_catalyst_date_or_window", "catalyst_windows"),
        ]:
            value = row.get(field, "")
            if value and value not in item[bucket]:
                item[bucket].append(value)
        confidence = row.get("source_confidence", "")
        if confidence and confidence not in item["confidences"]:
            item["confidences"].append(confidence)

    overview = [[
        "治疗领域", "靶点", "药物名称", "项目编号", "药物类型", "适应症数量",
        "最高研发阶段", "最新进展时间", "下一里程碑时间", "BD合作方", "BD交易金额", "字段可信度"
    ]]
    for item in overview_map.values():
        company = item["company_name"]
        company_tags = company_by_name.get(company, {}).get("disease_area_tags", "")
        matching_bd = bd_by_key.get((company, item["project_code"]), []) or bd_by_key.get((company, item["drug_name"]), [])
        partners = "；".join(dict.fromkeys(row.get("partner", "") for row in matching_bd if row.get("partner", "") and row.get("partner", "") != "待确认"))
        deal_values = "；".join(dict.fromkeys(display_deal_value(row) for row in matching_bd if display_deal_value(row)))
        overview.append(
            [
                therapeutic_area_from_indications(item["indications"], company_tags),
                item["target"],
                item["drug_name"],
                item["project_code"],
                item["modality"],
                len(item["indications"]),
                choose_highest_stage(item["stages"]),
                "；".join([value for value in item["progress_dates"] if value != "待确认"]) or "待确认",
                "；".join([value for value in item["catalyst_windows"] if value != "待确认"]) if aggregate_trust_tier(item["confidences"]) == "公告级" else "",
                partners,
                deal_values,
                aggregate_trust_tier(item["confidences"]),
            ]
        )
    if len(overview) == 1:
        overview.append(["待补充", "", "", "", "", "", "待确认", "待确认", "", "", "", "待核验"])

    summary = [[
        "公司名称", "治疗领域", "靶点", "药物名称", "项目编号", "药物类型",
        "适应症数量", "最高研发阶段", "最新进展时间", "BD合作方", "BD交易金额", "下一里程碑时间", "字段可信度"
    ]]
    for item in overview_map.values():
        company = item["company_name"]
        company_tags = company_by_name.get(company, {}).get("disease_area_tags", "")
        matching_bd = bd_by_key.get((company, item["project_code"]), []) or bd_by_key.get((company, item["drug_name"]), [])
        partners = join_unique_values([row.get("partner", "") for row in matching_bd])
        deal_values = join_unique_values([display_deal_value(row) for row in matching_bd])
        summary.append([
            company,
            therapeutic_area_from_indications(item["indications"], company_tags),
            item["target"],
            item["drug_name"],
            item["project_code"],
            item["modality"],
            len(item["indications"]),
            choose_highest_stage(item["stages"]),
            join_unique_values([value for value in item["progress_dates"] if value != "待确认"], "待确认"),
            partners,
            deal_values,
            join_unique_values([value for value in item["catalyst_windows"] if value != "待确认"], "") if aggregate_trust_tier(item["confidences"]) == "公告级" else "",
            aggregate_trust_tier(item["confidences"]),
        ])
    if len(summary) == 1:
        summary.append(["待补充", "", "", "", "", "", 0, "待确认", "待确认", "", "", "", "待核验"])

    detail = [[
        "公司名称", "靶点", "药物/项目编号", "药物类型", "适应症", "研发阶段", "最新进展",
        "进展时间", "下一里程碑", "下一里程碑时间", "update_needed", "字段可信度",
        "来源类型/具体来源", "source_note"
    ]]
    for row in pipeline_rows:
        confidence = row.get("source_confidence", "")
        update_needed = "是" if confidence == "低" or row.get("clinical_stage", "") in {"待确认", ""} else ""
        detail.append([
            row.get("company_name", ""),
            row.get("target", ""),
            row.get("drug_or_pipeline", ""),
            row.get("modality", ""),
            row.get("indication", ""),
            row.get("clinical_stage", ""),
            report_progress_summary(row, 120),
            row.get("progress_date", ""),
            row.get("next_catalyst", ""),
            display_milestone_window(row),
            update_needed,
            field_trust_tier(row),
            source_brief(row.get("source", "")),
            row.get("verification_notes", ""),
        ])
    grouped_detail = group_detail_table(detail)

    stage_counts: dict[str, dict[str, Any]] = {}
    for row in pipeline_rows:
        stage = row.get("clinical_stage", "") or "待确认"
        item = stage_counts.setdefault(stage, {"count": 0, "drugs": set(), "examples": []})
        item["count"] += 1
        item["drugs"].add(row.get("drug_or_pipeline", ""))
        if len(item["examples"]) < 5:
            item["examples"].append(f"{row.get('company_name', '')}-{row.get('drug_or_pipeline', '')}({row.get('indication', '')})")
    stage_summary = [["研发阶段", "适应症/记录数量", "涉及药物", "代表管线"]]
    for stage, item in sorted(stage_counts.items(), key=lambda pair: pair[0]):
        stage_summary.append([stage, item["count"], "；".join(sorted(item["drugs"])), "；".join(item["examples"])])
    if len(stage_summary) == 1:
        stage_summary.append(["待确认", 0, "", "暂无阶段数据"])

    bd_sheet = [[
        "公司名称", "靶点", "药物/项目编号", "药物类型", "合作方", "BD交易金额/结构",
        "授权区域", "覆盖适应症", "交易类型/关键日期", "最新进展/下一节点", "字段可信度", "来源/核验"
    ]]
    for row in bd_rows:
        deal_value = display_deal_value(row)
        key_dates = []
        for label, field in [
            ("公告", "announcement_date"),
            ("签约", "signing_date"),
            ("生效", "effective_date"),
            ("交割", "closing_date"),
        ]:
            value = row.get(field, "")
            if value and value != "待确认":
                key_dates.append(f"{label}:{value}")
        progress_parts = []
        if row.get("latest_progress", ""):
            latest = report_progress_summary(row, 110)
            latest_date = row.get("latest_update_date", "")
            progress_parts.append(f"{latest_date} {latest}".strip() if latest_date and latest_date != "待确认" else latest)
        if row.get("next_milestone", ""):
            milestone = row.get("next_milestone", "")
            window = row.get("next_milestone_date_or_window", "")
            progress_parts.append(f"下一步:{milestone}({window})" if window and window != "待确认" else f"下一步:{milestone}")
        source_note = join_unique_values([source_brief(row.get("source", "")), row.get("verification_notes", "")])
        bd_sheet.append([
            row.get("company_name", ""),
            row.get("target", ""),
            row.get("drug_or_pipeline", ""),
            row.get("modality", ""),
            row.get("partner", ""),
            deal_value,
            row.get("territory", ""),
            join_unique_segments(row.get("covered_indications", "")),
            join_unique_values([row.get("deal_type", ""), "；".join(key_dates)]),
            "；".join(progress_parts),
            field_trust_tier(row),
            source_note,
        ])
    if len(bd_sheet) == 1:
        bd_sheet.append(["待补充", "", "", "", "", "", "", "", "", "暂无BD交易种子", "待核验", ""])

    catalyst_sheet = [[
        "日期/窗口", "公告日期", "预计时间", "实际日期", "公司名称", "药物/管线",
        "事件类型", "事件内容", "状态", "结果", "字段可信度", "来源"
    ]]
    for row in catalyst_rows:
        catalyst_sheet.append([
            row.get("date_or_window", ""),
            row.get("announced_date", ""),
            row.get("expected_date_or_window", ""),
            row.get("actual_date", ""),
            row.get("company_name", ""),
            row.get("drug_or_pipeline", ""),
            row.get("catalyst_type", ""),
            row.get("event_summary", ""),
            row.get("status", ""),
            row.get("result", ""),
            field_trust_tier("低" if "social_media" in row.get("source", "") else "中"),
            source_brief(row.get("source", "")),
        ])

    verification_sheet = [["公司名称", "待核验事项", "建议来源", "创建日期", "计划核验日期", "解决日期", "来源"]]
    for row in verification_rows:
        verification_sheet.append([
            row.get("company_name", ""),
            row.get("missing_item", ""),
            row.get("suggested_next_source", ""),
            row.get("opened_at", ""),
            row.get("target_check_date", ""),
            row.get("resolved_at", ""),
            source_brief(row.get("source", ""), max_items=1, include_attachment_suffix=False),
        ])

    revenue_sheet = cm310_revenue_template_rows(company_rows, pipeline_rows)
    market_sheet = market_validation_template_rows(company_rows, catalyst_rows)

    attachment_sheet = [[
        "附件ID", "公司名称", "药物/项目编号", "靶点", "适应症", "来源类型",
        "来源标题", "发布日期", "链接/文件/SourceID", "置信度", "原始摘录/报告摘要", "抽取字段"
    ]]
    for idx, row in enumerate(source_manifest_rows, start=1):
        source_ref = row.get("source_path_or_url", "") or row.get("source_id", "")
        attachment_sheet.append([
            f"A{idx:04d}",
            row.get("company_name", ""),
            row.get("drug_or_pipeline", ""),
            row.get("target", ""),
            row.get("indication", ""),
            row.get("source_type", ""),
            row.get("source_title", ""),
            row.get("publish_date", ""),
            source_ref,
            row.get("source_confidence", ""),
            row.get("notes", ""),
            row.get("fields_to_extract", ""),
        ])
    if len(attachment_sheet) == 1:
        attachment_sheet.append(["A0001", "", "", "", "", "", "暂无附件来源索引", "", "", "", "", ""])

    def safe_sheet_title(name: str, used: set[str]) -> str:
        clean = re.sub(r"[\[\]\:\*\?\/\\]", "_", name or "未命名公司").strip()[:31] or "未命名公司"
        base = clean
        counter = 2
        while clean in used:
            suffix = f"_{counter}"
            clean = (base[: 31 - len(suffix)] + suffix)[:31]
            counter += 1
        used.add(clean)
        return clean

    company_detail_sheets: list[tuple[str, list[list[Any]]]] = []
    used_sheet_names = {
        "汇总", "靶点全景总览", "靶点-适应症明细", "阶段分布统计", "BD合作一览",
        "催化剂追踪", "待核验清单", "收入利润假设", "行情验证", "附件索引",
    }
    company_names = sorted({row.get("company_name", "") for row in pipeline_rows if row.get("company_name", "")})
    generated_date = datetime.now().strftime("%Y-%m-%d")
    source_line = f"数据更新日期：{generated_date} | 来源：{summarize_source_types(pipeline_rows, bd_rows, catalyst_rows)}"
    overall_company_label = company_display(company_rows)
    if len(company_names) > 1:
        for company in company_names:
            rows = [detail[0], *[line for line in detail[1:] if line and line[0] == company]]
            if len(rows) > 1:
                company_detail_sheets.append((
                    safe_sheet_title(company, used_sheet_names),
                    with_sheet_intro(company_display(company_rows, company), "靶点-适应症明细", group_detail_table(rows)),
                ))

    output = out_dir / "innovative_drug_analysis.xlsx"
    sheets: list[tuple[str, list[list[Any]]]] = [
        ("汇总", with_sheet_intro(overall_company_label, "汇总", summary, source_line)),
        *company_detail_sheets,
        ("靶点全景总览", with_sheet_intro(overall_company_label, "靶点全景总览", overview)),
        ("靶点-适应症明细", with_sheet_intro(overall_company_label, "靶点-适应症明细", grouped_detail)),
        ("阶段分布统计", with_sheet_intro(overall_company_label, "阶段分布统计", stage_summary)),
        ("BD合作一览", with_sheet_intro(overall_company_label, "BD合作一览", bd_sheet)),
        ("催化剂追踪", with_sheet_intro(overall_company_label, "催化剂追踪", catalyst_sheet)),
        ("待核验清单", with_sheet_intro(overall_company_label, "待核验清单", verification_sheet)),
        ("收入利润假设", with_sheet_intro(overall_company_label, "收入利润假设", revenue_sheet)),
        ("行情验证", with_sheet_intro(overall_company_label, "行情验证", market_sheet)),
        ("附件索引", with_sheet_intro(overall_company_label, "附件索引", attachment_sheet)),
    ]
    write_xlsx(output, sheets)
    return output


def summarize_cause_for_preview(row: dict[str, Any], cause_by_code: dict[str, dict[str, Any]]) -> str:
    cause = cause_by_code.get(row.get("code", ""))
    if cause:
        status = cause.get("evidence_status", "")
        judgement = cause.get("cause_judgement", "")
        source_type = cause.get("top_source_type", "")
        score = cause.get("top_relevance_score", "")
        summary = cause.get("analyst_judgement") or cause.get("evidence_summary") or cause.get("notes") or ""
        if len(summary) > 70:
            summary = summary[:70] + "..."
        links = [url for url in str(cause.get("source_url_or_path", "")).split("；") if url.strip()]
        link_text = "有链接" if links else "无链接"
        source_text = f"{source_type}/{score}" if source_type or score else ""
        return "；".join(part for part in [status, judgement, source_text, summary, link_text] if part)
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
    kline_sources = count_items([row.get("kline_provider", "") for row in kline_rows if row.get("kline_provider")])
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
            metric("K线来源", kline_sources[0][0] if kline_sources else "NA", kline_tone),
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
                ("kline_provider", "K线来源"),
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
    pipeline_rows = sanitize_pipeline_rows(read_csv_rows(out_dir / "pipeline_progress_seed.csv"))
    catalyst_rows = read_csv_rows(out_dir / "catalyst_tracker_seed.csv")
    bd_rows = expand_bd_rows_by_partner(read_csv_rows(out_dir / "bd_deal_tracker_seed.csv"))
    verification_rows = read_csv_rows(out_dir / "verification_queue.csv")

    modality_counts = count_items([tag for row in company_rows for tag in split_tags(row.get("modality_tags", ""))])
    disease_counts = count_items([tag for row in company_rows for tag in split_tags(row.get("disease_area_tags", ""))])
    pipeline_by_company: dict[str, list[dict[str, str]]] = {}
    catalyst_by_company: dict[str, list[dict[str, str]]] = {}
    bd_by_company: dict[str, list[dict[str, str]]] = {}
    for row in pipeline_rows:
        pipeline_by_company.setdefault(row.get("company_name", ""), []).append(row)
    for row in catalyst_rows:
        catalyst_by_company.setdefault(row.get("company_name", ""), []).append(row)
    for row in bd_rows:
        bd_by_company.setdefault(row.get("company_name", ""), []).append(row)

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

    project_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in pipeline_rows:
        key = (row.get("company_name", ""), row.get("drug_or_pipeline", ""), row.get("target", ""))
        item = project_map.setdefault(
            key,
            {
                "company_name": row.get("company_name", ""),
                "drug_or_pipeline": row.get("drug_or_pipeline", ""),
                "target": row.get("target", ""),
                "modality": row.get("modality", ""),
                "indications": [],
                "stages": [],
                "progress": [],
                "dates": [],
                "confidence": [],
                "sources": [],
                "next_windows": [],
            },
        )
        for field, bucket in [
            ("indication", "indications"),
            ("clinical_stage", "stages"),
            ("latest_progress", "progress"),
            ("progress_date", "dates"),
            ("source_confidence", "confidence"),
            ("source", "sources"),
            ("next_catalyst_date_or_window", "next_windows"),
        ]:
            value = row.get(field, "")
            if value and value not in item[bucket]:
                item[bucket].append(value)

    project_rows = list(project_map.values())
    project_rows.sort(
        key=lambda row: (
            row.get("company_name", ""),
            -stage_rank(choose_highest_stage(row.get("stages", []))),
            row.get("target", ""),
            row.get("drug_or_pipeline", ""),
        )
    )

    commercial_projects = [
        row for row in project_rows
        if "已上市" in choose_highest_stage(row.get("stages", [])) or any(
            word in "；".join(row.get("progress", [])) for word in ["商业化", "销售", "医保", "收入", "放量"]
        )
    ]
    medium_high_projects = [row for row in project_rows if stage_rank(choose_highest_stage(row.get("stages", []))) >= 60]
    bd_project_keys = {(row.get("company_name", ""), row.get("drug_or_pipeline", "")) for row in bd_rows}
    contamination_flags = []
    drug_to_companies: dict[str, set[str]] = {}
    for row in pipeline_rows:
        drug_to_companies.setdefault(row.get("drug_or_pipeline", ""), set()).add(row.get("company_name", ""))
    for drug, companies in drug_to_companies.items():
        if drug and len(companies) > 1:
            contamination_flags.append(f"{drug}: {'、'.join(sorted(companies))}")

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
    if not pipeline_rows:
        lines.append("当前资料主要完成公司池识别，缺少可核验的药物、靶点、适应症、阶段和催化剂信息；不能直接用于投资判断。")
    else:
        lines.append("本轮材料可以形成创新药跟踪底稿，但仍属于“结构化初稿”：关键管线阶段、BD权益、商业化放量和股价上涨逻辑仍需逐项核验。")
        if commercial_projects:
            names = "、".join(dict.fromkeys(row["company_name"] for row in commercial_projects[:5]))
            lines.append(f"- 商业化/收入线索：{names} 存在已上市、医保、销售或收入相关线索，应优先拆收入利润假设。")
        if medium_high_projects:
            assets = "、".join(dict.fromkeys(f"{row['company_name']}-{row['drug_or_pipeline']}" for row in medium_high_projects[:6]))
            lines.append(f"- 临床/申报催化线索：{assets} 处于中后期或申报/上市相关阶段，适合进入月度跟踪。")
        if bd_rows:
            bd_assets = "、".join(dict.fromkeys(f"{row.get('company_name','')}-{row.get('drug_or_pipeline','')}" for row in bd_rows[:6]))
            lines.append(f"- BD/出海线索：{bd_assets} 已识别合作或里程碑信息，但金额、权益区域和适应症覆盖必须回到公告/年报核验。")
        lines.append("- 当前报告不能直接作为投资结论：还缺少行情数据、指数相对收益、成交额、收入利润模型和竞品对比。")

    lines.extend(["", "## 二、重点观察对象", ""])
    if watchlist:
        lines.append("本轮不建议在 Markdown 里重复铺开全部底表。重点应放在“哪些公司/资产值得先看、为什么、下一步查什么”。完整字段请看 Excel：`汇总`、`靶点全景总览`、`靶点-适应症明细`、`催化剂追踪`。")
        for score, company, reasons, _row in watchlist[:6]:
            pipelines = pipeline_by_company.get(company, [])
            catalysts = catalyst_by_company.get(company, [])
            pipeline_text = "；".join(dict.fromkeys(
                f"{item.get('drug_or_pipeline', '')}({item.get('target', '')})" for item in pipelines[:4]
            )) or "待补管线底稿"
            catalyst_text = "；".join(dict.fromkeys(
                report_event_summary(item, 90) for item in catalysts[:2]
            )) or "待补催化剂"
            priority = "高" if score >= 4 else "中" if score >= 2 else "待补充"
            lines.extend([
                "",
                f"**{company}：{priority}优先级**",
                f"- 跟踪定位：{'、'.join(reasons) if reasons else '待补充公司资料'}。",
                f"- 代表资产：{pipeline_text}。",
                f"- 近期看点：{catalyst_text}。",
                "- 下一步：核验阶段口径、权益归属、BD条款、收入贡献和行情验证。",
            ])
    else:
        lines.append("暂无可排序观察对象，需先补公司池和来源索引。")

    lines.extend(["", "## 三、资产和催化剂判断", ""])
    lines.append("Markdown 只保留资产层面的判断，不再展开 `药物 × 靶点 × 适应症 × 阶段` 全量表。完整拆行请看 Excel `靶点-适应症明细`；阶段分布请看 `阶段分布统计`；催化剂时间线请看 `催化剂追踪`。")
    if project_rows:
        top_projects = project_rows[:8]
        for item in top_projects:
            stage = choose_highest_stage(item.get("stages", []))
            indications = "、".join(item.get("indications", [])[:4]) or "待细分适应症"
            progress = concise_research_text("；".join(item.get("progress", [])), 120)
            confidence = choose_highest_confidence(item.get("confidence", [])) if item.get("confidence") else "待确认"
            lines.append(
                f"- **{item['company_name']} - {item['drug_or_pipeline']}（{item['target']}）**："
                f"{stage}；覆盖 {indications}；{progress or '最新进展待补'}；来源可信度 {confidence}。"
            )
    else:
        lines.append("- 暂无资产级事实，不能形成管线判断。")

    if catalyst_rows:
        lines.extend(["", "**近期催化剂摘要**"])
        for row in catalyst_rows[:8]:
            lines.append(
                f"- {row.get('date_or_window','待确认')}｜{row.get('company_name','')}-"
                f"{row.get('drug_or_pipeline','')}：{report_event_summary(row, 140)}"
            )
    else:
        lines.append("- 暂无明确催化剂线索。")

    lines.extend(["", "## 四、BD / 出海判断", ""])
    if bd_rows:
        lines.append("BD 不适合只看“有没有合作”，需要拆到项目、合作方、区域、金额、权益和触发条件。完整交易拆行请看 Excel `BD合作一览`。")
        for row in bd_rows[:8]:
            terms = combine_deal_value(row) or "金额待确认"
            lines.append(
                f"- **{row.get('company_name','')} - {row.get('drug_or_pipeline','')}**："
                f"合作方 {row.get('partner','待确认')}；{terms}；区域 {row.get('territory','待确认')}；"
                f"公告/进展日期 {row.get('announcement_date','待确认')}。"
            )
    else:
        lines.append("当前没有抽到可用 BD 交易行。下一步优先查公告、年报、授权协议摘要和高质量研报。")

    lines.extend(["", "## 五、收入利润和商业化", ""])
    lines.append("收入利润部分不在 Markdown 中铺空表。Excel `收入利润假设` 已保留 CM310 等商业化品种的假设模板；Markdown 只记录建模口径。")
    if commercial_projects:
        commercial_text = "、".join(dict.fromkeys(f"{row['company_name']}-{row['drug_or_pipeline']}" for row in commercial_projects[:6]))
        lines.append(f"- 优先建模资产：{commercial_text}。")
    lines.extend([
        "- 必补字段：医保状态、患者池、可治疗比例、渗透率、年治疗费用、峰值销售额、2026E/2027E/2028E 收入、毛利率、销售费用率和利润贡献。",
        "- 建模原则：不要把券商假设直接当事实；可先作为情景参数，再用公司披露销售、医保执行和渠道覆盖数据校准。",
    ])

    lines.extend(["", "## 六、股价上涨逻辑验证", ""])
    lines.append("上涨逻辑不能只由管线新闻推出，必须叠加行情和时间线。Excel `行情验证` 已保留 1/5/20/60 日涨跌幅、成交额和相对指数收益字段。")
    lines.append("| 逻辑模块 | 当前状态 | 下一步需要的数据 | 判断方法 |")
    lines.append("| --- | --- | --- | --- |")
    event_evidence = "；".join(dict.fromkeys(
        f"{row.get('company_name','')}-{row.get('drug_or_pipeline','')}: {report_event_summary(row, 60)}"
        for row in catalyst_rows[:4]
    )) or "暂缺明确催化剂"
    narrative_evidence = "；".join(f"{name}({count})" for name, count in modality_counts[:5]) or "待补充"
    disease_evidence = "；".join(f"{name}({count})" for name, count in disease_counts[:5]) or "待补充"
    lines.append(f"| 事件催化 | 待验证；已有线索：{md_cell(event_evidence, 110)} | 公告/会议/临床登记日期、催化剂完成状态 | 看股价是事件前预期、同步反应，还是兑现后回落 |")
    lines.append(f"| 叙事变化 | 待验证；技术路线：{md_cell(narrative_evidence, 70)}；适应症：{md_cell(disease_evidence, 70)} | 当期市场主线、同类公司涨跌、研报标题变化 | 判断是否为板块叙事扩散而非单一公司基本面 |")
    lines.append("| 业绩兑现 | 待核验 | 销售额、医保后放量、费用率、利润率 | 与收入利润假设表联动 |")
    lines.append("| 资金行为 | 待核验 | 1/5/20/60日涨跌幅、成交额、换手率、相对恒生医疗/创新药指数收益 | 判断是否放量、是否跑赢板块、是否利好兑现 |")

    lines.extend(["", "## 七、事实、推断和待核验边界", ""])
    high_count = sum(1 for row in pipeline_rows if row.get("source_confidence") == "高")
    medium_count = sum(1 for row in pipeline_rows if row.get("source_confidence") == "中")
    low_count = sum(1 for row in pipeline_rows if row.get("source_confidence") == "低")
    lines.extend([
        f"- 已确认/高可信事实：{high_count} 条。通常来自公告、年报、官方资料或高置信来源。",
        f"- 中等可信事实：{medium_count} 条。通常来自研报、路演纪要或 AlphaPai 投研资料，需要和官方资料交叉。",
        f"- 待核验线索：{low_count} 条。不得直接进入投资结论。",
        "- 所有资产阶段、BD金额、权益区域和商业化假设，最终以 Excel `附件索引` 对应来源回溯。",
    ])

    lines.extend(["", "## 八、优先待核验清单", ""])
    if verification_rows:
        for row in verification_rows[:10]:
            lines.append(
                f"- **{row.get('company_name','')}**：{row.get('missing_item','管线事实/阶段/来源核验')}；"
                f"建议来源：{row.get('suggested_next_source','公告、官网管线页、临床登记、年报、券商深度')}。"
            )
    else:
        for row in project_rows[:6]:
            lines.append(
                f"- **{row['company_name']} - {row['drug_or_pipeline']}**：核验阶段、适应症和来源；完成后更新 Excel `靶点-适应症明细`。"
            )

    lines.extend(["", "## 九、项目归属 / 交叉污染风险", ""])
    if contamination_flags:
        lines.append("以下项目在多家公司材料中同时出现，必须核验权益归属、原始授权方、现权益方、适应症和阶段，不能直接归为多家公司核心管线：")
        for flag in contamination_flags[:10]:
            lines.append(f"- {flag}")
    else:
        lines.append("当前自动分组未发现同一项目名被多家公司同时占用；但 BD/NewCo/共同开发项目仍需按公告原文复核权益归属。")
    lines.extend(
        [
            "",
            "## 十、使用边界",
            "",
            "本报告是结构化投研初稿，不是最终投资建议。已确认事实、推断和待核验线索必须分开使用；没有公告、年报、临床登记、会议摘要或高质量研报支撑的内容，不应直接进入投资结论。",
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

    include_kline_chart = fields.get("include_kline_chart") == "true"
    env_contexts = [
        temporary_env("STOCK_MONITOR_ENABLE_AKSHARE", "1") if include_kline_chart else contextlib.nullcontext(),
        temporary_env("STOCK_MONITOR_ENABLE_HK_KLINE", "1") if include_kline_chart else contextlib.nullcontext(),
        contextlib.nullcontext() if include_kline_chart else temporary_env("STOCK_MONITOR_FAST_MODE", "1"),
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ]
    with contextlib.ExitStack() as stack:
        for env_context in env_contexts:
            stack.enter_context(env_context)
        rows = stock_monitor.build_rows(stocks)
    stocks_by_code = {stock.code: stock for stock in stocks}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
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
    if include_kline_chart:
        chart_path = out_dir / f"kline_annotations_{run_date}.html"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            stock_monitor.write_kline_annotations(rows, stocks_by_code, cause_checks, chart_path)

    abnormal_count = sum(1 for row in rows if row.get("is_abnormal") == "是")
    return {
        "summary": f"已监控 {len(rows)} 只股票，发现 {abnormal_count} 条异动。",
        "files": output_files(out_dir),
        "bundle": output_bundle(out_dir),
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
        "bundle": output_bundle(out_dir),
        "preview": build_analyst_preview(enriched, scorecards, report_path),
    }


def run_drug_research(fields: dict[str, Any]) -> dict[str, Any]:
    upload = fields.get("file")
    selected_raw = (fields.get("selected_companies") or "").strip()
    selected_names: list[str] = []
    if selected_raw:
        try:
            parsed_selected = json.loads(selected_raw)
            if isinstance(parsed_selected, list):
                selected_names = [str(item).strip() for item in parsed_selected if str(item).strip()]
        except json.JSONDecodeError:
            selected_names = []

    if selected_names:
        pool = load_drug_company_pool()
        selected_set = {normalize_company_name(name) for name in selected_names}
        selected_companies = [
            row for row in pool if normalize_company_name(row.get("company_name", "")) in selected_set
        ]
        if not selected_companies:
            raise ValueError("没有在内置公司池中找到所选公司")
        path = UPLOAD_DIR / f"drug_selected_{timestamp()}.md"
        path.write_text(build_company_list_markdown(selected_companies), encoding="utf-8")
    elif upload and upload.get("filename"):
        path = save_upload(upload, "drug")
    else:
        raise ValueError("请上传公司列表，或从内置公司池中选择至少一家公司")

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
            "--source-name",
            f"上传公司列表：{path.name}",
        ]
        drug_seed.main()
    finally:
        sys.argv = old_argv

    companies_for_recall = list(dict.fromkeys(row.get("company_name", "") for row in parsed if row.get("company_name", "")))
    alphapai_status = enrich_drug_tables_with_alphapai(out_dir, companies_for_recall)
    alphapai_deep_status: dict[str, Any] = {}
    if alphapai_status.get("enabled") and len(companies_for_recall) == 1:
        try:
            alphapai_deep_status = alphapai_deep_research_company(companies_for_recall[0], out_dir)
        except Exception as exc:
            alphapai_deep_status = {"error": str(exc)}
    write_innovative_drug_analysis(out_dir, path.name)
    write_innovative_drug_excel(out_dir)

    alpha_summary = ""
    if alphapai_status.get("enabled"):
        alpha_summary = (
            f" AlphaPai已补充管线 {alphapai_status.get('pipeline', 0)} 条、"
            f"催化剂 {alphapai_status.get('catalysts', 0)} 条、"
            f"BD {alphapai_status.get('bd', 0)} 条。"
        )
        if alphapai_status.get("errors"):
            alpha_summary += f" 另有 {len(alphapai_status['errors'])} 家召回需重试。"
        if alphapai_deep_status.get("markdown"):
            alpha_summary += " 已生成AlphaPai深度投研底稿。"
        elif alphapai_deep_status.get("error"):
            alpha_summary += " AlphaPai深度底稿需重试。"
    else:
        alpha_summary = " AlphaPai未启用，本次使用本地种子数据。"
    return {
        "summary": f"已识别 {len(parsed)} 条公司列表记录，并生成结构化表和分析报告。{alpha_summary}",
        "files": output_files(out_dir),
        "bundle": output_bundle(out_dir),
        "preview": build_drug_preview(out_dir),
    }


class ResearchHandler(BaseHTTPRequestHandler):
    server_version = "ResearchAssistant/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The browser closed/refreshed the page while a response was being written.
            return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def resolve_output_file(self, path: str, prefix: str) -> Path | None:
        parts = path.split("/")
        if len(parts) != 4 or parts[1] != prefix:
            return None
        run_id, filename = parts[2], parts[3]
        folder = output_folder_for_run(run_id)
        file_path = (folder / filename).resolve() if folder else None
        if file_path and file_path.exists() and file_path.is_file() and folder and folder in file_path.parents:
            return file_path
        return None

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

        if path == "/api/drug/companies":
            self.send_json(200, {"companies": load_drug_company_pool()})
            return

        if path.startswith("/download-zip/"):
            parts = path.split("/")
            if len(parts) == 3:
                run_id = parts[2]
                folder = output_folder_for_run(run_id)
                if folder:
                    headers = {"Content-Disposition": f'attachment; filename="{folder.name}.zip"'}
                    self.send_bytes(200, build_output_zip(folder), "application/zip", headers)
                    return
            self.send_bytes(404, "打包文件不存在".encode("utf-8"), "text/plain; charset=utf-8")
            return

        if path.startswith("/preview/"):
            file_path = self.resolve_output_file(path, "preview")
            if file_path:
                self.send_bytes(200, render_file_preview(file_path), "text/html; charset=utf-8")
                return
            self.send_bytes(404, "预览文件不存在".encode("utf-8"), "text/plain; charset=utf-8")
            return

        if path.startswith("/download/"):
            file_path = self.resolve_output_file(path, "download")
            if file_path:
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
