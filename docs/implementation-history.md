# Implementation History

This history records structural milestones without publishing private Make,
Google, Slack, Gmail, or customer identifiers.

## Phase 1 — public repository foundation

- Created a sanitized Phase 2A baseline Blueprint and public documentation.
- Excluded private exports, local settings, real spreadsheets, and secrets.
- Established Gmail draft-only as a non-negotiable safety property.

## Phase 2A — prompt, schema, and privacy hardening

- Externalized the OpenAI prompt and structured-output JSON Schema.
- Removed the dedicated customer email column from the OpenAI input.
- Set `store: false` and `createConversation: false`.
- Added prompt-injection boundaries, length limits, sample data, and offline
  regression tests.
- Live-verified import, normal processing, a TC13-equivalent adversarial case,
  CRM/Slack writes, and Gmail draft creation on 2026-08-07.
- Reproduced the partial-success replay defect that motivated Phase 2B.

## Phase 2B — stateful orchestration candidate

- Designed an 18-column `Processing_State` contract and Request ID gate.
- Built the workflow incrementally in an Inactive Make test scenario using
  observed module shapes rather than invented Blueprint JSON.
- Added persisted AI output, re-fetch-before-side-effect routing, per-side-
  effect completion flags, finalization, and terminal-state stopping.
- Live-verified a complete happy path and duplicate replay prevention on
  2026-08-11.
- Exported and sanitized the resulting 72-module candidate without modifying
  its routing/mapping structure.
- Extended the public spreadsheet template with the 18-column
  `Processing_State` sheet, 200 empty preformatted rows, filters, frozen
  headers, and contract-aligned input validation.
- Added a sanitized Google Form specification and Apps Script creator with
  exact response headers, validation rules, privacy copy, and safe response-tab
  linking instructions.
- Linked a manually created Google Form to the test spreadsheet and completed
  a synthetic Form-to-Gmail-draft run on 2026-08-12. The run exposed and fixed
  the new-request gate's empty-aggregate handling by replacing
  `length(66.array) = 0` with a missing first Request ID test.
- Replayed that exact Form-originated success once. The terminal gate stopped
  the replay after six control operations; OpenAI and all three external side
  effects were skipped, with no additional CRM row or Gmail draft.
- Added repository-native architecture and synthetic demo SVGs for the public
  portfolio. They use only reconstructed `example.com` data, explicitly avoid
  private-account screenshots, and are included in the automated secret scan.
- Selected the MIT License and initialized a local `main` Git repository.
  Private source exports, local Claude settings, and Codex scratch files remain
  ignored. A reviewed initial portfolio commit was created locally and pushed
  to the public GitHub repository on 2026-08-12; `origin/main` is now the
  tracked public branch.
- Recorded the legacy row-number collision constraint and the live Form's
  Subject-validator deviation instead of presenting them as verified behavior.
- Retained explicit blocked filters for incomplete validation and abnormal
  routes. These are documented limitations, not hidden TODOs.

## Current handoff

The candidate is suitable for portfolio demonstration and further controlled
testing. Before production use, complete the blocked routes, perform safe
failure injection with dedicated connections, verify a fresh-account import,
and characterize concurrent/bulk behavior. See
[`runtime-verification.md`](runtime-verification.md) and
[`limitations.md`](limitations.md).
