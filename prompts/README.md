# Prompts

This directory is the reviewable, version-controlled source for the AI
prompt and output schema used by the OpenAI module (`id=3`,
`openai-gpt-3:createModelResponse`) in
[`make/blueprints/gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json).

## Files

- **[`support-triage-v1.md`](support-triage-v1.md)** — the prompt,
  documented (role, task, allowed classification values, priority/
  sentiment/`requires_human` criteria, reply rules, prohibitions,
  prompt-injection handling, output schema mapping, version). The
  canonical prompt text is the fenced ```` ```text ```` block under its
  "Canonical prompt body" heading.
- **[`response-schema.json`](response-schema.json)** — the JSON Schema the
  OpenAI structured-output response must satisfy. Standalone, valid JSON
  Schema (openable/lintable on its own).
- **[`CHANGELOG.md`](CHANGELOG.md)** — prompt/schema version history.

## Why this exists (vs. editing the blueprint directly)

Before Phase 2A, the prompt and schema only existed inline inside the
Make blueprint's JSON, as escaped strings — effectively unreviewable in a
PR diff and impossible to unit-test offline. Externalizing them here
makes the prompt readable, diffable, versionable, and testable
independently of Make.

## Keeping this in sync with the blueprint

There are two pieces of "truth" that must stay substantively identical to
their counterparts in
[`make/blueprints/gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json):

| Source of truth here | Must match in the blueprint |
|---|---|
| `support-triage-v1.md` → the fenced code block under "Canonical prompt body" | Module `id=3` → `mapper.input` (as a JSON string, so newlines are `\n`-escaped there) |
| `response-schema.json` (the whole file, parsed as JSON) | Module `id=3` → `mapper.format.schema` (stored **double-encoded**: it's a JSON string whose contents are themselves the JSON Schema text) |

**Double-encoding note:** Make stores `format.schema` as a *string*
containing JSON, not as a nested JSON object. Concretely,
`json.loads(module["mapper"]["format"]["schema"])` must equal
`json.load(open("prompts/response-schema.json"))`. If you hand-edit either
side, re-parse both and diff them — a byte-for-byte string compare across
the two layers of encoding is not meaningful, but the two *parsed*
objects should be.

**How this is verified today:** [`tests/validate_blueprint.py`](../tests/validate_blueprint.py)
checks both of the following on every run (no OpenAI/Make network calls —
pure static comparison):

1. The exact text of the "Canonical prompt body" fenced block in
   `support-triage-v1.md` equals `mapper.input` on module `id=3`.
2. The parsed JSON Schema in `response-schema.json` equals the parsed
   contents of `mapper.format.schema` on module `id=3` (enums, required
   list, `maxLength` values, and `additionalProperties: false` included).
3. Each `maxLength` (`summary` 200 / `reply_subject` 150 / `reply_body`
   3000) additionally matches a fixed expected value, independent of
   check 2 — so a change that loosens a limit identically in both
   `response-schema.json` and the blueprint at the same time still gets
   caught, rather than only catching the two copies drifting apart from
   each other.

Run it with:

```sh
python3 tests/validate_blueprint.py
```

## If you change the prompt or schema

1. Edit `support-triage-v1.md` (the fenced "Canonical prompt body" block)
   and/or `response-schema.json` first — these are the source of truth.
2. Update `make/blueprints/gmail-support-assistant.sanitized.json`'s
   `mapper.input` / `mapper.format.schema` on module `id=3` to match.
3. Add an entry to [`CHANGELOG.md`](CHANGELOG.md) and bump the version
   (e.g. `support-triage-v2.md`) if the change is behavior-affecting, per
   the versioning note in that changelog.
4. Run `python3 tests/validate_blueprint.py` and fix any mismatch it
   reports before committing.

This repository does not call the OpenAI API, so no automated check
verifies the prompt actually produces good completions — see
[`tests/README.md`](../tests/README.md) and
[`docs/limitations.md`](../docs/limitations.md) for what `tests/` does
and does not cover.
