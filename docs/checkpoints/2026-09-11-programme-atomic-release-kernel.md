# Checkpoint: dormant independent approval and atomic Programme release

- Date: 2026-09-11
- Phase: Programme Operations foundations, pre-certification milestone
- Issue: [#96](https://github.com/martonpornoi/maru/issues/96), child of #48
- Requirements: SCH-004, SCH-007, SCH-010, SCH-012, PRG-008, HR-014, HR-015,
  AUD-001 and NFR-001/002/005/008/009/013
- Decision: [ADR 0096](../architecture/decisions/0096-atomic-programme-release-and-invalidation.md)
- Base: protected #95 squash `413997c938de86daa88dc626f70389c5b84af36a`

## Outcome and decisions

Scheduling can independently approve one exact current candidate with complete
trusted owner evidence and authenticated release-warning acknowledgements.
Retained copy/restore authorship remains an exclusion after edits or departure.
A separately authorized publisher, distinct from the approver, verifies the
mandatory minimized canonical artifact before advancing one monotonic pointer.
Release, prior identity, bounded impact, artifact, receipt, audit and effects
commit atomically. Reasoned withdrawal preserves immutable history and retry
identity; neither release action silently changes accepted volunteer work.

Native Identity, Programme, Workforce, Events and Venue changes govern exact
tracked dependencies in their own transaction. A closed append-only generation
journal avoids taking unrelated release pointers during privacy withdrawal.
Database-owned time determines operational consequences against immutable ends;
disclosure has no historical expiry. Native Audit witnesses establish current
transaction attribution, never permission or business eligibility. Raw-DML,
readiness and runtime checks remain separate required boundaries.

Programme supports independent Ready/Live public-copy revalidation without
reopening private editing, plus immutable exact-copy withdrawal. Newest-copy
reads never fall back to older wording. Checked current/history manifests require
independent capability and field ceilings, final reauthorization and sensitive-read
audit; missing artifacts or incomplete journal evidence withhold selections.
Stored bytes are not current disclosure authority.

Published confirmed host presence participates in reciprocal work/rest protection
with Workforce claims under canonical person serialization. The minimized source
returns no foreign calendar, convention identity or rationale. Room/copy invalidation
does not silently cancel that commitment. Deliberate release replacement/withdrawal
or governed host relationship ending changes it; private alternatives do not.

## Changed boundaries

The owner graph adds Scheduling review/release/journal state, Programme copy
withdrawal and opt-in Audit witnesses, with cross-owner source guards. Runtime
relations remain SELECT-only; the native journal writer and Audit capture are
the explicitly listed definer exceptions. Source-pinned readiness verifies exact
schema, functions, supporting triggers, recorders, owners, search paths and ACLs.
Scheduling 0020 fences used evidence at the top of the release extension.

Requirements, module contracts, privacy/retention guidance, ADR index, roadmap
and [recovery runbook](../operations/programme-atomic-release-migration-and-recovery.md)
are updated. The real recovery functions are declared historical with all
participating owners. New diagnostic file weights use the existing median;
authoritative unmeasured groups retain their largest-known fallback. No measured
weight, test, threshold or protected gate is reduced.

## Verification at this milestone

- All 4,669 database-free unit tests passed. Ten earlier failures exposed stale
  catalog inventories, historical target dependencies and an obsolete receipt
  mock. Repairs preserve exact catalog checks and keep historical targets from
  reintroducing explicitly removed owners.
- All 270 tests in the 25 new PostgreSQL files passed together in 16m17s on the
  isolated synthetic database, including real commit/rollback races, native
  source changes, independent review/publication, raw-DML, runtime and recovery.
- A final 27-case group passed in 1m49s: prior-release artifact/pointer retention
  after preparation, verification and late audit failure; competing same-pointer
  publications; and existing Programme query behavior. This overlaps the earlier
  group and is not a combined distinct-test count.
- Focused foreign-host publication and Workforce races cover both lock-wait and
  rollback orders. Physical-property races use two genuinely separate edition
  selections of the same room. Checked-manifest tests verify one statement for
  complete generation/range observation and reject missing journal reads or
  overflow. Real-clock past-history tests distinguish approved history from
  attendance, current disclosure and fresh-release eligibility.
- Genuine runtime logins retain SELECT-only access to every new relation and
  reject work conflicting with a populated foreign published host. Native
  readiness and ordinary unused reverse/reapply pass; used evidence refuses
  contraction without removing migration records.
- Fresh-cache strict typing passed 534 source files. Formatting/lint, semantic
  Python documentation and NumPy docstrings passed. Documentation validation
  passed before this checkpoint was added and will be repeated in certification.

These are focused and whole-unit working-candidate results, not exact-commit
certification, protected hosted acceptance, production approval or a completed PR.

## Recovery evidence and explicit limitation

A same-image PostgreSQL 17.11 physical backup restored a populated release into
an isolated tmpfs clone. Exact readiness and retained manifest/artifact passed;
a fresh native copy withdrawal invalidated checked selections and exact retry
produced no duplicate consequence. The source remained unchanged. Earlier clone
startup failures came from archive-copy handling; native extraction corrected
the harness. Only exact label/ID-verified disposable resources were removed.

Three same-image logical dump/restore attempts instead reproduced an existing
array-cast CHECK-expression rendering mismatch. Native function/trigger/ACL and
recorder checks passed, but exact relation readiness failed. Nothing was waived
or blindly rebaselined. Native child [#97](https://github.com/martonpornoi/maru/issues/97)
owns supported logical recovery and negative weakened-constraint tests before
activation or the director pilot. Physical recovery is not logical or production
backup/PITR acceptance.

## Remaining gates and next actions

Certify the clean exact candidate, obtain its independent protected PR gate and
CodeQL results, then use the authorized squash flow and reconcile issues/main.
The milestone itself does not authorize bypass or establish merge success.
Next #48 work is shared role-specific outputs/change impact, continuity, guided
setup and integrated acceptance, retaining the #97 recovery prerequisite.

No current adoption profile, route, runtime writer, public output or worker is
activated. No Registration, Participation, payment or attendance state is created.
Manual #92 remains deferred, not passed or waived. No production data/deployment,
model escalation, schedule, general Docker cleanup or unrelated worktree change
is part of this milestone.
