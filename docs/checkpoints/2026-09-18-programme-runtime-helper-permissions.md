# Programme isolated runtime helper permissions

Date: 2026-09-18
Scope: #180, a necessary supporting child of #108 inside #48.

## Outcome and source finding

NFR-013, IDN-012/014, AUD-001/003, PRG-008 and SCH-007/008; existing
ADRs 0044/0046/0081/0096/0106 remain unchanged. Canonical production ACLs and
profiles are not activated. This is test-only candidate preparation, not native
acceptance or a supported Programme profile.

Static inspection found candidate table writers calling helpers excluded from
the unchanged production execution allowlist. Applications review, exact role
approval and Scheduling evidence/release/notice guards therefore lacked a complete
candidate execution contract. A database-free migration-source audit found
thirteen invoker-security validators. A stricter closure regression additionally
identified the legacy `maru_workforce_page9_try_scope_mutex(bigint)` called by
Applications review/conversion/file guards. Its SECURITY DEFINER body only calls
`pg_try_advisory_xact_lock` and raises SQLSTATE 40001 on contention; it writes no
rows, executes no dynamic SQL and retains no session-lifetime lock. The older
parser's LANGUAGE-before-AS limitation must not be mistaken for permission proof.

Fourteen literal signatures now have independent source/metadata expectations.
The isolated empty-fixture transaction requires owner-only baseline ACLs and exact
native definitions before any grant, grants only those signatures, and checks
owner plus non-grantable runtime ACLs afterward. PUBLIC, third-party grants,
changed bodies/flags/search paths/results/owners and incomplete sets fail closed.
Original lease, database identity, migration history, empty editions and table
ACL preconditions remain mandatory; failures roll back and require fixture
disposal. No production SQL, migration, owner, grant option or runtime-role query
changes. Trigger entrypoints and other owner-only helpers remain denied.

Five existing owner readiness contracts include these helpers: Applications,
Programme-role approval, Scheduling, Programme and Venues. Each entire original
contract is deterministically pinned and validated before any installation. Only
the explicit expected runtime execution set changes in the opted-in child; source
flags, functions, triggers, recorder dependencies and relation checks remain
identical. Canonical provenance checks for the legacy mutex remain unchanged.
Both the genuine candidate login probe and guarded startup additionally recheck
the complete fourteen-helper native metadata/ACL contract.

## Verification and remaining gates

Focused database-free feedback passed 194 cases in 1.02s. The tests cover each
owner baseline's drift, helper metadata, missing/duplicate signatures, unchanged
production declarations, exact invoker closure with the legacy lock-only leaf,
policy fences, no partial contract installation, SQL grant boundaries and failure
before application acceptance. Initial tests exposed an ineffective empty-value
mutation and incomplete closure accounting; the latter uncovered the real mutex
permission gap above. Neither a guard nor a negative assertion was weakened.

Complete database-free feedback passed 10,943 tests in 61.70s with three existing
Django URL-field warnings. Ruff and diff whitespace checks passed. Exact-head
retained certification is pending at this snapshot. Seven host-only provisioning
scenarios are maintained, including one
new real-login missing-grant/PUBLIC/grant-option/definer/body-drift refusal case.
The existing three variants now check all fourteen helpers alongside 82 table
matrices. Every native case remains uncollected/unexecuted under #102.
No Docker, scanner, database, migration, schema-only, server or browser ran.

Next: #175's genuine two-person Volunteer starter, P06 staffing and the remaining
complete P01–P12 composition. After preparation, restore the tracked PostgreSQL
policy through protected delivery and require #102, #97, #92 and #109 before
supported-profile promotion or closure of #108/#48. Do not reuse this candidate
permission inventory automatically for production activation.

## Protected delivery appendix — 2026-09-18 20:26 UTC

PR #181 merged certified head `cb28378c41f0fb0ddef7e8254f0bf61a0382d213`
as protected squash `bed5b3a7c029aaf24e2ef2888f4f489aa4cc3f1d`. Both trees
are `501389e81c22668da8b7ad8ffed161a9b59e57d2`. Clean separate main was
fast-forwarded to the protected result; the unrelated repair worktree remained
at `aa1ede69fb880dcb12d627bbfc049fba23166e68`. Uncommitted #175 work was
preserved on a separate branch from the equal-tree protected result.

All eight local retained gates passed in 341.676 seconds: 10,943 units in
61.96 seconds and 103 frontend cases. The version-four receipt was
`postgresql_deferred`, zero database instances and null coverage/headroom;
SHA-256 `90504fdd5f397771bbd005e558fd151e2a91fcbb52dfc259db0fa5890279de9e`.
Five artifacts were copied into ignored exact-head evidence and hash-verified.
Hosted run 35389311346 passed quality in 12m43s, units in 2m19s and aggregate
PR gate in 3s. All three processed CodeQL analyses matched the head without
errors/warnings. Complete review/thread pagination was empty; the only closing
reference was #180. Exact-head squash closed #180; #48/#108 checklists were
updated without closing either parent. Native cases remain deferred #102 debt.
