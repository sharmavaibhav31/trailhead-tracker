"""
parse_calendar.py

One-time (or re-run-when-the-sheet-changes) script that reads the Wipro
training-calendar Excel file and turns it into data/calendar.json, which
the FastAPI app serves to the frontend and matches against a trainee's
Trailhead badges.

Why this is a separate script instead of parsing the Excel file on every
request: the calendar is static reference data set once by the training
team. Re-parsing it on every page load would be slower and would make the
app depend on the Excel file being present at runtime. Run this script
again whenever the Excel file changes, then restart the server.

Usage:
    python parse_calendar.py path/to/calendar.xlsx [-o data/calendar.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl

URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?trailhead\.salesforce\.com/[^\s]+)", re.I)

# Column headers we look for to find the header row in each sheet.
EXPECTED_HEADERS = ["date", "day", "topic", "sub-topics", "trailhead modules", "hours"]


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _prettify_slug(url: str) -> str:
    """Turn a bare Trailhead URL into a readable fallback title, e.g.
    '.../modules/data_security' -> 'Data Security'."""
    slug = url.rstrip("/").split("/")[-1]
    slug = slug.split("?")[0]
    slug = re.sub(r"[-_]+", " ", slug)
    return slug.strip().title() or url


KNOWN_MODULE_URLS = {
    "configure businness hours, working days, & roles": "https://trailhead.salesforce.com/content/learn/modules/company_wide_org_settings",
    "configure business hours, working days, & roles": "https://trailhead.salesforce.com/content/learn/modules/company_wide_org_settings",
    "lightning app builder": "https://trailhead.salesforce.com/content/learn/modules/lightning_app_builder",
    "lightning experience customization": "https://trailhead.salesforce.com/content/learn/modules/lex_customization",
    "permission set groups": "https://trailhead.salesforce.com/content/learn/modules/permission-set-groups",
    "protect your data in salesforce": "https://trailhead.salesforce.com/content/learn/projects/protect-your-data-in-salesforce",
    "formulas and validations": "https://trailhead.salesforce.com/content/learn/modules/point_click_business_logic",
    "set up the service console": "https://trailhead.salesforce.com/content/learn/projects/set-up-the-service-console",
    "create a process for managing support cases": "https://trailhead.salesforce.com/content/learn/projects/create-a-process-for-managing-support-cases",
    "set up case escalation and entitlements": "https://trailhead.salesforce.com/content/learn/projects/set-up-case-escalation-entitlements",
    "agentexchange basics": "https://trailhead.salesforce.com/content/learn/modules/appexchange_basics",
    "appexchange basics": "https://trailhead.salesforce.com/content/learn/modules/appexchange_basics",
    "duplicate management": "https://trailhead.salesforce.com/content/learn/modules/sales_admin_duplicate_management",
    "import and export with data management tools": "https://trailhead.salesforce.com/content/learn/projects/import-and-export-with-data-management-tools",
    "create reports and dashboards for sales and marketing managers": "https://trailhead.salesforce.com/content/learn/projects/create-reports-and-dashboards-for-sales-and-marketing-managers",
    "business process automation": "https://trailhead.salesforce.com/content/learn/modules/business_process_automation",
    "record triggered flow": "https://trailhead.salesforce.com/content/learn/modules/record-triggered-flows",
    "asynchronous apex": "https://trailhead.salesforce.com/content/learn/modules/asynchronous_apex",
    "apex integration services": "https://trailhead.salesforce.com/content/learn/modules/apex_integration_services",
    "apex testing": "https://trailhead.salesforce.com/content/learn/modules/apex_testing",
    "get started with modern javascript development": "https://trailhead.salesforce.com/content/learn/modules/modern-javascript-development",
    "lightning web components basics": "https://trailhead.salesforce.com/content/learn/modules/lightning-web-components-basics",
}


def _split_module_cell(raw_text, cell_hyperlink):
    """A 'Trailhead Modules' cell may contain one module name per line, and/or
    raw URLs typed directly into the text, and/or (separately) one Excel
    hyperlink attached to the whole cell.

    When multiple modules exist in a single cell, we resolve individual URLs
    from explicit in-text URLs, the cell hyperlink, or the verified
    KNOWN_MODULE_URLS catalog so every module gets a working link.
    """
    lines = [_clean(l) for l in re.split(r"[\r\n]+", raw_text or "") if _clean(l)]

    modules = []
    for line in lines:
        m = URL_RE.search(line)
        if m:
            url = m.group(1)
            if url.lower().startswith("www.") or url.lower().startswith("trailhead"):
                url = "https://" + url
            modules.append({"name": _prettify_slug(url), "url": url})
        else:
            modules.append({"name": line, "url": None})

    if not modules and cell_hyperlink:
        modules.append({"name": _prettify_slug(cell_hyperlink), "url": cell_hyperlink})

    if cell_hyperlink and not any(m["url"] == cell_hyperlink for m in modules):
        for m in modules:
            if m["url"] is None:
                m["url"] = cell_hyperlink
                break

    for m in modules:
        if not m["url"]:
            norm_name = m["name"].strip().lower()
            m["url"] = KNOWN_MODULE_URLS.get(norm_name)

    return modules


def _find_header_row(ws, max_scan=10):
    for row in ws.iter_rows(min_row=1, max_row=max_scan):
        values = [_clean(c.value).lower() for c in row]
        if "date" in values and any("trailhead" in v for v in values):
            col_index = {}
            for c in row:
                key = _clean(c.value).lower()
                if key:
                    col_index[key] = c.column
            return row[0].row, col_index
    raise ValueError(f"Could not find a header row in sheet '{ws.title}'")


def parse_sheet(ws):
    header_row_num, col_index = _find_header_row(ws)

    def col(name):
        return col_index.get(name)

    date_col = col("date")
    day_col = col("day")
    topic_col = col("topic")
    subtopic_col = col("sub-topics")
    modules_col = col("trailhead modules")
    hours_col = col("hours")

    # Sheet title looks like "Phase 1 (Admin + PD1)" -- pull a "covers" line
    # from the row just under the title if present.
    covers = ""
    for row in ws.iter_rows(min_row=1, max_row=header_row_num - 1):
        for c in row:
            text = _clean(c.value)
            if text.lower().startswith("covers"):
                covers = text
                break

    rows = []
    r = header_row_num + 1
    while True:
        date_cell = ws.cell(row=r, column=date_col) if date_col else None
        date_val = _clean(date_cell.value) if date_cell else ""
        if not date_val:
            break

        modules_cell = ws.cell(row=r, column=modules_col) if modules_col else None
        raw_modules_text = _clean(modules_cell.value) if modules_cell else ""
        hyperlink = modules_cell.hyperlink.target if (modules_cell and modules_cell.hyperlink) else None
        modules = _split_module_cell(raw_modules_text, hyperlink)

        rows.append({
            "date": date_val,
            "day": _clean(ws.cell(row=r, column=day_col).value) if day_col else "",
            "topic": _clean(ws.cell(row=r, column=topic_col).value) if topic_col else "",
            "subtopics": _clean(ws.cell(row=r, column=subtopic_col).value) if subtopic_col else "",
            "hours": _clean(ws.cell(row=r, column=hours_col).value) if hours_col else "",
            "reference_link": hyperlink,
            "modules": modules,
        })
        r += 1

    return covers, rows


def parse_workbook(xlsx_path: str):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    phases = []
    for i, ws in enumerate(wb.worksheets, start=1):
        try:
            covers, rows = parse_sheet(ws)
        except ValueError:
            continue  # skip sheets that don't look like a training calendar
        if not rows:
            continue
        phases.append({
            "id": f"phase{i}",
            "title": ws.title,
            "covers": covers,
            "rows": rows,
        })
    return {"phases": phases}


def main():
    parser = argparse.ArgumentParser(description="Parse a Wipro Salesforce training calendar into calendar.json")
    parser.add_argument("xlsx_path", help="Path to the .xlsx training calendar")
    parser.add_argument("-o", "--output", default="data/calendar.json", help="Output JSON path")
    args = parser.parse_args()

    result = parse_workbook(args.xlsx_path)

    total_modules = sum(len(row["modules"]) for phase in result["phases"] for row in phase["rows"])
    if total_modules == 0:
        print("Warning: parsed 0 modules. Check that the sheet headers match "
              "Date / Day / Topic / Sub-Topics / Trailhead Modules / Hours.", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} — {len(result['phases'])} phase(s), {total_modules} module entries total.")


if __name__ == "__main__":
    main()
