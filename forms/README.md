# Google Form Reference

This directory provides a reproducible, sanitized intake-form design for the
Gmail Support Assistant. It contains no live Form ID, Spreadsheet ID, email
address, customer data, or account-specific setting.

Google references: [Forms response destinations](https://support.google.com/docs/answer/2917686)
and [Apps Script Forms service](https://developers.google.com/apps-script/reference/forms).

## Files

- [`google-form-spec.json`](google-form-spec.json) — machine-readable form
  title, copy, settings, fields, validation, and response-sheet contract.
- [`create-google-form.gs`](create-google-form.gs) — optional Google Apps
  Script that creates the form. It deliberately does **not** link a response
  spreadsheet.

## Form design

**Title:** お問い合わせフォーム | Gmail Support Assistant Demo

All four questions are required and kept in this exact order:

| Order | Stored header | UI meaning | Type | Validation |
|---:|---|---|---|---|
| 1 | `Name` | お名前 | Short answer | 1–100 characters |
| 2 | `Email` | 返信先メールアドレス | Short answer | Valid email address |
| 3 | `Subject` | 件名 | Short answer | 1–150 characters |
| 4 | `Message` | お問い合わせ内容 | Paragraph | 1–5000 characters |

This table is the reproducible reference contract. In the 2026-08-12 manual
UI verification, Google Forms rejected valid Subject values while the
response-length rule was enabled, so the live demo Form kept the 150-character
help text but did not enforce that rule in the Form UI. Make still validates
the input before AI processing. The Apps Script build below retains the desired
Subject validator, but that exact script-created behavior has not been
live-verified; see [`docs/runtime-verification.md`](../docs/runtime-verification.md).

Google Forms does not provide a normal placeholder property for these items,
so examples and warnings are placed in each question's help text. The stored
English titles are intentional: they produce the exact response headers that
the current spreadsheet/Make contract expects.

The form does not automatically collect the signed-in user's email. `Email`
is an explicit required field, which allows external customers to submit and
keeps one unambiguous email column. Do not enable both automatic email
collection and the explicit `Email` question without also redesigning the
sheet and Make mappings.

## Create the Form

### Option A — Apps Script

1. Open [Google Apps Script](https://script.google.com) and create a project.
2. Paste the contents of [`create-google-form.gs`](create-google-form.gs).
3. Run `createGmailSupportAssistantForm` and approve the Google Forms scope.
4. Open the edit and responder URLs written to the execution log.
5. Compare the result with [`google-form-spec.json`](google-form-spec.json).

### Option B — Google Forms UI

Create a blank Form and reproduce the title, description, confirmation
message, four questions, required flags, and validations from the table above.
Keep question order and stored titles exact.

## Connect responses without breaking the sheet contract

Google Forms can save responses to a new spreadsheet or an existing
spreadsheet, but it creates/manages a response tab; it does not append to an
arbitrary prebuilt `Form` tab. Use this sequence:

1. Keep the Make test scenario **Inactive**.
2. In the Form, open **Responses → More → Select destination for responses**.
3. Select the spreadsheet created from
   [`spreadsheet/templates/gmail-support-assistant-template.xlsx`](../spreadsheet/templates/gmail-support-assistant-template.xlsx).
4. Google creates a new response tab. Do not point Make at the old empty
   template tab.
5. Rename the old empty `Form` tab to `Form_Template` temporarily.
6. Rename Google's new response tab to exactly `Form`.
7. Confirm row 1 is exactly:
   `Timestamp, Name, Email, Subject, Message`.
8. Confirm `CRM` and `Processing_State` are unchanged.
9. Re-select the spreadsheet and `Form` tab in Make's Watch Rows module, save,
   and leave the scenario Inactive.
10. Submit one synthetic `example.com` response and use **Run once**. Inspect
    Make History before considering the connection verified.
11. After verification, the unused `Form_Template` tab may be removed
    deliberately. Do not remove it before confirming the response tab and
    Make mapping.

Changing question titles or order after linking can change the response-sheet
contract. Treat such changes as a migration: pause Make, inspect headers,
update mappings and tests, then run a synthetic verification.

If the new response tab starts at row numbers already present in
`Processing_State.Source_Row`, use a clean test spreadsheet or deliberately
migrate/archive the old state first. Do not delete or overwrite historical
state merely to force a test through.

## Privacy and UX choices

- The description states which services process the inquiry.
- The message help text warns against passwords and payment information.
- The confirmation message says AI output is reviewed and not auto-sent.
- No internal category, priority, sentiment, or routing question is exposed to
  customers; those are derived by OpenAI.
- File uploads are intentionally excluded because they require additional
  Drive permissions, malware/content handling, retention rules, and Make
  routing that the current workflow does not implement.

## Future-compatible additions

Order number, product, preferred language, attachments, consent records, and
customer history can be added later, but every new response column requires a
documented data-model and Make-mapping migration. Append new fields after the
current four unless a versioned breaking change is intended.
