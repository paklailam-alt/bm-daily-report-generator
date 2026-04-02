from __future__ import annotations

import html
import io
import json
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

DEFAULT_CONFIG = {
    "themes": {"haeco_dark": {"accent": "#1cd6b4", "panel": "#0b2930", "bg": "#041f25"}},
    "tone_presets": {
        "Executive": {"title_suffix": "Executive Snapshot", "issue_prefix": "Mgmt Alert"},
        "Engineering": {"title_suffix": "Engineering Detail", "issue_prefix": "Technical Issue"},
        "Action-Oriented": {"title_suffix": "Action Board", "issue_prefix": "Action Required"},
    },
    "format_presets": {
        "Detailed": {"max_reason": 4, "max_critical": 6, "max_progress": 6},
        "Management Snapshot": {"max_reason": 2, "max_critical": 3, "max_progress": 3},
    },
}


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
    return re.sub(r"\s+", " ", line)


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
    lines = _non_empty_lines(sub[:end_pos])
    return [re.sub(r"^[-:]\s*", "", line) for line in lines if line]


def _guess_regn_from_filename(file_name: str) -> str:
    stem = Path(file_name).stem
    token = re.split(r"[_\s]", stem)[0]
    token = token.strip("-")
    return token.upper() if token else "UNKNOWN"


def _load_config() -> dict:
    path = Path(__file__).with_name("ui_output_config.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG


def parse_pdf_file(file_name: str, file_bytes: bytes) -> AircraftReport:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    raw = "\n".join(_non_empty_lines(text))

    regn = _extract_first(
        [r"A/C\s*Regn[:\s]+([A-Z0-9\-]+)", r"Aircraft\s*Regn[:\s]+([A-Z0-9\-]+)"],
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

    return AircraftReport(
        file_name=file_name,
        regn=regn,
        bay=_extract_first([r"\bBay[:\s]+([A-Z0-9]+)\b", r"\bLocation[:\s]+Bay\s*([A-Z0-9]+)\b"], raw),
        customer=_extract_first([r"Customer[:\s]+([A-Za-z0-9 /&\-\(\)]+)"], raw),
        ac_type=_extract_first([r"Type[:\s]+([A-Za-z0-9\-]+)", r"A/C\s*Type[:\s]+([A-Za-z0-9\-]+)"], raw),
        check_type=_extract_first([r"Check\s*Type[:\s]+([A-Za-z0-9+\/\-\s\(\)]+)"], raw),
        status=status,
        ata=_extract_first([r"\bATA[:\s]+([0-9: /A-Za-z\-\(\)]+)"], raw),
        etc=_extract_first([r"\bETC[:\s]+([0-9: /A-Za-z\-\(\)\+]+)"], raw),
        etd=_extract_first([r"\bETD[:\s]+([0-9: /A-Za-z\-\(\)\+]+)"], raw),
        day=_extract_first([r"\bDay[:\s]+([0-9 ]+of[ 0-9]+)"], raw),
        insp_maint=_extract_first([r"\bINSP\s*/\s*MAINT[:\s]+([0-9% /]+)"], raw),
        reason=_extract_block(r"Reason", [r"Critical Task", r"Progress Highlights", r"RTC", r"Remarks"], raw),
        critical_issues=_extract_block(
            r"Critical\s*Task\s*/\s*Issue", [r"Progress Highlights", r"RTC", r"Remarks"], raw
        )
        or _extract_block(r"Critical\s*Issue", [r"Progress", r"RTC", r"Remarks"], raw),
        progress_highlights=_extract_block(r"Progress Highlights", [r"RTC", r"Remarks"], raw)
        or _extract_block(r"Work Done", [r"RTC", r"Remarks"], raw),
    )


def _issue_tag(line: str) -> str:
    l = line.lower()
    if any(k in l for k in ["aog", "waiting", "pending", "blocked", "shortage", "fault", "crack"]):
        return "BLOCKING"
    if any(k in l for k in ["wip", "monitor", "inspection", "rectification"]):
        return "MONITOR"
    return "INFO"


def _tone_line(issue_prefix: str, tone: str, issue: str) -> str:
    tag = _issue_tag(issue)
    if tone == "Executive":
        return f"- [{tag}] {issue_prefix}: {issue}"
    if tone == "Action-Oriented":
        return f"- [{tag}] {issue} | Next: follow-up and close"
    return f"- [{tag}] {issue}"


def _summary(items: list[AircraftReport]) -> tuple[int, int, int]:
    green = sum(i.status_class == "green" for i in items)
    amber = sum(i.status_class == "amber" for i in items)
    red = sum(i.status_class == "red" for i in items)
    return green, amber, red


def render_text_report(
    items: list[AircraftReport], report_date: str, tone: str, format_style: str, config: dict
) -> str:
    format_cfg = config["format_presets"][format_style]
    tone_cfg = config["tone_presets"][tone]
    max_reason = format_cfg["max_reason"]
    max_critical = format_cfg["max_critical"]
    max_progress = format_cfg["max_progress"]
    green, amber, red = _summary(items)

    lines: list[str] = [
        f"BM DAILY AIRCRAFT PROGRESS REPORT - {tone_cfg['title_suffix']}",
        f"Report Date: {report_date}",
        "",
        f"Total A/Cs: {len(items)} | Green: {green} | Amber: {amber} | Red: {red}",
        "============================================================",
    ]

    if format_style == "Management Snapshot":
        blockers = []
        for i in sorted(items, key=lambda x: x.bay):
            for issue in i.critical_issues:
                if _issue_tag(issue) == "BLOCKING":
                    blockers.append((i.bay, i.regn, issue))
        lines += ["TOP BLOCKERS", "------------------------------------------------------------"]
        if blockers:
            for bay, regn, issue in blockers[:10]:
                lines.append(f"- Bay {bay} | {regn}: {issue}")
        else:
            lines.append("- No blockers identified.")
        lines.append("")

    lines += ["MAINTENANCE IN PROGRESS", "============================================================"]
    for i in sorted(items, key=lambda x: x.bay):
        lines.append(f"Bay {i.bay} - {i.regn} ({i.customer} / {i.ac_type}) {i.check_type} | {i.status}")
        lines.append(f"ATA: {i.ata} | ETC: {i.etc}" + (f" | ETD: {i.etd}" if i.etd != "-" else ""))

        if i.reason:
            lines.append("Reason:")
            for r in i.reason[:max_reason]:
                lines.append(f"- {r}")

        lines.append("Critical Task / Issue:")
        if i.critical_issues:
            for c in i.critical_issues[:max_critical]:
                lines.append(_tone_line(tone_cfg["issue_prefix"], tone, c))
        else:
            lines.append("- (none)")

        lines.append("Progress Highlights:")
        if i.progress_highlights:
            for p in i.progress_highlights[:max_progress]:
                lines.append(f"- {p}")
        else:
            lines.append("- (none)")
        lines.append("")

    return "\n".join(lines)


def render_html_report(
    items: list[AircraftReport], report_date: str, tone: str, format_style: str, config: dict
) -> str:
    format_cfg = config["format_presets"][format_style]
    tone_cfg = config["tone_presets"][tone]
    max_reason = format_cfg["max_reason"]
    max_critical = format_cfg["max_critical"]
    max_progress = format_cfg["max_progress"]
    green, amber, red = _summary(items)

    cards = []
    for i in sorted(items, key=lambda x: x.bay):
        reason_html = "".join(f"<li>{html.escape(r)}</li>" for r in i.reason[:max_reason]) or "<li>(none)</li>"
        crit_html = "".join(
            f"<li><strong>[{_issue_tag(c)}]</strong> {html.escape(c)}</li>" for c in i.critical_issues[:max_critical]
        ) or "<li>(none)</li>"
        prog_html = (
            "".join(f"<li>{html.escape(p)}</li>" for p in i.progress_highlights[:max_progress]) or "<li>(none)</li>"
        )
        cards.append(
            f"""
            <div class="card {i.status_class}">
              <h3 contenteditable="true">Bay {html.escape(i.bay)} - {html.escape(i.regn)} | {html.escape(i.status)}</h3>
              <p contenteditable="true">{html.escape(i.customer)} / {html.escape(i.ac_type)} | {html.escape(i.check_type)}</p>
              <p contenteditable="true"><strong>ATA:</strong> {html.escape(i.ata)} | <strong>ETC:</strong> {html.escape(i.etc)} | <strong>ETD:</strong> {html.escape(i.etd)}</p>
              <div class="cols">
                <div><h4 contenteditable="true">Reason</h4><ul contenteditable="true">{reason_html}</ul></div>
                <div><h4 contenteditable="true">{html.escape(tone_cfg["issue_prefix"])}</h4><ul contenteditable="true">{crit_html}</ul></div>
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
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #061f25; color:#dbe7ea; }}
    .header {{ background: linear-gradient(120deg, #05232a 0%, #0b3740 70%); color:#fff; padding:16px; border-radius:12px; }}
    .stats {{ margin-top:8px; font-size:14px; color:#bde7dd; }}
    .card {{ background:#0e2f36; border-radius:10px; padding:14px; margin:12px 0; border-left:6px solid #4f5b66; }}
    .green {{ border-color:#2ecc71; }} .amber {{ border-color:#f1c40f; }} .red {{ border-color:#ff6b6b; }}
    .cols {{ display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px; }}
    h3 {{ margin:0 0 6px 0; color:#ecf6f9; }} p {{ margin:4px 0; color:#cbe2e8; }} h4 {{ color:#7fffd4; }}
    ul {{ margin:6px 0 0 18px; color:#dce7ea; }}
    [contenteditable="true"] {{ outline: 1px dashed transparent; border-radius:4px; }}
    [contenteditable="true"]:hover {{ outline-color:#57c8b3; }}
    [contenteditable="true"]:focus {{ outline:2px solid #1cd6b4; background:#123c45; }}
  </style>
</head>
<body>
  <div class="header">
    <h1 contenteditable="true">BM Daily Aircraft Progress Report - {html.escape(tone_cfg["title_suffix"])}</h1>
    <div class="stats" contenteditable="true">Date: {html.escape(report_date)} | Format: {html.escape(format_style)} | Total: {len(items)} | Green: {green} | Amber: {amber} | Red: {red}</div>
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


def _apply_streamlit_theme(accent: str, panel: str, bg: str) -> None:
    st.markdown(
        f"""
        <style>
          .stApp {{
            background: radial-gradient(circle at 10% 10%, #0c3a42 0%, {bg} 45%, #02171b 100%);
            color: #dff4f6;
          }}
          [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #061f25 0%, {panel} 100%);
          }}
          .stButton > button {{
            background: {accent}; color: #012028; border: 0; font-weight: 700;
          }}
          .metric-card {{
            background: rgba(17, 61, 70, 0.72);
            border: 1px solid rgba(28, 214, 180, 0.28);
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 10px;
          }}
          .right-panel {{
            background: rgba(7, 40, 46, 0.85);
            border: 1px solid rgba(122, 243, 222, 0.2);
            border-radius: 14px;
            padding: 14px;
          }}
          .visit-item {{
            background: rgba(10, 63, 74, 0.65);
            border-radius: 10px;
            padding: 10px;
            margin-bottom: 8px;
            border: 1px solid rgba(28, 214, 180, 0.12);
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_outputs(
    reports: list[AircraftReport],
    report_date: str,
    tone: str,
    format_style: str,
    config: dict,
    output_dir: str | None = None,
) -> None:
    txt = render_text_report(reports, report_date, tone, format_style, config)
    html_out = render_html_report(reports, report_date, tone, format_style, config)
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

    st.text_area("Text Preview", txt, height=380)
    st.components.v1.html(html_out, height=680, scrolling=True)


def app() -> None:
    st.set_page_config(page_title="BM Daily Report Generator", layout="wide")
    config = _load_config()
    theme = config["themes"]["haeco_dark"]
    _apply_streamlit_theme(theme["accent"], theme["panel"], theme["bg"])

    st.sidebar.header("Report Controls")
    report_date = st.sidebar.text_input("Report Date", value=datetime.now().strftime("%d %b %Y"))
    tone = st.sidebar.selectbox("Output Tone", list(config["tone_presets"].keys()), index=0)
    format_style = st.sidebar.selectbox("Output Format", list(config["format_presets"].keys()), index=0)
    mode = st.sidebar.radio("Input Mode", ["Upload PDFs", "Watch Folder"])

    left, right = st.columns([1.7, 1.0], gap="large")
    with left:
        st.title("HAECO BM Daily Report Assistant")
        st.caption("Upload or watch a daily PDF folder, then generate text + HTML summaries with selectable tone.")

    with right:
        st.markdown(
            """
            <div class="right-panel">
              <h4 style="margin-top:0;color:#dffff5;">Recent Actions</h4>
              <div class="visit-item">Analyse Workcards</div>
              <div class="visit-item">Daily Report Generation</div>
              <div class="visit-item">Management Snapshot Export</div>
              <div class="visit-item">Maintenance Risk Summary</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if mode == "Upload PDFs":
        files = st.file_uploader("Upload daily PDF files", type=["pdf"], accept_multiple_files=True)
        if not files:
            st.info("Upload one or more PDFs to generate the report.")
            return
        reports = process_uploaded_files(files)
        if not reports:
            st.error("No reports could be parsed.")
            return
        g, a, r = _summary(reports)
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f'<div class="metric-card"><b>Total</b><br>{len(reports)}</div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><b>Green</b><br>{g}</div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="metric-card"><b>Amber</b><br>{a}</div>', unsafe_allow_html=True)
        c4.markdown(f'<div class="metric-card"><b>Red</b><br>{r}</div>', unsafe_allow_html=True)
        render_outputs(reports, report_date, tone, format_style, config)
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

    if not files_found:
        st.info("No PDF files found in the selected folder yet.")
        return

    st.caption(f"Found {len(files_found)} PDF file(s).")
    with st.expander("Show files found"):
        for f in files_found:
            st.text(f)

    if not reports:
        st.error("No reports could be parsed from folder files.")
        return

    g, a, r = _summary(reports)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="metric-card"><b>Total</b><br>{len(reports)}</div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card"><b>Green</b><br>{g}</div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-card"><b>Amber</b><br>{a}</div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="metric-card"><b>Red</b><br>{r}</div>', unsafe_allow_html=True)

    render_outputs(reports, report_date, tone, format_style, config, output_dir=output_folder)


if __name__ == "__main__":
    app()
