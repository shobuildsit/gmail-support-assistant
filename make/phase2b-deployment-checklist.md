# Phase 2B Deployment Checklist (for ChatGPT Work / live Make work)

This checklist records how the Phase 2B candidate was built in a live Make
test scenario and which gates remain. The resulting sanitized export is
[`make/blueprints/gmail-support-assistant.phase2b.candidate.json`](blueprints/gmail-support-assistant.phase2b.candidate.json).
It is not import-and-go production automation: several branches remain
explicitly blocked and fresh-account import is unverified.

## Verification status (2026-08-11)

- Confirmed: valid-input happy path, persisted AI output, CRM/Slack/Gmail
  completion flags, finalization, and terminal replay stopping.
- Confirmed: Gmail draft-only and OpenAI `store: false` /
  `createConversation: false`.
- Not confirmed: invalid-input notification, abnormal zero/multiple re-fetch
  routes, injected failure recovery, concurrency, and fresh-account import.
- The test scenario remained Inactive. The original scenario was not changed.

This checklist applies the design in
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md)
to the **live** Make scenario. Read that document first — this file is
"how," that one is "what and why." **In particular, read
[Idempotency gate](../docs/error-handling-and-idempotency.md#idempotency-gate-runs-before-validation)
before starting section 2 below — the gate runs before the Router, not
after it, which is the main correction from an earlier draft of this
checklist.**

## Before you start

- [ ] Confirm you're working on a **test/cloned scenario**, not the
      scenario end users depend on, until everything below is verified.
- [ ] Confirm the scenario is **Inactive** and stays that way unless you
      have explicit permission to Activate it.
- [ ] Confirm `[1] google-sheets:watchRows` and `[3] google-sheets:addRow`
      both currently point at the spreadsheet you intend to test against
      (re-select it in both modules if you're not sure — a Drive rename
      can leave Make's UI showing a stale display name even though the
      underlying Spreadsheet ID is unchanged). See
      [`make/mapping-guide.md`](mapping-guide.md#spreadsheet-renames-display-name-vs-spreadsheet-id)
      for the full 7-step procedure if you've renamed the spreadsheet
      since this scenario was last configured.
- [ ] Have [`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
      row 1 (a valid inquiry) and row 4 (the deliberately invalid-email
      test row — see [`sample_data/README.md`](../sample_data/README.md))
      available. Row 4 is for **Test A** (input validation) below; the
      original duplicate-risk bug is reproduced and confirmed-fixed by
      **Test B**, which needs a *valid* row plus a safely-induced Gmail
      failure — see [section 6](#6-test) for why these are two separate
      tests, and for why Test B must **not** touch a shared Gmail
      connection.
- [ ] **Identify whether the Gmail connection this test scenario uses is
      shared with anything else** (production scenario, other test
      scenarios). If you're not certain it's dedicated to this test, treat
      it as shared. This matters for Test B — see
      [section 6](#6-test).
- [ ] **Confirm whether a dedicated, test-only Gmail connection is
      available (or can be created) for Test B.** Test B now has only one
      sanctioned method — see
      [section 6](#6-test) — and an explicit **stop condition**: if no
      such connection is available, Test B is not run at all and is
      recorded as **not verified**, rather than substituted with any
      other failure-injection method.

## 1. Add a `Processing_State` sheet

- [ ] In the same spreadsheet as `Form` and `CRM`, add a new tab named
      `Processing_State`.
- [ ] Header row: `Request_ID, Source_Row, Status, Attempt_Count,
      Last_Error, Validation_Error_Notified, AI_Completed, AI_Category,
      AI_Priority, AI_Sentiment, AI_Requires_Human, AI_Summary,
      AI_Reply_Subject, AI_Reply_Body, CRM_Written, Slack_Notified,
      Gmail_Draft_Created, Completed_At` — see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#state-tracking-columns)
      for what each column means. `Request_ID` is the exact matching key;
      `Source_Row` is the human-readable label used in notifications —
      they're different columns on purpose, see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#source_row-a-separate-human-readable-reference-for-notifications).
      `Validation_Error_Notified` is diagnostic only, see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#route-b-invalid-input).
      The eight `AI_*` columns (`AI_Completed` plus a persisted copy of
      each of OpenAI's seven structured-output fields) are new in this
      revision — they exist so a retry that only needs to redo one
      downstream step (most often Gmail) can reuse the same AI output
      already used for any steps that already succeeded, instead of
      calling OpenAI again — see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#ai-output-persistence).
- [ ] New rows are created with the initial values documented at
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#initial-values-for-a-new-processing_state-row)
      (`Status = PENDING`, `Attempt_Count = 0`, all boolean flags
      `false`, all `AI_*` value columns and `Completed_At` blank).

## 2. Compute the Request ID and add the idempotency gate — before the Router

**This runs immediately after the trigger, for every row, before any
valid/invalid split.** An earlier draft of this checklist computed the
Request ID only inside the "valid" route, which meant a rejected invalid
row would recompute from scratch and re-trigger Route B on every rerun —
duplicating both the `Processing_State` row and the error notification.
See
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#idempotency-gate-runs-before-validation)
for the full reasoning.

- [ ] Immediately after `[1] google-sheets:watchRows`, add mapper
      expressions computing:
      - `Request_ID = {{2.__SHEET__}}|{{2.__ROW_NUMBER__}}|{{2.\`0\`}}`
        (sheet + row number + the row's `Timestamp` column — **no PII**).
      - `Source_Row = {{2.__SHEET__}} + " row " + {{2.__ROW_NUMBER__}}`
        (human-readable, used in notifications instead of `Request_ID`).
      See
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#request-id)
      for the full design rationale, why the earlier
      `Timestamp|Email|Subject` draft was rejected, and the
      row-renumbering limitation.
- [ ] The field names `__SHEET__` and `__ROW_NUMBER__` are **confirmed**
      to exist on this trigger module — they're declared in
      `metadata.interface` on module `id=2` in
      [`make/blueprints/gmail-support-assistant.sanitized.json`](blueprints/gmail-support-assistant.sanitized.json).
      What still needs confirming live: whether referencing them needs
      backtick-quoting the way the numeric column fields
      (`` {{2.`0`}} `` etc.) do, or whether `{{2.__ROW_NUMBER__}}` works
      directly as written above.
- [ ] Immediately after that, look up `Request_ID` in `Processing_State`.
      Confirm what Google Sheets module Make offers for a row
      search/lookup (this project's existing blueprint only uses
      `google-sheets:watchRows` and `google-sheets:addRow` — a
      search/lookup module is a different, unverified module type; note
      its exact identifier when you find it — see section 5).
      **This lookup's output is for the gate only** — deciding whether a
      record exists, feeding the gate table below, and providing values
      for creating a new row. **Never map `[3]`/`[4]`/`[5]` from this
      module's output**, even after `[2]`'s output has been saved to
      `Processing_State` later in the same execution — this lookup ran
      before that save happened, so its own output stays a stale
      snapshot for the rest of this execution. See
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#the-pre-router-lookup-is-gate-only-not-a-downstream-data-source)
      and section 4 below (the mandatory re-fetch) for the fix.
- [ ] Implement the gate's branching **before** the Router from section 3:
  - No existing record → create a `Processing_State` row (`Request_ID`,
    `Source_Row`, `Status = PENDING`) → proceed to the Router.
  - `Status = COMPLETED` → stop. Nothing further runs.
  - `Status = FAILED_VALIDATION` → stop. Nothing further runs — this is
    what prevents a duplicate `Processing_State` row *and* a duplicate
    error notification on a rerun of a rejected row.
  - `Status = FAILED_PERMANENT` or `NEEDS_HUMAN` → stop. Needs a human.
  - `Status = PROCESSING` → stop; do not auto-retry (see
    [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#the-processing-state-is-a-deliberate-caution-not-a-solved-problem)).
  - `Status = FAILED_RETRYABLE` → proceed to the Router (this state is
    only reachable after the row already passed validation once).

## 3. Router: split into valid / invalid, only after the gate said "proceed"

- [ ] Add a **Router** after the idempotency gate (section 2), before
      `[2] openai-gpt-3:createModelResponse`. The Router itself sits
      **after** Request ID computation and the gate now, not before.
- [ ] Route A ("valid"): filter condition — `Name`, `Email`, `Subject`,
      `Message` all non-empty, and `Email` matches a minimal
      contains-`@`-and-`.`-with-no-spaces check. Continues to
      [section 4](#4-set-status-processing-persist-ai-output-and-skip-already-completed-steps-route-a)
      below — **not** straight to `[2]` as in earlier drafts of this
      checklist.
- [ ] Route B ("invalid"): the inverse filter. Does **not** call OpenAI,
      CRM, Slack, or Gmail. Instead:
      - **Updates the existing `Processing_State` row** (created by the
        gate in section 2 — do **not** insert a second row) to
        `Status = FAILED_VALIDATION`, with a `Last_Error` describing
        which rule failed (not the raw message body), and
        `Validation_Error_Notified = false`.
      - Sends the minimal, distinct error notification — see
        [error notification content rules](../docs/error-handling-and-idempotency.md#error-notification-content).
      - Updates `Validation_Error_Notified = true` after the
        notification is sent.
      Because the gate in section 2 stops a rerun of an already-
      `FAILED_VALIDATION` row before it ever reaches the Router, Route B
      is structurally only entered once per row — see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#route-b-invalid-input)
      for the residual gap this doesn't close (a failure *during* the
      notify step itself).
- [ ] Confirm in Make's UI exactly what module type/version this
      environment offers for "Router" and "Filter" — record it (see
      section 5).

## 4. Set `Status = PROCESSING`, persist AI output, and skip already-completed steps (Route A)

Full design and rationale:
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#route-a-valid-input)
and
[AI output persistence](../docs/error-handling-and-idempotency.md#ai-output-persistence).
**This section replaces an earlier draft that jumped straight from the
Router to "skip already-completed steps" without ever setting
`Status = PROCESSING` or persisting OpenAI's output** — under that
earlier draft, a Gmail-only retry had nothing to give `[5]` (it reads
`{{3.result.reply_subject}}`/`{{3.result.reply_body}}`, which only exist
if `[2]` ran *in that same execution*), and `Attempt_Count` was
ambiguous about whether it incremented once per attempt or once per
failure.

- [ ] **Immediately upon entering Route A** (both for a brand-new row and
      for a `FAILED_RETRYABLE` retry): set
      `Processing_State.Status = PROCESSING`, then increment
      `Attempt_Count` by exactly `1`. **This is the only point where
      `Attempt_Count` is incremented** — do not increment it again later
      in this same attempt if a step below fails.
- [ ] If `AI_Completed = false`: call
      `[2] openai-gpt-3:createModelResponse`.
  - On success: write its seven output fields to `Processing_State`'s
    `AI_Category`, `AI_Priority`, `AI_Sentiment`, `AI_Requires_Human`,
    `AI_Summary`, `AI_Reply_Subject`, `AI_Reply_Body`, then set
    `AI_Completed = true`.
  - On failure: see [OpenAI error handling](#openai-error-handling)
    below. Stop this execution — do **not** increment `Attempt_Count`
    again.
- [ ] If `AI_Completed = true` (just set, or already `true` from a prior
      attempt): **do not call `[2]` again.**

### Mandatory: re-fetch `Processing_State` before `[3]`/`[4]`/`[5]` — every attempt

**Do not map `[3]`/`[4]`/`[5]` from the section-2 gate lookup, and do not
map them from `[2]`'s own `{{3.result...}}` output.** Full rationale:
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#re-fetching-the-latest-processing_state-row-before-downstream-steps).
**This step is required on every attempt** — a first run right after
saving `[2]`'s output, and a retry where `AI_Completed` was already
`true` before this execution even started. Do not treat a retry as
exempt just because its section-2 gate lookup happens to already show
correct `AI_*` values by coincidence of timing.

- [ ] Add a **new** Google Sheets row search/lookup module call here
      (the same module type identified in section 2, used again — not a
      reference to that earlier module's output), searching
      `Processing_State` for this exact `Request_ID` again.
- [ ] Validate the result before using it:
  - Exactly **one** row is returned.
  - Its `Request_ID` matches this execution's computed value exactly.
  - `AI_Completed = true`.
  - All seven `AI_*` columns have a value.
  - `Status = PROCESSING`.
- [ ] **If validation fails, do not proceed to `[3]`/`[4]`/`[5]`.**
  - **Zero rows returned:** do not write anything to `Processing_State`
    (there's no row to address) — stop this execution and let it surface
    as a Make execution error/failure for a human to notice.
  - **Multiple rows returned:** do not write anything to
    `Processing_State` (which one is authoritative is ambiguous) — stop
    this execution the same way.
  - **Exactly one row, but `AI_Completed`/the `AI_*` columns/`Status`
    don't hold:** this row **can** be addressed safely — set
    `Status = NEEDS_HUMAN` on it, with a short `Last_Error` category
    (never the inquiry text or AI output), and stop. Do not proceed.
  - Full reasoning for this three-way split:
    [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#if-the-re-fetch-is-abnormal-zero-rows-multiple-rows-or-missing-ai-output).
  - **Exactly which Make module/routing produces each of these three
    outcomes, and how to branch on them in Make's UI, is not something
    this checklist guesses at — confirm live and record it below in
    section 5.**
- [ ] From here on, **only** this re-fetched row's `AI_*` values and
      `CRM_Written`/`Slack_Notified`/`Gmail_Draft_Created` flags are used
      for the rest of this execution.

**Possible shortcut — not the default, requires live confirmation of 4
conditions:** if the "update existing row" module used to save `[2]`'s
output (above) turns out to output the full, current, unambiguous
18-column row itself, that output could replace this separate re-fetch.
Do **not** assume this without confirming, live, **all four** of:
(1) the update module outputs all 18 columns, not just the ones it
changed; (2) the `AI_*` values in that output are current, not stale;
(3) the output unambiguously corresponds to this execution's
`Request_ID`; (4) this holds identically on both a first run and a
retry. If any of the four isn't confirmed, use the explicit re-fetch
above. Full reasoning:
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#alternative-using-the-update-modules-own-output-instead-of-a-separate-re-fetch).

### Downstream steps (Route A), using the re-fetched row

- [ ] Before `[3] google-sheets:addRow`: skip if `CRM_Written = true` on
      the **re-fetched** row for this `Request_ID`. Otherwise run it
      using the re-fetched `AI_*` values (plus `Name`/`Email`/
      `Original_Subject`/`Original_Message` from the trigger bundle,
      unchanged from today).
- [ ] Before `[4] slack:CreateMessage`: skip if `Slack_Notified = true`
      on the re-fetched row. Otherwise run it using the re-fetched
      `AI_*` values.
- [ ] Before `[5] google-email:createADraft`: skip if
      `Gmail_Draft_Created = true` on the re-fetched row. Otherwise run
      it using `AI_Reply_Subject`/`AI_Reply_Body` from the **re-fetched**
      row — not `{{3.result.reply_subject}}`/`{{3.result.reply_body}}`,
      and not the section-2 gate lookup. The exact mapper reference for
      reading the re-fetch module's output (its output reference syntax)
      depends on the live Make module used — **confirm live** and record
      it in section 5.
- [ ] After each of `[3]`/`[4]`/`[5]` succeeds, update the corresponding
      `Processing_State` flag to `true` (requires a Google Sheets
      "update existing row" module — again, not present in the existing
      blueprint; confirm its exact identifier, same module as used for
      writing the `AI_*` fields above).
- [ ] After all three flags (`CRM_Written`, `Slack_Notified`,
      `Gmail_Draft_Created`) are `true`, set `Status = COMPLETED` and
      `Completed_At = now`.
- [ ] If `[3]`, `[4]`, or `[5]` fails: set `Status = FAILED_RETRYABLE` (or
      `FAILED_PERMANENT` if the error is structurally unrecoverable, e.g.
      a clearly malformed address rejected outright), and record a short
      `Last_Error` — **not** the full inquiry body. `Attempt_Count` is
      **not** incremented again here (see the first bullet above).

### OpenAI error handling

- [ ] Transient failures (rate limit, timeout, 5xx-class error): set
      `Status = FAILED_RETRYABLE`. `AI_Completed` stays `false`, so the
      next retry calls `[2]` again — see
      [the pre-save retry boundary](../docs/error-handling-and-idempotency.md#the-pre-save-retry-boundary)
      for why this is safe (nothing downstream has run yet).
- [ ] Non-transient failures (auth/config error, or a response that fails
      schema validation against
      [`prompts/response-schema.json`](../prompts/response-schema.json)):
      set `Status = FAILED_PERMANENT` or `NEEDS_HUMAN` — these need a
      human to fix configuration, not an automatic retry.
- [ ] `Last_Error` for an OpenAI failure is a short module name + error
      category (e.g. `"OpenAI: request timed out"`) — never the inquiry
      text, and never partial/malformed AI output.
- [ ] Do **not** proceed to `[3]`/`[4]`/`[5]` until the write of
      `AI_Completed = true` (and the `AI_*` fields) to `Processing_State`
      has itself completed — a successful `[2]` call alone is not
      sufficient. See
      [OpenAI failure handling](../docs/error-handling-and-idempotency.md#openai-failure-handling).

## 5. Confirm and record the real Make module types used

Because none of these module types exist in the current, published
blueprint, write down (for a future session to turn into an accurate
Blueprint) the exact `module` identifier and version Make actually used
for each, once you've built them in the UI:

- [ ] Router
- [ ] Filter (on a route)
- [ ] Google Sheets "search/lookup rows" (or equivalent) — used **twice**
      per execution, as two **separate** module calls with two separate
      outputs, even though it's likely the same module type both times.
      Record both, and note whether their configuration differs at all:
  - The **gate lookup** (section 2), before the Router — gate-decision
    use only, never a downstream mapping source.
  - The **downstream re-fetch** (section 4), immediately before
    `[3]`/`[4]`/`[5]` — the only source those three modules read `AI_*`
    values and completion flags from. Also record: what this module
    returns for zero-row and multiple-row results specifically (e.g. an
    empty bundle, an error, an empty array), since section 4's stop
    conditions branch on exactly that.
- [ ] Google Sheets "update an existing row" (or equivalent) — used for
      every `Processing_State` field write in this checklist (`Status`,
      `Attempt_Count`, the `AI_*` fields, and the `_Written`/`_Notified`/
      `_Created` flags alike; no separate module type per field). Also
      confirm: does this module's own output include the full updated
      row? If so, and if it meets all four conditions in section 4's
      "possible shortcut" note, it may be usable in place of the
      downstream re-fetch above — record what you found either way.
- [ ] Whether you used Make's built-in error-handler routes
      (Break/Resume/Ignore/Rollback) on `[3]`/`[4]`/`[5]` instead of, or
      in addition to, explicit status tracking — and if so, their exact
      JSON shape (export the scenario's blueprint from Make and inspect
      it).
- [ ] ~~Whether the `google-sheets:watchRows` trigger bundle exposes a
      stable per-row identifier~~ — **confirmed**: `__ROW_NUMBER__`,
      `__SPREADSHEET_ID__`, and `__SHEET__` are declared on this module
      (see section 2 above) and are used in the current `Request_ID`
      design. What's still open: the exact mapper syntax for referencing
      them (see section 2), and whether Make offers a UUID-generation
      function as a possible future alternative (see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#request-id)).

## 6. Test

**Test A and Test B use different inputs and check different things —
see
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#testing-strategy-two-distinct-failure-scenarios)
for why an invalid email address is Test A material only, and cannot
also be used to test Test B's partial-success/retry behavior under this
design (it never reaches the Gmail step to fail there — it's rejected
before OpenAI is even called).**

### Test A — input validation, including the rerun case

- [ ] Run once with a normal, valid inquiry (e.g.
      [`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
      row 1). Confirm `Processing_State` shows `COMPLETED`, `AI_Completed
      = true` with all seven `AI_*` fields populated, and all three
      downstream flags (`CRM_Written`, `Slack_Notified`,
      `Gmail_Draft_Created`) `true`. **Also confirm the re-fetch fix
      itself, by inspecting each module's output in Make's execution
      History, not just the final result:**
  - The `[2]`-output-saving update module succeeded.
  - The section-4 re-fetch module ran **after** that save and returned
    exactly one row with `AI_Completed = true` and all seven `AI_*`
    columns populated.
  - `[3]`, `[4]`, and `[5]` are mapped from the **re-fetch module's**
    output.
  - The section-2 gate lookup module's own output (inspect it
    separately) still shows blank `AI_*` values — confirming it was
    never the source `[3]`/`[4]`/`[5]` actually used.
- [ ] Run once with the invalid-email test row (row 4). Confirm:
  - The gate (section 2) finds no prior record, creates one
    `Processing_State` row, and lets it reach the Router.
  - The Router sends it to Route B.
  - OpenAI is **not** called; no `CRM` row is written; no
    customer-inquiry Slack message is sent; no Gmail draft is created.
  - Exactly **one** `Processing_State` row exists for this row's
    `Request_ID`, showing `Status = FAILED_VALIDATION`.
  - Exactly **one** validation-error notification was sent.
- [ ] Run once with an empty-`Name` or empty-`Message` row. Confirm the
      same outcome as above (`FAILED_VALIDATION`, nothing downstream
      runs, one state row, one notification).
- [ ] **Re-run the invalid-email row.** Confirm:
  - The gate finds the existing `FAILED_VALIDATION` record and stops —
    the Router is never reached, so Route B does not run again.
  - `Processing_State` **still has exactly one row** for this
    `Request_ID` — no duplicate was created.
  - **No second validation-error notification was sent.**
  - OpenAI/CRM/normal-Slack/Gmail are still not called.

### Test B — partial success and idempotent retry

**Only one method is sanctioned for inducing the Gmail failure: a
dedicated, test-only Gmail connection.** An earlier draft of this
checklist offered a fallback (temporarily redirecting `[5]`'s recipient
to a reserved/example domain). **That fallback has been removed** — see
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#test-b-partial-success-and-idempotent-retry)
for why: `example.com` is a syntactically valid address, and since `[5]`
only *creates a draft* (never sends), that method would most likely make
`[5]` **succeed**, defeating the test. No other content-independent way
to reliably fail a Gmail draft-creation module has been verified for
this project.

**Do not revoke, expire, disconnect, reauthorize, or otherwise modify
the credentials or permissions of a *shared* Gmail connection** — one
attached to production or to any other scenario. Treat any Gmail
connection as shared unless you created it specifically for this test
and have independently confirmed nothing else uses it.

- [ ] Confirm the test scenario is a **cloned, Inactive** scenario.
- [ ] In Make, confirm the dedicated Gmail connection is not referenced
      by the production scenario or by any other scenario. If you cannot
      confirm this, treat it as shared and do not use it — see the
      **stop condition** below.
- [ ] Export/save a copy of the current scenario blueprint as a backup
      before changing anything.
- [ ] Deliberately disable or disconnect **only** the dedicated test
      connection to reproduce a Gmail-module failure.
- [ ] Run once with a **valid** inquiry (e.g. row 1 again). Confirm via
      Make's execution History:
  - `[2]` (OpenAI) succeeds; `Processing_State.AI_Completed = true` with
    all seven `AI_*` fields populated.
  - `[3]` (CRM) and `[4]` (Slack) succeed; `[5]` (Gmail) fails — a
    module-level failure, not just "the scenario finished with a
    warning."
  - `Processing_State` shows `CRM_Written = true`, `Slack_Notified =
    true`, `Gmail_Draft_Created = false`, `Status = FAILED_RETRYABLE`.
- [ ] Restore the dedicated connection (reconnect/re-enable it).
- [ ] **Verify independently** that the connection is restored (e.g. a
      trivial test action, or checking its status in Make's connections
      list) — don't assume the reconnect worked just because no error was
      shown.
- [ ] Re-run the **same row** (same `Request_ID`). Confirm:
  - `[2]`, `[3]`, and `[4]` are **skipped** — per a **fresh section-2
    gate lookup performed at the top of this retry execution** showing
    `AI_Completed`, `CRM_Written`, and `Slack_Notified` already `true`
    (no repeat OpenAI call, no duplicate CRM row, no duplicate Slack
    message).
  - The section-4 re-fetch runs again on this retry, immediately before
    `[5]` — confirm this in Make's execution History, don't just assume
    it ran because the previous test passed.
  - `[5]` runs, mapped from **that re-fetch's** output
    (`AI_Reply_Subject`/`AI_Reply_Body`), and now succeeds.
  - The Gmail draft's subject/body match what's already in the `CRM` row
    and the Slack message from the first run.
  - `Processing_State` shows `Status = COMPLETED`.
- [ ] Leave the test scenario **Inactive** when finished.

**Stop condition: if no dedicated, confirmed-unshared Gmail connection is
available, do not run Test B.** Do not substitute a fake recipient
address, a reserved domain, or any other unverified failure-injection
method. Record Test B as **not verified** instead — see
[`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#if-no-dedicated-connection-is-available).

### Both

- [ ] Check Make's execution History for every test run above — confirm
      module-level success/failure matches what's expected, not just
      "the scenario finished."

## 7. What must not change

- [ ] `[5]` stays `google-email:createADraft` — never switch it to a
      send-email module.
- [ ] The OpenAI module keeps `store: false` and `createConversation:
      false`.
- [ ] The OpenAI prompt keeps its prompt-injection and boundary-escape
      defenses (see [`prompts/support-triage-v1.md`](../prompts/support-triage-v1.md)).
- [ ] No real Spreadsheet ID, Drive folder ID, connection ID, Slack
      channel ID, or account name gets pasted into any file in this
      public repository. If you export an updated blueprint from Make to
      bring back here, sanitize it the same way
      [`make/mapping-guide.md`](mapping-guide.md) describes for the
      Phase 1/2A blueprint before it's added to this repo.
- [ ] Don't Activate the scenario without explicit permission, and don't
      leave a test scenario running unattended.
- [ ] **Never modify credentials/permissions on a Gmail connection
      shared with production or other scenarios** — see section 6,
      Test B.
- [ ] **Do not use a reserved/example domain (e.g. `example.com`) as a
      way to induce a Gmail-module failure.** It's a syntactically valid
      address, and since `[5]` only creates a *draft* (never sends), this
      would most likely make the module succeed rather than fail — see
      [`docs/error-handling-and-idempotency.md`](../docs/error-handling-and-idempotency.md#test-b-partial-success-and-idempotent-retry).
- [ ] If Test B's dedicated Gmail connection prerequisite isn't met,
      **don't invent a substitute failure-injection method** — record
      Test B as not verified and stop, per the stop condition in
      section 6.

## Candidate publication status

The module types and shapes were observed by building the workflow in Make;
they were not guessed from the five-module baseline. The final saved server
export was sanitized with
[`make/scripts/sanitize_phase2b_blueprint.py`](scripts/sanitize_phase2b_blueprint.py)
and published as the candidate above. Static tests lock its module inventory,
safety invariants, placeholders, and named verified/blocked filters.

Publication does not convert blocked routes into completed features. Before
production use, finish those branches in the Make UI, verify each route in
History, save, and create a fresh sanitized server export.
