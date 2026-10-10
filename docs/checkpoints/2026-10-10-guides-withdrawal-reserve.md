# Guides withdrawal reserve and clearer consequences

Date: 2026-10-10\
Status: Source repair and focused feedback complete; fresh native proof pending

## Bounded change

Starting from preserved `ba5c83e1386dc18fdbcd5aaf23bdc02d06fc3e1e`, the reviewed
eight-path reserve patch and three-path wording patch were applied without
overlap. KNO-011–012, ADR 0118 and the Knowledge module now specify an 8 KiB
withdrawal receipt allowance within the unchanged 8 MiB retained-evidence cap.
Normal writes must leave it available; withdrawal may spend it. New work after
withdrawal must reserve it again. Exact successful retries remain free.

K0002 checks actual final retained state and the persisted head, rather than the
individual deferred receipt's operation. This permits ordinary work followed by
withdrawal in the same outer transaction without demanding the reserve twice.
The 256-revision state machine remains below the 4,096 item-command limit; no
count cap, general reserve framework, table, role, grant or runtime generation
was added. Readiness derives the edited guard source directly; schema and
observation pins are unchanged. An old installed migration does not receive new
SQL from a source edit. Already-full legacy states cannot recover unavailable
space without a separately reviewed path; no deletion or cap increase is implied.

The **Remove guide from readers** page names the admitted affected copy, explains
current/stopped/unpublished states and warns that pending review ends. It
discloses neither private bodies nor review feedback. **Removed from readers**
is the visible status; the outcome says history is kept. Form/access labels and
the walkthrough use the same wording. Backend status, operation and capability
identifiers are unchanged. Restoring a guide requires a new saved version and
review; resuming Guides alone does not restore it.

## Verification and prepared native proof

The last full baseline run passed **14,160 units in 76.25 seconds** (wrapper
80.625) at ba5, with three existing warnings. Its immutable evidence is under
`.tools/guidance-development/frozen-units-20261010/`. That run, prior handbook
checks, the 44-case native workflow and eight-case recovery selections, and the
genuine restricted-runtime command journey all predate this repair.

Installed focused feedback passed **117 cases in 1.83 seconds**. Scoped Ruff,
formatting, mypy (three production files), pydoclint and semantic documentation
checks passed. The final plain-language refinement then passed 60 affected
view/form/access cases in 1.28 seconds, with scoped Ruff, formatting, mypy,
pydoclint and semantic documentation checks. The updated K0002 parser contract closes 18 triggers and three
functions; this proves source structure, not installed PostgreSQL behavior.

Two real-command native tests are collected with actual fixture closure and
fixture/database setup forbidden. They approach the actual byte cap through
ordinary revisions, then cover refused growth with the old approved copy kept,
maximum legal withdrawal reason, exact retry without new rows, complete private
export within 16 MiB, and ordinary write plus withdrawal in one transaction.
The denial snapshot includes every Knowledge row and Audit/Effects evidence;
equality is checked after the command savepoint unwinds but before protective
test cleanup. Fault injection bypasses only the application byte callback to
isolate the native refusal. No native guard or authority is bypassed.

The export assertion compares every retained guide revision and item receipt ID,
including withdrawal, before the retry snapshot. This later test-only refinement
was recollected and linted; the two native cases remain **unexecuted**. The actual
public command uses Audit's valid 40-character source input. Guidance's separate
41–80-character producer/consumer mismatch remains an unapplied finding. A
currently admitted public command caller can supply that longer source through
`GuidanceRequest`, then fail Audit's narrower validation and roll back. Ordinary
UI commands use `knowledge-html`; the separate finding is retained in the ignored
proposal's `source-channel-finding.md`, not repaired by this reserve change.

## Complete selection and evidence

The active planner assigns all 384 groups exactly once across 87 shards, at most
two historical groups per shard and eight workers. Predicted maximum duration
is 3,594.181 seconds under the unchanged 3,600-second target. The new current
group uses the largest-known group fallback of 1,573.166 seconds. The diagnostic
file map adds 6,288.322 seconds under its existing largest-known policy. Both are
**unmeasured estimates**, not runtime observations; no timing gate was weakened.

All integration evidence is retained under
`.tools/guidance-development/withdrawal-reserve-integration-20261010/`: exact
patch hashes and before/after inventories, protected fixture hashes, command
logs, collection/fixture closure, planner output, static results and final freeze.
The first ignored planner verifier failed because its Counter comparison used
dictionary values rather than keys; its script/log remain intact. The corrected
verification passed without changing tracked planner code or policy. The export
assertion's first lint run found one 90-character line; its retained failure was
resolved by wrapping that line, then lint/format and collection passed. Final
documentation validation and whitespace checks are recorded with the freeze.

The original proposals remain under the original checkout's
`.tools/guides-withdrawal-reserve-20261010/tests-v1/` and this checkout's
`.tools/guidance-development/withdrawal-ux-proposal-01/`. No prior result is
rewritten. The stopped synthetic runtime fixture and seven harness inputs were
untouched. No database, Docker, browser, server, role provisioning, full unit
rerun or certification was performed in this batch. Downstream checkouts retain
their frozen K0002 until deliberate propagation and new appropriate evidence.


## Follow-up: native reserve proof and source-channel admission

The later parent-owned run in
`.tools/guidance-development/native-withdrawal-reserve-20261010/native-reserve-20261010T004034Z-953e3597/`
passed **two cases in 326.98 seconds**, with a **333.219-second wrapper**. The exact
owned container `44e9fd42253fd1c884601545bbe175ec562ad29e9a9e2aa7d189f18e4a11b917`
was removed. Source before/after remained
`56a4f93b03eab68a35fe8dca521fb8838723f9f2aa6721c344ebe3ae2ab4dc5d`.
The result covers the retained-byte/native-guard cases described above, including
exact retry and same-transaction final withdrawal. It is migration-owner evidence,
not restricted-login, browser, full certification or production acceptance.
This isolated run is not complete calibration evidence, so the existing timing
fallback and planner policy remain unchanged.

After that run, the reviewed limit-only source-channel patch was applied from
the original checkout's `.tools/guides-source-channel-proposal-20261010-r02/`;
patch SHA256 is
`19d55cbe964862df6ec26e2f63d8827cc76a19f2218ae600fac7e23a66a478f3`.
The earlier unapplied proposal and failures remain intact. New command attribution
is now limited to 40 Unicode characters, matching the unchanged Audit record.
The existing noncanonical-input error and exact retry behavior are preserved;
no normalization, truncation or Audit capacity increase was introduced. An AST
comparison restoring 80/removing the named constant matches the original command
support exactly. The public DTO and owning contract document the bound; the
fixed `knowledge-html` browser value is unaffected. The historical receipt field
and conservative reserve accounting retain 80 characters.

The native reserve result predates this input-admission correction. No model,
migration, SQL, source/schema/function pin, runtime privilege or root route was
changed by it. The stopped genuine-runtime fixture, its retained volume/accounts
and all seven harness inputs remain untouched; no resource command was run during
this correction. Focused installed checks and final source inventories are in
`.tools/guidance-development/source-channel-admission-20261010/`. Full exact-commit
certification and authenticated browser acceptance remain pending.


### Installed source-admission verification

The installed attribution, domain and reserve unit files passed **79 cases in
0.75 seconds** (2.641-second wrapper). All three database connection entrypoints
were forbidden and recorded zero calls. Scoped Ruff/format, strict typing of the
two production files, pydoclint, semantic Python-docstring validation,
documentation validation and `git diff --check` passed. Source before/after the
checks was identical. The 17 new attribution cases cover the 40/41-character
boundary, unchanged noncanonical errors, rejection before writes/retry lookup,
unaltered exact retry and current authorization, including multibyte text.

The final inventory and complete uncommitted diff are retained beside those
logs in `.tools/guidance-development/source-channel-admission-20261010/`.
The Unreleased changelog now describes the whole Guides evaluator journey.
The preserved native reserve run remains earlier evidence; no new native,
browser, resource, full-unit or certification run was performed for this fix.
