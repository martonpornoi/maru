# Dormant Programme notice commands and genuine personal detail

Date: 2026-09-13. Branch: `codex/programme-change-communication`, following local
schema/preview commit `155f796`. This is a local implementation checkpoint inside
#104, not a new delivery item, protected PR, completed #104 or activated profile.

## Implementation boundary

Scheduling now owns dormant preparation, explicit independent approval/rejection,
manual handoff and exact-recipient acknowledgement commands. Each has its own
closed capability/operation and uses the existing atomic edition control,
immutable receipt, native audit witness and minimized event stream. Preparation
stores exact source/purpose references, not copied messages or contact details.
Subsequent facts use the notice's optimistic evidence version. Self-acknowledgement
accepts no free-text explanation; it uses a fixed code-owned action reason and
does not imply attendance, accepted work or provider delivery.

After current owner/person admission, the writer requires read-committed isolation,
locks the complete current/predecessor dependency-key union in kind/source order,
and verifies the exact generation-use digest without acquiring more owner-source
locks. A legitimately shared dependency may have several placement/horizon uses;
the earlier preview uniqueness mistake is corrected with a regression test.
No migration or observed schema fingerprint changes are required by this fix.

The shared executor now requires a replay validator for each closed notice
operation. Matching retries still require current authority, exact current source,
eligible recipient purpose and matching retained notice/fact, followed by the
generation freeze. They return the original identifier-only receipt without
repeating the already-recorded lifecycle transition. Changed retry intent remains
an idempotency conflict; stale or revoked purpose cannot be grandfathered.

Restricted sender detail and genuine personal detail independently reauthorize
source disclosure. Personal detail admits only one's own approved package, excludes
other actors, and never fetches organizer rationale for its projection. Receipt
equality is checked as a scoped database boolean; rationale columns remain deferred
for personal reads. Changed sources fail closed rather than serving old content.

## Verification actually performed

- Final non-database unit suite: **5,505 passed**, **47.83s**, two existing
  Django URLField warnings. Report:
  `.tools/issue104-notice-commands-checkpoint.xml`.
- Focused source/command privacy checks: 72 passed in 0.59s. Earlier combined
  source/command/lifecycle focus: 118 passed in 0.66s, before the final five
  rationale/receipt-projection assertions were added.
- Strict mypy: 574 source files. Ruff formatting/lint and focused docstrings pass.
- Semantic documentation: 595 sources. Documentation structure passes.
- The maintained operator integration module collected 14 cases successfully.
  Collection did not execute tests or database fixtures. Its existing synthetic
  lifecycle cases now include preparation, independent review, acknowledgement,
  handoff, exact retries, wrong-self rejection, event-failure rollback, raw
  immutable-row rejection and stale acknowledgement replay after withdrawal.

**No PostgreSQL suite, fixture workflow, container, schema-only run, runtime
provisioning or database certification executed in this continuation.** Integration
assertions are maintained but unexecuted #102 debt. The earlier schema-only
observation remains limited to its documented forward metadata; native behavior,
reverse/reapply, races and logical restore are not accepted by this checkpoint.
Active measured timing weights and their provenance remain untouched.

## Remaining delivery work

Complete the maintained native negative/race scenarios, then implement the
page-contracted same-shell sender and genuine-personal journeys with bounded
discovery, explicit stale/rejected states, visible rationale where privileged
decisions are made, and current timetable navigation. Defer required human checks
under #92/#48 as authorized; do not fabricate browser or screen-reader evidence.
Certify the complete exact #104 head in deferred mode, pass protected hosted gates,
merge and reconcile #104/#48 before moving to #107/#108. #102 database restoration,
#97 logical recovery and #109 integrated proof remain mandatory before activation.
