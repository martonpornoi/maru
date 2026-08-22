# What works today?

**Audience:** Evaluators, contributors, and operators\
**Outcome:** Distinguish current behavior from partial, proposed, and historical
material\
**Reading time:** 7 minutes

Maru is under active development. It is not yet a supported hosted service, a
PyPI package, or approved for production personal data. A green repository gate
proves the checked behavior described by that gate; it does not by itself prove
deployment readiness, accessibility, recovery, or operational ownership.

## How to read status claims

| Term | Meaning |
| --- | --- |
| **Implemented or mounted** | Executable behavior exists in the current application and has the stated repository evidence. |
| **API-only** | A supported service or endpoint exists, but a complete current browser journey may not. |
| **Partial** | A useful slice exists, while named workflows or acceptance evidence remain open. |
| **Preserved or historical** | Material remains as design or behavior evidence but is not the supported current route. |
| **Proposed or planned** | Direction or acceptance intent, not implemented behavior. |
| **Deployment-gated** | Repository behavior exists, but production-shaped operational evidence remains incomplete. |

## Current shape

The current application has a tested Django/PostgreSQL foundation, scoped
authorization, audit and outbox boundaries, one management shell, generated
OpenAPI and Python references, and several implemented product slices. Important
production gates remain open, including broader authenticated accessibility and
visual evidence, representative recovery and point-in-time recovery, deployment
rehearsal, and accountable production ownership.

Use these maintained sources instead of inferring status from an old tutorial or
checkpoint:

1. [Current project state](../project/CURRENT.md) — the maintained handoff and
   most recent verification.
2. [Production-consolidation ledger](../project/PRODUCTION_CONSOLIDATION.md) —
   the detailed implemented/API-only/partial/absent/deployment-gated inventory.
3. [Roadmap](../project/ROADMAP.md) — outcome sequence and remaining work.
4. [Requirements](../product/requirements.md) — stable behavior and acceptance
   intent.

Decision records and checkpoints explain *why* the project reached a state;
they do not override these current sources. Find them in
[reference and history](../reference/index.md).

**Next:** [Run Maru locally](run-locally.md).
