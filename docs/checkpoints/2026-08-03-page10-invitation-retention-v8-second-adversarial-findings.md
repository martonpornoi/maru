# Page 10 invitation retention v8 second adversarial findings

Date: 2026-08-03

## Verdict

Independent review **rejected** retention v8 despite green focused readiness,
runtime-role, migration, and ordinary retention matrices. This checkpoint is
append-only evidence and supersedes no earlier findings.

## Verified baseline

- Retention focus: 28 passed; exact readiness: 165 passed; runtime-role matrix:
  119 passed.
- Empty `0018 -> 0017 -> 0018`, populated downgrade fence, ten SECURITY
  DEFINER ACL/search-path checks, 50 function fingerprints, 74 trigger
  contracts, 16 index contracts, migration drift, strict mypy, and Ruff lint
  passed.
- Ordinary tombstone, arbitrary challenge-history, fairness, duplicate-policy,
  source-allowlist, command-error, and false-assessment cases passed.

## Seven release blockers

1. Scheduler heartbeat/cursor rows have no INSERT-time PostgreSQL clock and
   coherence guard. A direct row 250 milliseconds in the future committed.
2. Public service parameters can backdate policy activation and disposal
   receipt, tombstone, audit, assessment, and heartbeat evidence instead of
   materializing one actual database timestamp.
3. A legitimate v7 provider value already shaped
   `disposed-provider-11111111111111111111111111111111` makes migration `0018`
   fail before every parent/attempt/late reference changes.
4. Active holds are filtered out before inspection, so `held_count` remains
   zero, no current `active_hold` assessment is recorded, and fair cursor
   traversal cannot explain the held row.
5. A terminal `disposed` assessment can still be raw-updated to an arbitrary
   later version and timestamp.
6. Parent delivery evidence can still receive raw aggregate-version and
   timestamp updates after its one receipt-bound disposal transition.
7. The adjacent matrix is 76/78 and the invitation-query matrix is 6/7 because
   helpers still address a removed combined delivery trigger; three retention
   files also fail the format check.

## Required next evidence

Retention v9 must close each direct probe, update the exact readiness and
runtime-role catalogs, pass the pattern-shaped populated-v7 upgrade plus empty
reverse/reapply and downgrade fence, and make the complete focused, adjacent,
query, format, lint, typing, and migration gates green. A different reviewer
must issue a new explicit verdict before any deployment retention policy is
activated.
