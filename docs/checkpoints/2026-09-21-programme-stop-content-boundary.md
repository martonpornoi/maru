# Programme stop content and personal privacy boundary

Issue #190 within #108/#48; ADR 0111, EVT-007, ARC-003, ARC-005, AUD-001 and
NFR-013. Local owner-component implementation, not integrated stop acceptance.

Programme 0022 adds canonical old/new Events locking and terminal admission to
all nineteen operational relations. Three archive-custody relations remain under
their independent requester/source/expiry contract. The literal model inventory
is checked against Django metadata; new relations cannot silently gain an exception.

Seven operational relations admit only individually bound consequences of existing
personal decline/withdrawal, host availability withdrawal or public-copy withdrawal.
Protected fields and unrelated readiness concerns cannot move. Each consequence
requires exact original item/host version, actor, retained owner receipt and fresh
native audit witness with exact capability, changed fields and retry binding.
The original history/effect/outbox and release invalidation constraints remain.
No test-authorizer substitution or effect-admission bypass is used by the new
candidate privacy-command tests. Candidate DDL is transaction-local; terminal
state is a component arrangement, not an executed Stop Programme command.

Verification:

- Initial native matrix: 22 passed in 2.58s, run1.
- Expanded run2: 28 passed, two fixture errors. One used a nonexistent item
  column; the other deferred setup evidence beyond subsequent readiness changes.
  Corrected fixtures drain setup constraints at the genuine command boundary;
  no owner constraint was weakened.
- Corrected expanded matrix: 30 passed in 5.67s, run3.
- Final stop matrix, public-copy withdrawal, established host privacy/rollback/
  dependency workflows and metadata units: 81 passed in 28.25s, run4.

Reports: `.tools/programme-stop-content-native-{1,2,3,4}.xml`. Coverage includes
personal decline, erasing shared periods then withdrawing hosting, exact copy
withdrawal/retry, stopped confirmation/sharing/removal refusal, hidden item changes,
unrelated native audit rollback, selective dependency updates and all nineteen
missing-guard readiness negatives. Existing non-Programme workflows still pass.
The new CI file has a conservative uncalibrated 300-second weight.

Source and isolated-runtime contracts include the exact new guards; no helper
execution rights change. Applications/Events closure, complete stop preview/UI,
integrated races/recovery, final acceptance and protected bundle delivery remain.
