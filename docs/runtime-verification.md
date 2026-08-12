# Runtime Verification

This document separates results observed in a live Make.com test scenario
from the offline checks under [`tests/`](../tests/). Live verification was
performed manually with ChatGPT Work. Repository tooling does not connect to
Make, Google, OpenAI, Slack, or Gmail.

## Publication and safety rules

No real account identifier, connection ID, Spreadsheet ID, Slack channel,
email address, draft ID, Make run ID, execution URL, or inquiry text is
recorded here. The original production scenario was not modified. The test
scenario remained **Inactive**, and Gmail was kept **draft-only**.

## Phase 2A baseline — 2026-08-07

The five-module sanitized baseline Blueprint imported successfully. A normal
inquiry and a TC13-equivalent boundary-marker escape inquiry both completed
the chain: trigger → OpenAI → CRM → Slack → Gmail draft. The adversarial case
required human review, did not follow the injected instruction, and did not
disclose internal prompt content. Its category differed from the original
single expected value, so TC13 was corrected to accept multiple safe
categories while retaining strict safety requirements.

The live OpenAI call used `store: false` and `createConversation: false`.
Gmail created drafts and did not send email.

That pass also reproduced a Phase 2A defect: after CRM and Slack succeeded,
a Gmail-draft failure followed by replay duplicated the earlier side effects.
This finding motivated Phase 2B.

## Phase 2B candidate — 2026-08-11

The stateful Phase 2B scenario was assembled and verified incrementally in a
separate test scenario. A sanitized export is published as
[`make/blueprints/gmail-support-assistant.phase2b.candidate.json`](../make/blueprints/gmail-support-assistant.phase2b.candidate.json).

### Confirmed working

- The complete valid-input path ran from a `PENDING` state through OpenAI,
  persisted AI output, CRM, Slack, Gmail draft, and `COMPLETED` (24
  operations; 13 seconds in the observed run).
- Replaying the same terminal Request ID stopped at the common idempotency
  gate after six control/gate operations. It did not call OpenAI or create a
  second CRM row, Slack message, or Gmail draft.
- Retry/skip routing uses the latest re-fetched `Processing_State` row and can
  skip side effects already marked complete.
- OpenAI remained `store: false` / `createConversation: false`; its input did
  not include the email column.
- Both Gmail modules are `google-email:createADraft`; no send-email module is
  present.
- The final saved server export matched the immediately preceding export and
  retained the verified route filters. The scenario remained Inactive with no
  execution left running.
- Test cleanup restored the pre-existing Form and Processing_State values and
  removed the temporary CRM evidence row. The Slack test message and Gmail
  draft were intentionally retained as evidence; no email was sent.

### Verified scope

The live pass covered the happy path, persisted-AI retry/skip path, CRM/Slack/
Gmail completion flags, finalization, and terminal duplicate prevention. This
is evidence for those routes only—not for every branch in the 72-module
candidate.

### Intentionally blocked or still unverified routes

The following filters remain explicit stop markers in the candidate rather
than pretending their routes are complete:

- `INVALID_INPUT_FALLBACK_BLOCKED`
- `PHASE2_VALIDATION_NOTIFY_BLOCK`
- `PHASE2_REFETCH_ABNORMAL_AI_PATH_BLOCK`
- `PHASE2_REFETCH_ABNORMAL_SKIP_PATH_BLOCK`
- `PHASE2_REQUEST_ID_MULTIPLE_MATCHES_BLOCKED`
- `PHASE2_STATUS_RETRYABLE_PROCEED_BLOCKED`

Accordingly, invalid-input notification, zero/multiple-match abnormal
re-fetch handling, and the dedicated failure route are not production-ready.
A non-destructive Gmail failure-injection test was also not performed because
the available Gmail connection was shared; its credentials or permissions
were not modified.

## Google Form to Gmail draft — 2026-08-12

A published Google Form was linked to the existing test spreadsheet and the
Make Watch Rows module was re-selected against Google's response-managed
`Form` tab. The original `Form` tab was retained as a legacy backup. The live
test used synthetic `example.com` data only, and the scenario stayed Inactive
except for explicit **Run once** executions.

The first zero-match Request ID lookup exposed a Make-specific aggregation
detail: an empty Sheets search still produced one aggregate bundle, so
`length(66.array) = 0` did not identify a new request. The common gate was
changed to test whether the first mapped Request ID value does not exist:
`first(map(66.array; "0"))` with Make's `notexist` operator. A later test also
showed that new Form row numbers must not reuse occupied
`Processing_State.Source_Row` slots left by legacy test data.

After those two findings were isolated, one new synthetic response in an
unused row completed the full chain:

- Google Form wrote the exact five-column response contract.
- The common gate created a new `PENDING` state and the scenario completed one
  OpenAI call.
- `Processing_State` reached `COMPLETED` with `AI_Completed`, `CRM_Written`,
  `Slack_Notified`, and `Gmail_Draft_Created` all true.
- CRM contained one matching row.
- Make's executed Slack route and the persisted `Slack_Notified` flag both
  indicated success. Slack was not independently inspected in its own UI.
- Gmail's Drafts count increased by one and the matching generated subject and
  body were visible. No email was sent.

The exact successful Form-originated run was then replayed once. The replay
completed in six control/gate operations and stopped on the terminal
`COMPLETED` state before OpenAI, CRM, Slack, or Gmail. `Attempt_Count` remained
1, CRM still contained exactly one matching row, and Gmail Drafts remained at
the same count. Because the Slack module did not execute, no duplicate Slack
message was created by this replay. The scenario was left Inactive with no
execution running.

The live manually configured Form did not retain a Subject response-length
validator: enabling it in the UI rejected valid test subjects. The 150-character
limit remains the desired reference contract in [`forms/`](../forms/) and is
checked by Make before AI processing, but that exact Google Forms UI validation
is not claimed as live-verified.

## Still not verified

- Fresh import and setup on an unrelated Make/Google/Slack/OpenAI account
- Concurrent or bulk submissions and race conditions
- Rate limits, sustained load, cost controls, and long-running operation
- Failure injection and recovery for OpenAI, CRM, Slack, and Gmail
- Strict exactly-once guarantees under all failure/concurrency conditions
- All 13 prompt cases against the live OpenAI model
- Make's exact escaping behavior for arbitrary customer text
- The reference Apps Script Form build, including its Subject length validator

## Readiness judgment

The Phase 2B candidate is a credible, importable portfolio artifact and the
verified happy/idempotency routes and the live Form-to-draft chain are suitable
for a controlled demo. It is
**not production-ready** until the blocked branches are implemented and
tested, a fresh-account import is completed, and concurrency/failure behavior
is characterized.

See also [`docs/limitations.md`](limitations.md),
[`docs/error-handling-and-idempotency.md`](error-handling-and-idempotency.md),
and [`make/phase2b-deployment-checklist.md`](../make/phase2b-deployment-checklist.md).
