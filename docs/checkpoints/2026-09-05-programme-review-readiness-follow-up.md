# Programme review readiness certification follow-up

Date: 2026-09-05
Scope: issue [#71](https://github.com/martonpornoi/maru/issues/71) only

## First candidate and cause

The first full default eight-shard certification tested clean commit
`aa2295542ac6c718741107b080908dca33c5bbb0`. It ran 5,838 Python cases;
all 2,824 unit tests and all 79 new Programme integration cases passed. The
slowest integration shard took 80m55s. The run did not certify the candidate:
108 wider integration cases failed at shared authorization readiness or its
function-fingerprint assertions.

Authorization `0024` correctly installed the new scope function, but the
shared provenance readiness manifest still pinned the preceding definition.
Read-only PostgreSQL inspection independently matched the installed function's
body, language, volatility, parallel mode, invoker/strict/scalar behavior,
search path, and result type against the declaration. Every existing capability
and all four new Department capabilities retained their declared scope.

The verified current fingerprint is
`022691da80e52efa1968854ccd3b2db879e622e54c7c8be0bc96214b8f654897`.
The stale predecessor was
`00c48870aef3f144e6030ead08a411e8dd3dab722e4021a8998be2d9ca12a05e`.
The correction updates that pin; no installed SQL guard, capability scope,
runtime privilege, activation gate, or acceptance policy is relaxed.

## Earlier feedback and focused proof

Two new database-free tests compare the current migration declaration with
the readiness fingerprint and prove the complete additive capability catalog.
The migration-contract unit group passes all six cases in 0.25 seconds. This
catches the stale-pin class of mistake before an expensive integration matrix.

All 2,826 unit cases pass in 12.17 seconds. Eleven focused PostgreSQL cases pass
in 99.30 seconds, covering actual scope-function identity, clean authority
activation and audited postflight, count-only readiness, runtime helper tamper,
real runtime login and SET ROLE, plus all five review migration cases. A new
real reverse-migration case proves that a retained review role prevents scope
vocabulary contraction before the function or migration record disappears.
The review migration file's measured scheduling weight is updated to 79.398
seconds; all previous cases, timeouts, and coverage requirements remain.

Existing future intake/adoption page contracts now link the dedicated review
projection contract while retaining their unmounted, inactive boundary. They
do not imply accepted-item conversion or a usable Programme workspace.

## Delivery boundary

The failed candidate's reports/logs were preserved in the ignored issue evidence
folder before restarting certification. These focused results do not certify
the repaired commit. The delivery PR must identify a fresh successful default
exact-head local receipt and independently green protected hosted checks.
No first-candidate result may be reused as acceptance of a changed commit.

After #71's protected merge, verify and synchronize clean main, reconcile the
completed child in umbrella #48, and stop. The accepted-item adapter, hosts,
Scheduling, surfaces, and final Programme-only rehearsal remain successors.
