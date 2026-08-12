# Error Handling & Idempotency Design (Phase 2B)

**Status: partially implemented and live-verified.** The main happy path,
persisted-AI retry/skip path, finalization, and terminal duplicate gate are
implemented in
[`make/blueprints/gmail-support-assistant.phase2b.candidate.json`](../make/blueprints/gmail-support-assistant.phase2b.candidate.json).
Some validation and abnormal routes remain explicitly blocked; see
[`docs/runtime-verification.md`](runtime-verification.md). See
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)
for the implementation sequence and remaining gates.

## Problem this addresses

**Confirmed by live verification** — see
[`docs/runtime-verification.md`](runtime-verification.md):

1. `[3] google-sheets:addRow` succeeds — a CRM row is written.
2. `[4] slack:CreateMessage` succeeds — a Slack notification is posted.
3. `[5] google-email:createADraft` fails (e.g. invalid destination email).
4. Re-running the row re-executes `[3]` and `[4]` too, producing a
   **duplicate CRM row and a duplicate Slack notification**.

A secondary, related gap: there is currently **no input validation**
before an inquiry reaches OpenAI/CRM/Slack/Gmail — an empty name, a
malformed email, an empty subject, or an empty message is processed the
same as any valid inquiry today.

**Found by design review, not live-verified** (this design hasn't been
built live yet, so these are logical flaws caught by re-reading the
design, not something observed running):

- An earlier draft of this document computed the Request ID and checked
  prior processing state *inside* the "valid input" route only, **after**
  the Router had already split into Route A (valid) / Route B (invalid).
  Under that ordering, re-running an already-rejected invalid row would
  go through the Router again, land on Route B again, and Route B would
  create *another* `Processing_State` row and send *another* error
  notification — the same class of duplication bug as the CRM/Slack one
  above, just for the validation-rejection path instead of the
  downstream-success path. See
  [Idempotency gate](#idempotency-gate-runs-before-validation) below for
  the fix: the gate now runs **before** the Router, so it applies
  uniformly to both routes.
- **The "retry Gmail only" recovery this document describes cannot
  actually reuse the AI's output, as originally designed.** `[5]
  google-email:createADraft` reads `{{3.result.reply_subject}}` and
  `{{3.result.reply_body}}` directly from `[3]
  openai-gpt-3:createModelResponse`'s own output *within the same
  execution*. If a retry skips `[3]` (because "OpenAI already ran
  successfully last time, no need to call it again" was the original,
  unstated assumption), there is no `{{3.result...}}` to read in *this*
  execution — those references resolve to nothing. If instead the retry
  calls OpenAI again, the model may return a different classification or
  reply text than what was already written to `CRM` and sent to Slack in
  the first attempt, so the Gmail draft could end up describing a
  different reply than the one already on record. Neither option works
  under the design as originally written. See
  [AI output persistence](#ai-output-persistence) below for the fix:
  OpenAI's output is written to `Processing_State` before any downstream
  side effect runs, so a Gmail-only retry reads the *same* stored output
  the CRM row and Slack message were already built from.
- **There was no explicit step that moves `Status` to `PROCESSING`.**
  The [gate outcomes table](#gate-outcomes) already *checks* for
  `Status = PROCESSING` (to avoid auto-retrying a row that might be
  mid-flight), but nothing in the earlier draft ever *set* a row to
  `PROCESSING` in the first place — so that check could never actually
  trigger, and it was also unclear whether `Attempt_Count` was meant to
  be incremented once per attempt or once per failure (which, combined,
  could double-count a single attempt). See
  [Route A](#route-a-valid-input) below for the explicit transition and
  the single-increment rule.
- **Test B's originally-proposed fallback failure-injection method
  (Method B: temporarily pointing the Gmail module's recipient at a
  reserved/example domain) does not reliably fail.** `example.com` is a
  reserved domain, but it is still a *syntactically valid* email address,
  and `[5]` only **creates a Gmail draft** — it does not send anything,
  so there is no delivery/bounce step where an undeliverable domain would
  cause a module-level failure. In practice this method would likely
  make `[5]` **succeed** (a draft addressed to a fake-looking recipient
  gets created just fine), which is the opposite of what Test B needs to
  demonstrate. See [Test B](#test-b-partial-success-and-idempotent-retry)
  below: this method has been removed, not just deprioritized.
- **The AI output persistence fix above is itself incomplete on a first
  run: it saves the data, but nothing was reading the saved data back.**
  The idempotency gate's `Processing_State` lookup happens **once**,
  immediately after the trigger, **before** the Router. That lookup's
  output bundle is what a Make module produces at the moment it runs —
  it is a snapshot, not a live reference, so it does not change later in
  the same execution just because a different module (the `AI_*`-saving
  step) subsequently updates the same spreadsheet row. On a **first run**
  of a new row, the gate's lookup happened *before* `[2]` ever ran, so
  that snapshot's `AI_*` columns are blank — exactly as they should be at
  that moment. If `[3]`/`[4]`/`[5]` were mapped from that same, by-then
  stale snapshot (as an earlier draft of this document ambiguously
  allowed — see the old wording of
  [Design: persist AI output before any downstream side effect](#design-persist-ai-output-before-any-downstream-side-effect)),
  they would see blank `AI_*` values on every first run, even though the
  values were, moments earlier in the same execution, successfully
  written to the sheet. A **retry** happens to work under the old wording
  only because the retry's *own* gate lookup runs in a *new* execution,
  started *after* the previous execution's `AI_*` write already landed —
  so the retry's snapshot is current by coincidence of timing, not by
  design. See
  [Re-fetching the latest Processing_State row before downstream steps](#re-fetching-the-latest-processing_state-row-before-downstream-steps)
  below for the fix: a fresh, explicit re-fetch immediately before
  `[3]`/`[4]`/`[5]` run, on **every** attempt — first run and retry alike
  — so downstream steps never depend on how old a snapshot happens to be.

## Design goals

1. Reject clearly-invalid input **before** it reaches OpenAI, CRM, Slack,
   or Gmail.
2. Make re-running a row after a partial failure — of *any* kind,
   including a validation rejection — **not** repeat side effects
   (`Processing_State` rows, notifications, CRM rows, Slack messages)
   that already happened.
3. Make a retry that only needs to redo **one** downstream step (most
   commonly Gmail, per the [confirmed live finding](#problem-this-addresses))
   able to do so using the **same** AI-generated classification and reply
   text that any already-succeeded steps (CRM, Slack) were built from —
   not by skipping OpenAI and reading nothing, and not by silently
   re-generating different content. See
   [AI output persistence](#ai-output-persistence).
4. Be explicit about what this design does and does not guarantee —
   in particular, it does **not** claim strict exactly-once processing
   under all failure and concurrency conditions. See
   [Concurrency limitations](#concurrency-and-exactly-once-limitations).

## Request ID

Every Form row needs a stable identifier so re-processing can check "has
this row already been seen?" — regardless of whether it turned out to be
valid or invalid — instead of blindly re-running.

### Earlier draft (superseded) and why it was rejected

An earlier version of this design proposed
`Timestamp + "|" + Email + "|" + Subject`. A review pass rejected this
before it reached any live testing or the deployment checklist, for
concrete reasons — not just style:

- It **duplicates personal data (`Email`) into a pipeline-internal
  tracking key**, and that key would then flow into `Processing_State`
  and potentially into error notifications — expanding where a
  customer's email address lives for no real benefit.
- `Subject` is customer-authored text; using it in an identifier means
  the identifier can itself carry inquiry content.
- **It's not actually stable.** If a human corrects a typo in `Email` or
  `Subject` after the row was first seen (e.g. fixing a CRM record by
  hand), the computed `Request_ID` changes, and the row would look like
  a brand-new, never-seen submission on the next check — defeating the
  entire point of having a stable ID.
- Putting this ID in an error notification (as the original design's
  "error notification content" section did) would put the customer's
  email address and subject line into Slack, even though the intent for
  the validation-failure path was to send the *minimum* necessary
  information.

### Current design: positional + immutable-timestamp, no PII

`Request_ID` is built from **trigger metadata**, not customer-entered
content:

```
Request_ID = {{2.__SHEET__}} + "|" + {{2.__ROW_NUMBER__}} + "|" + {{2.`0`}}
```

i.e. **sheet name + row number + the row's `Timestamp` column
(column A)**. This is grounded in what the published, live-verified
blueprint's trigger module actually declares — not a guess: module
`id=2` (`google-sheets:watchRows`)'s `metadata.interface` in
[`make/blueprints/gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json)
explicitly lists `__ROW_NUMBER__` (type `number`, "Row number"),
`__SPREADSHEET_ID__` (type `text`, "Spreadsheet ID"), and `__SHEET__`
(type `text`, "Sheet") as fields this trigger module exposes, alongside
the numbered column fields (`` `0` `` = Timestamp, `` `1` `` = Name,
etc.) already used elsewhere in this same blueprint. **What is
confirmed:** these field names exist on this module. **What is not yet
confirmed:** the exact mapper reference syntax for the double-underscore
fields when actually building this live (e.g. whether `{{2.__ROW_NUMBER__}}`
needs backtick-quoting the way numeric field names like `` `1` `` do) —
confirm this when implementing, per
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md).

`__SPREADSHEET_ID__` is deliberately **not** included in `Request_ID`:
within one deployed scenario there's only ever one spreadsheet, so it
adds no discriminating power, and leaving it out means `Request_ID`
never contains a Spreadsheet ID that could later leak into a
notification.

**Computed once, for every row, before validation.** This is the key
change in this revision: `Request_ID` (and `Source_Row`) are no longer
computed only on the "valid" route — they're computed immediately after
the trigger, for every row regardless of whether it will turn out to be
valid or invalid. See
[Idempotency gate](#idempotency-gate-runs-before-validation).

**Why this satisfies the design requirements:**

- Contains no `Email`, `Name`, `Subject`, or `Message` — no customer
  content at all.
- If a human edits the row's `Email`/`Name`/`Subject`/`Message` after
  the fact, `Request_ID` **does not change** (sheet name, row position,
  and original `Timestamp` are unaffected by editing other columns), so
  the row is still recognized as the same tracked inquiry.
- Safe to put in an error notification as-is (see
  [Error notification content](#error-notification-content)) — no PII
  to redact.

**Known limitation — row renumbering.** `__ROW_NUMBER__` is positional.
If a row above it is deleted, every row below shifts up one position,
changing its `__ROW_NUMBER__`. Two things follow:

1. A row's `Request_ID` **can change** if rows are deleted above it
   between processing attempts — a rerun could then fail to find its own
   prior `Processing_State` entry and be treated as brand-new. This is a
   real gap: the design does not solve it, and the practical mitigation
   is procedural — avoid deleting `Form` rows above unprocessed/pending
   entries, or restrict who can delete rows in that sheet at all.
2. Conversely, if `Request_ID`s were based on row number *alone* (no
   timestamp), a *new* submission that happens to land on a row number
   previously used by a now-deleted row would collide with stale
   `Processing_State` data from the deleted row. Including
   `Timestamp` closes this specific gap: a coincidentally-reused row
   number will almost certainly carry a different `Timestamp`, so the
   composite key won't falsely match the old record.

**Collision conditions, stated plainly:** two different rows would only
produce the same `Request_ID` if they had the same sheet, the same row
number, *and* the same `Timestamp` value (Google Forms timestamps are
typically second-precision) — i.e. effectively only in the row-reuse
scenario just described, and even then only if the coincidence extends
to the timestamp too. This is a materially smaller collision surface
than the rejected `Timestamp+Email+Subject` design, and it fails safe in
the more likely direction (treating a genuinely-new row as new, rather
than silently merging two different customers' inquiries).

**UUID alternative — not adopted, not ruled out.** A generated UUID per
row would sidestep the row-renumbering issue entirely. This isn't used
here because this repository has not confirmed that Make exposes a UUID
-generation function usable in a mapper expression for this scenario —
asserting one exists without checking would be exactly the kind of
guess this project avoids. If
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)
confirms a UUID function is available in the live Make function picker,
switching to it removes the row-renumbering limitation above and would
be a reasonable follow-up revision to this design.

### `Source_Row` — a separate, human-readable reference for notifications

`Processing_State` also gets a `Source_Row` column, distinct from
`Request_ID`:

```
Source_Row = {{2.__SHEET__}} + " row " + {{2.__ROW_NUMBER__}}
```

e.g. `"Form row 42"`. Both `Request_ID` and `Source_Row` are already
PII-free under this design, so the split isn't about hiding anything in
`Request_ID` — it's about keeping the exact machine-matching key
(`Request_ID`, pipe-delimited, used for lookups) separate from the
human-facing label (`Source_Row`, used in notifications and anywhere a
person needs to glance at *which row* without needing to parse a
delimited key). If `Request_ID`'s format ever changes (e.g. adding a
disambiguating suffix), `Source_Row`'s format doesn't have to change
with it.

## Idempotency gate (runs before validation)

This is the central fix in the revision that introduced it. The gate is
**one shared step**, run immediately after the trigger and **before**
the valid/invalid Router — not duplicated per-route, and not skipped for
either route:

```
[1] Google Sheets: Watch Rows
        ↓
Compute Request_ID / Source_Row
        ↓
Look up Request_ID in Processing_State
        ↓
Idempotency gate (decide what happens next, based on existing state)
        ↓
   ┌────┴─────────────────────────────┐
   │ only if the gate says "proceed"  │
   ▼                                  │
Router: is this input valid?          │
   ├── Route A (valid) ───────────────┤
   └── Route B (invalid) ─────────────┘
```

### Gate outcomes

| Existing `Processing_State` for this `Request_ID` | Gate action |
|---|---|
| No record | Create one row with the [initial values below](#initial-values-for-a-new-processing_state-row) (`Status = PENDING`), then proceed to the Router. |
| `COMPLETED` | Stop. Nothing further runs. |
| `FAILED_VALIDATION` | Stop. Nothing further runs — **including no repeat notification** (see [Route B](#route-b-invalid-input) for why a repeat can't happen structurally, not just by convention). |
| `FAILED_PERMANENT` | Stop. Needs a human. |
| `NEEDS_HUMAN` | Stop. Needs a human. |
| `PROCESSING` | Stop. Do not auto-retry — see [The `PROCESSING` state is a deliberate caution](#the-processing-state-is-a-deliberate-caution-not-a-solved-problem). |
| `FAILED_RETRYABLE` | Proceed to the Router. (This state is only reachable after input already passed validation once — see [Processing state machine](#processing-state-machine) — so re-evaluating it on Route A is expected to reach the same "valid" outcome and then resume in [Route A](#route-a-valid-input) at whichever step didn't complete yet — OpenAI included, if `AI_Completed` is still `false`.) |

Because **both** Route A and Route B are only ever reached *after* this
gate has already run and decided "proceed," a row that was already
marked `FAILED_VALIDATION` (or any other terminal state) on a previous
attempt can never re-enter Route B on a rerun — the gate stops it first.
This is what makes "no duplicate `Processing_State` row, no duplicate
notification" a structural property of the design, not something each
route has to separately remember to check.

## Processing state machine

### States

| State | Meaning |
|---|---|
| `PENDING` | Row seen by the trigger, not yet picked up for processing |
| `PROCESSING` | Currently being worked on (validation passed, OpenAI/CRM/Slack/Gmail steps in flight) — see [Route A](#route-a-valid-input) for exactly when a row enters this state |
| `COMPLETED` | All steps (OpenAI, CRM write, Slack notification, Gmail draft) succeeded |
| `FAILED_VALIDATION` | Input validation failed — never reached OpenAI. Terminal — see the gate table above. |
| `FAILED_RETRYABLE` | OpenAI or a downstream step (CRM/Slack/Gmail) failed in a way that a retry might resolve (e.g. a transient API error). Only reachable after validation already passed once. |
| `FAILED_PERMANENT` | OpenAI or a downstream step failed in a way retrying won't fix (e.g. Gmail rejects the address as structurally invalid, or OpenAI reports a configuration error) |
| `NEEDS_HUMAN` | Processing cannot safely continue automatically and a person must intervene — distinct from the AI's own `Requires_Human` classification field on the `CRM` row (see [Don't confuse two different "needs a human" signals](#dont-confuse-two-different-needs-a-human-signals) below) |

### State-tracking columns

Rather than adding pipeline-internal bookkeeping columns to the
customer-facing `CRM` sheet, this design uses a **separate
`Processing_State` sheet** in the same spreadsheet (see
[Data Store vs. spreadsheet](#make-data-store-vs-spreadsheet-based-state-tracking)
for why). One row per Form submission:

| Column | Meaning |
|---|---|
| `Request_ID` | The composite key described above (sheet + row number + timestamp — no PII) |
| `Source_Row` | Human-readable row reference for notifications (e.g. `"Form row 42"`) — see [Request ID](#request-id) |
| `Status` | One of the states above |
| `Attempt_Count` | How many attempts have been made for this row. Incremented **exactly once per attempt**, at the moment `Status` transitions to `PROCESSING` — see [Route A](#route-a-valid-input). Never incremented a second time when that same attempt later fails. |
| `Last_Error` | A short, sanitized description of the most recent failure (module name + error category — not the full inquiry body, and not the AI's output — see [OpenAI failure handling](#openai-failure-handling)) |
| `Validation_Error_Notified` | Boolean — has the validation-error notification for this row been sent? Diagnostic only (see [Route B](#route-b-invalid-input)); the gate's `FAILED_VALIDATION` stop does not depend on this flag's value. |
| `AI_Completed` | Boolean — has `[2] openai-gpt-3:createModelResponse` succeeded for this row **and** have its structured-output fields already been written to the `AI_*` columns below? See [AI output persistence](#ai-output-persistence). |
| `AI_Category` | OpenAI's structured output, persisted — see [AI output persistence](#ai-output-persistence) |
| `AI_Priority` | OpenAI's structured output, persisted |
| `AI_Sentiment` | OpenAI's structured output, persisted |
| `AI_Requires_Human` | OpenAI's structured output, persisted |
| `AI_Summary` | OpenAI's structured output, persisted |
| `AI_Reply_Subject` | OpenAI's structured output, persisted |
| `AI_Reply_Body` | OpenAI's structured output, persisted |
| `CRM_Written` | Boolean — has `[3] google-sheets:addRow` succeeded for this row? |
| `Slack_Notified` | Boolean — has `[4] slack:CreateMessage` succeeded for this row? |
| `Gmail_Draft_Created` | Boolean — has `[5] google-email:createADraft` succeeded for this row? |
| `Completed_At` | Timestamp when `Status` became `COMPLETED` (blank until then) |

The seven `AI_*` columns are a straightforward, field-by-field copy of
the same structured-output shape already defined in
[`prompts/response-schema.json`](../prompts/response-schema.json) — this
is not a second, independent schema to keep in sync; it's the same seven
fields (`category`, `priority`, `sentiment`, `requires_human`, `summary`,
`reply_subject`, `reply_body`) that already flow into the `CRM` sheet
today, just also written one step earlier, to `Processing_State`, before
`CRM`/Slack/Gmail consume them. See
[AI output persistence](#ai-output-persistence) for why.

### Initial values for a new `Processing_State` row

When the [gate](#gate-outcomes) creates a row because it found no
existing record for a `Request_ID`, the row is created with:

| Column | Initial value |
|---|---|
| `Request_ID`, `Source_Row` | Computed as described in [Request ID](#request-id) |
| `Status` | `PENDING` |
| `Attempt_Count` | `0` |
| `Last_Error` | (blank) |
| `Validation_Error_Notified` | `false` |
| `AI_Completed` | `false` |
| `AI_Category` … `AI_Reply_Body` (all 7 columns) | (blank) |
| `CRM_Written` | `false` |
| `Slack_Notified` | `false` |
| `Gmail_Draft_Created` | `false` |
| `Completed_At` | (blank) |

### Don't confuse two different "needs a human" signals

This project already has a `Requires_Human` field on the `CRM` sheet
(see [`docs/data-model.md`](data-model.md)) — that's the AI's own
classification of whether a *reply* needs human review before sending.
`Processing_State.Status = NEEDS_HUMAN` is a **different, pipeline-level**
signal: it means something about *running the automation itself* went
wrong in a way automation can't safely resolve (e.g. repeated transient
failures, an ambiguous partial-completion state). A row can be
`CRM.Requires_Human = true` and `Processing_State.Status = COMPLETED` at
the same time (the AI flagged the reply for review, but the pipeline
itself ran fine) — these are orthogonal. `Processing_State.AI_Requires_Human`
is a third, related-but-distinct thing: it's simply the persisted copy
of the AI's `requires_human` output (same value that ends up in
`CRM.Requires_Human`), stored so a retry can write it to `CRM` without
calling OpenAI again — it does not drive any pipeline-level state
transition itself.

## AI output persistence

### Why a Gmail-only retry needs stored AI output

Per the [confirmed live finding](#problem-this-addresses), the most
common partial-failure shape is: CRM and Slack succeed, only Gmail
fails. The whole point of `Attempt_Count`/the `_Written`/`_Notified`/
`_Created` flags is to let a retry redo **only** the step(s) that didn't
finish. But `[5] google-email:createADraft` needs a subject and a body,
and today those come directly from `[3]`'s own output
(`{{3.result.reply_subject}}`, `{{3.result.reply_body}}`) in the *same*
execution. A retry that skips `[3]` (because it already succeeded last
time) has no `{{3.result...}}` to read. A retry that calls `[3]` again
risks the model returning different text than what's already sitting in
the `CRM` row and the Slack message from the first attempt — the
customer's CRM record and their Slack-flagged summary would then
describe a different reply than the one actually drafted in Gmail.

### Design: persist AI output before any downstream side effect

`[2] openai-gpt-3:createModelResponse` runs, and its structured output is
written to `Processing_State`'s seven `AI_*` columns **before** `[3]`
(CRM), `[4]` (Slack), or `[5]` (Gmail) run at all — not just before
Gmail. This means every downstream step, on every attempt (first attempt
or retry alike), reads the **same** stored values:

1. Call `[2] openai-gpt-3:createModelResponse`.
2. On success, write its seven output fields to `Processing_State.AI_Category`
   … `AI_Reply_Body`, then set `AI_Completed = true`, and confirm the
   write itself succeeded (see
   [OpenAI failure handling](#openai-failure-handling) for what "confirm"
   means and what happens if it doesn't).
3. On a retry, if `AI_Completed = true` already (as determined by the
   re-fetch described below — not by the gate's original lookup), **skip
   `[2]` entirely**.
4. Either way, `[3]` (CRM), `[4]` (Slack), and `[5]` (Gmail) read the
   classification/reply content they need from a **freshly re-fetched**
   `Processing_State` row — never from the gate's original lookup bundle,
   and never from `[2]`'s own `{{3.result...}}` output directly. See
   [Re-fetching the latest Processing_State row before downstream
   steps](#re-fetching-the-latest-processing_state-row-before-downstream-steps)
   immediately below for why and how.
5. `[3]`, `[4]`, and `[5]` each run only if their own completion flag
   (`CRM_Written`, `Slack_Notified`, `Gmail_Draft_Created`), as read from
   that same re-fetched row, is `false` — see
   [Route A](#route-a-valid-input) for the full sequencing.

This makes the Gmail-only retry the design goal describes possible: the
same `AI_Reply_Subject`/`AI_Reply_Body` that were used to write `CRM` and
notify Slack on the first attempt are exactly what `[5]` uses on the
retry, whether that retry happens a second later or a week later.

### The pre-Router lookup is gate-only, not a downstream data source

The idempotency gate's `Processing_State` lookup (see
[Idempotency gate](#idempotency-gate-runs-before-validation)) exists for
exactly three purposes:

1. Deciding whether a `Processing_State` record already exists for this
   `Request_ID`.
2. Feeding the [gate outcomes table](#gate-outcomes) — i.e. deciding
   whether to stop or proceed.
3. Providing the values used to create a brand-new row when none existed
   yet.

**It must never be used as the mapping source for `[3]`, `[4]`, or `[5]`
— on a first run or a retry.** A Make module's output bundle reflects
the data at the moment that module ran; it is a snapshot, not a live
reference that updates itself when a later module in the same execution
writes to the same spreadsheet row. The gate's lookup runs once, at the
very start of the execution, before `[2]` has even been called — so by
the time `[2]`'s output has been saved to `Processing_State`, the gate's
own snapshot of that row is already out of date. Treating it as current
is exactly the bug this revision fixes: see
[the design-review finding above](#problem-this-addresses) for how a
first run under the earlier wording would have mapped `[3]`/`[4]`/`[5]`
from blank `AI_*` values, even though correct values had, moments
earlier in the same execution, already been written to the sheet.

This holds regardless of whether Make's Google Sheets modules happen to
offer some other way to reference "live" cell data — this design simply
does not rely on that question either way. An explicit re-fetch (below)
is correct whether or not such a thing exists; it costs one extra
lookup, and removes the need to depend on unverified Make behavior.

### Re-fetching the latest `Processing_State` row before downstream steps

Immediately before `[3]`, `[4]`, or `[5]` can run — on **every**
attempt, first run and retry alike, whether or not `[2]` was just called
in this same execution — re-fetch `Processing_State` by `Request_ID`:

1. Confirm the AI-output write (or, on a retry where `AI_Completed` was
   already `true`, simply reach this point) — see the Sequence step
   above.
2. Search/look up `Processing_State` for this exact `Request_ID` again,
   in a **new** module call — not a reference to the gate's original
   lookup module, and not a reference to `[2]`'s own output.
3. This re-fetch is the **only** source `[3]`, `[4]`, and `[5]` read
   `AI_*` values and the `CRM_Written`/`Slack_Notified`/
   `Gmail_Draft_Created` flags from, for the rest of this execution.

The exact Make module used for this re-fetch, and the exact mapper
syntax for referencing its output from `[3]`/`[4]`/`[5]`, depends on
what Google Sheets row-search/lookup module Make actually offers — this
is the same not-yet-verified module type already flagged in
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)
for the gate's own lookup; **confirm live**, and record whether the gate
lookup and this downstream re-fetch end up using the same module type
with two separate calls, or something else — see
[Alternative: using the update module's own output instead of a separate
re-fetch](#alternative-using-the-update-modules-own-output-instead-of-a-separate-re-fetch)
below for the one case where a second lookup call might not be needed.

### If the re-fetch is abnormal: zero rows, multiple rows, or missing AI output

The re-fetch above must be validated before its result is trusted as the
mapping source for `[3]`/`[4]`/`[5]`:

- Exactly **one** row is returned.
- Its `Request_ID` matches the one just computed for this execution
  exactly.
- `AI_Completed = true`.
- All seven `AI_*` columns have a value (none blank).
- `Status = PROCESSING` (i.e. still the state this same execution set it
  to, earlier in [Route A](#route-a-valid-input) — not something else,
  which would suggest a concurrent write this design didn't anticipate).

**If any of these don't hold, `[3]`/`[4]`/`[5]` must not run.** What
happens instead depends on whether the row can be safely, unambiguously
addressed for a state update:

- **Zero rows found:** there is no row to write a status update to (the
  `Request_ID` this execution is working on doesn't match anything, even
  though this same execution's own gate lookup and AI-output save
  presumably targeted a real row moments earlier). Do not guess at a row
  to update. **Stop this execution without writing to `Processing_State`
  at all** — this is a genuine anomaly that needs to surface through
  Make's own execution-history/error reporting so a human notices it,
  since the pipeline's own state-tracking sheet cannot describe a problem
  with locating its own row.
- **Multiple rows found:** which one is authoritative for this
  `Request_ID` is ambiguous (this shouldn't happen given the
  [Request ID collision analysis](#request-id) above, but the re-fetch
  must not assume its own uniqueness guarantee held). Writing a status
  update to one of several candidates risks updating the wrong row.
  **Stop this execution without writing to `Processing_State`** — same
  reasoning as the zero-row case. A human resolving this manually, later,
  by inspecting the sheet directly, is safer than an automatic guess.
- **Exactly one row, but `AI_Completed`/the seven `AI_*` columns/`Status`
  don't hold:** unlike the two cases above, there **is** one unambiguous
  row to update. Set `Status = NEEDS_HUMAN` on that row, with a short
  `Last_Error` category (e.g. `"Re-fetch after AI save returned
  incomplete state"`) — **never** the customer's inquiry text or the
  AI's reply content, per the same rule as every other `Last_Error`
  value (see [OpenAI failure handling](#openai-failure-handling)). Do
  **not** proceed to `[3]`/`[4]`/`[5]`.

**Exactly which Make module(s)/routing produce the zero-row vs.
multiple-row vs. single-row-but-incomplete outcomes, and how to branch on
each in Make's own UI, is not something this document guesses at** —
confirm live and record it in
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md),
per this project's standing rule against inventing unverified Make JSON.

### Alternative: using the update module's own output instead of a separate re-fetch

Some "update an existing row" Google Sheets modules return the updated
row's own values as their output — if Make's does, and that output
includes all 18 `Processing_State` columns with the just-written `AI_*`
values, it could in principle replace the separate re-fetch above with
one fewer module call. The live Phase 2B candidate did not adopt this
shortcut: its verified implementation uses an explicit re-fetch. The Phase 2A
baseline has no update module from which this behavior could be inferred, so
this design's **default remains the explicit re-fetch above**.

Using the update module's own output as a substitute for the re-fetch is
only acceptable once ChatGPT Work has confirmed, live, **all** of the
following:

1. The update module (used to write `AI_Completed = true`/the `AI_*`
   fields) outputs the full, updated set of 18 `Processing_State`
   columns — not just the columns it was told to change.
2. The `AI_*` values in that output are the just-written, current
   values — not stale ones captured before the write.
3. The output unambiguously corresponds to the exact row for this
   execution's `Request_ID` (not, for example, a generic "last updated
   row" reference that could be wrong under concurrent executions).
4. This holds identically on **both** a first run (immediately after the
   AI-output save) and a retry (immediately before resuming CRM/Slack/
   Gmail) — not just one of the two.

If any of these can't be confirmed, use the explicit re-fetch. Do not
assume the update module's output can substitute for it without having
checked all four conditions live.

### The pre-save retry boundary

If a failure happens **after** `[2]` succeeds internally but **before**
`AI_Completed = true` is durably written to `Processing_State` (e.g. the
Sheets write itself fails, or execution is interrupted mid-write), the
next attempt sees `AI_Completed = false` and calls `[2]` again. **This is
deliberate and acceptable, not a gap:** at this point no `CRM` row, Slack
message, or Gmail draft has been created yet — every one of those is
gated on `AI_Completed = true` first (see above) — so there is nothing
downstream yet for a freshly re-generated classification/reply to be
inconsistent *with*. The only cost is that the newly-generated output may
differ slightly from whatever the lost first attempt would have produced
(OpenAI is not asked to be deterministic here); that's a re-generation,
not the duplicate-side-effects problem this document otherwise exists to
prevent. Contrast this with a failure **after** `AI_Completed = true` has
already been written — from that point on, `[2]` is never called again
for this row (see [Design](#design-persist-ai-output-before-any-downstream-side-effect)
above), specifically so that CRM/Slack/Gmail never end up disagreeing
with each other about what the reply said.

### OpenAI failure handling

Earlier drafts of this document mostly discussed CRM/Slack/Gmail
failures. `[2] openai-gpt-3:createModelResponse` can fail too, and needs
the same state-machine treatment:

- **Transient failures** (rate limiting, timeout, a 5xx-class API error):
  set `Status = FAILED_RETRYABLE`. `AI_Completed` stays `false`. A later
  retry calls `[2]` again per the gate/Route A logic above.
- **Non-transient failures** (authentication/configuration error, or a
  response that doesn't validate against
  [`prompts/response-schema.json`](../prompts/response-schema.json)):
  set `Status = FAILED_PERMANENT` or `NEEDS_HUMAN` — retrying
  automatically won't fix a bad API key or a schema mismatch that needs a
  human to look at the prompt/schema/model configuration.
- **`Last_Error` for an OpenAI failure** follows the same rule as every
  other `Last_Error` value: a short module name + error category (e.g.
  `"OpenAI: request timed out"`, `"OpenAI: response failed schema
  validation"`). It must **not** contain the customer's inquiry text, and
  it must **not** contain any partial or malformed AI output — only a
  category description of what went wrong.
- **Nothing downstream runs until the `AI_Completed` write itself has
  succeeded.** A successful `[2]` call by itself is not sufficient to
  proceed to `[3]`/`[4]`/`[5]` — the write of the `AI_*` columns and
  `AI_Completed = true` to `Processing_State` must also have completed.
  See [the pre-save retry boundary](#the-pre-save-retry-boundary) above
  for why treating an interruption at this exact point as "safe to retry
  OpenAI" is the correct, deliberate behavior rather than a bug.

### Storing generated reply content: an access note

Once `AI_Reply_Subject`/`AI_Reply_Body` (and the other `AI_*` fields) are
persisted, `Processing_State` stops being purely pipeline-internal
bookkeeping — unlike `Request_ID`/`Source_Row`, which are deliberately
PII-free, the `AI_*` columns hold AI-generated content derived from the
customer's original inquiry, similar in sensitivity to what
[`docs/data-model.md`](data-model.md)'s `CRM` sheet already stores.
Anyone with read access to `Processing_State` can read a customer's
classification and drafted reply without needing access to `CRM`.
Whatever access-control and retention decisions apply to `CRM` (see
[`SECURITY.md`](../SECURITY.md) and
[`docs/limitations.md`](limitations.md) for this project's existing,
still-unresolved data-retention discussion) should be applied to
`Processing_State` too, once this design is deployed. This document does
not add a new retention/deletion policy — it only flags that one more
sheet now needs to be covered by whatever policy is eventually decided.

## Route A — valid input

Reached only when the [gate](#gate-outcomes) said "proceed" *and* the row
passes [input validation](#input-validation). At this point
`Processing_State.Status` is either `PENDING` (first attempt) or
`FAILED_RETRYABLE` (a prior attempt got partway through).

### New-record transition to `PROCESSING`

1. No `Processing_State` record existed → the gate created one with
   `Status = PENDING` (see
   [initial values](#initial-values-for-a-new-processing_state-row)).
2. The Router evaluates [input validation](#input-validation) and sends
   the row to Route A.
3. Set `Status = PROCESSING` — **before** `[2] openai-gpt-3:createModelResponse`
   runs.
4. Increment `Attempt_Count` by exactly `1`.
5. Continue with the [AI output persistence](#ai-output-persistence) /
   downstream sequence below.

### Retry transition to `PROCESSING`

1. `Processing_State.Status = FAILED_RETRYABLE` for this `Request_ID`.
2. The gate (per the [gate outcomes table](#gate-outcomes)) lets the row
   proceed to the Router.
3. The Router re-evaluates [input validation](#input-validation) (this is
   redundant in practice, since `FAILED_RETRYABLE` is only reachable
   after validation already passed once — see [States](#states) — but
   the row still goes through the same Route A/B split as any other row)
   and sends it to Route A.
4. Set `Status = PROCESSING` — before resuming any incomplete step.
5. Increment `Attempt_Count` by exactly `1`. **This is the only place in
   Route A where `Attempt_Count` is incremented** — a step failing later
   in this same attempt (see below) does not increment it again.
6. Check `AI_Completed`, `CRM_Written`, `Slack_Notified`, and
   `Gmail_Draft_Created` and run only what's still `false` — see the
   sequence below.

### Sequence (applies to both a new record and a retry, once `Status = PROCESSING`)

1. If `AI_Completed = false` (per the gate's original lookup — this is
   the one and only place that lookup's `AI_*` snapshot is trusted, since
   it's evaluated *before* `[2]` could have changed anything): call
   `[2] openai-gpt-3:createModelResponse`.
   - On success: write the seven structured-output fields to
     `Processing_State.AI_Category` … `AI_Reply_Body`, then set
     `AI_Completed = true`, and confirm the write succeeded. See
     [AI output persistence](#ai-output-persistence).
   - On failure: handle per
     [OpenAI failure handling](#openai-failure-handling) (`Status =
     FAILED_RETRYABLE` or `FAILED_PERMANENT`/`NEEDS_HUMAN`, record
     `Last_Error`) and stop this execution. `Attempt_Count` was already
     incremented above — do not increment it again here.
2. **Re-fetch `Processing_State` for this `Request_ID`** — a fresh
   lookup, not the gate's original one from step 1 above (or from before
   step 1, on a retry where `AI_Completed` was already `true`). See
   [Re-fetching the latest Processing_State row before downstream
   steps](#re-fetching-the-latest-processing_state-row-before-downstream-steps).
   This happens **every time**, whether `[2]` was just called in this
   execution or skipped because `AI_Completed` was already `true`.
3. Validate the re-fetched row per
   [If the re-fetch is abnormal](#if-the-re-fetch-is-abnormal-zero-rows-multiple-rows-or-missing-ai-output).
   If it fails validation, stop here per that section — do not proceed to
   step 4.
4. From this point on, the re-fetched row — **not** the gate's original
   lookup, and not `[2]`'s own `{{3.result...}}` output — is the only
   source read for `AI_*` values and for `CRM_Written`/`Slack_Notified`/
   `Gmail_Draft_Created`.
5. If `CRM_Written = false` (per the re-fetched row): run
   `[3] google-sheets:addRow`, using the re-fetched `AI_*` values (plus
   `Name`/`Email`/`Original_Subject`/`Original_Message` from the trigger
   bundle, unchanged from today). On success, set `CRM_Written = true`.
6. If `Slack_Notified = false` (per the re-fetched row): run
   `[4] slack:CreateMessage`, using the re-fetched `AI_*` values. On
   success, set `Slack_Notified = true`.
7. If `Gmail_Draft_Created = false` (per the re-fetched row): run
   `[5] google-email:createADraft`, using `AI_Reply_Subject`/
   `AI_Reply_Body` from the re-fetched row. On success, set
   `Gmail_Draft_Created = true`. This is exactly the case from the
   [confirmed live finding](#problem-this-addresses): CRM and Slack
   already succeeded, only Gmail needs retrying, and this step now has
   the same reply content available that CRM/Slack already used.
8. If any of `[3]`, `[4]`, or `[5]` fails: set `Status = FAILED_RETRYABLE`
   (or `FAILED_PERMANENT` if the error is structurally unrecoverable),
   record a short `Last_Error`. `Attempt_Count` is **not** incremented
   again — it was already incremented once for this attempt, above.
9. Once `CRM_Written`, `Slack_Notified`, and `Gmail_Draft_Created` are all
   `true`: set `Status = COMPLETED` and `Completed_At = now`.

### The `PROCESSING` state is a deliberate caution, not a solved problem

If a run is interrupted mid-flight (e.g. Make itself has an outage
between steps), a row can be left in `Status = PROCESSING` indefinitely.
Automatically treating "stuck in `PROCESSING`" as safe-to-retry would
reintroduce the exact duplicate risk this design exists to prevent,
*if* the interruption happened after a side effect (CRM write, Slack
message) but before the state was updated to reflect it. This design
does not attempt to solve that with a timeout-based auto-retry; a row
stuck in `PROCESSING` past a reasonable window should be surfaced for
manual review (e.g. `Status` manually moved to `NEEDS_HUMAN`), not
silently retried.

## Route B — invalid input

Reached only when the gate said "proceed" *and* the row fails input
validation (see [Input validation](#input-validation) below). At this
point a `Processing_State` row for this `Request_ID` **already exists**
(the gate created it, or it existed from an earlier `FAILED_RETRYABLE`
attempt — though a row that failed validation before wouldn't reach here
again, per the gate table above). Route B:

- Does **not** call OpenAI. `AI_Completed` and the `AI_*` columns stay at
  their initial blank/`false` values.
- Does **not** write a normal `CRM` record.
- Does **not** create a Gmail draft.
- Does **not** send the normal customer-inquiry Slack notification.
- Does **not** touch `Attempt_Count` — that column only tracks Route A
  attempts (see [Route A](#route-a-valid-input)).
- **Updates the existing `Processing_State` row** (does not insert a new
  one) to `Status = FAILED_VALIDATION`, with `Last_Error` describing
  which rule failed (not the raw message body), and sets
  `Validation_Error_Notified = false`.
- Sends the minimal error notification described in
  [Error notification content](#error-notification-content).
- Updates `Validation_Error_Notified = true` after the notification is
  sent.

**Residual gap, stated plainly:** if the notification send succeeds but
the final `Validation_Error_Notified = true` write fails (or vice
versa), the flag may not accurately reflect whether the notification
went out — and because the gate treats `FAILED_VALIDATION` as a hard
stop regardless of `Validation_Error_Notified`, Route B is not
re-entered on a later rerun to retry the notification specifically. This
mirrors the [Gmail post-success state write gap](#a-failure-window-this-design-does-not-close-the-post-success-state-write)
below: `Validation_Error_Notified` is a **diagnostic field** (a human
inspecting `Processing_State` can tell whether the notification is
believed to have gone out) rather than something that drives further
automatic retries. Closing this completely would need the same kind of
atomic write-plus-send guarantee this document already says it doesn't
provide anywhere else.

## Input validation

Applied on Route A/B evaluation, **after** the idempotency gate above
has already run:

| Field | Rule |
|---|---|
| `Name` | Not empty (after trimming whitespace) |
| `Email` | Not empty, and matches a minimal shape check: contains exactly one `@`, at least one character before it, and at least one `.` after it, with no whitespace anywhere. This is intentionally **not** full RFC 5321 validation — it's a cheap filter for obviously-broken input (empty, missing `@`, stray spaces), not a guarantee the address is deliverable. |
| `Subject` | Not empty |
| `Message` | Not empty |

### Error notification content

The error notification (Slack and/or the state-tracking record) must
**not** include the full inquiry message body or unnecessary personal
data. It should contain only enough to locate and act on the problem:

- The source row reference — use `Source_Row` (e.g. `"Form row 42"`),
  **not** `Request_ID` and not the customer's `Email`/`Subject`. See
  [`Source_Row`](#source_row-a-separate-human-readable-reference-for-notifications)
  above for why a separate, notification-safe field exists.
- Which validation rule(s) failed (e.g. `"Email format invalid"`), not
  the invalid value verbatim if it could itself be sensitive (an email
  address is already handled elsewhere in this project as data that
  goes to Slack today — see [`SECURITY.md`](../SECURITY.md) — so this is
  a judgment call for whoever deploys this; at minimum, the message body
  should never be echoed into an error notification).
- A timestamp.
- Sent **exactly once** per row, by construction — see
  [Route B](#route-b-invalid-input) and the gate table above.

## Testing strategy: two distinct failure scenarios

An earlier draft of this design and
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)
conflated two different things by testing them with the same input (an
invalid email address): (A) rejecting bad input before it's processed,
and (B) recovering from a downstream step failing after earlier steps
already succeeded. **These need different test inputs, because an
invalid email address is now caught by input validation and never
reaches the Gmail step at all.** Using it to test "partial success"
would be self-contradictory under this design.

### Test A — input validation, plus a normal valid-input run

Before the invalid-email case below, run once with a **valid** inquiry
(e.g. [`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
row 1) and confirm the [re-fetch fix](#re-fetching-the-latest-processing_state-row-before-downstream-steps)
actually works, not just the input-validation behavior this test is
mainly about:

- `[2]` (OpenAI) succeeds, the `AI_*`-saving update module succeeds, and
  `AI_Completed = true` is confirmed written.
- The re-fetch module then runs and returns exactly one row for this
  `Request_ID`, with `AI_Completed = true` and all seven `AI_*` columns
  populated.
- `[3]`, `[4]`, and `[5]` are mapped from the **re-fetch module's**
  output — check this directly in Make's execution History/module
  output inspector, not just the final result — and **not** from the
  gate's original pre-Router lookup module (whose output, inspected the
  same way, should still show blank `AI_*` values, since it ran before
  `[2]`).
- `Processing_State` ends up `COMPLETED` with all three downstream flags
  `true`, as before.

**Input (invalid-email case):** an invalid email address (e.g.
[`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
row 4 — see that file's notes on why this row is test-only).

**Expected behavior, first run:**

- The gate finds no existing `Processing_State` record, creates one
  (`Status = PENDING`), and lets the row proceed to the Router.
- The Router sends the row to Route B (invalid).
- Route B updates that **same** `Processing_State` row to
  `Status = FAILED_VALIDATION` — exactly **one** `Processing_State` row
  exists for this `Request_ID`.
- OpenAI is **never called**; no `CRM` record is written; no
  customer-inquiry Slack notification is sent; no Gmail draft is
  created.
- Exactly **one** validation-error notification is sent.

**Expected behavior, re-run:**

- The gate finds `Status = FAILED_VALIDATION` for this `Request_ID` and
  stops **before** the Router — Route B is not re-entered.
- `Processing_State` still has exactly **one** row for this
  `Request_ID` — no duplicate row was created.
- **No second validation-error notification is sent.**
- OpenAI/CRM/normal-Slack/Gmail are still never called.

**Important:** under the *current, published* Phase 2A blueprint (which
does not yet have input validation or this gate), this same row does
**not** behave this way — OpenAI, CRM, and Slack all still run today,
and only Gmail fails. [`sample_data/crm-records.csv`](../sample_data/crm-records.csv)'s
row 4 documents *that* current (pre-Phase-2B) behavior. Once this
design is actually deployed, this row's outcome changes to what's
described above. See [`sample_data/README.md`](../sample_data/README.md)
for how this distinction is flagged there.

### Test B — partial success and idempotent retry

**Input:** a **valid** inquiry (input validation must pass — e.g.
[`sample_data/form-submissions.csv`](../sample_data/form-submissions.csv)
row 1). The failure must be induced **after** validation, at the Gmail
step specifically, using a method that reliably fails `[5]` and doesn't
touch anything outside this test.

**Only one method is sanctioned: a dedicated, test-only Gmail
connection.** An earlier draft of this section also offered a fallback
(temporarily pointing `[5]`'s recipient at a reserved/example domain).
**That fallback has been removed** — see
[why](#problem-this-addresses) above: `example.com` is a syntactically
valid address, and since `[5]` only creates a *draft* (never sends), it
would most likely make `[5]` **succeed**, not fail, defeating the test.
No other content-independent way to reliably fail a Gmail
draft-creation module (as opposed to a *send*) has been verified for
this project — inventing one here would be exactly the kind of guess
this project avoids.

**Do not revoke, expire, disconnect, reauthorize, or otherwise modify
the credentials or permissions of a *shared* Gmail connection** — one
attached to production or to any other scenario. Make connections can be
shared across scenarios in ways that aren't always obvious from a single
scenario's editor view; breaking one to force a test failure risks
breaking everything else that connection is attached to. This is a hard
rule, not a "check first and it's probably fine": treat any Gmail
connection as shared unless you created it specifically for this test
and have independently confirmed nothing else uses it.

**Procedure (dedicated connection only):**

1. Use this procedure only on a **cloned, Inactive** test scenario —
   never on the scenario end users depend on.
2. In Make, confirm the dedicated Gmail connection is not referenced by
   the production scenario or by any other scenario.
3. If you cannot confirm this, treat the connection as shared and do
   **not** use it — see the [stop condition](#if-no-dedicated-connection-is-available)
   below.
4. Export/save a copy of the current scenario blueprint as a backup
   before changing anything.
5. Deliberately disable or disconnect **only** the dedicated test
   connection (not any shared connection) to reproduce a Gmail-module
   failure.
6. Run once with a **valid** inquiry (e.g. row 1). Confirm via Make's
   execution History that `[3]` (CRM) and `[4]` (Slack) succeeded and
   `[5]` (Gmail) failed — a module-level failure, not just "the scenario
   finished with a warning."
7. Restore the dedicated connection (reconnect/re-enable it).
8. **Verify independently** that the connection is restored (e.g. a
   trivial test action in Make, or checking the connection's status in
   Make's connections list) — don't assume the reconnect worked just
   because no error was shown.
9. Re-run the **same row** (same `Request_ID`).
10. Confirm OpenAI, CRM, and Slack are **not** re-run (their flags —
    `AI_Completed`, `CRM_Written`, `Slack_Notified` — are already `true`
    from step 6). Before `[5]` runs, confirm the
    [re-fetch](#re-fetching-the-latest-processing_state-row-before-downstream-steps)
    happens again on this retry — check its module output directly in
    Make's execution History — and that `[5]` is mapped from that
    re-fetch's `AI_Reply_Subject`/`AI_Reply_Body`, which should match
    what was saved during step 6's OpenAI call, not a fresh OpenAI
    result. Confirm only `[5]` runs, and now succeeds.
11. Leave the test scenario **Inactive** when finished.

**Expected behavior, first run (step 6 above):**

- `[2]` (OpenAI) succeeds; `Processing_State.AI_Completed = true` and the
  `AI_*` columns are populated.
- The re-fetch module runs and returns that same, now-populated row.
- `[3]` (CRM) and `[4]` (Slack), mapped from the re-fetch's output,
  succeed; `[5]` (Gmail), also mapped from the re-fetch's output, fails
  (the induced connection failure).
- `Processing_State`: `CRM_Written = true`, `Slack_Notified = true`,
  `Gmail_Draft_Created = false`, `Status = FAILED_RETRYABLE`.

**Expected behavior, re-run (steps 9–10 above):**

- `[2]`, `[3]`, and `[4]` are **skipped** (`AI_Completed`, `CRM_Written`,
  and `Slack_Notified` are already `true` — as read from a **fresh
  re-fetch performed at the top of this retry execution**, not assumed
  from the previous execution).
- The re-fetch runs again immediately before `[5]` (per
  [Re-fetching the latest Processing_State row before downstream
  steps](#re-fetching-the-latest-processing_state-row-before-downstream-steps) —
  this happens on every attempt, retries included), and `[5]` is mapped
  from that re-fetch's `AI_Reply_Subject`/`AI_Reply_Body`.
- Only `[5]` runs, and now succeeds.
- No duplicate CRM row, no duplicate Slack message, and the Gmail draft's
  subject/body match what's already in the `CRM` row and the Slack
  message from the first run — because both were built from the same
  persisted `AI_*` values, just re-fetched at different times.
- `Processing_State` shows `Status = COMPLETED`.

#### If no dedicated connection is available

**This is a stop condition, not an invitation to improvise.** If a
dedicated, confirmed-unshared Gmail connection cannot be created or
obtained, **do not run Test B** using any other failure-injection
method. Record Test B as **not verified** in whatever report or checklist
tracks this deployment, and leave it there — do not substitute an
alternate method (a fake recipient address, a reserved domain, editing
the module's mapper to something invalid, or anything else) whose
reliability at actually failing `[5]` hasn't been independently
confirmed. See
[`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md#test-b-partial-success-and-idempotent-retry)
for where this is tracked.

### A failure window this design does not close: the post-success state write

There is a narrower race this design does not solve, distinct from the
CRM/Slack duplication bug: if `[5] google-email:createADraft` **succeeds**
but the subsequent write of `Gmail_Draft_Created = true` to
`Processing_State` itself fails (e.g. a transient Sheets error at that
exact moment), the state still shows `Gmail_Draft_Created = false`. A
later retry would then create a **second Gmail draft** for the same
inquiry, because — unlike a CRM row or a Slack message, which this
design successfully prevents from duplicating — Gmail draft creation has
no natural content-based dedup key in this design to detect "a draft for
this inquiry already exists." This is a real, acknowledged gap, not an
oversight: closing it would need either an idempotency key Gmail's API
itself honors (not something this design assumes exists) or a
check-before-create step that searches existing drafts (which would need
a verified Make module for that, not present in the existing blueprint).
Stated plainly: **this design reduces duplicate risk, it does not
eliminate every duplicate-producing window.** This is a different
failure window from [the pre-save retry boundary](#the-pre-save-retry-boundary)
for OpenAI's own output — that one is explicitly safe to retry from
scratch because nothing downstream has happened yet; this one is not,
because a Gmail draft (an external side effect) has already happened.

## Make Data Store vs. spreadsheet-based state tracking

Two ways to hold `Processing_State`:

| | Make Data Store | Spreadsheet (`Processing_State` sheet, chosen) |
|---|---|---|
| Setup | Requires creating a Data Store in the Make organization — a separate feature to configure, redo per deployment | Just another tab in the same spreadsheet already used by `Form`/`CRM` |
| Visibility | Only inspectable from Make's UI | Directly visible/screenshot-able alongside `Form`/`CRM` — easier to explain in a GitHub portfolio context and easier for a non-technical reviewer to understand |
| Lookup performance | Native key-value get, fast | Requires a row search/lookup in Sheets (slower, and Make's exact Google Sheets "search rows" module type/schema is not verified from the existing blueprint — see the deployment checklist) |
| Atomicity | Get/set per key; still not a true distributed lock without extra design | No atomic compare-and-set; concurrent runs can race (see below) |
| Portability | Tied to the Make organization; not something that travels with "just the spreadsheet" | Travels with the spreadsheet — consistent with this project's existing "Google Sheets as source of truth" design |

**Decision: spreadsheet-based (`Processing_State` sheet).** For a
publicly-documented reference project where the goal is that someone can
read the design, open the spreadsheet, and understand what's happening
without needing access to Make's Data Store UI, the spreadsheet approach
is more explainable and requires no additional Make-side feature setup
beyond what's already used (Google Sheets modules). The tradeoff, stated
plainly: it's slower at scale and has weaker concurrency guarantees than
a real key-value store — acceptable for this project's current scope
(a support inbox, not a high-throughput system), not necessarily the
right call for a higher-volume deployment. Storing the `AI_*` columns
here too (rather than, say, a separate store) follows the same
reasoning: one place to look, at the cost of the same weaker
concurrency/atomicity guarantees already accepted for the rest of
`Processing_State`.

## Concurrency and exactly-once limitations

**This design does not guarantee strict exactly-once processing.** Be
specific about why:

- Checking `Processing_State` and then acting on what you found (read →
  decide → write) is not atomic in a spreadsheet. If the *same* row were
  somehow triggered twice in close succession (e.g. a manual rerun
  overlapping with a still-in-flight run), both executions could read
  "no record yet" or the same pre-update status before either writes its
  update, and both could proceed — reintroducing duplication in that
  specific race window. This applies to the idempotency gate itself, and
  to every flag check in [Route A](#route-a-valid-input) (`AI_Completed`,
  `CRM_Written`, `Slack_Notified`, `Gmail_Draft_Created`) — not just the
  top-level gate.
- This design **does** solve the confirmed, actually-observed bug (a
  sequential rerun after a partial success/failure, for both the
  downstream-step case and the validation-rejection case), because by
  the time a human triggers a rerun, the prior run has already reached a
  terminal or clearly-stuck state and the flags reflect what really
  happened.
- It does **not** provide a hard guarantee against true concurrent
  overlapping execution of the same row. A real guarantee would need an
  atomic test-and-set primitive (e.g., a proper locking pattern against
  a key-value store, or a database with row-level locking) — out of
  scope for what's designed here.
- Make's own trigger polling behavior (how it decides which rows are
  "new" and whether it could ever redeliver the same row bundle) has not
  been independently verified for this scenario — see
  [`docs/limitations.md`](limitations.md).
- There is also a narrower, non-concurrency failure window specific to
  the Gmail step — see
  [the post-success state write gap](#a-failure-window-this-design-does-not-close-the-post-success-state-write)
  above — and a mirror-image one for the validation-notification step —
  see [Route B](#route-b-invalid-input). The equivalent window for
  OpenAI's own output ([the pre-save retry boundary](#the-pre-save-retry-boundary))
  is, by contrast, explicitly *not* a gap — see that section for why.

## What this document does not include

- An importable Make Blueprint implementing this design. See
  [`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md)
  for why and what's needed to build one with confidence instead of by
  guessing.
- A resolution to the free-text-message PII exposure gap described in
  [`docs/limitations.md`](limitations.md) — that's a separate, unrelated
  problem to this one.
- A retention/deletion policy for the `AI_*` columns now stored in
  `Processing_State` — see
  [Storing generated reply content: an access note](#storing-generated-reply-content-an-access-note)
  above.
