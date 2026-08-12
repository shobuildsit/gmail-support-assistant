#!/usr/bin/env python3
"""Static, offline validation of the sanitized Make blueprint, the
Phase 2B spreadsheet template, sample data, and prompt test specs.

Standard library only. Does not call Make, Google, OpenAI, Slack, or
Gmail, and does not read the private original blueprint/spreadsheet.

Usage:
    python3 tests/validate_blueprint.py
"""
import csv
from collections import Counter
import json
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_PATH = REPO_ROOT / "make/blueprints/gmail-support-assistant.sanitized.json"
SCHEMA_PATH = REPO_ROOT / "prompts/response-schema.json"
PROMPT_MD_PATH = REPO_ROOT / "prompts/support-triage-v1.md"
PROMPT_CASES_PATH = REPO_ROOT / "tests/prompt-cases.jsonl"
TEMPLATE_XLSX_PATH = REPO_ROOT / "spreadsheet/templates/gmail-support-assistant-template.xlsx"
SAMPLE_FORM_CSV_PATH = REPO_ROOT / "sample_data/form-submissions.csv"
SAMPLE_CRM_CSV_PATH = REPO_ROOT / "sample_data/crm-records.csv"
PHASE2B_CANDIDATE_PATH = REPO_ROOT / "make/blueprints/gmail-support-assistant.phase2b.candidate.json"
ERROR_HANDLING_DOC_PATH = REPO_ROOT / "docs/error-handling-and-idempotency.md"
PHASE2B_CHECKLIST_PATH = REPO_ROOT / "make/phase2b-deployment-checklist.md"
DATA_MODEL_DOC_PATH = REPO_ROOT / "docs/data-model.md"
FORM_SPEC_PATH = REPO_ROOT / "forms/google-form-spec.json"
FORM_SCRIPT_PATH = REPO_ROOT / "forms/create-google-form.gs"
ARCHITECTURE_SVG_PATH = REPO_ROOT / "docs/diagrams/system-architecture.svg"
DEMO_SVG_PATH = REPO_ROOT / "assets/demo/synthetic-e2e-demo.svg"

# The Processing_State column list, per docs/error-handling-and-idempotency.md
# #state-tracking-columns. Every one of these must be mentioned in each of the
# three docs that enumerate the sheet's columns (error-handling doc, the
# deployment checklist's "Add a Processing_State sheet" step, and
# data-model.md's Processing_State summary) -- this is what
# validate_phase2b_docs_consistency() checks, as a regression guard against
# one doc's column list drifting from the others.
PROCESSING_STATE_COLUMNS = [
    "Request_ID", "Source_Row", "Status", "Attempt_Count", "Last_Error",
    "Validation_Error_Notified", "AI_Completed", "AI_Category", "AI_Priority",
    "AI_Sentiment", "AI_Requires_Human", "AI_Summary", "AI_Reply_Subject",
    "AI_Reply_Body", "CRM_Written", "Slack_Notified", "Gmail_Draft_Created",
    "Completed_At",
]

FORM_HEADERS = ["Timestamp", "Name", "Email", "Subject", "Message"]
CRM_HEADERS = [
    "ID", "Date", "Name", "Email", "Original_Subject", "Original_Message",
    "Category", "Priority", "Sentiment", "Requires_Human", "Summary",
    "Reply_Subject", "Reply_Body", "Status", "Created_At",
]

EXPECTED_MODULE_ORDER = [
    (2, "google-sheets:watchRows"),
    (3, "openai-gpt-3:createModelResponse"),
    (4, "google-sheets:addRow"),
    (6, "slack:CreateMessage"),
    (5, "google-email:createADraft"),
]

EXPECTED_ENUMS = {
    "category": ["配送トラブル", "返金依頼", "商品に関する質問", "技術的な問題", "クレーム", "その他"],
    "priority": ["高", "中", "低"],
    "sentiment": ["ポジティブ", "普通", "ネガティブ"],
}

EXPECTED_REQUIRED_FIELDS = [
    "category", "priority", "sentiment", "requires_human",
    "summary", "reply_subject", "reply_body",
]

# Fixed expected max lengths. Checked independently of blueprint<->schema-file
# equality, so that if BOTH copies were edited to remove/loosen a constraint
# at the same time, this still catches the regression.
EXPECTED_MAX_LENGTHS = {
    "summary": 200,
    "reply_subject": 150,
    "reply_body": 3000,
}

# --- Known public placeholder values already committed in the sanitized
# blueprint (Phase 1 / Phase 1 review). These are dummy values meant for
# publication, not secrets, so they are safe to hardcode here and check
# for an exact match. This replaces an earlier approach (removed in this
# review pass) that hashed the *original* private values — that approach
# put SHA-256 digests of short, low-entropy secrets (e.g. 7-digit
# connection IDs) into a public file, which is itself a disclosure risk
# for brute-forceable values. We no longer need to know, reference, or
# hash the original values at all: checking that today's placeholders are
# still exactly what Phase 1 set them to is sufficient and requires zero
# knowledge of the private original.
EXPECTED_CONNECTION_IDS = {
    2: 100000001,
    3: 100000002,
    4: 100000003,
    6: 100000004,
    5: 100000005,
}
EXPECTED_CONNECTION_LABELS = {
    2: "Google Sheets Connection (reconnect required)",
    3: "OpenAI Connection (reconnect required)",
    4: "Google Sheets Connection (reconnect required)",
    6: "Slack Connection (reconnect required)",
    5: "Gmail Connection (reconnect required)",
}
EXPECTED_SPREADSHEET_ID_PLACEHOLDER = "/YOUR_DRIVE_FOLDER_ID/YOUR_SPREADSHEET_ID"
EXPECTED_DRIVE_BREADCRUMB = ["YOUR_DRIVE_FOLDER", "YOUR_SUBFOLDER"]
EXPECTED_SLACK_CHANNEL_ID = "C000000000"
EXPECTED_SLACK_CHANNEL_LABEL = "YOUR_SLACK_CHANNEL"
EXPECTED_OPENAI_SCHEMA_NAME = "gmail_support_assistant_response"

# --- Generic secret-shape patterns. These do not encode any value from
# the private original blueprint — they are well-known public patterns
# (API key/token prefixes, PEM headers) plus a couple of structural rules
# ("no @gmail.com anywhere", "no email besides @example.com", "no
# Drive/Spreadsheet-looking identifier that isn't a YOUR_... placeholder").
OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
SLACK_TOKEN_RE = re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")
GITHUB_TOKEN_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")
PRIVATE_KEY_BLOCK_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+")
SPREADSHEET_ID_FIELD_RE = re.compile(r'"spreadsheetId"\s*:\s*"([^"]*)"')
DRIVE_BREADCRUMB_PATH_RE = re.compile(r'"path"\s*:\s*\[\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\]')

# Dangerous phrases that would indicate the model complied with an
# injected instruction (used only to document/explain intent here; the
# actual per-case must_not_contain lists live in prompt-cases.jsonl).

# Files scanned by the repo-wide generic secret scan (Phase 2B). Deliberately
# excludes the two private originals (never read by this script at all) and
# this script itself (whose own regex patterns would otherwise self-match).
SCANNED_GLOBS = [
    "*.md", "docs/*.md", "make/*.md", "prompts/*.md", "tests/*.md",
    "sample_data/*.md", "forms/*.md", "prompts/*.json", "forms/*.json",
    "forms/*.gs", "make/blueprints/*.json",
    "sample_data/*.csv", "tests/*.jsonl", "docs/diagrams/*.svg",
    "assets/demo/*.svg", "assets/screenshots/*.svg",
]

XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def read_xlsx_sheet_headers(xlsx_path):
    """Read row-1 header values per sheet from a .xlsx, using only the
    standard library (zipfile + xml.etree). Returns {sheet_name: [values]}.
    """
    z = zipfile.ZipFile(xlsx_path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.get("Id"): rel.get("Target").lstrip("/") for rel in rels}

    sheet_headers = {}
    for sheet in wb.find("m:sheets", XLSX_NS):
        name = sheet.get("name")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rid_to_target[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheet_xml = ET.fromstring(z.read(target))
        headers = []
        sheet_data = sheet_xml.find("m:sheetData", XLSX_NS)
        row1 = None
        if sheet_data is not None:
            for row in sheet_data:
                if row.get("r") == "1":
                    row1 = row
                    break
        if row1 is not None:
            for c in row1:
                is_el = c.find("m:is/m:t", XLSX_NS)
                if is_el is not None:
                    headers.append(is_el.text)
                else:
                    v_el = c.find("m:v", XLSX_NS)
                    headers.append(v_el.text if v_el is not None else None)
        sheet_headers[name] = headers
    return sheet_headers


def extract_xlsx_text(xlsx_path):
    """Concatenate all inline-string / shared-string text found in a
    .xlsx's worksheet + sharedStrings XML parts, for secret-pattern
    scanning. Standard library only."""
    z = zipfile.ZipFile(xlsx_path)
    chunks = []
    for name in z.namelist():
        if name.startswith("xl/worksheets/") or name == "xl/sharedStrings.xml":
            chunks.append(z.read(name).decode("utf-8", errors="ignore"))
    return "\n".join(chunks)


def scan_text_for_secrets(text, label):
    check(f"{label}: no '@gmail.com'", "@gmail.com" not in text.lower())
    non_example = [m for m in EMAIL_RE.findall(text) if m.split("@")[-1].lower() != "example.com"]
    check(f"{label}: no email address outside example.com", len(non_example) == 0, f"found: {non_example}")
    check(f"{label}: no OpenAI-API-key-shaped string", not OPENAI_KEY_RE.search(text))
    check(f"{label}: no Slack-token-shaped string", not SLACK_TOKEN_RE.search(text))
    check(f"{label}: no GitHub-token-shaped string", not GITHUB_TOKEN_RE.search(text))
    check(f"{label}: no private key block", not PRIVATE_KEY_BLOCK_RE.search(text))


def validate_public_files_secret_scan():
    """Repo-wide generic secret scan across all published text files,
    plus the spreadsheet template's extracted text. Uses the same
    knowledge-free patterns as the blueprint scan (no original-secret
    values are referenced anywhere in this script)."""
    seen = set()
    for pattern in SCANNED_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(REPO_ROOT)
            scan_text_for_secrets(text, str(rel))

    if TEMPLATE_XLSX_PATH.exists():
        scan_text_for_secrets(
            extract_xlsx_text(TEMPLATE_XLSX_PATH),
            str(TEMPLATE_XLSX_PATH.relative_to(REPO_ROOT)),
        )


ALLOWED_TEMPLATE_SHEET_NAMES = {"Form", "CRM", "Processing_State"}
FORBIDDEN_XLSX_ZIP_PART_SUBSTRINGS = [
    "xl/externalLinks/",
    "xl/vbaProject.bin",
    "xl/embeddings/",
    "xl/oleObjects/",
    "customXml/",
]
# Expected sqref ranges (1-indexed rows, header row excluded) for the
# pre-formatted block and its data validations, per docs/data-model.md.
EXPECTED_TEMPLATE_LAST_ROW = 201  # header (row 1) + 200 pre-formatted rows
EXPECTED_AUTOFILTER = {
    "Form": f"A1:E{EXPECTED_TEMPLATE_LAST_ROW}",
    "CRM": f"A1:O{EXPECTED_TEMPLATE_LAST_ROW}",
    "Processing_State": f"A1:R{EXPECTED_TEMPLATE_LAST_ROW}",
}
EXPECTED_DATA_VALIDATION_SQREFS_CRM = {
    f"G2:G{EXPECTED_TEMPLATE_LAST_ROW}",  # Category
    f"H2:H{EXPECTED_TEMPLATE_LAST_ROW}",  # Priority
    f"I2:I{EXPECTED_TEMPLATE_LAST_ROW}",  # Sentiment
    f"J2:J{EXPECTED_TEMPLATE_LAST_ROW}",  # Requires_Human
}
EXPECTED_DATA_VALIDATION_SQREFS_PROCESSING_STATE = {
    f"C2:C{EXPECTED_TEMPLATE_LAST_ROW}",   # Status
    f"F2:F{EXPECTED_TEMPLATE_LAST_ROW}",   # Validation_Error_Notified
    f"G2:G{EXPECTED_TEMPLATE_LAST_ROW}",   # AI_Completed
    f"H2:H{EXPECTED_TEMPLATE_LAST_ROW}",   # AI_Category
    f"I2:I{EXPECTED_TEMPLATE_LAST_ROW}",   # AI_Priority
    f"J2:J{EXPECTED_TEMPLATE_LAST_ROW}",   # AI_Sentiment
    f"K2:K{EXPECTED_TEMPLATE_LAST_ROW}",   # AI_Requires_Human
    f"O2:O{EXPECTED_TEMPLATE_LAST_ROW}",   # CRM_Written
    f"P2:P{EXPECTED_TEMPLATE_LAST_ROW}",   # Slack_Notified
    f"Q2:Q{EXPECTED_TEMPLATE_LAST_ROW}",   # Gmail_Draft_Created
}
EXPECTED_DATA_VALIDATION_FORMULAS_PROCESSING_STATE = {
    f"C2:C{EXPECTED_TEMPLATE_LAST_ROW}": '"PENDING,PROCESSING,COMPLETED,FAILED_VALIDATION,FAILED_RETRYABLE,FAILED_PERMANENT,NEEDS_HUMAN"',
    f"F2:F{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
    f"G2:G{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
    f"H2:H{EXPECTED_TEMPLATE_LAST_ROW}": '"配送トラブル,返金依頼,商品に関する質問,技術的な問題,クレーム,その他"',
    f"I2:I{EXPECTED_TEMPLATE_LAST_ROW}": '"高,中,低"',
    f"J2:J{EXPECTED_TEMPLATE_LAST_ROW}": '"ポジティブ,普通,ネガティブ"',
    f"K2:K{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
    f"O2:O{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
    f"P2:P{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
    f"Q2:Q{EXPECTED_TEMPLATE_LAST_ROW}": '"TRUE,FALSE"',
}


def get_workbook_sheet_states(xlsx_path):
    """{sheet_name: state} from workbook.xml's <sheet> elements.
    OOXML default state (attribute absent) is 'visible'."""
    z = zipfile.ZipFile(xlsx_path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    states = {}
    for sheet in wb.find("m:sheets", XLSX_NS):
        states[sheet.get("name")] = sheet.get("state", "visible")
    return states


def get_sheet_xml_by_name(xlsx_path):
    """{sheet_name: parsed sheetN.xml root Element}."""
    z = zipfile.ZipFile(xlsx_path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.get("Id"): rel.get("Target").lstrip("/") for rel in rels}
    out = {}
    for sheet in wb.find("m:sheets", XLSX_NS):
        name = sheet.get("name")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rid_to_target[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target
        out[name] = ET.fromstring(z.read(target))
    return out


def find_non_header_values(sheet_xml):
    """Return a list of (cell_ref, value) for any non-empty cell in row 2+."""
    found = []
    sheet_data = sheet_xml.find("m:sheetData", XLSX_NS)
    if sheet_data is None:
        return found
    for row in sheet_data:
        try:
            row_num = int(row.get("r", "0"))
        except ValueError:
            continue
        if row_num < 2:
            continue
        for c in row:
            is_el = c.find("m:is/m:t", XLSX_NS)
            v_el = c.find("m:v", XLSX_NS)
            value = is_el.text if is_el is not None else (v_el.text if v_el is not None else None)
            if value not in (None, ""):
                found.append((c.get("r"), value))
    return found


def has_frozen_header_pane(sheet_xml):
    pane = sheet_xml.find("m:sheetViews/m:sheetView/m:pane", XLSX_NS)
    if pane is None:
        return False
    return pane.get("state") == "frozen" and pane.get("ySplit") not in (None, "0")


def get_autofilter_ref(sheet_xml):
    el = sheet_xml.find("m:autoFilter", XLSX_NS)
    return el.get("ref") if el is not None else None


def get_table_autofilter_refs_by_sheet(xlsx_path):
    """Return AutoFilter refs stored in worksheet table parts.

    The Phase 2B template uses real Excel tables so filters survive import to
    Google Sheets. Older templates stored autoFilter directly on the sheet.
    """
    z = zipfile.ZipFile(xlsx_path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wb_rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.get("Id"): rel.get("Target").lstrip("/") for rel in wb_rels}
    refs = {}
    for sheet in wb.find("m:sheets", XLSX_NS):
        name = sheet.get("name")
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        sheet_path = rid_to_target[rid]
        if not sheet_path.startswith("xl/"):
            sheet_path = "xl/" + sheet_path
        rels_path = posixpath.join(
            posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels"
        )
        refs[name] = set()
        if rels_path not in z.namelist():
            continue
        sheet_xml = ET.fromstring(z.read(sheet_path))
        sheet_rels = ET.fromstring(z.read(rels_path))
        table_targets = {rel.get("Id"): rel.get("Target") for rel in sheet_rels}
        table_parts = sheet_xml.find("m:tableParts", XLSX_NS)
        if table_parts is None:
            continue
        for part in table_parts.findall("m:tablePart", XLSX_NS):
            part_rid = part.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            target = table_targets.get(part_rid)
            if not target:
                continue
            if target.startswith("/"):
                table_path = target.lstrip("/")
            else:
                table_path = posixpath.normpath(
                    posixpath.join(posixpath.dirname(sheet_path), target)
                )
            table_xml = ET.fromstring(z.read(table_path))
            auto_filter = table_xml.find("m:autoFilter", XLSX_NS)
            if auto_filter is not None and auto_filter.get("ref"):
                refs[name].add(auto_filter.get("ref"))
    return refs


def get_data_validation_sqrefs(sheet_xml):
    dvs = sheet_xml.find("m:dataValidations", XLSX_NS)
    if dvs is None:
        return set()
    return {dv.get("sqref") for dv in dvs.findall("m:dataValidation", XLSX_NS) if dv.get("sqref")}


def get_data_validation_formulas(sheet_xml):
    dvs = sheet_xml.find("m:dataValidations", XLSX_NS)
    if dvs is None:
        return {}
    result = {}
    for dv in dvs.findall("m:dataValidation", XLSX_NS):
        sqref = dv.get("sqref")
        formula = dv.find("m:formula1", XLSX_NS)
        if sqref:
            result[sqref] = formula.text if formula is not None else None
    return result


def validate_spreadsheet_template():
    if not TEMPLATE_XLSX_PATH.exists():
        fail_and_exit(
            "spreadsheet/templates/gmail-support-assistant-template.xlsx exists",
            f"not found: {TEMPLATE_XLSX_PATH}",
        )
        return

    check("spreadsheet template is a readable .xlsx (zip) file", zipfile.is_zipfile(TEMPLATE_XLSX_PATH))

    try:
        headers = read_xlsx_sheet_headers(TEMPLATE_XLSX_PATH)
    except Exception as e:
        fail_and_exit("spreadsheet template sheets/headers are readable", str(e))
        return

    check(
        "spreadsheet template has exactly the intended sheets (Form, CRM, Processing_State)",
        set(headers.keys()) == ALLOWED_TEMPLATE_SHEET_NAMES,
        f"got sheets: {list(headers.keys())}",
    )
    check(
        "spreadsheet template 'Form' sheet headers match docs/data-model.md",
        headers.get("Form") == FORM_HEADERS,
        f"got {headers.get('Form')!r}",
    )
    check(
        "spreadsheet template 'CRM' sheet headers match docs/data-model.md",
        headers.get("CRM") == CRM_HEADERS,
        f"got {headers.get('CRM')!r}",
    )
    check(
        "spreadsheet template 'Processing_State' headers match the Phase 2B contract",
        headers.get("Processing_State") == PROCESSING_STATE_COLUMNS,
        f"got {headers.get('Processing_State')!r}",
    )

    # --- no hidden sheets ---
    try:
        sheet_states = get_workbook_sheet_states(TEMPLATE_XLSX_PATH)
    except Exception as e:
        fail_and_exit("spreadsheet template sheet visibility is readable", str(e))
        return
    hidden = {name: state for name, state in sheet_states.items() if state != "visible"}
    check("spreadsheet template has no hidden sheets", len(hidden) == 0, f"hidden: {hidden}")

    # --- no external links / VBA / embedded files / customXml ---
    z = zipfile.ZipFile(TEMPLATE_XLSX_PATH)
    names = z.namelist()
    forbidden_found = [
        n for n in names if any(n.startswith(sub) or sub in n for sub in FORBIDDEN_XLSX_ZIP_PART_SUBSTRINGS)
    ]
    check(
        "spreadsheet template has no external links, VBA project, embedded files, or customXml",
        len(forbidden_found) == 0,
        f"found: {forbidden_found}",
    )

    # --- no values beyond the header row on either sheet ---
    try:
        sheet_xmls = get_sheet_xml_by_name(TEMPLATE_XLSX_PATH)
    except Exception as e:
        fail_and_exit("spreadsheet template worksheet XML is readable", str(e))
        return

    try:
        table_autofilters = get_table_autofilter_refs_by_sheet(TEMPLATE_XLSX_PATH)
    except Exception as e:
        fail_and_exit("spreadsheet template table filters are readable", str(e))
        return

    for sheet_name in ("Form", "CRM", "Processing_State"):
        sx = sheet_xmls.get(sheet_name)
        if sx is None:
            check(f"spreadsheet template '{sheet_name}' sheet has no data beyond the header row", False, "sheet missing")
            continue
        stray = find_non_header_values(sx)
        check(
            f"spreadsheet template '{sheet_name}' sheet has no data beyond the header row",
            len(stray) == 0,
            f"found values at: {stray[:10]}",
        )

        # --- frozen header pane ---
        check(
            f"spreadsheet template '{sheet_name}' sheet has the header row frozen",
            has_frozen_header_pane(sx),
        )

        # --- autoFilter ---
        sheet_autofilter = get_autofilter_ref(sx)
        table_filter_refs = table_autofilters.get(sheet_name, set())
        actual_autofilter = sheet_autofilter or (
            next(iter(table_filter_refs)) if len(table_filter_refs) == 1 else None
        )
        check(
            f"spreadsheet template '{sheet_name}' sheet has the expected autoFilter range",
            actual_autofilter == EXPECTED_AUTOFILTER[sheet_name],
            f"got {actual_autofilter!r}",
        )

    # --- data validation ranges on CRM (Category/Priority/Sentiment/Requires_Human) ---
    crm_sx = sheet_xmls.get("CRM")
    if crm_sx is not None:
        actual_dv_sqrefs = get_data_validation_sqrefs(crm_sx)
        check(
            "spreadsheet template 'CRM' sheet has the expected data-validation ranges "
            "(Category/Priority/Sentiment/Requires_Human)",
            actual_dv_sqrefs == EXPECTED_DATA_VALIDATION_SQREFS_CRM,
            f"got {actual_dv_sqrefs!r}",
        )

    processing_sx = sheet_xmls.get("Processing_State")
    if processing_sx is not None:
        actual_dv_sqrefs = get_data_validation_sqrefs(processing_sx)
        check(
            "spreadsheet template 'Processing_State' has the expected data-validation ranges",
            actual_dv_sqrefs == EXPECTED_DATA_VALIDATION_SQREFS_PROCESSING_STATE,
            f"got {actual_dv_sqrefs!r}",
        )
        actual_dv_formulas = get_data_validation_formulas(processing_sx)
        check(
            "spreadsheet template 'Processing_State' validation lists match the runtime contract",
            actual_dv_formulas == EXPECTED_DATA_VALIDATION_FORMULAS_PROCESSING_STATE,
            f"got {actual_dv_formulas!r}",
        )


def read_csv_headers_and_rows(csv_path):
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return (rows[0] if rows else []), rows[1:]


def validate_sample_data():
    if not SAMPLE_FORM_CSV_PATH.exists():
        fail_and_exit("sample_data/form-submissions.csv exists", f"not found: {SAMPLE_FORM_CSV_PATH}")
        return
    if not SAMPLE_CRM_CSV_PATH.exists():
        fail_and_exit("sample_data/crm-records.csv exists", f"not found: {SAMPLE_CRM_CSV_PATH}")
        return

    form_headers, form_rows = read_csv_headers_and_rows(SAMPLE_FORM_CSV_PATH)
    check(
        "sample_data/form-submissions.csv column order matches docs/data-model.md",
        form_headers == FORM_HEADERS,
        f"got {form_headers!r}",
    )
    check("sample_data/form-submissions.csv has at least 1 data row", len(form_rows) >= 1)
    check(
        "sample_data/form-submissions.csv rows all have 5 fields",
        all(len(r) == len(FORM_HEADERS) for r in form_rows),
    )

    crm_headers, crm_rows = read_csv_headers_and_rows(SAMPLE_CRM_CSV_PATH)
    check(
        "sample_data/crm-records.csv column order matches docs/data-model.md",
        crm_headers == CRM_HEADERS,
        f"got {crm_headers!r}",
    )
    check("sample_data/crm-records.csv has at least 1 data row", len(crm_rows) >= 1)
    check(
        "sample_data/crm-records.csv rows all have 15 fields",
        all(len(r) == len(CRM_HEADERS) for r in crm_rows),
    )

    # Every email in the sample CSVs must be @example.com (belt-and-suspenders;
    # also covered by the repo-wide secret scan, but checked here directly
    # against the parsed CSV cells rather than raw text).
    bad_emails = []
    email_col_form = FORM_HEADERS.index("Email")
    email_col_crm = CRM_HEADERS.index("Email")
    for r in form_rows:
        val = r[email_col_form]
        if val and "@" in val and not val.lower().endswith("@example.com"):
            bad_emails.append(("form-submissions.csv", val))
    for r in crm_rows:
        val = r[email_col_crm]
        if val and "@" in val and not val.lower().endswith("@example.com"):
            bad_emails.append(("crm-records.csv", val))
    check(
        "sample CSV email columns are all @example.com or clearly non-address test values",
        len(bad_emails) == 0,
        f"found: {bad_emails}",
    )

    # ID must be a real epoch-millisecond value consistent with Created_At,
    # not just a plausible-looking 13-digit number. docs/data-model.md
    # documents ID as formatDate(now; "x") -- epoch ms -- so a sample row's
    # ID should equal its own Created_At interpreted as a timestamp.
    id_idx = CRM_HEADERS.index("ID")
    created_idx = CRM_HEADERS.index("Created_At")
    # 2000-01-01 .. 2100-01-01 in epoch ms: a generous sanity bound, not a
    # tight one -- just enough to reject obviously-wrong values (e.g. a
    # plain row counter) while not hardcoding "this year" and rotting.
    EPOCH_MS_MIN, EPOCH_MS_MAX = 946684800000, 4102444800000
    tz = ZoneInfo("Asia/Tbilisi")
    id_format_ok = True
    id_range_ok = True
    id_matches_created_at = True
    mismatches = []
    for r in crm_rows:
        id_val = r[id_idx]
        created_val = r[created_idx]
        if not id_val.isdigit():
            id_format_ok = False
            continue
        id_ms = int(id_val)
        if not (EPOCH_MS_MIN <= id_ms <= EPOCH_MS_MAX):
            id_range_ok = False
            continue
        try:
            dt = datetime.strptime(created_val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        except ValueError:
            id_matches_created_at = False
            mismatches.append((id_val, created_val, "unparseable Created_At"))
            continue
        expected_ms = int(dt.timestamp() * 1000)
        # Created_At has only second precision in this CSV, so an exact
        # match is expected; a small tolerance (<1s) is allowed in case a
        # future edit adds sub-second precision without updating this check.
        if abs(expected_ms - id_ms) > 999:
            id_matches_created_at = False
            mismatches.append((id_val, created_val, f"expected ~{expected_ms}"))

    check("sample_data/crm-records.csv ID column is all-integer", id_format_ok)
    check(
        "sample_data/crm-records.csv ID values are plausible epoch-millisecond timestamps",
        id_range_ok,
    )
    check(
        "sample_data/crm-records.csv ID matches Created_At interpreted as Asia/Tbilisi "
        "(epoch ms, tolerance <1s for Created_At's second-level precision)",
        id_matches_created_at,
        f"mismatches: {mismatches}",
    )


def validate_google_form_reference():
    if not FORM_SPEC_PATH.exists():
        fail_and_exit("forms/google-form-spec.json exists", f"not found: {FORM_SPEC_PATH}")
        return
    if not FORM_SCRIPT_PATH.exists():
        fail_and_exit("forms/create-google-form.gs exists", f"not found: {FORM_SCRIPT_PATH}")
        return

    try:
        spec = json.loads(FORM_SPEC_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail_and_exit("Google Form spec is valid JSON", str(e))
        return
    check("Google Form spec is valid JSON", True)

    expected_titles = ["Name", "Email", "Subject", "Message"]
    questions = spec.get("questions", [])
    actual_titles = [question.get("title") for question in questions]
    check(
        "Google Form has exactly the four contract questions in order",
        actual_titles == expected_titles,
        f"got {actual_titles!r}",
    )
    check(
        "every Google Form question is required",
        len(questions) == 4 and all(question.get("required") is True for question in questions),
    )
    check(
        "Google Form response headers match the Form sheet contract",
        spec.get("response_sheet_contract", {}).get("headers") == FORM_HEADERS,
    )
    check(
        "Google Form response sheet name is Form",
        spec.get("response_sheet_contract", {}).get("sheet_name") == "Form",
    )
    settings = spec.get("settings", {})
    check(
        "Google Form does not collect a second automatic email field",
        settings.get("collect_email_automatically") is False,
    )
    expected_lengths = {"Name": 100, "Subject": 150, "Message": 5000}
    actual_lengths = {
        question.get("title"): question.get("max_length")
        for question in questions
        if "max_length" in question
    }
    check(
        "Google Form text limits match the public contract",
        actual_lengths == expected_lengths,
        f"got {actual_lengths!r}",
    )
    email_question = next((q for q in questions if q.get("title") == "Email"), {})
    check("Google Form Email question uses email validation", email_question.get("type") == "email")

    script = FORM_SCRIPT_PATH.read_text(encoding="utf-8")
    script_titles = re.findall(r"\.setTitle\('([^']+)'\)", script)
    check(
        "Apps Script creates questions in the contract order",
        script_titles == expected_titles,
        f"got {script_titles!r}",
    )
    check("Apps Script explicitly disables automatic email collection", ".setCollectEmail(false)" in script)
    check("Apps Script includes email-address validation", ".requireTextIsEmail()" in script)
    check(
        "Apps Script does not auto-link a response destination",
        ".setDestination(" not in script,
    )


def validate_phase2b_candidate_if_present():
    if not PHASE2B_CANDIDATE_PATH.exists():
        check("phase2b candidate blueprint exists", False)
        return

    raw = PHASE2B_CANDIDATE_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        fail_and_exit("phase2b candidate blueprint is valid JSON", str(e))
        return
    check("phase2b candidate blueprint is valid JSON", True)
    scan_text_for_secrets(raw, "make/blueprints/gmail-support-assistant.phase2b.candidate.json")
    check(
        "phase2b candidate has the public scenario name",
        data.get("name") == "Gmail Support Assistant - Phase 2B Candidate",
        f"got {data.get('name')!r}",
    )

    modules = []

    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get("id"), int) and isinstance(value.get("module"), str):
                modules.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(data)
    by_id = {module["id"]: module for module in modules}
    expected_ids = [2, 3, 4, 5, 6, 8, *range(10, 76)]
    check("phase2b candidate has exactly 72 modules", len(modules) == 72, f"got {len(modules)}")
    check(
        "phase2b candidate module IDs match the live-verified export",
        sorted(by_id) == expected_ids,
        f"got {sorted(by_id)}",
    )

    expected_types = Counter({
        "google-sheets:updateRow": 22,
        "util:SetVariables": 12,
        "google-sheets:getSheetContent": 12,
        "builtin:BasicRouter": 8,
        "builtin:Commit": 7,
        "slack:CreateMessage": 3,
        "google-sheets:addRow": 2,
        "google-email:createADraft": 2,
        "google-sheets:watchRows": 1,
        "google-sheets:filterRows": 1,
        "builtin:BasicAggregator": 1,
        "openai-gpt-3:createModelResponse": 1,
    })
    actual_types = Counter(module["module"] for module in modules)
    check(
        "phase2b candidate module-type counts match the live-verified export",
        actual_types == expected_types,
        f"got {dict(actual_types)}",
    )

    check(
        "phase2b trigger limit remains 10",
        by_id.get(2, {}).get("parameters", {}).get("limit") == 10,
    )
    gmail_modules = [m for m in modules if m["module"].startswith("google-email:")]
    check(
        "phase2b Gmail integration is draft-only",
        len(gmail_modules) == 2
        and all(m["module"] == "google-email:createADraft" for m in gmail_modules),
    )

    openai = by_id.get(3, {}).get("mapper", {})
    check("phase2b OpenAI module has store: false", openai.get("store") is False)
    check(
        "phase2b OpenAI module has createConversation: false",
        openai.get("createConversation") is False,
    )
    check(
        "phase2b OpenAI input does not reference the email column",
        "{{2.`2`}}" not in openai.get("input", ""),
    )
    try:
        candidate_schema = json.loads(openai.get("format", {}).get("schema", ""))
    except json.JSONDecodeError:
        candidate_schema = None
    canonical_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    check(
        "phase2b OpenAI schema matches prompts/response-schema.json",
        candidate_schema == canonical_schema,
    )

    connection_ids = {
        module.get("parameters", {}).get("__IMTCONN__")
        for module in modules
        if "__IMTCONN__" in module.get("parameters", {})
    }
    check(
        "phase2b connection IDs use only public placeholders",
        connection_ids == {100000001, 100000002, 100000003, 100000004},
        f"got {connection_ids}",
    )
    connection_labels = set()

    def collect_connection_labels(value):
        if isinstance(value, dict):
            restored = value.get("__IMTCONN__")
            if isinstance(restored, dict) and isinstance(restored.get("label"), str):
                connection_labels.add(restored["label"])
            for child in value.values():
                collect_connection_labels(child)
        elif isinstance(value, list):
            for child in value:
                collect_connection_labels(child)

    collect_connection_labels(data)
    check(
        "phase2b connection labels use only public placeholders",
        connection_labels == {
            "Google Sheets Connection (reconnect required)",
            "OpenAI Connection (reconnect required)",
            "Slack Connection (reconnect required)",
            "Gmail Connection (reconnect required)",
        },
        f"got {connection_labels}",
    )
    spreadsheet_values = SPREADSHEET_ID_FIELD_RE.findall(raw)
    check(
        "phase2b spreadsheetId values are public placeholders",
        bool(spreadsheet_values)
        and all(all(part.startswith("YOUR_") for part in value.split("/") if part)
                for value in spreadsheet_values),
    )
    check(
        "phase2b Slack channel uses a public placeholder",
        all(m.get("mapper", {}).get("channel") == "YOUR_SLACK_CHANNEL_ID"
            for m in modules if m["module"] == "slack:CreateMessage"),
    )

    filter_names = {
        module.get("filter", {}).get("name")
        for module in modules
        if isinstance(module.get("filter"), dict)
    }
    verified_filters = {
        "PHASE2_FINALIZE_REFETCH_SKIP_AFTER_GMAIL_IDENTIFIED",
        "PHASE2_COMPLETE_SKIP_PATH_IDENTIFIED",
        "PHASE2_STATUS_TERMINAL_STOPPED",
    }
    blocked_filters = {
        "INVALID_INPUT_FALLBACK_BLOCKED",
        "PHASE2_VALIDATION_NOTIFY_BLOCK",
        "PHASE2_REFETCH_ABNORMAL_AI_PATH_BLOCK",
        "PHASE2_REFETCH_ABNORMAL_SKIP_PATH_BLOCK",
        "PHASE2_REQUEST_ID_MULTIPLE_MATCHES_BLOCKED",
        "PHASE2_STATUS_RETRYABLE_PROCEED_BLOCKED",
    }
    check("phase2b verified-route filters are present", verified_filters <= filter_names)
    check("phase2b intentionally blocked filters are present", blocked_filters <= filter_names)

    gate_conditions = by_id.get(68, {}).get("filter", {}).get("conditions", [])
    zero_match_branch = gate_conditions[0] if gate_conditions else None
    check(
        "phase2b zero-match Request ID gate uses the live-verified missing-value test",
        zero_match_branch == [{
            "a": '{{first(map(66.array; "0"))}}',
            "o": "notexist",
        }],
        f"got {zero_match_branch!r}",
    )


def validate_phase2b_docs_consistency():
    """Static, text-level regression checks over the Phase 2B design docs.

    These confirm specific required statements/column names are present in
    the relevant Markdown files -- not that the design itself is correct
    (that's a human judgment call, reviewed separately), only that a future
    edit can't silently drop one of these requirements from one file while
    leaving it in another, or remove a fix this project already made once.
    """
    doc_paths = {
        "docs/error-handling-and-idempotency.md": ERROR_HANDLING_DOC_PATH,
        "make/phase2b-deployment-checklist.md": PHASE2B_CHECKLIST_PATH,
        "docs/data-model.md": DATA_MODEL_DOC_PATH,
    }
    for label, path in doc_paths.items():
        if not path.exists():
            check(f"{label} exists", False, "file not found")
            return

    eh_raw = ERROR_HANDLING_DOC_PATH.read_text(encoding="utf-8")
    checklist_raw = PHASE2B_CHECKLIST_PATH.read_text(encoding="utf-8")
    data_model = DATA_MODEL_DOC_PATH.read_text(encoding="utf-8")

    # Phrase checks below match against whitespace-normalized text (line
    # wraps collapsed to single spaces) so that a Markdown line-wrap edit
    # can't spuriously break a check looking for a short, exact phrase that
    # happens to span two source lines. Column-name and other single-token
    # checks use the raw text -- normalization doesn't matter for those.
    def _norm(s):
        return re.sub(r"\s+", " ", s)

    eh = _norm(eh_raw)
    checklist = _norm(checklist_raw)

    # 1 & 2. Processing_State column list -- including AI_Completed and the
    # seven AI_* output columns -- is consistent across every doc that
    # enumerates it.
    for label, text in [
        ("docs/error-handling-and-idempotency.md", eh),
        ("make/phase2b-deployment-checklist.md", checklist),
        ("docs/data-model.md", data_model),
    ]:
        missing_cols = [c for c in PROCESSING_STATE_COLUMNS if c not in text]
        check(
            f"{label} mentions every Processing_State column, including "
            "AI_Completed and the AI_* output columns",
            not missing_cols,
            f"missing: {missing_cols}",
        )

    # 3. Downstream steps (CRM/Slack/Gmail) don't run until OpenAI's output
    # has actually been persisted to Processing_State -- not just called.
    check(
        "error-handling doc states AI output is persisted before any "
        "downstream side effect",
        "before any downstream side effect" in eh and "AI_Completed = true" in eh,
    )
    check(
        "checklist states CRM/Slack/Gmail must wait for the AI_Completed "
        "write to complete, not just a successful OpenAI call",
        "Do **not** proceed to `[3]`/`[4]`/`[5]` until the write of" in checklist,
    )

    # 4. An explicit transition to PROCESSING exists (earlier drafts only
    # ever checked for this state, never set it).
    check(
        "error-handling doc documents an explicit transition to PROCESSING "
        "for both a new row and a retry",
        "New-record transition to `PROCESSING`" in eh
        and "Retry transition to `PROCESSING`" in eh,
    )
    check(
        "checklist states Status is set to PROCESSING before OpenAI runs",
        "Processing_State.Status = PROCESSING" in checklist,
    )

    # 5. Attempt_Count increments exactly once per attempt (earlier drafts
    # left this ambiguous, risking a double-increment per failed attempt).
    check(
        "error-handling doc states Attempt_Count increments exactly once "
        "per attempt",
        "exactly once per attempt" in eh,
    )
    check(
        "checklist states Attempt_Count is incremented only at the "
        "PROCESSING transition, not again on failure",
        "This is the only point where" in checklist
        and "Attempt_Count` is incremented" in checklist,
    )

    # 6. OpenAI failures are part of the state machine, not just an
    # afterthought behind CRM/Slack/Gmail failures.
    check(
        "error-handling doc has a dedicated OpenAI failure handling section",
        "### OpenAI failure handling" in eh,
    )
    check(
        "checklist has a dedicated OpenAI error handling section",
        "### OpenAI error handling" in checklist,
    )

    # 7. A retry with AI_Completed already true skips OpenAI entirely.
    check(
        "error-handling doc states OpenAI is not called again once "
        "AI_Completed is true",
        "skip `[2]` entirely" in eh,
    )
    check(
        "checklist states a retry does not call OpenAI again once "
        "AI_Completed is true",
        "do not call `[2]` again" in checklist,
    )

    # 8. Gmail (and CRM/Slack) read the persisted AI_* columns, not [3]'s
    # live {{3.result...}} output -- this is the actual fix for the
    # Gmail-only-retry-can't-reuse-AI-output problem.
    check(
        "error-handling doc states downstream steps use the persisted "
        "AI_* columns, not {{3.result...}} directly",
        "never from `[2]`'s own `{{3.result...}}`" in eh,
    )
    check(
        "checklist states Gmail reads AI_Reply_Subject/AI_Reply_Body back "
        "from Processing_State, not {{3.result...}}",
        "not `{{3.result.reply_subject}}`" in checklist,
    )

    # 9. Shared Gmail connection credentials/permissions must never be
    # modified to induce a test failure.
    for label, text in [
        ("docs/error-handling-and-idempotency.md", eh),
        ("make/phase2b-deployment-checklist.md", checklist),
    ]:
        check(
            f"{label} prohibits modifying a shared Gmail connection's "
            "credentials/permissions",
            "Do not revoke, expire, disconnect, reauthorize" in text
            or "Never modify credentials/permissions on a Gmail connection" in text,
        )

    # 10. The reserved/example-domain ("Method B") Gmail-failure-injection
    # method is not offered as a usable option. The error-handling doc is
    # allowed exactly one historical mention (explaining why it was
    # rejected); the checklist must not mention it at all.
    check(
        "checklist does not offer the reserved/example-domain "
        "(\"Method B\") Gmail-failure-injection method",
        "Method B" not in checklist,
    )
    check(
        "error-handling doc only mentions the removed reserved/"
        "example-domain method historically, as something rejected -- "
        "not as a usable option",
        eh.count("Method B") <= 1 and "fallback has been removed" in eh,
    )

    # 11. Test B has an explicit stop condition, and "not verified" is the
    # documented outcome, when no dedicated Gmail test connection exists.
    check(
        "error-handling doc has a stop-condition section for when no "
        "dedicated Gmail test connection is available",
        "If no dedicated connection is available" in eh,
    )
    check(
        "checklist has an explicit Test B stop condition recording it as "
        "not verified rather than substituting another method",
        "Stop condition" in checklist and "not verified" in checklist,
    )

    # --- Re-fetch-before-downstream-mapping fix (second design-review pass) ---
    # The pre-Router gate lookup is a Make module output snapshot, captured
    # before OpenAI's output is saved -- it does not update itself when a
    # later module in the same execution writes to the same row. CRM/Slack/
    # Gmail must instead read a freshly re-fetched Processing_State row,
    # fetched immediately before they run, on every attempt.

    # 12. A dedicated, explicit re-fetch step (distinct from the gate lookup)
    # is documented as happening after the AI output save.
    check(
        "error-handling doc documents an explicit re-fetch of the latest "
        "Processing_State row before downstream steps",
        "Re-fetching the latest `Processing_State` row before downstream "
        "steps" in eh,
    )
    check(
        "checklist documents the same mandatory re-fetch step",
        "re-fetch `Processing_State` before" in checklist,
    )

    # 13. The pre-Router gate lookup is explicitly documented as never being
    # reused for downstream mapping.
    check(
        "error-handling doc states the pre-Router gate lookup must never be "
        "used as the downstream mapping source",
        "must never be used as the mapping source for `[3]`, `[4]`, or "
        "`[5]`" in eh,
    )
    check(
        "checklist states the gate lookup's output is for the gate only, "
        "never a downstream mapping source",
        "is for the gate only" in checklist,
    )

    # 14. The re-fetched row -- not the gate lookup, not {{3.result...}} --
    # is documented as the sole state-reference source for CRM/Slack/Gmail.
    check(
        "error-handling doc states the re-fetched row is the only source "
        "CRM/Slack/Gmail read from",
        "is the **only** source `[3]`, `[4]`, and `[5]` read" in eh,
    )
    check(
        "checklist states only the re-fetched row is used for the rest of "
        "the execution",
        "**only** this re-fetched row" in checklist,
    )

    # 15. Zero-row and multiple-row re-fetch results have a documented stop
    # condition (must not proceed to CRM/Slack/Gmail).
    check(
        "error-handling doc has stop conditions for zero-row and "
        "multiple-row re-fetch results",
        "Zero rows found:" in eh and "Multiple rows found:" in eh,
    )
    check(
        "checklist has stop conditions for zero-row and multiple-row "
        "re-fetch results",
        "Zero rows returned:" in checklist and "Multiple rows returned:" in checklist,
    )

    # 16. AI_Completed = true and all seven AI_* output columns are checked
    # as part of validating the re-fetched row (not just at save time).
    check(
        "error-handling doc's re-fetch validation checks AI_Completed and "
        "all seven AI_* columns",
        "AI_Completed = true" in eh and "All seven `AI_*` columns have a value" in eh,
    )
    check(
        "checklist's re-fetch validation checks AI_Completed and all seven "
        "AI_* columns",
        "AI_Completed = true" in checklist
        and "All seven `AI_*` columns have a value" in checklist,
    )

    # 17. Using the update module's own output instead of a separate
    # re-fetch is documented as requiring live verification first, not as
    # the default.
    check(
        "error-handling doc states the update-module-output shortcut is "
        "only acceptable once live-verified",
        "only acceptable once ChatGPT Work has confirmed, live" in eh,
    )
    check(
        "checklist states the update-module-output shortcut requires live "
        "confirmation of all 4 conditions, and is not the default",
        "requires live confirmation of 4 conditions" in checklist,
    )

    # 18. The re-fetch is documented as happening on every attempt -- first
    # run and retry alike -- not just on a retry.
    check(
        "error-handling doc states the re-fetch happens on every attempt, "
        "first run and retry alike",
        "first run and retry alike" in eh,
    )
    check(
        "checklist states the re-fetch step is required on every attempt",
        "required on every attempt" in checklist,
    )


def validate_public_visuals():
    for label, path, expected_viewbox in [
        ("architecture visual", ARCHITECTURE_SVG_PATH, "0 0 1440 720"),
        ("synthetic demo visual", DEMO_SVG_PATH, "0 0 1440 810"),
    ]:
        if not path.exists():
            check(f"{label} exists", False, f"not found: {path}")
            continue
        check(f"{label} exists", True)
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8"))
        except ET.ParseError as e:
            check(f"{label} is valid SVG XML", False, str(e))
            continue
        check(
            f"{label} is valid SVG XML with the expected canvas",
            root.tag == "{http://www.w3.org/2000/svg}svg"
            and root.get("viewBox") == expected_viewbox,
        )


results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


def fail_and_exit(name, detail):
    check(name, False, detail)
    print_report()
    sys.exit(1)


def print_report():
    print("=" * 70)
    ok_count = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        line = f"[{status}] {name}"
        if detail and not ok:
            line += f" — {detail}"
        print(line)
    print("=" * 70)
    print(f"{ok_count}/{len(results)} checks passed")


def validate_blueprint_and_prompt(data, raw):
    flow = data.get("flow", [])
    check("module count is 5", len(flow) == 5, f"got {len(flow)}")

    actual_order = [(m.get("id"), m.get("module")) for m in flow]
    check(
        "module IDs and order are 2, 3, 4, 6, 5",
        actual_order == EXPECTED_MODULE_ORDER,
        f"got {actual_order}",
    )

    modules_by_id = {m.get("id"): m for m in flow}
    gmail_mod = modules_by_id.get(5, {})
    check(
        "Gmail module is google-email:createADraft",
        gmail_mod.get("module") == "google-email:createADraft",
        f"got {gmail_mod.get('module')!r}",
    )

    openai_mod = modules_by_id.get(3, {})
    openai_mapper = openai_mod.get("mapper", {})
    openai_input = openai_mapper.get("input", "")

    check(
        "OpenAI input does not reference the email column ({{2.`2`}})",
        "{{2.`2`}}" not in openai_input,
    )

    check(
        "OpenAI module has store: false",
        openai_mapper.get("store") is False,
        f"got {openai_mapper.get('store')!r}",
    )
    check(
        "OpenAI module has createConversation: false",
        openai_mapper.get("createConversation") is False,
        f"got {openai_mapper.get('createConversation')!r}",
    )

    # --- schema comparison: blueprint (double-encoded) vs prompts/response-schema.json ---
    if not SCHEMA_PATH.exists():
        fail_and_exit("prompts/response-schema.json exists", f"not found: {SCHEMA_PATH}")
    schema_file_obj = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    schema_string_in_blueprint = openai_mapper.get("format", {}).get("schema", "")
    try:
        schema_blueprint_obj = json.loads(schema_string_in_blueprint)
    except json.JSONDecodeError as e:
        fail_and_exit("blueprint format.schema is valid JSON (double-encoded)", str(e))
        return

    check(
        "blueprint format.schema matches prompts/response-schema.json",
        schema_blueprint_obj == schema_file_obj,
        "parsed objects differ",
    )

    # --- schema content checks (validated against the on-disk schema file) ---
    props = schema_file_obj.get("properties", {})
    for field, expected_values in EXPECTED_ENUMS.items():
        actual_values = props.get(field, {}).get("enum")
        check(
            f"enum for '{field}' matches expected values",
            actual_values == expected_values,
            f"got {actual_values}",
        )

    required_in_schema = schema_file_obj.get("required", [])
    check(
        "all 7 required fields are present in schema 'required'",
        set(required_in_schema) == set(EXPECTED_REQUIRED_FIELDS)
        and len(required_in_schema) == len(EXPECTED_REQUIRED_FIELDS),
        f"got {required_in_schema}",
    )
    check(
        "all 7 fields exist under schema 'properties'",
        set(EXPECTED_REQUIRED_FIELDS).issubset(props.keys()),
        f"got {list(props.keys())}",
    )

    check(
        "schema has additionalProperties: false",
        schema_file_obj.get("additionalProperties") is False,
        f"got {schema_file_obj.get('additionalProperties')!r}",
    )

    # --- fixed maxLength checks (independent of blueprint<->schema-file equality) ---
    for field, expected_max in EXPECTED_MAX_LENGTHS.items():
        actual_max = props.get(field, {}).get("maxLength")
        check(
            f"schema '{field}' has maxLength == {expected_max}",
            actual_max == expected_max,
            f"got {actual_max!r}",
        )

    # --- prompt/blueprint sync (canonical prompt body in the .md vs mapper.input) ---
    if PROMPT_MD_PATH.exists():
        md_text = PROMPT_MD_PATH.read_text(encoding="utf-8")
        m = re.search(
            r"## Canonical prompt body \(verbatim\)\n\n.*?\n```text\n(.*?)\n```\n",
            md_text,
            re.S,
        )
        if m:
            canonical_prompt = m.group(1)
            check(
                "prompts/support-triage-v1.md canonical prompt matches blueprint mapper.input",
                canonical_prompt == openai_input,
                "extracted markdown fence differs from blueprint mapper.input",
            )
        else:
            check(
                "prompts/support-triage-v1.md canonical prompt matches blueprint mapper.input",
                False,
                "could not locate 'Canonical prompt body (verbatim)' fenced block in the markdown",
            )
    else:
        check(
            "prompts/support-triage-v1.md canonical prompt matches blueprint mapper.input",
            False,
            f"not found: {PROMPT_MD_PATH}",
        )

    # --- known-path placeholder checks (exact match against Phase 1's public dummy values) ---
    for mid, expected_conn_id in EXPECTED_CONNECTION_IDS.items():
        mod = modules_by_id.get(mid, {})
        actual = mod.get("parameters", {}).get("__IMTCONN__")
        check(
            f"Module {mid} parameters.__IMTCONN__ == {expected_conn_id}",
            actual == expected_conn_id,
            f"got {actual!r}",
        )

    for mid, expected_label in EXPECTED_CONNECTION_LABELS.items():
        mod = modules_by_id.get(mid, {})
        actual = (
            mod.get("metadata", {})
            .get("restore", {})
            .get("parameters", {})
            .get("__IMTCONN__", {})
            .get("label")
        )
        check(
            f"Module {mid} restore.parameters.__IMTCONN__.label == {expected_label!r}",
            actual == expected_label,
            f"got {actual!r}",
        )

    mod2 = modules_by_id.get(2, {})
    actual = mod2.get("parameters", {}).get("spreadsheetId")
    check(
        "Module 2 parameters.spreadsheetId matches public placeholder",
        actual == EXPECTED_SPREADSHEET_ID_PLACEHOLDER,
        f"got {actual!r}",
    )

    mod4 = modules_by_id.get(4, {})
    actual = mod4.get("mapper", {}).get("spreadsheetId")
    check(
        "Module 4 mapper.spreadsheetId matches public placeholder",
        actual == EXPECTED_SPREADSHEET_ID_PLACEHOLDER,
        f"got {actual!r}",
    )

    actual = (
        mod2.get("metadata", {})
        .get("restore", {})
        .get("parameters", {})
        .get("spreadsheetId", {})
        .get("path")
    )
    check(
        "Module 2 restore.parameters.spreadsheetId.path matches public placeholder breadcrumb",
        actual == EXPECTED_DRIVE_BREADCRUMB,
        f"got {actual!r}",
    )

    actual = (
        mod4.get("metadata", {})
        .get("restore", {})
        .get("expect", {})
        .get("spreadsheetId", {})
        .get("path")
    )
    check(
        "Module 4 restore.expect.spreadsheetId.path matches public placeholder breadcrumb",
        actual == EXPECTED_DRIVE_BREADCRUMB,
        f"got {actual!r}",
    )

    mod6 = modules_by_id.get(6, {})
    actual = mod6.get("mapper", {}).get("channel")
    check(
        "Module 6 mapper.channel matches public placeholder",
        actual == EXPECTED_SLACK_CHANNEL_ID,
        f"got {actual!r}",
    )

    actual = (
        mod6.get("metadata", {})
        .get("restore", {})
        .get("expect", {})
        .get("channel", {})
        .get("label")
    )
    check(
        "Module 6 restore.expect.channel.label matches public placeholder",
        actual == EXPECTED_SLACK_CHANNEL_LABEL,
        f"got {actual!r}",
    )

    mod3 = modules_by_id.get(3, {})
    actual = mod3.get("mapper", {}).get("format", {}).get("name")
    check(
        "Module 3 format.name matches public placeholder",
        actual == EXPECTED_OPENAI_SCHEMA_NAME,
        f"got {actual!r}",
    )

    # --- generic secret-shape / pattern scan (no knowledge of original values needed) ---
    check(
        "blueprint contains no '@gmail.com' anywhere",
        "@gmail.com" not in raw.lower(),
    )

    non_example_emails = [
        m for m in EMAIL_RE.findall(raw) if m.split("@")[-1].lower() != "example.com"
    ]
    check(
        "blueprint contains no email address outside example.com",
        len(non_example_emails) == 0,
        f"found: {non_example_emails}",
    )

    check("blueprint contains no OpenAI-API-key-shaped string", not OPENAI_KEY_RE.search(raw))
    check("blueprint contains no Slack-token-shaped string", not SLACK_TOKEN_RE.search(raw))
    check("blueprint contains no GitHub-token-shaped string", not GITHUB_TOKEN_RE.search(raw))
    check("blueprint contains no private key block", not PRIVATE_KEY_BLOCK_RE.search(raw))

    bad_spreadsheet_ids = []
    for value in SPREADSHEET_ID_FIELD_RE.findall(raw):
        segments = [seg for seg in value.split("/") if seg]
        if any(not seg.startswith("YOUR_") for seg in segments):
            bad_spreadsheet_ids.append(value)
    check(
        "every spreadsheetId value is a YOUR_... placeholder",
        len(bad_spreadsheet_ids) == 0,
        f"found: {bad_spreadsheet_ids}",
    )

    bad_breadcrumbs = []
    for a, b in DRIVE_BREADCRUMB_PATH_RE.findall(raw):
        if not a.startswith("YOUR_") or not b.startswith("YOUR_"):
            bad_breadcrumbs.append((a, b))
    check(
        "every Drive folder breadcrumb ('path': [...]) is a YOUR_... placeholder",
        len(bad_breadcrumbs) == 0,
        f"found: {bad_breadcrumbs}",
    )


def validate_prompt_cases():
    if not PROMPT_CASES_PATH.exists():
        fail_and_exit("tests/prompt-cases.jsonl exists", f"not found: {PROMPT_CASES_PATH}")
        return

    lines = [
        line for line in PROMPT_CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    cases = []
    for i, line in enumerate(lines):
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as e:
            fail_and_exit(f"prompt-cases.jsonl line {i + 1} is valid JSON", str(e))
            return

    check("prompt-cases.jsonl has exactly 13 cases", len(cases) == 13, f"got {len(cases)}")

    ids = [c.get("id") for c in cases]
    check("prompt-cases.jsonl case ids are unique", len(ids) == len(set(ids)), f"ids: {ids}")

    # "id"/"description"/"input"/"expected_priority"/"expected_sentiment"/
    # "expected_requires_human"/"must_not_contain"/"notes" are required on
    # every case. Category is required too, but as of the Phase 2A
    # re-review pass, a case may express it either as a single
    # "expected_category" (strict) or as "acceptable_categories" (a list —
    # for adversarial cases like TC13, where live verification showed the
    # model's topic classification can reasonably vary even though the
    # safety-relevant fields stay correct; see tests/README.md).
    required_keys = {
        "id", "description", "input", "expected_priority",
        "expected_sentiment", "expected_requires_human", "must_not_contain", "notes",
    }
    allowed_categories = set(EXPECTED_ENUMS["category"])
    allowed_priorities = set(EXPECTED_ENUMS["priority"])
    allowed_sentiments = set(EXPECTED_ENUMS["sentiment"])

    all_keys_ok = True
    all_input_ok = True
    all_category_ok = True
    all_priority_ok = True
    all_sentiment_ok = True
    all_bool_ok = True
    all_mnc_ok = True

    for c in cases:
        cid = c.get("id", "<missing id>")
        if not required_keys.issubset(c.keys()):
            all_keys_ok = False
            check(f"{cid}: has all required keys", False, f"missing: {required_keys - c.keys()}")

        input_obj = c.get("input", {})
        if not {"name", "subject", "message"}.issubset(
            input_obj.keys() if isinstance(input_obj, dict) else set()
        ):
            all_input_ok = False
            check(f"{cid}: input has name/subject/message", False, f"got keys: {input_obj}")

        has_expected = "expected_category" in c
        has_acceptable = "acceptable_categories" in c
        if has_expected == has_acceptable:
            # neither present, or both present -- exactly one is expected
            all_category_ok = False
            check(
                f"{cid}: has exactly one of expected_category / acceptable_categories",
                False,
                f"has_expected={has_expected} has_acceptable={has_acceptable}",
            )
        elif has_expected:
            if c.get("expected_category") not in allowed_categories:
                all_category_ok = False
                check(f"{cid}: expected_category is a valid enum value", False, f"got {c.get('expected_category')!r}")
        else:
            acceptable = c.get("acceptable_categories")
            if not (isinstance(acceptable, list) and acceptable and set(acceptable) <= allowed_categories):
                all_category_ok = False
                check(f"{cid}: acceptable_categories is a non-empty list of valid enum values", False, f"got {acceptable!r}")
            safety = c.get("safety_requirements")
            if not (isinstance(safety, list) and len(safety) > 0):
                all_category_ok = False
                check(f"{cid}: has non-empty safety_requirements (required when acceptable_categories is used)", False, f"got {safety!r}")

        if c.get("expected_priority") not in allowed_priorities:
            all_priority_ok = False
            check(f"{cid}: expected_priority is a valid enum value", False, f"got {c.get('expected_priority')!r}")

        if c.get("expected_sentiment") not in allowed_sentiments:
            all_sentiment_ok = False
            check(f"{cid}: expected_sentiment is a valid enum value", False, f"got {c.get('expected_sentiment')!r}")

        if not isinstance(c.get("expected_requires_human"), bool):
            all_bool_ok = False
            check(f"{cid}: expected_requires_human is boolean", False, f"got {c.get('expected_requires_human')!r}")

        mnc = c.get("must_not_contain")
        if not (isinstance(mnc, list) and all(isinstance(x, str) for x in mnc)):
            all_mnc_ok = False
            check(f"{cid}: must_not_contain is a list of strings", False, f"got {mnc!r}")

    check("all cases have the required keys", all_keys_ok)
    check("all cases' input has name/subject/message", all_input_ok)
    check("all cases' category field(s) (expected_category or acceptable_categories) are valid", all_category_ok)
    check("all cases' expected_priority is in the allowed enum", all_priority_ok)
    check("all cases' expected_sentiment is in the allowed enum", all_sentiment_ok)
    check("all cases' expected_requires_human is boolean", all_bool_ok)
    check("all cases' must_not_contain is a list of strings", all_mnc_ok)

    cases_by_id = {c.get("id"): c for c in cases}

    tc08 = next((c for c in cases if str(c.get("id", "")).startswith("TC08")), None)
    check(
        "TC08 (insufficient information) has expected_requires_human == true",
        tc08 is not None and tc08.get("expected_requires_human") is True,
        f"TC08: {tc08.get('expected_requires_human') if tc08 else 'not found'}",
    )

    tc10 = next((c for c in cases if str(c.get("id", "")).startswith("TC10")), None)
    check("TC10 (prompt injection) exists", tc10 is not None)
    if tc10 is not None:
        tc10_mnc = tc10.get("must_not_contain", [])
        check(
            "TC10's must_not_contain does not contain the bare generic word 'システムプロンプト'"
            " (a safe refusal can legitimately contain that word)",
            "システムプロンプト" not in tc10_mnc,
            f"got {tc10_mnc}",
        )

    tc13 = next((c for c in cases if str(c.get("id", "")).startswith("TC13")), None)
    check("TC13 (boundary marker escape attempt) exists", tc13 is not None)
    if tc13 is not None:
        check(
            "TC13 has expected_requires_human == true",
            tc13.get("expected_requires_human") is True,
            f"got {tc13.get('expected_requires_human')!r}",
        )
        tc13_message = tc13.get("input", {}).get("message", "")
        check(
            "TC13's message contains the customer-input end-boundary marker text",
            "---END CUSTOMER INPUT---" in tc13_message,
            "boundary marker string not found in TC13 input.message",
        )
        tc13_acceptable = tc13.get("acceptable_categories")
        check(
            "TC13 uses acceptable_categories (not a single expected_category), per live-verification finding",
            isinstance(tc13_acceptable, list)
            and {"その他", "商品に関する質問"} <= set(tc13_acceptable),
            f"got {tc13_acceptable!r}",
        )
        tc13_safety = tc13.get("safety_requirements", [])
        check(
            "TC13 declares safety_requirements as the mandatory adversarial-case checks",
            isinstance(tc13_safety, list) and len(tc13_safety) >= 4,
            f"got {tc13_safety!r}",
        )
        tc13_mnc = tc13.get("must_not_contain", [])
        check(
            "TC13's must_not_contain does not contain the bare generic word 'システムプロンプト'",
            "システムプロンプト" not in tc13_mnc,
            f"got {tc13_mnc}",
        )


def main():
    # --- load blueprint ---
    if not BLUEPRINT_PATH.exists():
        fail_and_exit("blueprint file exists", f"not found: {BLUEPRINT_PATH}")
    raw = BLUEPRINT_PATH.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        fail_and_exit("blueprint is valid JSON", str(e))
        return
    check("blueprint is valid JSON", True)

    validate_blueprint_and_prompt(data, raw)
    validate_prompt_cases()
    validate_spreadsheet_template()
    validate_sample_data()
    validate_google_form_reference()
    validate_phase2b_candidate_if_present()
    validate_phase2b_docs_consistency()
    validate_public_visuals()
    validate_public_files_secret_scan()

    print_report()
    if not all(ok for _, ok, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
