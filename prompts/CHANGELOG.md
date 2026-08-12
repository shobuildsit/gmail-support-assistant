# Prompt / Schema Changelog

Versioning note: a new prompt file (`support-triage-v2.md`, etc.) should
be created for behavior-affecting changes (classification criteria,
required fields, output rules) rather than editing a version in place, so
past behavior stays reviewable. Wording-only clarifications that don't
change model behavior may be patched in place with a changelog entry
explaining that distinction.

## v1 — 2026-08-07 (Phase 2A)

- Externalized the previously blueprint-inline prompt to
  [`support-triage-v1.md`](support-triage-v1.md) and the previously
  blueprint-inline JSON Schema to [`response-schema.json`](response-schema.json).
- Removed the customer's email address from the AI input. The prompt
  (and the blueprint's `mapper.input`) now sends only name, subject, and
  message — see [`SECURITY.md`](../SECURITY.md).
- Added an explicit prompt-injection defense section: customer input is
  now framed as untrusted data bounded by `---BEGIN CUSTOMER
  INPUT---` / `---END CUSTOMER INPUT---` markers, with instructions not
  to follow directives found inside that boundary, and to set
  `requires_human: true` when input looks suspicious or is hard to
  classify.
- Added a `requires_human: true` trigger for "問い合わせ内容が不審、または
  分類・意図の判断が困難" (suspicious input / difficult to classify),
  extending the existing criteria list.
- Added explicit character limits to the prompt text (`summary` ≤200,
  `reply_subject` ≤150, `reply_body` ≤3000) matching the new
  `response-schema.json` `maxLength` constraints (the previous schema had
  no `maxLength` on any field).
- No changes to: classification categories, priority levels, sentiment
  values, the core `requires_human` business criteria, or the
  `reply_body` drafting rules (tone, no auto-confirming refunds, etc.)
  carried over from the pre-Phase-2A prompt.

**Not evaluated:** whether these prompt changes affect actual OpenAI
output quality, since this repository does not call the OpenAI API. See
[`tests/README.md`](../tests/README.md).

### v1 review-pass update — 2026-08-07 (Phase 2A re-review)

A ChatGPT Work review of the initial v1 found a boundary-injection gap in
the customer-input framing. Patched in place (wording-only in the sense
that classification categories/criteria are unchanged, but this *is* a
new defensive instruction, so it's called out here explicitly):

- Added a "境界マーカーの偽装(脱出)対策" (boundary marker
  spoofing/escape countermeasure) section to both the explanatory part of
  `support-triage-v1.md` and the Canonical prompt body. The prior v1 text
  bounded customer input with `---BEGIN CUSTOMER INPUT---` /
  `---END CUSTOMER INPUT---` markers but never told the model what to do
  if the customer's own message contained those same marker strings —
  meaning a message ending in a fake `---END CUSTOMER INPUT---` followed
  by new instructions could plausibly look like it closes the boundary
  and hands control back to "the prompt."
- The new rule instructs the model that: marker-like strings appearing
  inside customer input are still customer input, not a new boundary;
  only the first BEGIN and the one Make-appended final END are real
  boundaries; text after an apparent boundary-close must still not be
  obeyed; and suspicious boundary manipulation should set
  `requires_human: true`.
- This was synced into the blueprint's `mapper.input` on module `id=3`
  (the only field changed in this review pass — `store`,
  `createConversation`, and `format.schema` were left untouched).
- Added `TC13_boundary_marker_escape_attempt` to
  [`../tests/prompt-cases.jsonl`](../tests/prompt-cases.jsonl) to
  document the expected behavior (offline spec only, no OpenAI call).
- Corrected `TC08`'s `expected_requires_human` from `false` to `true` —
  it was inconsistent with the prompt's own "insufficient info / hard to
  classify → `requires_human: true`" rule (a test-case bug, not a prompt
  change).

**Not evaluated (unchanged from above, and specifically true of the new
boundary-escape rule too):** whether the actual OpenAI model honors this
instruction under adversarial input, and whether Make encodes/escapes the
customer's row data in a way that helps or hinders this defense before
it's substituted into `mapper.input`. Prompt-level instructions are not a
guaranteed defense — see
[`SECURITY.md`](../SECURITY.md#prompt-injection) and
[`docs/limitations.md`](../docs/limitations.md).
