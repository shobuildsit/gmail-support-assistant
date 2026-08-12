# Reconnection / Mapping Guide

The sanitized blueprint at
[`make/blueprints/gmail-support-assistant.sanitized.json`](blueprints/gmail-support-assistant.sanitized.json)
is derived from a private, working Make.com scenario. All account-specific and
environment-specific values have been replaced with placeholders so the file
can be published safely.

The Phase 2B candidate at
[`make/blueprints/gmail-support-assistant.phase2b.candidate.json`](blueprints/gmail-support-assistant.phase2b.candidate.json)
uses the same four service types but repeats their bindings across more
modules. Its public placeholders are `100000001` (Google Sheets), `100000002`
(OpenAI), `100000003` (Slack), `100000004` (Gmail),
`YOUR_SPREADSHEET_ID`, `YOUR_GOOGLE_DRIVE_FOLDER_ID`, and
`YOUR_SLACK_CHANNEL_ID`. Reconnect every matching module after import; changing
one module does not automatically prove the others were updated.

**This means the sanitized blueprint cannot run as-is** — you must
reconnect accounts and restore real IDs before it does anything. The
good news: import itself, and a full run after reconnection, **has been
verified** on a live Make.com scenario — see
[`docs/runtime-verification.md`](../docs/runtime-verification.md) for
what was specifically checked, and [Not verified](#not-verified) below
for what wasn't.

## What was removed / replaced

| Item | Original | Replaced with |
|---|---|---|
| Google Sheets connection (watch rows) | Make connection ID + label incl. Gmail address | `100000001` / `Google Sheets Connection (reconnect required)` |
| OpenAI connection | Make connection ID + label | `100000002` / `OpenAI Connection (reconnect required)` |
| Google Sheets connection (add row) | Make connection ID + label incl. Gmail address (from an unrelated private scenario name) | `100000003` / `Google Sheets Connection (reconnect required)` |
| Slack connection | Make connection ID + label incl. workspace domain | `100000004` / `Slack Connection (reconnect required)` |
| Gmail connection (create draft) | Make connection ID + label incl. Gmail address | `100000005` / `Gmail Connection (reconnect required)` |
| Google Drive spreadsheet path | Real Drive folder ID + Spreadsheet ID | `/YOUR_DRIVE_FOLDER_ID/YOUR_SPREADSHEET_ID` |
| Google Drive folder breadcrumb (designer UI restore info) | Real folder name / project name | `["YOUR_DRIVE_FOLDER", "YOUR_SUBFOLDER"]` |
| Slack channel ID | Real channel ID | `C000000000` |
| OpenAI structured output schema name | Matched the original private scenario name | `gmail_support_assistant_response` |

Everything else — module order, module types, and the field mapper
expressions on modules other than the OpenAI one (`{{2.\`1\`}}` etc.) —
was left unchanged from the original, per the Phase 1 scope.

**Phase 2A update:** the OpenAI module's prompt (`mapper.input`) and
JSON Schema (`mapper.format.schema`) were *not* left as Phase 1 sanitized
them — they were deliberately changed. See
[What changed in Phase 2A](#what-changed-in-phase-2a-openai-module-only)
below.

## What changed in Phase 2A (OpenAI module only)

Unlike the rest of this document (which describes Phase 1's
secret-removal-only sanitization), the OpenAI module's content was
intentionally modified, not just sanitized. The change is scoped to
module `id=3` (`openai-gpt-3:createModelResponse`) only — no other
module was touched in Phase 2A:

| Field | Before (Phase 1) | After (Phase 2A) |
|---|---|---|
| `mapper.input` | Included a `メールアドレス： {{2.\`2\`}}` line | That line removed; input is now name + subject + message only. Also added an explicit prompt-injection defense section and `---BEGIN/END CUSTOMER INPUT---` boundary markers. |
| `mapper.store` | `true` | `false` |
| `mapper.createConversation` | `true` | `false` |
| `mapper.format.schema` | No `maxLength` constraints | Added `maxLength` on `summary` (200), `reply_subject` (150), `reply_body` (3000); enums and required fields unchanged |

The canonical, documented source for the current prompt and schema is
[`../prompts/support-triage-v1.md`](../prompts/support-triage-v1.md) and
[`../prompts/response-schema.json`](../prompts/response-schema.json) — see
[`../prompts/README.md`](../prompts/README.md) for how they're kept in
sync with this blueprint, and
[`../prompts/CHANGELOG.md`](../prompts/CHANGELOG.md) for the full change
log. `CRM.Email`, the Slack notification text, and the Gmail draft
recipient were **not** changed — they still read `Email` from the
trigger row, not from the OpenAI response.

## Connection count: 4 service types, 5 module connection bindings

The blueprint uses **4 external service types** — Google Sheets, OpenAI,
Slack, and Gmail — but wires up **5 separate module connection
bindings**, because the two Google Sheets modules (`watchRows` and
`addRow`) each carry their own independent placeholder connection ID
(`100000001` and `100000003` in the table above) rather than sharing one.
It's possible Make lets you point both Google Sheets modules at a single
reconnected Google Sheets connection, since they're the same service
type — but that has not been verified against a real Make import, so
treat "5 bindings, possibly reducible to 4 by reuse" as the accurate
description rather than assuming reuse works.

## What you must do after importing

1. **Re-create connections for all 4 service types** in Make (Google
   Sheets, OpenAI, Slack, Gmail) and attach them across the 5 module
   connection bindings described above. The placeholder connection IDs
   will not resolve to anything.
2. **Set the real Spreadsheet ID** on:
   - Module `id=2` (`google-sheets:watchRows`) → `parameters.spreadsheetId`
   - Module `id=4` (`google-sheets:addRow`) → `mapper.spreadsheetId`

   Both currently read `/YOUR_DRIVE_FOLDER_ID/YOUR_SPREADSHEET_ID`.
3. **Set the real Slack channel ID** on module `id=6`
   (`slack:CreateMessage`) → `mapper.channel` (currently `C000000000`).
4. **Confirm sheet names** (`Form`, `CRM`) match your spreadsheet's tab
   names, or update `sheetId` on modules `id=2` and `id=4`. For the Phase 2B
   candidate, also reconnect every state module to `Processing_State`. If you rename
   the spreadsheet itself later, see
   [Spreadsheet renames](#spreadsheet-renames-display-name-vs-spreadsheet-id)
   below.
5. **Review the OpenAI model name** (`gpt-5.4-mini` in the source blueprint)
   against what's available on your OpenAI account/connection at import
   time, since model availability changes over time.

## Spreadsheet renames: display name vs. Spreadsheet ID

Encountered directly during live verification of this project, so it's
worth calling out explicitly: **renaming a Google Sheet in Drive does
not change its Spreadsheet ID**, but Make's module configuration UI can
keep showing the *old* display name in the spreadsheet picker for
modules that were already configured before the rename, even though Make
is still internally referencing the same (unchanged) ID.

If you rename your spreadsheet after initially setting up the scenario:

1. Open `[1] google-sheets:watchRows` (module `id=2`) and re-select the
   spreadsheet from the picker — even though the ID hasn't changed,
   re-selecting it refreshes the display name Make shows you.
2. Do the same for `[3] google-sheets:addRow` (module `id=4`). Both
   Google Sheets modules need this — updating one does not update the
   other.
3. While you're there, re-confirm the `Form` and `CRM` tab names are
   still correctly selected on each module.
4. Save the scenario.
5. Run it once (**Run once**), not by activating it.
6. Check Make's execution **History** and confirm every module shows
   success — don't assume the rename was picked up correctly just
   because the save succeeded.
7. Leave the scenario **Inactive** unless you have explicitly decided to
   activate it — Activating makes it process new Form rows automatically,
   and that decision needs explicit permission, not just "the test
   passed."

This repository's own verification environment went through exactly this
sequence: the underlying spreadsheet kept the same Spreadsheet ID
throughout, but its display name changed from an old private-project
name to a new one, and the Watch Rows / Add a Row modules needed the
spreadsheet reselected before Make's UI reflected the new name. Neither
the old nor the new real spreadsheet name is recorded anywhere in this
repository — the published blueprint's Spreadsheet ID and Drive
breadcrumb remain the `YOUR_...` placeholders described above regardless
of what the real spreadsheet is named in any given deployment.

## Not verified

- ~~Whether Make.com accepts this file for import without manual
  repair~~ — **verified**: the published blueprint does import into a
  live Make.com scenario. See
  [`docs/runtime-verification.md`](../docs/runtime-verification.md).
  What remains unverified is a fresh import on a completely new
  Make/Google/Slack/OpenAI account from scratch (verification so far
  reused an existing, partially-configured environment).
- ~~Whether the OpenAI Structured Outputs `format` block is accepted as-is~~
  — **verified**: the live OpenAI module ran successfully using this
  blueprint's `format` block, for both a normal inquiry and a
  boundary-marker-escape test inquiry.
- ~~Whether Make's OpenAI module accepts the new `maxLength` constraints~~
  — **verified**: the live run succeeded with the `maxLength`-constrained
  schema in place. Whether a Make-specific `strict` flag exists for this
  module version, and whether it should be `true`, remains something
  this repository cannot confirm from the blueprint alone — none has
  been added, to avoid guessing at a Make-specific setting.
- ~~Whether `store: false` / `createConversation: false` are accepted~~ —
  **verified**: the live call ran with both settings as `false`. What
  remains unverified is what OpenAI's platform actually does with that
  setting server-side (retention policy specifics) — see
  [`docs/limitations.md`](../docs/limitations.md).
- **Still not verified:** bulk/concurrent submissions, rate limiting,
  long-term operation, automatic error recovery, and strict
  exactly-once processing. See
  [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md)
  and [`docs/limitations.md`](../docs/limitations.md).

If you test the import yourself, please note the result — this section
should be kept up to date based on actual verification, not assumption.
