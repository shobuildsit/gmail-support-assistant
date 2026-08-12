# Make.com Blueprints

This directory holds Make.com scenario blueprint(s) for the Gmail Support
Assistant automation.

## Files

- **`blueprints/gmail-support-assistant.sanitized.json`** — a sanitized
  (secret-free) export of the working scenario. Safe to publish. See
  [`mapping-guide.md`](mapping-guide.md) for exactly what was removed and
  what you need to reconfigure before this can run in your own Make account,
  and for what the OpenAI module's `mapper.input` / `mapper.format.schema`
  now look like after Phase 2A (email removed from the AI input,
  `store`/`createConversation` set to `false`, schema `maxLength` added).
- **`blueprints/gmail-support-assistant.phase2b.candidate.json`** — the
  sanitized 72-module stateful candidate built from a saved live export.
  Happy-path completion, terminal duplicate prevention, and a synthetic
  Google Form-to-Gmail-draft run were live-verified;
  blocked branches and remaining tests are listed in
  [`../docs/runtime-verification.md`](../docs/runtime-verification.md).
- **`scripts/sanitize_phase2b_blueprint.py`** — reproducibly replaces private
  connections, spreadsheet/Drive references, and Slack channel metadata in a
  private Phase 2B export. It does not redesign routes or mappings.

The OpenAI module's prompt and schema are also published, documented, and
versioned separately at [`../prompts/`](../prompts/) — see
[`../prompts/README.md`](../prompts/README.md) for how those files are
kept in sync with this blueprint. [`../tests/validate_blueprint.py`](../tests/validate_blueprint.py)
checks that sync automatically (offline, no API calls).

## What's intentionally excluded

The original, unsanitized blueprint export (and any future
`*-private.json` / `*-production.json` files) are excluded via
[`.gitignore`](../.gitignore) and are never committed to this repository.

## Importing into Make

1. In Make.com, create a new scenario and choose **Import Blueprint**.
2. Select the Phase 2A baseline or Phase 2B candidate described above.
3. Follow [`mapping-guide.md`](mapping-guide.md) to reconnect accounts and
   restore the real Spreadsheet ID / Slack channel ID.

Phase 2A import and the configured Phase 2B live workflow were verified in an
existing test environment. A completely fresh-account import remains
unverified; see the [Not verified](mapping-guide.md#not-verified) section.
