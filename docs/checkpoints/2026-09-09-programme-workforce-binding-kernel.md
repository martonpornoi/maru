# Programme to Workforce binding kernel checkpoint

Date: 2026-09-09
Scope: local [#88](https://github.com/martonpornoi/maru/issues/88) continuation,
under HR-015 and ADR 0093. No PR, hosted acceptance, merge or activation.

## Implemented

- Typed exact create/link/reconcile/successor intent and independently authorized
  preview/apply. The preview includes current Programme/Scheduling source, work
  terms, binding/demand versions and retained/active counts; it grants no authority
  and is recomputed under canonical owner locks. A new claim changes the impact
  even when the demand version stays unchanged.
- Existing Workforce commands perform every demand mutation. Linking identical
  uncommitted work does not rewrite it. Reconciliation needs a genuinely
  uncommitted draft. Successors preserve old demand/decisions, cancel only through
  Workforce, and create separate drafts without copied claims or confirmations.
  Independent read authority remains required, including for matching retries.
- Retained Workforce binding identity and immutable source/retry/effect revisions,
  bounded at 1,000. Demand lineage cannot be borrowed or silently reassigned.
  Shift/cancellation receipts are one-to-one and cannot certify a second binding
  revision; reconciliation advances the owner work version.
- Workforce migrations `0019`–`0021`: native schema, closed scope/source/work/receipt
  guards, reciprocal audit/event/outbox evidence, no-truncate protection and a
  populated downgrade fence. Runtime provisioning remains SELECT-only; exact
  authorization readiness pins six new triggers and three new functions. Binding
  audit/events use the existing Workforce restricted-retention class.
- Source selection now explicitly rejects an inactive owning Programme item,
  not only a retired requirement or stale occurrence/candidate/day.

## Verification actually performed

- Full fast suite: **4,202 unit tests passed in 23.92s**, with two pre-existing
  Django URLField default-scheme warnings.
- Binding commands: **19 PostgreSQL cases passed in 80.26s**. These exercise real
  owner commands, exact retries, source movement, retained claims/confirmations,
  claim-after-preview detection, full successor rollback, competing first
  bindings/retries and raw update/delete/truncate rejection.
- Integrity/recovery: **six PostgreSQL cases passed in 32.75s**, covering forged
  private sources, reused work revisions, disabled-trigger readiness, populated
  downgrade refusal and an unused round trip preserving Programme requirements.
- Strict Mypy, focused Ruff and semantic NumPy-docstring checks passed during
  implementation; Django reports no model/migration drift. Documentation checks
  passed before this checkpoint was added. Exact new function fingerprints were
  read from the migrated disposable database, not guessed.

The checks reused the task-owned synthetic PostgreSQL database. The volunteer
fixtures explicitly use the existing full-convention Participation setup; they
are not a Programme-only exclusion or runtime-activation rehearsal. The empty
binding graph was genuinely reversed and reapplied while refining unpublished
migrations; no migration was faked and no retained history bypassed its fence.
Conservative CI timing estimates remain scheduling input, not calibration claims.

## Still incomplete

Binding/history projections, independently authorized exact-source Scheduling
coverage, native staffing/recovery UI and browser acceptance remain unfinished.
Complete issue-level certification and exact-head protected delivery are also
pending. #88 and umbrella #48 remain open; #87 and the later release, continuity,
setup and integrated Programme-only acceptance remain activation gates. There is
no approved Programme runtime writer, production data or general Docker cleanup.
