# Sample Data

Two CSVs with `example.com`-only emails and fictional names, for loading
into a test spreadsheet built from
[`spreadsheet/templates/gmail-support-assistant-template.xlsx`](../spreadsheet/templates/gmail-support-assistant-template.xlsx).
No real customer data. Column order matches
[`docs/data-model.md`](../docs/data-model.md) and the spreadsheet
template exactly.

## Files

- **`form-submissions.csv`** — 4 rows matching the `Form` sheet's columns
  (`Timestamp, Name, Email, Subject, Message`).
- **`crm-records.csv`** — 4 rows matching the `CRM` sheet's columns (the
  15 columns documented in
  [`docs/data-model.md`](../docs/data-model.md)), representing what those
  same 4 inquiries would look like *after* processing. Per
  [`docs/data-model.md`](../docs/data-model.md), `ID` is
  `formatDate(now; "x")` — epoch milliseconds — so each row's `ID` is
  computed from its own `Created_At` value interpreted in the
  `Asia/Tbilisi` timezone (not just a 13-digit-looking placeholder
  number); `tests/validate_blueprint.py` checks this consistency
  directly.

## What each row is testing

| # | Scenario | `form-submissions.csv` | `crm-records.csv` |
|---|---|---|---|
| 1 | Normal inquiry | A benign product question | `requires_human: false`, ordinary classification |
| 2 | Refund / human-confirmation-required | A damaged-item refund request | `requires_human: true`, `Priority: 高`, reply does **not** confirm a refund (per the prompt's rules — see [`prompts/support-triage-v1.md`](../prompts/support-triage-v1.md)) |
| 3 | Prompt-injection attempt | A message trying to override instructions and disclose the system prompt | `requires_human: true`, no compliance with the injected instruction, no prompt disclosure |
| 4 | **Invalid email (test-only)** | `Email` is `not-a-valid-email`, and every text field is prefixed `[TEST]` / `[TEST専用]` | Depends which blueprint you're running — see below |

## Row 4 is deliberately test-only — and its expected outcome depends on which blueprint you're testing

Row 4 exists to demonstrate the partial-success/duplicate-risk finding
from Phase 2A live verification (see
[`docs/runtime-verification.md`](../docs/runtime-verification.md)) — but **what
should happen depends on which Blueprint and route maturity you are testing**:

- **Against the current, published blueprint**
  ([`make/blueprints/gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json),
  no input validation): the pipeline does **not** stop early — OpenAI
  classification, the CRM write, and the Slack notification all succeed
  *before* the Gmail draft step fails. That's why `crm-records.csv`'s
  row 4 looks like a normal, complete CRM record — that's what actually
  gets written today, even though the corresponding Gmail draft fails.
  This is **Test A material once Phase 2B is deployed, but today it
  demonstrates the bug itself**, not a fix.
- **Against the Phase 2B candidate** (see
  [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md)
  and [`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)),
  this row is the intended invalid-input test, but the validation fallback and
  notification branches remain explicitly blocked and were not live-verified.
  Do not treat the current candidate as a completed rejection workflow until
  those filters are implemented and tested. The target result remains: no
  OpenAI call, no CRM/Slack/Gmail side effect, and
  `Processing_State.Status = FAILED_VALIDATION`.
- The original duplicate-risk bug (CRM + Slack succeeding, only Gmail
  failing, and a rerun duplicating CRM/Slack) is what **Test B** in
  [`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md#6-test)
  exercises instead — using a *valid* row plus a Gmail failure induced
  through a **dedicated, test-only Gmail connection** confirmed unused by
  anything else (**never** a shared Gmail connection's credentials, and
  **never** a reserved/example domain in the recipient address — see
  [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#test-b-partial-success-and-idempotent-retry)
  for why that method was tried and removed), not this row. If no
  dedicated connection is available, Test B is recorded as not verified
  rather than run with a substitute method.

**Do not submit `form-submissions.csv` row 4 against a live/production
scenario expecting normal behavior**, regardless of which blueprint
version is deployed. Every field in that row is prefixed with `[TEST]`
or `[TEST専用]` specifically so it's never mistaken for a real inquiry
if it ends up somewhere unexpected.

## Loading these into a spreadsheet

- Google Sheets: File → Import → Upload, choose "Insert new sheet(s)" or
  "Replace data at selected cell", pointing at the `Form` or `CRM` tab
  created from the template.
- Excel: Data → From Text/CSV, or just copy/paste the CSV rows under the
  existing header row.

See [`docs/setup.md`](../docs/setup.md) for the full setup walkthrough.
