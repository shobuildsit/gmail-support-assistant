# Architecture

## Overview

Gmail Support Assistant turns a Google Form submission into an AI-triaged CRM
record, a Slack notification, and a Gmail reply **draft**. The repository
contains two sanitized Make Blueprints:

- [`gmail-support-assistant.sanitized.json`](../make/blueprints/gmail-support-assistant.sanitized.json) —
  the Phase 2A five-module baseline.
- [`gmail-support-assistant.phase2b.candidate.json`](../make/blueprints/gmail-support-assistant.phase2b.candidate.json) —
  the stateful Phase 2B candidate, with routers, re-fetches, completion flags,
  and a common idempotency gate.

## Phase 2B data flow

![Phase 2B system architecture](diagrams/system-architecture.svg)

The SVG is a public-safe architectural view. It is intentionally reconstructed
from the verified workflow instead of capturing private live-account screens.

```text
Google Form → Form sheet → Make Watch Rows
                              │
                              ▼
                  derive Request ID + find state
                              │
                 terminal? ───┴─── yes → stop
                              │ no
                              ▼
                    validate / mark PROCESSING
                              │
                 AI saved? ───┴─── no → OpenAI → persist AI_*
                              │ yes
                              ▼
                   re-fetch Processing_State
                              │
                   CRM_Written?       → CRM
                   Slack_Notified?    → Slack
                   Gmail_Draft_Created? → Gmail draft
                              │
                              ▼
                         COMPLETED
```

`Processing_State` is the source of retry decisions. OpenAI output is
persisted before downstream side effects, and every downstream branch reads a
fresh state row rather than depending on transient output from the OpenAI
module. Completed flags allow a retry to skip work that already succeeded.

## External components

| Component | Role |
|---|---|
| Google Forms | Inquiry intake |
| Google Sheets `Form` | Source rows |
| Google Sheets `Processing_State` | Request state, persisted AI output, completion flags |
| Google Sheets `CRM` | Support record |
| Make.com | Triggering, routing, state transitions, and orchestration |
| OpenAI | Structured classification and reply drafting |
| Slack | Internal notification |
| Gmail | Human-reviewable reply draft |

The OpenAI input uses name, subject, and message—not the dedicated email
column. Email remains available to the CRM, Slack, and Gmail steps. See
[`docs/data-model.md`](data-model.md) and [`SECURITY.md`](../SECURITY.md).

## Idempotency model

The Request ID and `Processing_State` row provide practical replay protection:

1. A common pre-validation gate looks up the Request ID.
2. Terminal states stop before OpenAI or external side effects.
3. A retry reuses persisted `AI_*` values when `AI_Completed = true`.
4. `CRM_Written`, `Slack_Notified`, and `Gmail_Draft_Created` independently
   suppress completed work.
5. Finalization re-fetches state before setting `COMPLETED`.

Live verification confirmed terminal duplicate prevention and the normal
completion path, including a Form-originated success and its terminal replay.
It did not establish strict exactly-once behavior under
concurrency. Several abnormal and validation routes remain explicit blocked
branches; see [`docs/runtime-verification.md`](runtime-verification.md).

## Safety property: drafts, not sends

Every Gmail module is `google-email:createADraft`. No send-email module exists
in either published Blueprint. A human must review and send the draft. Any
automatic-send change is a breaking change to the project's safety model.

## Baseline comparison

The Phase 2A Blueprint is intentionally retained as a small teaching artifact
and historical baseline. It is a linear chain:

```text
Watch Rows → OpenAI → CRM → Slack → Gmail draft
```

It imported and ran successfully, but replay after partial success can repeat
earlier side effects. New deployments should evaluate the Phase 2B candidate
and its documented limitations rather than treat the baseline as resilient.
