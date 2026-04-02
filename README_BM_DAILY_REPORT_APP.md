# BM Daily Report App

Generates daily BM summary reports from uploaded PDF files.

## Setup

```bash
python3 -m pip install -r requirements_bm_daily_report.txt
```

## Run

```bash
streamlit run bm_daily_report_app.py
```

Open in browser:

- `http://localhost:8501`

## What it generates

- Text report (`.txt`)
- HTML report (`.html`, editable fields enabled)

## Watch Folder mode

1. In the app, choose `Watch Folder`.
2. Set `Watch Folder Path` to your daily PDF folder (e.g. `~/Downloads/2Apr Daily Report`).
3. Set `Output Folder Path` (can be the same folder).
4. Keep `Auto-generate from folder on each refresh` enabled, or click `Scan Folder Now`.
5. The app writes fresh `.txt` and `.html` outputs to the output folder automatically.

## Notes

- The parser uses report-heading patterns (`Reason`, `Critical Task / Issue`, `Progress Highlights`).
- If a specific PDF format changes, update regex patterns in `parse_pdf_file()`.
- Always review output before sending; the app does not fabricate missing values and leaves unknown fields as `-`.
