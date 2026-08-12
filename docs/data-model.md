# Data Model

This describes the spreadsheet structure the automation reads from and
writes to. It was originally derived by inspecting the structure (sheet
names, header row, and cell types) of the private
`Gmail_Support_Assistant.xlsx` workbook — **not** by copying any of its
data. That workbook is excluded from this repository (see
[`.gitignore`](../.gitignore)).

**A public, header-only template implementing this schema now exists:**
[`spreadsheet/templates/gmail-support-assistant-template.xlsx`](../spreadsheet/templates/gmail-support-assistant-template.xlsx).
It was built from scratch against the schema documented below (not
copied from the private workbook), contains **no real customer data**,
and has **only the header row populated** on all three sheets. A block of
rows below the header (currently the first 200) carries pre-applied
formatting — white background, wrap-text on long-text columns, a date/
time number format on timestamp columns — so that content pasted or
typed into them displays correctly (see
[`docs/setup.md`](setup.md) and this template's own validation in
[`tests/validate_blueprint.py`](../tests/validate_blueprint.py)), but
those rows contain no values. Rows beyond that pre-formatted block are
plain, unformatted spreadsheet rows, same as any new row you'd add
yourself.

The workbook has three sheets: **`Form`**, **`CRM`**, and
**`Processing_State`**.

## `Form` sheet

Populated by a Google Form response (or equivalent manual entry). Watched
by the Make scenario's trigger module (`google-sheets:watchRows`).

| Column | Field | Notes |
|---|---|---|
| A | `Timestamp` | Form submission time |
| B | `Name` | Customer name |
| C | `Email` | Customer email address |
| D | `Subject` | Inquiry subject |
| E | `Message` | Inquiry body |

## `CRM` sheet

Written by the automation (`google-sheets:addRow`) once OpenAI has
classified the inquiry and drafted a reply. One row per processed inquiry.

| Column | Field | Source | Notes |
|---|---|---|---|
| A | `ID` | Generated (`formatDate(now; "x")`, i.e. epoch ms) | Provisional ID based on a millisecond timestamp. This does **not** guarantee uniqueness — two rows created in the same millisecond (e.g. concurrent scenario runs) would collide. Switching to a UUID or the Google Form response ID is a candidate for Phase 2; not yet implemented. |
| B | `Date` | Copied from `Form!A` (Timestamp) | |
| C | `Name` | Copied from `Form!B` | |
| D | `Email` | Copied from `Form!C` | |
| E | `Original_Subject` | Copied from `Form!D` | |
| F | `Original_Message` | Copied from `Form!E` | |
| G | `Category` | OpenAI output | One of: `配送トラブル`, `返金依頼`, `商品に関する質問`, `技術的な問題`, `クレーム`, `その他` |
| H | `Priority` | OpenAI output | One of: `高`, `中`, `低` |
| I | `Sentiment` | OpenAI output | One of: `ポジティブ`, `普通`, `ネガティブ` |
| J | `Requires_Human` | OpenAI output | Boolean (`true`/`false`) |
| K | `Summary` | OpenAI output | One-sentence Japanese summary |
| L | `Reply_Subject` | OpenAI output | Draft reply subject |
| M | `Reply_Body` | OpenAI output | Draft reply body |
| N | `Status` | Set to `未対応` (unhandled) on insert | Intended for manual update once a human reviews/sends the reply |
| O | `Created_At` | Generated (`now`) | Row creation timestamp |

## OpenAI structured output schema

The `Category`, `Priority`, `Sentiment`, `Requires_Human`, `Summary`,
`Reply_Subject`, and `Reply_Body` fields above are produced by a single
OpenAI structured-output (JSON Schema) response. As of Phase 2A, the
canonical, versioned copies of the prompt and schema live in
[`prompts/support-triage-v1.md`](../prompts/support-triage-v1.md) and
[`prompts/response-schema.json`](../prompts/response-schema.json) — see
[`prompts/README.md`](../prompts/README.md) for how those stay in sync
with the `mapper.input` / `mapper.format.schema` fields on module `id=3`
in
[`make/blueprints/gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json).

The schema now also constrains max length: `summary` ≤200 characters,
`reply_subject` ≤150, `reply_body` ≤3000.

## AI input vs. downstream fields

**As of Phase 2A**, the OpenAI module's input (`mapper.input` on module
`id=3`) includes only `Name`, `Subject`, and `Message` from the `Form`
row — **not** `Email`. This differs from the `Form` → `CRM` field flow
described above, where `Email` is copied through untouched.

`Email` is still required, and still used, by the modules downstream of
the AI call:

| Module | Uses `Email` for |
|---|---|
| `[3] google-sheets:addRow` | Writing the `CRM.Email` column |
| `[4] slack:CreateMessage` | Including it in the Slack notification text |
| `[5] google-email:createADraft` | Addressing the Gmail draft to the customer |

These three modules read `Email` directly from `[1]`'s row output — not
from the OpenAI response — so removing `Email` from the AI input did not
require (and did not get) any change to the CRM sheet, Slack message
content, or the Gmail draft's recipient. See
[`docs/architecture.md`](architecture.md#phase-2b-data-flow) and
[`SECURITY.md`](../SECURITY.md#third-party-data-exposure-when-this-scenario-runs)
for why this line was drawn here.

## Downstream consumers of `CRM` row data

- **Slack notification** (`slack:CreateMessage`) — formats `Name`, `Email`,
  `Category`, `Priority`, `Sentiment`, `Requires_Human`, `Summary`,
  `Reply_Subject`, and `Reply_Body` into a message to a configured channel.
- **Gmail draft** (`google-email:createADraft`) — creates a draft addressed
  to the customer's `Email`, using `Reply_Subject` and `Reply_Body`. The
  draft is **never sent automatically** — a human must review and send it.

## `Processing_State` (Phase 2B runtime schema)

[`docs/error-handling-and-idempotency.md`](error-handling-and-idempotency.md)
designs a third sheet, `Processing_State` (columns: `Request_ID`,
`Source_Row`, `Status`, `Attempt_Count`, `Last_Error`,
`Validation_Error_Notified`, `AI_Completed`, `AI_Category`,
`AI_Priority`, `AI_Sentiment`, `AI_Requires_Human`, `AI_Summary`,
`AI_Reply_Subject`, `AI_Reply_Body`, `CRM_Written`, `Slack_Notified`,
`Gmail_Draft_Created`, `Completed_At`), to track per-row pipeline state
so a rerun after a partial failure — including a rejected/invalid
submission, not just a downstream success/failure — doesn't repeat
completed side effects (duplicate state rows, duplicate notifications,
duplicate CRM/Slack/Gmail actions). The eight `AI_*` columns exist so a
retry that only needs to redo one downstream step (most often Gmail —
see the [confirmed live finding](error-handling-and-idempotency.md#problem-this-addresses))
can reuse the *same* OpenAI output that any already-succeeded steps were
built from, instead of re-calling OpenAI and risking a different
result — see
[AI output persistence](error-handling-and-idempotency.md#ai-output-persistence).
Downstream steps never read the row-search module that runs before the
Router (that lookup only feeds the idempotency gate) — they read a
row fetched fresh, immediately before they run, on every attempt; see
[Re-fetching the latest Processing_State row before downstream steps](error-handling-and-idempotency.md#re-fetching-the-latest-processing_state-row-before-downstream-steps).

This sheet is implemented by the Phase 2B candidate Blueprint and is included
in
[`spreadsheet/templates/gmail-support-assistant-template.xlsx`](../spreadsheet/templates/gmail-support-assistant-template.xlsx).
The template preformats 200 empty rows, freezes the header, adds filters, and
provides input validation for Status, AI classification, and boolean flag
columns. It contains no processing records or customer data.
