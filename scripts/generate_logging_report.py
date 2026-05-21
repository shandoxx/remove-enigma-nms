#!/usr/bin/env python3
import argparse
import difflib
import re
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

TARGETS = ["10.10.70.100", "10.10.60.100"]

def read_file(path):
    p = Path(path)
    return p.read_text(errors="ignore").rstrip() if p.exists() else ""

def sanitize_config(text):
    out = []
    in_interface = False
    truncated_count = 0

    for line in text.splitlines():
        stripped = line.strip()

        if re.match(r"^username\s+", stripped, re.I):
            continue

        if re.match(r"^interface\s+", stripped, re.I):
            if not in_interface:
                out.append("! [INTERFACE SECTIONS TRUNCATED]")
            in_interface = True
            truncated_count += 1
            continue

        if in_interface:
            if stripped == "!":
                in_interface = False
            continue

        out.append(line)

    out.append(f"! NOTE: Interface sections have been truncated. Interface section count removed: {truncated_count}")
    out.append("! NOTE: Username lines have been removed from this sanitized report.")
    return "\n".join(out)

def make_html(args, before_logging, after_logging, removed, still_present, status):
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Cisco Logging Host Removal Report</title>
<style>
body {{ font-family: Arial, Helvetica, sans-serif; background:#f4f4f4; padding:20px; }}
.container {{ background:white; border:1px solid #ccc; max-width:900px; margin:auto; }}
.header {{ background:#1f4e79; color:white; text-align:center; padding:12px; }}
.section {{ padding:16px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border:1px solid #ccc; padding:8px; text-align:left; }}
pre {{ background:#f7f7f7; border:1px solid #ddd; padding:10px; white-space:pre-wrap; }}
.success {{ color:green; font-weight:bold; }}
.failed {{ color:red; font-weight:bold; }}
</style>
</head>
<body>
<div class="container">
<div class="header"><h2>Cisco Logging Host Removal Report</h2></div>
<div class="section">
<table>
<tr><th>Host</th><td>{escape(args.host)}</td></tr>
<tr><th>IP</th><td>{escape(args.ip)}</td></tr>
<tr><th>Timestamp</th><td>{escape(args.timestamp)}</td></tr>
<tr><th>Status</th><td class="{status.lower()}">{status}</td></tr>
<tr><th>Removed Targets</th><td>{escape(", ".join(removed) if removed else "None confirmed")}</td></tr>
<tr><th>Still Present</th><td>{escape(", ".join(still_present) if still_present else "None")}</td></tr>
</table>

<h3>Logging Command Snapshot - Before</h3>
<pre>{escape(before_logging or "No logging entries found")}</pre>

<h3>Logging Command Snapshot - After</h3>
<pre>{escape(after_logging or "No logging entries found")}</pre>

<p><b>PDF attached:</b> sanitized BEFORE and AFTER running-config side by side with diff markers. Username lines removed. Interface sections truncated.</p>
</div>
</div>
</body>
</html>
"""
    Path(args.html).write_text(html)

def footer(c, page, width):
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.black)
    c.drawRightString(width - 10*mm, 7*mm, f"Page {page}")

def wrap_line(line, max_chars):
    return [line[i:i+max_chars] for i in range(0, len(line), max_chars)] or [""]

def build_rows(before_lines, after_lines):
    rows = []
    sm = difflib.SequenceMatcher(None, before_lines, after_lines)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        left_block = before_lines[i1:i2]
        right_block = after_lines[j1:j2]
        max_len = max(len(left_block), len(right_block))

        for idx in range(max_len):
            left = left_block[idx] if idx < len(left_block) else ""
            right = right_block[idx] if idx < len(right_block) else ""

            if tag == "equal":
                sym = "="
            elif tag == "delete":
                sym = "-"
            elif tag == "insert":
                sym = "+"
            else:
                sym = "!" if left and right else "-" if left else "+"

            rows.append((sym, left, right))

    return rows

def make_pdf(args, before_full, after_full, before_logging, after_logging, removed, still_present, status):
    before_sanitized = sanitize_config(before_full)
    after_sanitized = sanitize_config(after_full)

    width, height = landscape(A4)
    c = canvas.Canvas(args.pdf, pagesize=landscape(A4))

    margin = 8 * mm
    gap = 6 * mm
    sym_w = 7 * mm
    col_w = (width - 2 * margin - gap - sym_w) / 2
    centre_x = margin + col_w + (sym_w / 2)
    divider_x = margin + col_w + sym_w + (gap / 2)
    right_x = margin + col_w + sym_w + gap
    y_top = height - margin
    y = y_top
    page = 1

    def draw_config_header(suffix=""):
        nonlocal y
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.black)
        c.drawString(margin, y, f"BEFORE sanitized running-config {suffix}".strip())
        c.drawCentredString(centre_x, y, "DIFF")
        c.drawString(right_x, y, f"AFTER sanitized running-config {suffix}".strip())
        y -= 3 * mm
        c.setStrokeColor(colors.darkgrey)
        c.setLineWidth(1.2)
        c.line(divider_x, y + 4*mm, divider_x, 10*mm)
        c.setStrokeColor(colors.lightgrey)
        c.line(margin, y, width - margin, y)
        y -= 3 * mm

    def new_page():
        nonlocal y, page
        footer(c, page, width)
        c.showPage()
        page += 1
        y = y_top
        draw_config_header("continued")

    def draw_row(sym, left, right):
        nonlocal y
        max_chars = 88
        left_parts = wrap_line(left, max_chars)
        right_parts = wrap_line(right, max_chars)
        row_lines = max(len(left_parts), len(right_parts))
        line_h = 3.1 * mm
        row_h = row_lines * line_h

        if y - row_h < 12 * mm:
            new_page()

        if sym == "-":
            c.setFillColor(colors.Color(1, 0.86, 0.86))
            c.rect(margin - 1, y - row_h + 2, col_w, row_h, stroke=0, fill=1)
        elif sym == "+":
            c.setFillColor(colors.Color(0.86, 1, 0.86))
            c.rect(right_x - 1, y - row_h + 2, col_w, row_h, stroke=0, fill=1)
        elif sym == "!":
            c.setFillColor(colors.Color(1, 1, 0.75))
            c.rect(margin - 1, y - row_h + 2, col_w, row_h, stroke=0, fill=1)
            c.rect(right_x - 1, y - row_h + 2, col_w, row_h, stroke=0, fill=1)

        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.black)
        c.drawCentredString(centre_x, y, sym)

        c.setFont("Courier", 5.3)
        yy = y
        for part in left_parts:
            c.drawString(margin, yy, part)
            yy -= line_h

        yy = y
        for part in right_parts:
            c.drawString(right_x, yy, part)
            yy -= line_h

        y -= row_h

    rows = build_rows(before_sanitized.splitlines(), after_sanitized.splitlines())

    deletes = sum(1 for sym, _, _ in rows if sym == "-")
    inserts = sum(1 for sym, _, _ in rows if sym == "+")
    changes = sum(1 for sym, _, _ in rows if sym == "!")

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "Cisco Logging Host Removal Report")
    y -= 10 * mm

    for k, v in [
        ("Host", args.host),
        ("IP", args.ip),
        ("Timestamp", args.timestamp),
        ("Status", status),
        ("Removed Targets", ", ".join(removed) if removed else "None confirmed"),
        ("Still Present", ", ".join(still_present) if still_present else "None"),
        ("Diff Summary", f"Removed lines: {deletes}, Added lines: {inserts}, Changed lines: {changes}"),
        ("Sanitization", "Username lines removed. Interface sections truncated."),
    ]:
        c.setFont("Helvetica-Bold", 8)
        c.drawString(margin, y, f"{k}:")
        c.setFont("Helvetica", 8)
        c.drawString(margin + 35*mm, y, v)
        y -= 4.7 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Logging Command Snapshot - Before")
    c.drawString(right_x, y, "Logging Command Snapshot - After")
    y -= 5 * mm

    c.setFont("Courier", 6.5)
    before_log = before_logging.splitlines() or ["No logging entries found"]
    after_log = after_logging.splitlines() or ["No logging entries found"]

    for i in range(max(len(before_log), len(after_log))):
        if i < len(before_log):
            c.drawString(margin, y, before_log[i][:90])
        if i < len(after_log):
            c.drawString(right_x, y, after_log[i][:90])
        y -= 3.8 * mm

    y -= 5 * mm
    draw_config_header()

    for sym, left, right in rows:
        draw_row(sym, left, right)

    footer(c, page, width)
    c.save()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--before-full", required=True)
    parser.add_argument("--after-full", required=True)
    parser.add_argument("--html", required=True)
    parser.add_argument("--pdf", required=True)
    args = parser.parse_args()

    before_logging = read_file(args.before)
    after_logging = read_file(args.after)
    before_full = read_file(args.before_full)
    after_full = read_file(args.after_full)

    removed = [t for t in TARGETS if t in before_logging and t not in after_logging]
    still_present = [t for t in TARGETS if t in after_logging]
    status = "SUCCESS" if not still_present else "FAILED"

    make_html(args, before_logging, after_logging, removed, still_present, status)
    make_pdf(args, before_full, after_full, before_logging, after_logging, removed, still_present, status)

if __name__ == "__main__":
    main()
