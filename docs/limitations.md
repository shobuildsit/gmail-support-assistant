# Limitations

This is a portfolio and controlled-demo project, not a production-readiness
claim. The exact live evidence is in
[`docs/runtime-verification.md`](runtime-verification.md).

## Confirmed

- The Phase 2A sanitized Blueprint imports and its five-module chain completed
  normal and boundary-marker test inquiries.
- The Phase 2B candidate completed a valid inquiry through state creation,
  OpenAI, persisted AI output, CRM, Slack, Gmail draft, and `COMPLETED`.
- Replaying the same terminal Request ID stopped before OpenAI and all three
  external side effects; no duplicate CRM row, Slack message, or Gmail draft
  was created in the observed replay. This was also confirmed against the
  2026-08-12 Form-originated live test row.
- OpenAI ran with `store: false` and `createConversation: false`.
- Gmail integration is draft-only; no email was sent by the automation.
- A synthetic Google Form response completed the live Form → Sheets → Make →
  OpenAI → CRM/Slack → Gmail-draft chain in the existing test environment.

## Phase 2B routes not completed or not live-verified

The published candidate deliberately retains blocked filters for incomplete
paths. It must not be presented as a finished production workflow:

- Invalid-input fallback and validation notification
- Zero-result and multiple-result state re-fetch anomalies
- Multiple Request ID matches
- The blocked retryable-status fallback branch
- Safe injected failures and recovery for OpenAI, Sheets, Slack, and Gmail

The blocked filter names are recorded in
[`docs/runtime-verification.md`](runtime-verification.md). A Gmail failure was
not induced by changing a shared connection, because doing so could affect
other scenarios.

## Operational behavior not verified

- Fresh-account import/setup from scratch
- Concurrent or bulk submissions, including Request ID races
- Strict exactly-once processing under every failure or concurrency condition
- Rate limits, burst behavior, cost controls, and long-running operation
- Recovery after platform outages or credential expiration
- OpenAI output quality across all 13 offline prompt cases
- Make's exact escaping/encoding behavior for arbitrary customer text
- Current availability of the model name embedded in the exported Blueprint
- The reference Apps Script-created Form and its Subject length validator

## Testing boundaries

[`tests/validate_blueprint.py`](../tests/validate_blueprint.py) is offline and
structural. It checks Blueprint shape, safety invariants, prompt/schema sync,
public placeholders, sample data, and documentation contracts. It does not
call external APIs or prove live behavior. [`tests/prompt-cases.jsonl`](../tests/prompt-cases.jsonl)
contains specifications but no API-calling evaluation runner.

## Data and privacy gaps

- The dedicated email column is excluded from the OpenAI input, but customers
  can still type personal data into free text.
- Slack receives customer-identifying information and AI-generated content.
- Retention and abuse-monitoring behavior must be verified against current
  OpenAI and organizational policies; `store: false` alone is not a complete
  privacy assessment.
- Access controls, retention periods, deletion procedures, and data-processing
  agreements are deployment responsibilities.

See [`SECURITY.md`](../SECURITY.md) before using real customer data.

## Repository gaps

- A reproducible Google Form specification and Apps Script creator are
  published under [`forms/`](../forms/). Manual Form creation/linking was
  live-verified in the existing test environment, but the Apps Script build
  and a fresh-account setup remain unverified.
- Fresh-account setup documentation has not been independently followed from
  start to finish.
- A repository-native architecture diagram and synthetic-data demo visual are
  included. Real live-account UI screenshots remain intentionally excluded
  until every account/workspace identifier can be reliably removed.
- Continuous integration is not yet included.
- The header-only public spreadsheet template now contains `Form`, `CRM`, and
  `Processing_State`, but its import has not yet been verified on a completely
  fresh Google/Make account.
- `CRM.Status` represents support workflow status and still requires a human
  process; it is distinct from pipeline `Processing_State.Status`.

## Deliberate scope boundaries

- Gmail drafts are never sent automatically.
- Private source exports, real spreadsheets, credentials, IDs, and customer
  data are excluded from the repository.
