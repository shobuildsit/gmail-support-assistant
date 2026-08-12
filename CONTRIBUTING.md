# Contributing

Thanks for your interest in this project. It's primarily a portfolio/
reference project, but improvements are welcome.

## Ground rules

- **Never commit secrets.** No API keys, OAuth tokens, service account
  files, `.env` files, real connection IDs, real Spreadsheet/Drive IDs, or
  real Slack channel IDs. See [`SECURITY.md`](SECURITY.md) and
  [`.gitignore`](.gitignore).
- **Never commit real customer data.** Use `example.com` email addresses
  and clearly fictional names/messages in any sample data, tests, or
  screenshots.
- **Preserve the draft-only Gmail behavior.** Do not submit changes that
  make the Gmail integration send email automatically without extensive
  discussion — see
  [`docs/architecture.md`](docs/architecture.md#safety-property-drafts-not-sends).
- **Don't claim things are verified that aren't.** If you add or change
  setup steps, only describe them as tested if you actually ran them
  end-to-end. Otherwise, flag them as unverified (see
  [`docs/limitations.md`](docs/limitations.md) for the current list).

## Making changes

1. Fork and branch from `main`.
2. Keep changes focused — separate unrelated fixes into separate PRs.
3. If you change the Make blueprint
   (`make/blueprints/gmail-support-assistant.sanitized.json`), update
   [`make/mapping-guide.md`](make/mapping-guide.md) to match, and confirm
   the file still parses as valid JSON.
4. If you change the spreadsheet structure, update
   [`docs/data-model.md`](docs/data-model.md) to match.
5. Open a PR describing what changed and, if applicable, how you tested
   it.

## Questions

Open an issue if something in the docs is unclear or you're unsure whether
a change fits the project's scope.
