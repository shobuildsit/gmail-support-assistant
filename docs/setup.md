# Setup

> **Status:** This guide describes the setup steps implied by the sanitized
> blueprint's structure. The overall import → connect → run flow **has**
> been exercised on a live Make.com scenario (see
> [`docs/runtime-verification.md`](runtime-verification.md)), but that
> verification reused an existing, already-configured account rather than
> following this guide on a completely fresh Make/Google/Slack/OpenAI
> account from scratch. So treat this as a mostly-confirmed starting
> point, not a guide independently verified step-by-step on a clean
> account. Please open an issue or PR with corrections if a step turns
> out to be inaccurate.

## Prerequisites

- A [Make.com](https://www.make.com) account with access to create
  scenarios and connections
- A Google account with:
  - A Google Form created from [`forms/`](../forms/) (or another way to
    populate the `Form` sheet)
  - A Google Sheet with `Form`, `CRM`, and `Processing_State` tabs (see
    [`docs/data-model.md`](data-model.md) for the expected columns)
  - Gmail (for draft creation)
- An OpenAI account with API access and available credit
- A Slack workspace and a channel to receive notifications

## 1. Prepare the Google Sheet

1. Create a spreadsheet with `Form`, `CRM`, and `Processing_State` tabs, or start from
   [`spreadsheet/templates/gmail-support-assistant-template.xlsx`](../spreadsheet/templates/gmail-support-assistant-template.xlsx)
   (header-only, no real data — upload it to Google Drive and open with
   Google Sheets, or import it into an existing spreadsheet).
2. Confirm the header rows match [`docs/data-model.md`](data-model.md)
   (the template already matches; if you're creating tabs manually,
   double-check column order and names).
   The template already includes the Phase 2B `Processing_State` tab with its
   exact 18-column order, filters, frozen header, and input validation.
3. Create and connect the Google Form by following
   [`forms/README.md`](../forms/README.md). Google Forms creates a new response
   tab when linked; it does not write into the template's prebuilt empty
   `Form` tab. Follow the documented rename/checkpoint sequence so Make watches
   the generated response tab named `Form`.
4. Optionally load [`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
   into the `Form` tab and
   [`sample_data/crm-records.csv`](../sample_data/crm-records.csv) into
   the `CRM` tab for test rows — see [`sample_data/README.md`](../sample_data/README.md)
   for what each row is testing and which rows are marked test-only
   (e.g. the deliberately invalid email address case; never submit that
   one against a live scenario expecting it to succeed).

**A note on print/PDF layout:** the template is designed for on-screen
use (frozen header row, autofilter, wrapped long-text columns) — it has
**no print-specific setup** (no forced landscape orientation, no
fit-to-width scaling, no repeated print title row). If you later want to
export this sheet to PDF or print it, expect to configure that yourself;
it hasn't been optimized for it.

## 2. Import the Make blueprint

1. In Make.com, create a new scenario and choose **Import Blueprint**.
2. Choose one Blueprint:
   - Phase 2A learning baseline:
     [`gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json)
   - Phase 2B stateful candidate:
     [`gmail-support-assistant.phase2b.candidate.json`](../make/blueprints/gmail-support-assistant.phase2b.candidate.json)

   Prefer Phase 2B for controlled demonstrations, but read its blocked-route
   limitations before use. The module-number instructions below describe the
   smaller Phase 2A baseline; the Phase 2B candidate requires reconnecting all
   matching service modules and mapping `Processing_State` as well.
3. Follow [`make/mapping-guide.md`](../make/mapping-guide.md) to:
   - Re-create and attach connections for the blueprint's **4 service
     types** (Google Sheets, OpenAI, Slack, Gmail), which the blueprint
     wires up across **5 module connection bindings** — the two Google
     Sheets modules each have their own placeholder connection ID, so
     you'll attach a connection twice for Google Sheets even though it's
     one service type. Whether Make lets you reuse a single Google Sheets
     connection for both modules is not verified — see
     [`make/mapping-guide.md`](../make/mapping-guide.md) for details.
   - Set the real Spreadsheet ID on the two Google Sheets modules
   - Set the real Slack channel ID on the Slack module
   - Confirm the `Form` / `CRM` sheet names match your spreadsheet; for Phase
     2B, also confirm every state module points to `Processing_State`

### If you rename the spreadsheet later

Renaming the Google Sheet in Drive does **not** change its Spreadsheet
ID, but Make's module configuration screens can keep showing the old
display name until you reselect the file. If that happens: open both
`[1] google-sheets:watchRows` and `[3] google-sheets:addRow` and
re-select the spreadsheet from the picker (even though the underlying ID
hasn't changed), reconfirm the `Form` / `CRM` tab names, save, then
**Run once** and check Make's execution History for all modules
succeeding before considering it done. Leave the scenario **Inactive**
throughout unless you have explicit permission to Activate it. See
[`make/mapping-guide.md`](../make/mapping-guide.md#spreadsheet-renames-display-name-vs-spreadsheet-id)
for the full explanation and why this was specifically called out (it
was encountered during live verification of this project).

## 3. Configure the OpenAI connection

- The blueprint's OpenAI module uses the Responses API
  (`createModelResponse`) with a structured-output JSON Schema. Confirm
  the model name configured in the module (`gpt-5.4-mini` in the source
  export) is one your OpenAI account/connection can access — model
  availability and naming change over time, so verify this rather than
  assuming it will still be valid.

## 4. Configure Slack

- Invite the Make Slack connection/bot to the target channel if required
  by your workspace's permission model.

## 5. Test

1. Submit a test inquiry through your Form (use an `example.com` email
   address for testing — never a real customer's; see
   [`sample_data/`](../sample_data/) for ready-made example rows).
2. Confirm a new row appears in `Form`.
3. Run the Make scenario manually (**Run once**), to observe each
   module's output — do **not** switch the scenario to Active/scheduled
   until you've deliberately decided to, since an active scenario will
   process every new Form row automatically, including any further test
   rows.
4. Confirm:
   - A new row was added to `CRM` with classification fields populated
   - A Slack message was posted
   - A **draft** (not a sent email) appeared in the connected Gmail
     account's Drafts folder
5. Check Make's execution **History** for the run. For Phase 2A, confirm all
   five modules succeeded. For Phase 2B, inspect every executed route and
   confirm final state is `COMPLETED`; a green overall run alone is not enough.

This import → connect → Run once → check History flow has been
exercised on a live scenario — see
[`docs/runtime-verification.md`](runtime-verification.md). What that
verification does *not* cover is a fresh setup from scratch, so treat
each step above as something to confirm for your own environment rather
than assume will "just work."

## Notes

- Because Gmail drafts are never sent automatically, testing this
  scenario cannot accidentally email a real customer — but it can still
  post to a real Slack channel and write to a real spreadsheet. Use
  dedicated test resources where possible.
- **Do not test with an intentionally invalid email address unless you
  know what you're checking for.** Phase 2A can duplicate CRM/Slack after a
  partial failure, while Phase 2B's invalid-input/notification route remains
  explicitly blocked and unverified. See
  [`docs/error-handling-and-idempotency.md`](error-handling-and-idempotency.md)
  and
  [`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
  for a clearly-labeled test row that reproduces it deliberately.
- See [`docs/limitations.md`](limitations.md) for known gaps and
  [`SECURITY.md`](../SECURITY.md) for handling of credentials and PII.
