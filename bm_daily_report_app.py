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
        if "potential delay" in s or "potenial delay" in s:
            return "amber"
        if s == "delay" or ("delay" in s and "potential" not in s and "potenial" not in s):
            return "red"
        return "unknown"


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

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


def _normalize_header(line: str) -> str:
    line = line.lower()
    line = re.sub(r"[^a-z0-9/ ]+", " ", line)
    return re.sub(r"\s+", " ", line).strip()


def _compact_lines(items: list[str], max_items: int = 20) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        x = _clean_line(item)
        if not x or len(x) < 3:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(x)
        if len(cleaned) >= max_items:
            break
    return cleaned


# ---------------------------------------------------------------------------
# Noise / keyword constants
# ---------------------------------------------------------------------------

NOISE_PATTERNS = [
    r"^a/c overall",
    r"^status\b",
    r"^on schedule$",
    r"^potential delay$",
    r"^potenial delay$",
    r"^delay$",
    r"^milestone",
    r"^card figures",
    r"^manpower by trade",
    r"^total mr",
    r"^total manpower",
    r"^last night shift",
    r"^n shift support",
    r"^critical shortage",
    r"^raise date",
    r"^keyword holding",
    r"^holding up areas",
    r"^provide details",
    r"^occurr?ence reporting",
    r"^safety issue",
    r"^quality and safety",
    r"^air con connected",
    r"^yesterday mhr",
    r"^arrival fob",
    r"^check controller",
    r"^planning in.charge",
    r"^aging airplane",
    r"^fuel tank panels open up$",
    r"^cancel.*completed",
    r"^completed\s*total",
    r"^completed$",
    r"^days? of",
    r"^days?\s*\d",
    r"^days? rtc",
    r"^aircraft arrival",
    r"^critical material",
    r"^critical tar",
    r"^tools p/n",
    r"^general material shortage",
    r"^cabin shortage",
    r"^risk item",
    r"^left blank",
    r"^d\.d\.d",
    r"^handler$",
    r"^mc remark",
    r"^prod remark",
    r"^ts reply",
    r"^tar description",
    r"^tar status",
    r"^tar #",
    r"^total raised",
    r"^outstanding\b",
    r"^# risk\b",
    r"^risk$",
    r"^report date",
    r"^bm daily aircraft",
    r"^wp no",
    r"^a/c regn",
    r"^customer\s",
    r"^chk type",
    r"^check type",
    r"^schedule$",
    r"^-- \d+ of \d+ --$",
    r"^\d+$",
    r"^[a-z]$",
    r"^yes$",
    r"^no$",
    r"^n/a",
    r"^a/r$",
    r"^remark\b",
    r"^eta\b",
    r"^ets\b",
    r"^ata\b",
    r"^ats\b",
    r"^trt$",
    r"^rtc$",
    r"^fob\b",
    r"^defuel\b",
    r"^refuel\b",
    r"^p33\b",
    r"^risk\s+qty",
    r"^etd\b",
    r"^esd\b",
    r"^d\s*d\s*d",
    r"^p33 mod",
    r"^log \d+",
    r"^inspection target",
    r"^maintenance start",
    r"^power (on|off)",
    r"^roll (in|out)",
    r"^engine (idle|high|run)",
    r"^ldg retraction",
    r"^weighing",
    r"^aircraft exterior",
    r"^compass swing",
    r"^air test",
    r"^a/c weighing",
    r"^technical details",
    r"^progress highlights",
    r"^critical task",
    r"^zone critical",
    r"^initial plan",
    r"^latest plan",
    r"^actual date",
    r"^tia completion",
    r"^departure\b",
    r"^check completion",
    r"^1c check$",
    r"^b check$",
    r"^overall initial",
    r"^shortage$",
    r"^qtypart",
    r"^qty\s+part",
    r"^keyword\s+holding",
    r"^raise date\s+qty",
    r"^\d{1,2}\-[a-z]{3}\-\d{2}\s+\w+\s+\d",
    r"^risk tar",
    r"^\d+\s+etc\b",
    r"^\d+\s+rtc\b",
    r"^open$",
    r"^defer$",
    r"^cr\s",
    r"^wo\s",
    r"^swo\s",
    r"^total\s+\d",
]

ISSUE_KEYWORDS = [
    "crack", "aog", "pending", "waiting", "fault", "leak", "corrosion",
    "damage", "shortage", "tar", "blocked", "repair", "fail", "broken",
    "torn", "erosi", "delamina", "ingress", "defect", "hold up", "held up",
    "robbed", "missing", "interference",
]

PROGRESS_KEYWORDS = [
    "completed", "installation", "install", "close up", "build up",
    "inspection", "restoration", "replacement", "application", "check",
    "open up", "wip", "done", "restore", "remove", "removal",
    "rectification", "modification", "mod", "lubrication", "servicing",
    "cleaning", "painting", "pre-hangar", "pre hangar", "pre flight",
    "defuel", "refuel", "engine run",
]

ZONE_NAMES = frozenset({
    "cab", "cabin", "fus / cgo", "fus/cgo", "fuselage",
    "eng / apu", "eng/apu", "engine",
    "wing", "emp", "hyd / ldg", "hyd/ldg",
    "hyd / ldg emp", "hyd / ldg & emp",
    "aim", "av", "fx", "cgo", "sm", "access",
    "im", "eim", "sc",
    "ldg", "fus", "emp lh",
})


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_valid_regn(value: str) -> bool:
    v = value.strip().upper()
    if not v or len(v) < 3 or v in {"UNKNOWN", "BAY", "NOSE"}:
        return False
    if re.search(r"[0-9]", v) and len(v) >= 3:
        return True
    if "-" in v and len(v) >= 4:
        return True
    return bool(re.match(r"^[A-Z]{4,6}$", v)) and not v.startswith(("CAB", "RTC", "ATA"))


def _is_noise_line(line: str) -> bool:
    t = _normalize_header(line)
    if len(t) <= 2:
        return True
    if re.fullmatch(r"[0-9 ./%:,\-()]+", t):
        return True
    alnum = sum(ch.isalnum() for ch in t)
    if alnum and (sum(ch.isdigit() for ch in t) / max(alnum, 1)) > 0.6:
        return True
    # "A/C OVERALL" appearing anywhere (header label, never real content)
    if "a/c overall" in t:
        return True
    for pat in NOISE_PATTERNS:
        if re.search(pat, t):
            return True
    return False


def _guess_regn_from_filename(file_name: str) -> str:
    stem = Path(file_name).stem
    token = re.split(r"[_\s]", stem)[0]
    token = token.strip("-")
    return token.upper() if token else "UNKNOWN"


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _extract_bay(raw: str, lines: list[str]) -> str:
    """Extract bay from all known formats."""
    # HAECO standard: "Bay : BAY 4", "Bay : BAY E", "Bay : BAY H"
    m = re.search(r"Bay\s*:\s*BAY\s+([A-Z0-9]+)", raw, re.IGNORECASE)
    if m:
        val = m.group(1).strip().upper()
        if val not in {"PLANNING", "IN", "CHARGE", "BAY"}:
            return val

    # HAECO: "Bay : M23" (no BAY prefix)
    m = re.search(r"Bay\s*:\s*(M\d+)", raw, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()

    # UA scrambled format: bay value is on a separate line near "Bay :"
    for i, line in enumerate(lines):
        cl = _clean_line(line)
        if re.match(r"Bay\s*:\s*$", cl, re.IGNORECASE):
            # Value is on a line 1-4 positions before "Bay :"
            for j in range(max(0, i - 4), i):
                prev = _clean_line(lines[j])
                # Single letter (A, B, E, etc.)
                if re.fullmatch(r"[A-Z]", prev, re.IGNORECASE):
                    return prev.upper()
                # Number like "5" or "6"
                if re.fullmatch(r"\d{1,2}", prev):
                    return prev
                # Alphanumeric like "L412"
                if re.fullmatch(r"[A-Z]\d{1,4}", prev, re.IGNORECASE):
                    return prev.upper()
                # "A Chk Type :" or "AChk Type :" (bay letter merged with next column)
                m2 = re.match(r"^([A-Z])\s*Chk\s*Type", prev, re.IGNORECASE)
                if m2:
                    return m2.group(1).upper()
            break

    # Body-text mention: "TOW AIRCRAFT TO M21"
    m = re.search(r"TOW\s+(?:AIRCRAFT\s+)?TO\s+(M\d+|BAY\s*[A-Z0-9]+)", raw, re.IGNORECASE)
    if m:
        val = re.sub(r"^BAY\s*", "", m.group(1), flags=re.IGNORECASE).strip()
        return val.upper()

    return "-"


def _extract_customer(raw: str) -> str:
    """Extract customer name."""
    # Standard: "Customer : Brussels Airlines A/C Type: A333"
    m = re.search(
        r"Customer\s*:\s*([A-Za-z][A-Za-z0-9 /&\-().,']{1,40}?)\s*(?:A/C\s*Type|$)",
        raw, re.IGNORECASE | re.MULTILINE,
    )
    if m:
        val = m.group(1).strip()
        bad = {"dayata", "fuel", "aircraft arrival", "day", "ata", "trt"}
        if val and val.lower() not in bad and not any(x in val.lower() for x in bad):
            return val

    # UA/AA format: infer from carrier code before "A/C Type"
    # Handle both ": UA A/C Type" and ":UA A/C Type" (no space after colon)
    m = re.search(r"(?:^|[\s:])([A-Z]{2,4})\s+A/C\s*Type", raw, re.IGNORECASE | re.MULTILINE)
    if m:
        code = m.group(1).upper()
        code_map = {
            "UA": "United Airlines", "AA": "American Airlines",
            "AC": "Air Canada", "CX": "Cathay Pacific",
            "QF": "Qantas", "AY": "Finnair", "SN": "Brussels Airlines",
            "5Y": "Atlas Air",
        }
        if code in code_map:
            return code_map[code]

    return "-"


def _extract_status(raw: str, lines: list[str]) -> str:
    # Priority 1: "A/C OVERALL STATUS <value>" pattern
    m = re.search(r"A/C\s*OVERALL\s*STATUS\s+(.+)", raw, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        if "potential delay" in val or "potenial delay" in val:
            return STATUS_AMBER
        if "on schedule" in val:
            return STATUS_GREEN
        if "delay" in val:
            return STATUS_RED

    # Priority 2: "STATUS" line followed by value on same or next line
    for i, line in enumerate(lines):
        n = _normalize_header(line)
        if n == "status" or "overall" in n and "status" in n:
            combined = n
            if i + 1 < len(lines):
                combined += " " + _normalize_header(lines[i + 1])
            if "potential delay" in combined or "potenial delay" in combined:
                return STATUS_AMBER
            if "on schedule" in combined:
                return STATUS_GREEN
            if re.search(r"\bdelay\b", combined):
                return STATUS_RED

    # Priority 3: look for standalone status lines near top of document
    for line in lines[:60]:
        n = _normalize_header(line)
        if n == "potential delay" or n == "potenial delay":
            return STATUS_AMBER
        if n == "on schedule":
            return STATUS_GREEN

    # Priority 4: broad text scan
    joined = " ".join(_normalize_header(x) for x in lines[:120])
    if "potential delay" in joined or "potenial delay" in joined:
        return STATUS_AMBER
    if re.search(r"\bdelay\b", joined) and "potential" not in joined:
        return STATUS_RED
    if "on schedule" in joined:
        return STATUS_GREEN

    return "Unknown"


def _extract_check_type(raw: str) -> str:
    """Extract check type, stopping before Bay or Planning fields."""
    m = re.search(
        r"(?:Chk|Check)\s*Type\s*:\s*(.+?)(?:\s+Bay\s*:|\s+Planning|\s*$)",
        raw, re.IGNORECASE | re.MULTILINE,
    )
    if m:
        val = m.group(1).strip()
        val = re.sub(r"\s+", " ", val)
        if len(val) > 2:
            return val
    return "-"


def _extract_etc(raw: str) -> str:
    m = re.search(r"\bETC\s+(\d{1,2}[\s\-/][A-Za-z]{3}[\s\-/]\d{2,4}(?:\s+\d{2}:\d{2})?)", raw)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bETC\s+(\d{2}\-[A-Za-z]{3}\-\d{2}\s+\d{2}:\d{2})", raw)
    if m:
        return m.group(1).strip()
    return "-"


def _extract_etd(raw: str) -> str:
    m = re.search(r"\bETD\s+(\d{1,2}[\s\-/][A-Za-z]{3}[\s\-/]\d{2,4}(?:\s+\d{2}:\d{2})?)", raw)
    if m:
        return m.group(1).strip()
    return "-"


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def _extract_reason_section(lines: list[str], status: str) -> list[str]:
    """Extract Reason lines (between 'Reason:' and 'Milestone'/'Card Figures')."""
    start = -1
    for i, line in enumerate(lines):
        if re.match(r"Reason\s*:", line, re.IGNORECASE):
            start = i + 1
            break
    if start < 0:
        return []

    # Noise patterns specific to reason blocks (manpower, personnel, schedule data)
    reason_noise = re.compile(
        r"(^af\s*\d.*(?:im|av|sm)\s*\d"  # manpower: "AF: 16 IM: 10 AV: 4"
        r"|^total\s*(mr|manpower)"
        r"|^last night|^n shift"
        r"|dayata"
        r"|^\d{2}\-[a-z]{3}\-\d{2}"
        r"|^etc\b|^etd\b"
        r"|^days of|^days rtc"
        r"|^1c\s|^b\s*chk|^chk type"
        r"|^\w{1,3}\s+\w{2,10}\s+\d{5,7})",  # personnel: "SL LAM 291766" (normalized)
        re.IGNORECASE,
    )

    out: list[str] = []
    for j in range(start, min(start + 15, len(lines))):
        line = _clean_line(lines[j])
        n = _normalize_header(line)
        if "milestone" in n or "card figures" in n or "technical details" in n:
            break
        if _is_noise_line(line):
            continue
        if reason_noise.search(n):
            continue
        if status == STATUS_GREEN and len(line) < 15:
            continue
        cleaned = re.sub(r"^[-•]\s*", "", line)
        if cleaned and len(cleaned) >= 8:
            out.append(cleaned)
    return out


def _has_zone_table(lines: list[str]) -> bool:
    """True if the PDF uses a HAECO-style zone table with all headers on one line."""
    for line in lines:
        n = _normalize_header(line)
        if "zone" in n and "critical task" in n and "progress" in n:
            return True
        if "zone" in n and "critical task" in n:
            return True
    return False


def _extract_from_zone_table(lines: list[str], overall_status: str) -> tuple[list[str], list[str]]:
    """Parse the HAECO zone table into critical issues and progress highlights."""
    # Prefer "Zone Critical Task" line; fall back to "Technical Details"
    start = -1
    for i, line in enumerate(lines):
        n = _normalize_header(line)
        if "zone" in n and "critical task" in n:
            start = i + 1
            break
    if start < 0:
        for i, line in enumerate(lines):
            n = _normalize_header(line)
            if n == "technical details":
                start = i + 1
                break
    if start < 0:
        return [], []

    zone_status = overall_status
    items: list[tuple[str, str]] = []

    for j in range(start, len(lines)):
        line = _clean_line(lines[j])
        n = _normalize_header(line)

        if "critical material" in n or "critical tar" in n or "critical shortage" in n:
            break
        if re.match(r"^-- \d+ of \d+ --$", line):
            continue
        # Skip zone table header if encountered again (multi-page)
        if "zone" in n and ("critical task" in n or "progress highlight" in n):
            continue
        if n == "technical details":
            continue

        # Track per-zone status
        if n in {"on schedule"}:
            zone_status = STATUS_GREEN
            continue
        if n in {"potential delay", "potenial delay"}:
            zone_status = STATUS_AMBER
            continue
        if n == "delay":
            zone_status = STATUS_RED
            continue

        # Skip zone names, sub-headers, INSP/MAINT lines, milestone data
        if _is_section_noise(line, n):
            continue
        if _is_noise_line(line):
            continue
        if len(line) < 5:
            continue

        cleaned = re.sub(r"^[-•]\s*", "", line)
        if cleaned and len(cleaned) >= 4:
            items.append((cleaned, zone_status))

    # Classify items into critical vs progress
    critical: list[str] = []
    progress: list[str] = []

    for item, zs in items:
        low = item.lower()
        is_issue = any(k in low for k in ISSUE_KEYWORDS)
        is_prog = any(k in low for k in PROGRESS_KEYWORDS)

        if is_issue and not is_prog:
            critical.append(item)
        elif is_prog and not is_issue:
            progress.append(item)
        elif is_issue and is_prog:
            if zs in {STATUS_AMBER, STATUS_RED}:
                critical.append(item)
            else:
                progress.append(item)
        else:
            # No keyword match: use zone status and length heuristic
            if zs in {STATUS_AMBER, STATUS_RED} and len(item) >= 15:
                critical.append(item)
            elif len(item) >= 8:
                progress.append(item)

    return critical, progress


def _is_section_noise(line: str, n: str) -> bool:
    """Check if a line is noise within critical/progress sections."""
    if n in ZONE_NAMES:
        return True
    if re.match(r"^(insp|maint|initial)", n):
        return True
    if n in {"on schedule", "potential delay", "delay", "potenial delay"}:
        return True
    # Date-heavy lines from milestone tables (normalized: dashes removed)
    if re.match(r"^\d{1,2}\s+[a-z]{3}\s+\d{2,4}", n):
        return True
    # Shortage table references (date + part/keyword)
    if re.match(r"^\d{1,2}\s*[a-z]{3}\s*\d{2}\s+\w+", n):
        return True
    # Manpower summary: "AF : 0 IM : 0 SM: 0 AV :0"
    if re.search(r"af\s*\d.*(?:im|av|sm)\s*\d", n):
        return True
    # Shortage/material tracking lines with "//" notation
    if "//" in line and re.search(r"(?:tar|po|awb|esd|eta|req|sr|pn|mf)\b", line.lower()):
        return True
    if "//" in line and re.search(r"\d{4,}", line):
        return True
    return False


def _extract_ua_sections(lines: list[str]) -> tuple[list[str], list[str]]:
    """Extract critical/progress from UA/AA-format PDFs with separate headers."""
    crit_start = -1
    prog_start = -1
    crit_end = len(lines)

    for i, line in enumerate(lines):
        n = _normalize_header(line)
        if ("critical task" in n) and "zone" not in n:
            crit_start = i + 1
        if ("progress highlights" in n or "progress highlight" in n) and "zone" not in n:
            prog_start = i + 1
            if crit_start >= 0 and crit_end == len(lines):
                crit_end = i

    critical: list[str] = []
    progress: list[str] = []

    if crit_start >= 0:
        for j in range(crit_start, min(crit_end, len(lines))):
            line = _clean_line(lines[j])
            if _is_noise_line(line):
                continue
            n = _normalize_header(line)
            if _is_section_noise(line, n):
                continue
            cleaned = re.sub(r"^[-•]\s*", "", line)
            if cleaned and len(cleaned) >= 8:
                critical.append(cleaned)

    if prog_start >= 0:
        for j in range(prog_start, len(lines)):
            line = _clean_line(lines[j])
            n = _normalize_header(line)
            if "critical material" in n or "critical tar" in n or "critical shortage" in n:
                break
            if _is_noise_line(line):
                continue
            if _is_section_noise(line, n):
                continue
            cleaned = re.sub(r"^[-•]\s*", "", line)
            if cleaned and len(cleaned) >= 8:
                progress.append(cleaned)

    return critical, progress


# ---------------------------------------------------------------------------
# Main PDF parser
# ---------------------------------------------------------------------------

def parse_pdf_file(file_name: str, file_bytes: bytes, high_fidelity: bool = True) -> AircraftReport:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = _non_empty_lines(text)
    raw = "\n".join(lines)

    # Registration - try standard pattern, then reversed pattern (N718ANA/C Regn)
    regn_raw = _extract_first(
        [r"A/C\s*Regn[:\s]+([A-Z0-9\-]+)", r"Aircraft\s*Regn[:\s]+([A-Z0-9\-]+)"],
        raw,
        "",
    )
    if not _is_valid_regn(regn_raw):
        # Try reversed: regn merged before "A/C Regn" (e.g. "N718ANA/C Regn")
        m = re.search(r"([A-Z0-9]{4,8})A/C\s*Regn", raw, re.IGNORECASE)
        if m and _is_valid_regn(m.group(1)):
            regn_raw = m.group(1)
    regn = regn_raw if _is_valid_regn(regn_raw) else _guess_regn_from_filename(file_name)

    # Bay
    bay = _extract_bay(raw, lines)

    # Status
    status = _extract_status(raw, lines)

    # Customer
    customer = _extract_customer(raw)

    # A/C Type
    ac_type = _extract_first(
        [r"A/C\s*Type[:\s]+([A-Za-z0-9\-]{2,12})", r"Type[:\s]+([A-Za-z0-9\-]{2,12})"],
        raw,
    )

    # Check type
    check_type = _extract_check_type(raw)

    # Dates
    etc_val = _extract_etc(raw)
    etd_val = _extract_etd(raw)
    ata_val = _extract_first([r"\bATA[:\s]+(\d{1,2}[\s\-/][A-Za-z]{3}[\s\-/]\d{2,4}(?:\s+\d{2}:\d{2})?)"], raw)
    day_val = _extract_first([r"\bDay\s+(\d+\s*(?:of\s*\d+)?)"], raw)

    # Reason
    reason_block = _extract_reason_section(lines, status)
    # Fallback: if no Reason section found, look for bullet points after status line
    if not reason_block and status in {STATUS_AMBER, STATUS_RED}:
        for i, line in enumerate(lines):
            n = _normalize_header(line)
            if "status" in n and ("delay" in n or "potential" in n or "potenial" in n):
                for j in range(i + 1, min(i + 15, len(lines))):
                    jl = _clean_line(lines[j])
                    if re.match(r"Milestone", jl, re.IGNORECASE):
                        break
                    if jl.startswith("-") and len(jl) > 10:
                        reason_block.append(re.sub(r"^-\s*", "", jl))
                break

    # Critical Task / Issue and Progress Highlights
    if _has_zone_table(lines):
        crit_block, prog_block = _extract_from_zone_table(lines, status)
    else:
        crit_block, prog_block = _extract_ua_sections(lines)

    # Salvage: if critical is empty but we have issue-like lines (only for non-green)
    if high_fidelity and not crit_block and status != STATUS_GREEN:
        salvage = []
        for l in lines:
            cl = _clean_line(l)
            n = _normalize_header(cl)
            if _is_noise_line(cl) or _is_section_noise(cl, n):
                continue
            if any(k in cl.lower() for k in ISSUE_KEYWORDS) and len(cl) >= 15:
                salvage.append(re.sub(r"^[-•]\s*", "", cl))
        crit_block = _compact_lines(salvage, max_items=8)

    # Salvage: if progress is empty but we have progress-like lines
    if high_fidelity and not prog_block:
        salvage = []
        for l in lines:
            cl = _clean_line(l)
            n = _normalize_header(cl)
            if _is_noise_line(cl) or _is_section_noise(cl, n):
                continue
            if any(k in cl.lower() for k in PROGRESS_KEYWORDS) and len(cl) >= 10:
                salvage.append(re.sub(r"^[-•]\s*", "", cl))
        prog_block = _compact_lines(salvage, max_items=8)

    return AircraftReport(
        file_name=file_name,
        regn=regn,
        bay=bay,
        customer=customer,
        ac_type=ac_type,
        check_type=check_type,
        status=status,
        ata=ata_val,
        etc=etc_val,
        etd=etd_val,
        day=day_val,
        insp_maint="-",
        reason=_compact_lines(reason_block),
        critical_issues=_compact_lines(crit_block),
        progress_highlights=_compact_lines(prog_block),
    )


# ---------------------------------------------------------------------------
# Quality & normalization
# ---------------------------------------------------------------------------

def _report_quality_score(r: AircraftReport) -> int:
    score = 0
    if _is_valid_regn(r.regn):
        score += 4
    if r.bay != "-":
        score += 3
    if r.status != "Unknown":
        score += 2
    if r.etc != "-":
        score += 1
    if r.etd != "-":
        score += 1
    score += min(len(r.critical_issues), 6)
    score += min(len(r.progress_highlights), 6)
    bad_tokens = ("dayata", "keyword holding", "cancel %completed")
    for x in r.critical_issues + r.progress_highlights:
        if any(t in x.lower() for t in bad_tokens):
            score -= 2
    return score


def _normalize_reports(reports: list[AircraftReport]) -> list[AircraftReport]:
    filtered: list[AircraftReport] = []
    for r in reports:
        if not _is_valid_regn(r.regn):
            continue
        crit_set = {x.lower() for x in r.critical_issues}
        r.progress_highlights = [p for p in r.progress_highlights if p.lower() not in crit_set]
        filtered.append(r)

    best_by_regn: dict[str, AircraftReport] = {}
    for r in filtered:
        key = r.regn.upper()
        if key not in best_by_regn:
            best_by_regn[key] = r
            continue
        if _report_quality_score(r) > _report_quality_score(best_by_regn[key]):
            best_by_regn[key] = r

    result = list(best_by_regn.values())
    result.sort(key=lambda x: (x.bay == "-", x.bay, x.regn))
    return result


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _issue_tag(line: str) -> str:
    l = line.lower()
    if any(k in l for k in ["aog", "waiting", "pending", "blocked", "shortage", "fault", "crack", "broken"]):
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


def _show_data_quality_hints(items: list[AircraftReport]) -> None:
    missing_bay = [i.regn for i in items if i.bay == "-"]
    missing_sections = [i.regn for i in items if not i.critical_issues and not i.progress_highlights]
    if missing_bay or missing_sections:
        hints = []
        if missing_bay:
            hints.append(f"Missing bay on: {', '.join(missing_bay[:6])}")
        if missing_sections:
            hints.append(f"Missing critical/progress sections on: {', '.join(missing_sections[:6])}")
        st.warning("Data quality checks: " + " | ".join(hints))


def _load_config() -> dict:
    path = Path(__file__).with_name("ui_output_config.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

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
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #061f25; color:#fff; }}
    .header {{ background: linear-gradient(120deg, #05232a 0%, #0b3740 70%); color:#fff; padding:16px; border-radius:12px; }}
    .stats {{ margin-top:8px; font-size:14px; color:#fff; }}
    .card {{ background:#0e2f36; border-radius:10px; padding:14px; margin:12px 0; border-left:6px solid #4f5b66; }}
    .green {{ border-color:#2ecc71; }} .amber {{ border-color:#f1c40f; }} .red {{ border-color:#ff6b6b; }}
    .cols {{ display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px; }}
    h3 {{ margin:0 0 6px 0; color:#fff; }} p {{ margin:4px 0; color:#fff; }} h4 {{ color:#fff; }}
    ul {{ margin:6px 0 0 18px; color:#fff; }}
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


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_uploaded_files(files: list, high_fidelity: bool = True) -> list[AircraftReport]:
    reports: list[AircraftReport] = []
    for f in files:
        try:
            reports.append(parse_pdf_file(f.name, f.getvalue(), high_fidelity=high_fidelity))
        except Exception as exc:
            st.warning(f"Failed to parse {f.name}: {exc}")
    return _normalize_reports(reports)


def process_folder(folder_path: str, high_fidelity: bool = True) -> tuple[list[AircraftReport], list[str]]:
    path = Path(folder_path).expanduser()
    if not path.exists() or not path.is_dir():
        return [], []
    pdf_files = sorted(path.glob("*.pdf"))
    reports: list[AircraftReport] = []
    for p in pdf_files:
        try:
            reports.append(parse_pdf_file(p.name, p.read_bytes(), high_fidelity=high_fidelity))
        except Exception as exc:
            st.warning(f"Failed to parse {p.name}: {exc}")
    return _normalize_reports(reports), [str(x) for x in pdf_files]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def _apply_streamlit_theme(accent: str, panel: str, bg: str) -> None:
    st.markdown(
        f"""
        <style>
          .stApp {{
            background: radial-gradient(circle at 10% 10%, #0c3a42 0%, {bg} 45%, #02171b 100%);
            color: #ffffff;
          }}
          [data-testid="stHeader"] {{
            background: transparent !important;
            border-bottom: none !important;
          }}
          [data-testid="stDecoration"] {{
            display: none !important;
          }}
          #MainMenu, footer {{
            visibility: hidden;
          }}
          [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #061f25 0%, {panel} 100%);
          }}
          [data-testid="stSidebar"] * {{
            color: #ffffff !important;
          }}
          .stApp, .stApp p, .stApp span, .stApp div, .stApp label, .stCaption, .stMarkdown {{
            color: #ffffff;
          }}
          .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div, .stDateInput input {{
            background: rgba(14, 47, 54, 0.9) !important;
            color: #ffffff !important;
            border: 1px solid rgba(28, 214, 180, 0.3) !important;
          }}
          [data-testid="stFileUploaderDropzone"] {{
            background: rgba(14, 47, 54, 0.92) !important;
            border: 2px dashed rgba(28, 214, 180, 0.55) !important;
            border-radius: 14px !important;
            padding: 24px 16px !important;
          }}
          [data-testid="stFileUploaderDropzone"]:hover {{
            border-color: #1cd6b4 !important;
            background: rgba(18, 60, 69, 0.96) !important;
          }}
          [data-testid="stFileUploaderDropzone"] * {{
            color: #ffffff !important;
          }}
          [data-testid="stFileUploader"] button,
          [data-testid="stFileUploaderDropzone"] button,
          [data-testid="stBaseButton-secondary"] {{
            background: #1cd6b4 !important;
            color: #012028 !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
          }}
          [data-testid="stFileUploader"] button:hover,
          [data-testid="stFileUploaderDropzone"] button:hover,
          [data-testid="stBaseButton-secondary"]:hover {{
            background: #20e7c4 !important;
            color: #012028 !important;
          }}
          [data-testid="stFileUploaderFile"] {{
            background: rgba(14, 47, 54, 0.95) !important;
            border: 1px solid rgba(28, 214, 180, 0.35) !important;
            border-radius: 10px !important;
          }}
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFile"] {{
            background: rgba(14, 47, 54, 0.98) !important;
          }}
          [data-testid="stFileUploader"] section {{
            background: transparent !important;
          }}
          [data-testid="stFileUploader"] section > div {{
            background: transparent !important;
          }}
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFileData"] {{
            background: transparent !important;
          }}
          [data-testid="stFileUploaderFile"] * {{
            color: #ffffff !important;
          }}
          [data-testid="stFileUploaderFileName"] {{
            color: #ffffff !important;
            font-weight: 600 !important;
          }}
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFileName"],
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFileName"] span,
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFileData"] div,
          [data-testid="stFileUploader"] section [data-testid="stFileUploaderFileData"] span {{
            color: #ffffff !important;
            background: transparent !important;
          }}
          [data-testid="stFileUploaderDeleteBtn"] {{
            background: #17424a !important;
            color: #ffffff !important;
            border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 8px !important;
          }}
          [data-testid="stFileUploaderDeleteBtn"]:hover {{
            background: #1f5a64 !important;
            color: #ffffff !important;
          }}
          .stRadio > div, .stCheckbox > label {{
            color: #ffffff !important;
          }}
          .stButton > button {{
            background: #0f6b73 !important;
            color: #ffffff !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            font-weight: 700;
            border-radius: 10px;
          }}
          .stButton > button:hover {{
            background: #138690 !important;
          }}
          .stDownloadButton > button {{
            background: #17424a !important;
            color: #ffffff !important;
            border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 10px;
          }}
          .stDownloadButton > button:hover {{
            background: #1e5660 !important;
          }}
          .metric-card {{
            background: rgba(17, 61, 70, 0.72);
            border: 1px solid rgba(28, 214, 180, 0.28);
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 10px;
          }}
          .hero-card {{
            background: rgba(7, 40, 46, 0.88);
            border: 1px solid rgba(122, 243, 222, 0.25);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 12px;
          }}
          .step-chip {{
            display: inline-block;
            background: rgba(10, 63, 74, 0.8);
            border-radius: 10px;
            padding: 6px 10px;
            margin-right: 8px;
            margin-top: 6px;
            border: 1px solid rgba(28, 214, 180, 0.2);
            font-size: 12px;
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
    key_prefix: str = "default",
) -> None:
    txt = render_text_report(reports, report_date, tone, format_style, config)
    html_out = render_html_report(reports, report_date, tone, format_style, config)
    safe_date = report_date.replace("/", "-").replace(" ", "_")
    txt_name = f"BM_Daily_Report_{safe_date}.txt"
    html_name = f"BM_Daily_Report_{safe_date}.html"

    st.success(f"Generated from {len(reports)} PDF file(s).")
    st.download_button(
        "Download Text Report (.txt)",
        txt,
        file_name=txt_name,
        key=f"download_txt_{key_prefix}",
    )
    st.download_button(
        "Download HTML Report (.html)",
        html_out,
        file_name=html_name,
        key=f"download_html_{key_prefix}",
    )

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
    high_fidelity = st.sidebar.checkbox("High-Fidelity Parsing", value=True)
    st.title("HAECO BM Daily Report Assistant")
    st.markdown(
        """
        <div class="hero-card">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px;">Generate Daily BM Summaries in 3 Steps</div>
          <div style="opacity:0.95;">Pick tone and format in the sidebar, then either upload PDFs or point to your watch folder.</div>
          <div>
            <span class="step-chip">1. Choose Tone + Format</span>
            <span class="step-chip">2. Upload PDFs or Scan Folder</span>
            <span class="step-chip">3. Download TXT + HTML</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_upload, tab_watch = st.tabs(["Upload PDFs", "Watch Folder"])

    with tab_upload:
        st.markdown(
            """
            <div class="hero-card">
              <div style="font-size:16px;font-weight:700;margin-bottom:6px;">Drag & Drop Daily PDF Reports</div>
              <div style="opacity:0.95;">Drop one or more PDF files below, then click Generate.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        files = st.file_uploader(
            "Drag and drop PDF files here",
            type=["pdf"],
            accept_multiple_files=True,
            help="You can also click the area to browse files.",
        )
        if not files:
            st.info("Upload one or more PDFs to generate the report.")
        else:
            st.success(f"{len(files)} file(s) ready.")
            generate_uploaded = st.button("Generate Report from Uploaded Files")
            if generate_uploaded:
                reports = process_uploaded_files(files, high_fidelity=high_fidelity)
                if not reports:
                    st.error("No reports could be parsed.")
                else:
                    g, a, r = _summary(reports)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(f'<div class="metric-card"><b>Total</b><br>{len(reports)}</div>', unsafe_allow_html=True)
                    c2.markdown(f'<div class="metric-card"><b>Green</b><br>{g}</div>', unsafe_allow_html=True)
                    c3.markdown(f'<div class="metric-card"><b>Amber</b><br>{a}</div>', unsafe_allow_html=True)
                    c4.markdown(f'<div class="metric-card"><b>Red</b><br>{r}</div>', unsafe_allow_html=True)
                    _show_data_quality_hints(reports)
                    render_outputs(reports, report_date, tone, format_style, config, key_prefix="upload")

    with tab_watch:
        default_watch = str(Path.home() / "Downloads" / "2Apr Daily Report")
        watch_folder = st.text_input("Watch Folder Path", value=default_watch)
        output_folder = st.text_input("Output Folder Path", value=watch_folder)
        auto_generate = st.checkbox("Auto-generate from folder on each refresh", value=True)
        run_now = st.button("Scan Folder Now")

        reports: list[AircraftReport] = []
        files_found: list[str] = []
        if auto_generate or run_now:
            reports, files_found = process_folder(watch_folder, high_fidelity=high_fidelity)

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

        _show_data_quality_hints(reports)
        render_outputs(
            reports,
            report_date,
            tone,
            format_style,
            config,
            output_dir=output_folder,
            key_prefix="watch",
        )


if __name__ == "__main__":
    app()
