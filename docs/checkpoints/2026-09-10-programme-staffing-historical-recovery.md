# Programme staffing and retained historical host recovery

- Date: 2026-09-10 (Europe/Budapest).
- Child: [#88](https://github.com/martonpornoi/maru/issues/88), parent #48.
- Original exhaustive candidate: `24e8fd77a47fc957d9791543d135cc080be3c89b`.
- Focused test-only corrections; no migration or production behavior changes.

## Failure and exact boundary

The exhaustive run reported failures in the three host-bearing variants of
the pre-existing conversion downgrade test. A separate isolated reproduction
confirmed that its closed unused-successor set omitted Programme 0010-0012 and
Workforce 0019-0021. Django legitimately reverses those unused staffing successors
before reaching the populated host fence. Retained conversion and host evidence
must still survive unchanged.

The recovery test now names those six exact successors, alongside the existing
unused Scheduling/Venue successors, and preserves equality of every remaining
migration-recorder entry. It does not broadly allow arbitrary later migrations.

Historical host guards are inspected against the exact host contract: source,
required migrations, relation ownership, trigger/function definitions, function
execution ACL and function ownership must all remain correct. The general
catalog's `relations_installed` uses current model relations; it must be false
while the unused staffing relations are reversed. Current Programme readiness
also must remain false. Reapplying the current graph restores complete readiness
while preserving the same conversion binding and host version.

The standalone retained-host test exercises the same distinction and now checks
the retained host again after explicit reapply. No database guard, readiness
implementation, timeout, coverage threshold or recovery fence is weakened.

## Evidence and remaining work

All six conversion variants (three downgrade targets, with/without a retained
host) and the standalone host fence/reapply case passed together: **7 tests in
928.25s (15m28s)** on the separately owned synthetic PostgreSQL fixture. Focused
Ruff formatting/lint and whitespace validation pass. The run overlapped the
eight-database exhaustive diagnosis; its duration is not a standalone benchmark.

The original full run continues only to reveal any additional failures. It has
failed acceptance and cannot certify the repaired working tree. Review its full
failure inventory and diagnostic coverage, finish any remaining focused repairs,
then certify one new clean commit before protected PR delivery. #88 and #48 stay
open, and no Programme profile, route or runtime writer is activated.
