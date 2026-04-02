from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import streamlit as st
from pypdf import PdfReader


STATUS_GREEN = "On Schedule"
STATUS_AMBER = "Potential Delay"
STATUS_RED = "Delay"


@dataclass
class AircraftReport:
    file_name: str
    regn: str = "UNKNOWN"
    bay: str = "-"
    customer: str = "-"
    ac_type: str = "-"
    check_type: str = "-"
    status: str = "Unknown"
    ata: str = "-"
    etc: str = "-"
    etd: str = "-"
    day: str = "-"
    insp_maint: str = "-"
    reason: list[str] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    progress_highlights: list[str] = field(default_factory=list)

    @property
    def status_class(self) -> str:
        s = self.status.lower()
        if "on schedule" in s:
            return "green"
        if "potential delay" in s:
            return "amber"
        if s == "delay":
            return "red"
        return "unknown"


def _clean_line(line: str) -> str:
    line = line.replace("\u2022", "-").replace("\u25cf", "-").strip()
    line = re.sub(r"\s+", " ", line)
    return line


def _non_empty_lines(text: str) -> list[str]:
    return [_clean_line(x) for x in text.splitlines() if _clean_line(x)]


def _extract_first(patterns: Iterable[str], text: str, default: str = "-") -> str:
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return _clean_line(match.group(1))
    return default


def _extract_block(start_re: str, end_res: list[str], text: str) -> list[str]:
    start = re.search(start_re, text, re.IGNORECASE)
    if not start:
        return []
    sub = text[start.end() :]
    end_pos = len(sub)
    for end_re in end_res:
        m = re.search(end_re, sub, re.IGNORECASE)
        if m:
            end_pos = min(end_pos, m.start())
    block = sub[:end_pos]
    lines = _non_empty_lines(block)
    cleaned: list[str] = []
    for line in lines:
        line = re.sub(r"^[-:]\s*", "", line)
        if line:
            cleaned.append(line)
    return cleaned


def _guess_regn_from_filename(file_name: str) -> str:
    stem = Path(file_name).stem
    token = re.split(r"[_\s]", stem)[0]
    token = token.strip("-")
    return token.upper() if token else "UNKNOWN"


def parse_pdf_file(file_name: str, file_bytes: bytes) -> AircraftReport:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = _non_empty_lines(text)
    raw = "\n".join(lines)

    regn = _extract_first(
        [
            r"A/C\s*Regn[:\s]+([A-Z0-9\-]+)",
            r"Aircraft\s*Regn[:\s]+([A-Z0-9\-]+)",
        ],
        raw,
        _guess_regn_from_filename(file_name),
    )

    status = _extract_first(
        [r"A/C\s*Overall\s*Status[:\s]+([A-Za-z ]+)", r"Overall\s*Status[:\s]+([A-Za-z ]+)"],
        raw,
        "Unknown",
    )
    if "on schedule" in status.lower():
        status = STATUS_GREEN
    elif "potential delay" in status.lower():
        status = STATUS_AMBER
    elif re.search(r"\bdelay\b", status, re.IGNORECASE):
        status = STATUS_RED

    bay = _extract_first([r"\bBay[:\s]+([A-Z0-9]+)\b", r"\bLocation[:\s]+Bay\s*([A-Z0-9]+)\b"], raw)
    customer = _extract_first([r"Customer[:\s]+([A-Za-z0-9 /&\-\(\)]+)"], raw)
    ac_type = _extract_first([r"Type[:\s]+([A-Za-z0-9\-]+)", r"A/C\s*Type[:\s]+([A-Za-z0-9\-]+)"], raw)
    check_type = _extract_first([r"Check\s*Type[:\s]+([A-Za-z0-9+\/\-\s\(\)]+)"], raw)

    ata = _extract_first([r"\bATA[:\s]+([0-9: /A-Za-z\-\(\)]+)"], raw)
    etc = _extract_first([r"\bETC[:\s]+([0-9: /A-Za-z\-\(\)\+]+)"], raw)
    etd = _extract_first([r"\bETD[:\s]+([0-9: /A-Za-z\-\(\)\+]+)"], raw)
    day = _extract_first([r"\bDay[:\s]+([0-9 ]+of[ 0-9]+)"], raw)
    insp_maint = _extract_first([r"\bINSP\s*/\s*MAINT[:\s]+([0-9% /]+)"], raw)

    reason = _extract_block(r"Reason", [r"Critical Task", r"Progress Highlights", r"RTC", r"Remarks"], raw)
    crit = _extract_block(r"Critical\s*Task\s*/\s*Issue", [r"Progress Highlights", r"RTC", r"Remarks"], raw)
    prog = _extract_block(r"Progress Highlights", [r"RTC", r"Remarks"], raw)

    # Fallbacks for reports with inconsistent headings.
    if not crit:
        crit = _extract_block(r"Critical\s*Issue", [r"Progress", r"RTC", r"Remarks"], raw)
    if not prog:
        prog = _extract_block(r"Work Done", [r"RTC", r"Remarks"], raw)

    return AircraftReport(
        file_name=file_name,
        regn=regn,
        bay=bay,
        customer=customer,
        ac_type=ac_type,
        check_type=check_type,
        status=status,
        ata=ata,
        etc=etc,
        etd=etd,
        day=day,
        insp_maint=insp_maint,
        reason=reason,
        critical_issues=crit,
        progress_highlights=prog,
    )


def _issue_tag(line: str) -> str:
    l = line.lower()
    if any(k in l for k in ["aog", "waiting", "pending", "blocked", "shortage", "fault", "crack"]):
        return "BLOCKING"
    if any(k in l for k in ["wip", "monitor", "inspection", "rectification"]):
        return "MONITOR"
    return "INFO"


def render_text_report(items: list[AircraftReport], report_date: str) -> str:
    green = sum(i.status_class == "green" for i in items)
    amber = sum(i.status_class == "amber" for i in items)
    red = sum(i.status_class == "red" for i in items)
    delivered = [i for i in items if "complete" in i.status.lower() or i.etd != "-"]
    active = len(items) - 0

    lines: list[str] = []
    lines += [
        "BM DAILY AIRCRAFT PROGRESS REPORT",
        f"Report Date: {report_date}",
        "",
        f"Total A/Cs: {len(items)} | Green: {green} | Amber: {amber} | Red: {red}",
        f"BM Active Maintenance: {active}",
        "",
        "MAINTENANCE IN PROGRESS",
        "============================================================",
    ]
    for i in sorted(items, key=lambda x: x.bay):
        lines.append(f"Bay {i.bay} - {i.regn} ({i.customer} / {i.ac_type}) {i.check_type} | {i.status}")
        lines.append(f"ATA: {i.ata} | ETC: {i.etc}" + (f" | ETD: {i.etd}" if i.etd != "-" else ""))
        if i.reason:
            lines.append("Reason:")
            for r in i.reason[:4]:
                lines.append(f"- {r}")
        lines.append("Critical Task / Issue:")
        if i.critical_issues:
            for c in i.critical_issues[:6]:
                lines.append(f"- [{_issue_tag(c)}] {c}")
        else:
            lines.append("- (none)")
        lines.append("Progress Highlights:")
        if i.progress_highlights:
            for p in i.progress_highlights[:6]:
                lines.append(f"- {p}")
        else:
            lines.append("- (none)")
        lines.append("")
    if delivered:
        lines.append("Delivered / ETD Set:")
        for i in delivered:
            lines.append(f"- {i.regn} (Bay {i.bay}) ETD: {i.etd}")
    return "\n".join(lines)


def render_html_report(items: list[AircraftReport], report_date: str) -> str:
    green = sum(i.status_class == "green" for i in items)
    amber = sum(i.status_class == "amber" for i in items)
    red = sum(i.status_class == "red" for i in items)
    cards = []
    for i in sorted(items, key=lambda x: x.bay):
        reason_html = "".join(f"<li>{html.escape(r)}</li>" for r in i.reason[:4]) or "<li>(none)</li>"
        crit_html = "".join(
            f"<li><strong>[{_issue_tag(c)}]</strong> {html.escape(c)}</li>" for c in i.critical_issues[:6]
        ) or "<li>(none)</li>"
        prog_html = "".join(f"<li>{html.escape(p)}</li>" for p in i.progress_highlights[:6]) or "<li>(none)</li>"
        cards.append(
            f"""
            <div class="card {i.status_class}">
              <h3 contenteditable="true">Bay {html.escape(i.bay)} - {html.escape(i.regn)} | {html.escape(i.status)}</h3>
              <p contenteditable="true">{html.escape(i.customer)} / {html.escape(i.ac_type)} | {html.escape(i.check_type)}</p>
              <p contenteditable="true"><strong>ATA:</strong> {html.escape(i.ata)} | <strong>ETC:</strong> {html.escape(i.etc)} | <strong>ETD:</strong> {html.escape(i.etd)}</p>
              <div class="cols">
                <div><h4 contenteditable="true">Reason</h4><ul contenteditable="true">{reason_html}</ul></div>
                <div><h4 contenteditable="true">Critical Task / Issue</h4><ul contenteditable="true">{crit_html}</ul></div>
                <div><h4 contenteditable="true">Progress Highlights</h4><ul contenteditable="true">{prog_html}</ul></div>
              </div>
            </div>
            """
        )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>BM Daily Report - {html.escape(report_date)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f4f6f8; }}
    .header {{ background:#102a43; color:#fff; padding:16px; border-radius:10px; }}
    .stats {{ margin-top:8px; font-size:14px; }}
    .card {{ background:#fff; border-radius:10px; padding:14px; margin:12px 0; border-left:6px solid #999; }}
    .green {{ border-color:#28a745; }} .amber {{ border-color:#f0ad4e; }} .red {{ border-color:#d9534f; }}
    .cols {{ display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px; }}
    h3 {{ margin:0 0 6px 0; }} p {{ margin:4px 0; }} ul {{ margin:6px 0 0 18px; }}
    [contenteditable="true"] {{ outline: 1px dashed transparent; border-radius:4px; }}
    [contenteditable="true"]:hover {{ outline-color:#6aa0d8; }}
    [contenteditable="true"]:focus {{ outline:2px solid #3f83c4; background:#eef7ff; }}
  </style>
</head>
<body>
  <div class="header">
    <h1 contenteditable="true">BM Daily Aircraft Progress Report</h1>
    <div class="stats" contenteditable="true">Date: {html.escape(report_date)} | Total: {len(items)} | Green: {green} | Amber: {amber} | Red: {red}</div>
  </div>
  {"".join(cards)}
</body>
</html>"""


def process_uploaded_files(files: list) -> list[AircraftReport]:
    reports: list[AircraftReport] = []
    for f in files:
        try:
            reports.append(parse_pdf_file(f.name, f.getvalue()))
        except Exception as exc:
            st.warning(f"Failed to parse {f.name}: {exc}")
    return reports


def process_folder(folder_path: str) -> tuple[list[AircraftReport], list[str]]:
    path = Path(folder_path).expanduser()
    if not path.exists() or not path.is_dir():
        return [], []
    pdf_files = sorted(path.glob("*.pdf"))
    reports: list[AircraftReport] = []
    for p in pdf_files:
        try:
            reports.append(parse_pdf_file(p.name, p.read_bytes()))
        except Exception as exc:
            st.warning(f"Failed to parse {p.name}: {exc}")
    return reports, [str(x) for x in pdf_files]


def render_outputs(reports: list[AircraftReport], report_date: str, output_dir: str | None = None) -> None:
    txt = render_text_report(reports, report_date)
    html_out = render_html_report(reports, report_date)
    safe_date = report_date.replace("/", "-").replace(" ", "_")
    txt_name = f"BM_Daily_Report_{safe_date}.txt"
    html_name = f"BM_Daily_Report_{safe_date}.html"

    st.success(f"Generated from {len(reports)} PDF file(s).")
    st.download_button("Download Text Report (.txt)", txt, file_name=txt_name)
    st.download_button("Download HTML Report (.html)", html_out, file_name=html_name)

    if output_dir:
        out_path = Path(output_dir).expanduser()
        if out_path.exists() and out_path.is_dir():
            txt_path = out_path / txt_name
            html_path = out_path / html_name
            txt_path.write_text(txt, encoding="utf-8")
            html_path.write_text(html_out, encoding="utf-8")
            st.info(f"Saved files to: {txt_path} and {html_path}")
        else:
            st.warning(f"Output folder does not exist: {out_path}")

    st.text_area("Text Preview", txt, height=420)
    st.components.v1.html(html_out, height=700, scrolling=True)


def app() -> None:
    st.set_page_config(page_title="BM Daily Report Generator", layout="wide")
    st.title("BM Daily Report Generator")
    st.caption("Upload daily aircraft PDFs and generate management-ready text + HTML summaries.")

    report_date = st.text_input("Report Date", value=datetime.now().strftime("%d %b %Y"))
    mode = st.radio("Input Mode", ["Upload PDFs", "Watch Folder"], horizontal=True)

    if mode == "Upload PDFs":
        files = st.file_uploader("Upload daily PDF files", type=["pdf"], accept_multiple_files=True)
        if not files:
            st.info("Upload one or more PDFs to generate the report.")
            return
        reports = process_uploaded_files(files)
        if not reports:
            st.error("No reports could be parsed.")
            return
        render_outputs(reports, report_date)
        return

    default_watch = str(Path.home() / "Downloads" / "2Apr Daily Report")
    watch_folder = st.text_input("Watch Folder Path", value=default_watch)
    output_folder = st.text_input("Output Folder Path", value=watch_folder)
    auto_generate = st.checkbox("Auto-generate from folder on each refresh", value=True)
    run_now = st.button("Scan Folder Now")

    reports: list[AircraftReport] = []
    files_found: list[str] = []

    if auto_generate or run_now:
        reports, files_found = process_folder(watch_folder)

    if files_found:
        st.caption(f"Found {len(files_found)} PDF file(s) in folder.")
        with st.expander("Show files found"):
            for f in files_found:
                st.text(f)
    else:
        st.info("No PDF files found in the selected folder yet.")
        return

    if not reports:
        st.error("No reports could be parsed from folder files.")
        return

    render_outputs(reports, report_date, output_dir=output_folder)


if __name__ == "__main__":
    app()
