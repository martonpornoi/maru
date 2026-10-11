# Checkpoint: Announcements setup-only admission

- Date: 2026-10-10
- Phase: Standalone Announcements review repair; fresh protected acceptance pending
- Related requirements: ANN-007, EVT-006 and NFR-013
- Related ADRs: 0080 and 0117
- Review baseline: `dccd7dcd9c43198b7864b9aed135e667c394d43b` on PR #210

## Outcome and decisions

The shared edition selector previously offered `announcements_only` through generic
HTML and API creation. That path could create an edition without the dedicated
setup's representation and complete receipt. The generic choices now omit that
profile. The shared command requires the existing private Announcements setup
writer scope before persistence; the dedicated command opens it only around its
child edition creation. No public bypass flag is introduced, and authority remains
checked before the setup-specific refusal.

Generic Announcements retries also direct callers to **Set up Announcements**.
The dedicated command retains complete receipt replay with current actor and exact
supported-profile admission, independently of today's new-selection mapping. The
existing immutable profile and persisted read choices remain unchanged. A failed
child creation resets the scope and cannot leave later generic calls admitted.

The Events 0019 migration descriptions now state that it adds persisted Announcements
profile choices, the supported-pair constraint and retained setup receipts. Its
operations are unchanged. This enforces ADR 0117 rather than superseding it.

## Verification

Four focused regressions first failed against the review baseline: Announcements
was offered by the generic form, and service/API/HTML channel requests reached
persistence without setup admission. After repair, the bounded setup/adoption batch
passed **257 database-free cases in 2.02 seconds**. It includes actual HTML and API
adapter refusal, direct command refusal, dedicated setup calling the real child
command with mocked persistence, representation/receipt composition, exact setup
replay and scope reset on failure. These are application proofs, not PostgreSQL
transaction or native guard acceptance.

Focused strict mypy passed for all six changed source modules. Ruff lint and
formatting, NumPy docstrings and semantic Python documentation passed. Documentation
references passed for 720 Markdown files, four repository skills and 218 requirements.
OpenAPI regeneration validated with zero schema errors (existing nonfatal enum
naming and local invitation-encryption warnings remain). The generated TypeScript
contract separates generic creation choices from retained read choices, and the
installed TypeScript compiler passed. The pinned pnpm launcher refused its automatic
dependency check without a TTY; the already-installed generator and compiler were
then invoked directly without changing dependencies, configuration or CI mode.

Native regressions now cover generic rendered choices, crafted browser/API posts
and absence of partial edition, receipt, audit, domain-event and outbox writes.
Existing native dedicated-setup tests retain successful minimal setup, representation,
complete receipt and replay coverage. No pre-existing integration fixture directly
creates an Announcements edition through the generic service.

## Data, migration and deployment notes

No migration operation, schema guard, runtime permission, profile manifest or
recovery policy changes. Historical migration and failed/interrupted certification
evidence remains preserved. This repair creates no new external effects or
unrelated module records and does not activate a production profile.

## Incomplete work and next action

Native tests were not executed during this repair. Freeze and independently review
the coherent change, then run a fresh full exact-commit required certification and
hosted acceptance before protected delivery. Earlier commit-specific receipts do
not certify the changed source. Independent human, accessibility, operational and
production acceptance retain their existing separate limits.
