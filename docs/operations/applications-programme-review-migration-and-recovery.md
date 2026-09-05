# Programme review migration and recovery

Owner: Applications; [ADR 0085](../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md),
PRG-003/PRG-004, issue [#71](https://github.com/martonpornoi/maru/issues/71).
This is dormant infrastructure, not a production rollout or profile activation.

## Forward boundary

Authorization `0024_programme_review_capabilities` extends the immutable
minimum-scope function with the four exact-Department staff capabilities. It
grants nothing, preserves all preceding codes, and keeps recipient capabilities
nonpersistable. Reversal refuses retained grants or role bundles using the new
staff codes. The code catalog policy version is `2026-09-05.1`.

Applications `0013_programme_review_persistence` creates policy, case,
assignment, entry, decision, recipient acknowledgement, and receipt relations.
Their references preserve exact proposal revisions and protected Identity,
Audit, and Effects evidence; no existing proposal is converted or backfilled
with invented review actors. No Programme, Scheduling, Workforce, or target
record is created by review.

`0014_programme_review_integrity` adds closed writer/append-only guards,
shared statement and edition mutex barriers, exact revision/policy/tenant
coherence, contiguous cursors, explicit rubric and stage evidence, distinct
actors, recipient checks, bounded payloads, and deferred receipt/audit/event/
outbox coupling. Raw inverted writes fail retryably with SQLSTATE `40001`.
The shared Applications retry guard covers all four receipt namespaces.
Each trigger has its own stable name; every new function is owner-only,
invoker-security, and pinned to the explicit catalog search path.

`0015_programme_review_downgrade_fence` precedes removal of any review table or
guard on reversal. It locks all seven relations and refuses downgrade if any
review evidence, including a policy, remains. Empty reversal and fresh forward
installation are exercised with the real migration executor.

## Runtime admission and readiness

Run migrations only through the existing separately credentialed migration
owner workflow. The ordinary runtime login retains **SELECT only** on all seven
new tables, not INSERT/UPDATE/DELETE/REFERENCES/TRIGGER/TRUNCATE. Follow the
explicit additions to
[runtime role provisioning](postgresql-runtime-role-provisioning.sql.example)
after blanket/default grants. No review helper is added to the runtime function
execute allowlist. An application writer flag is not database authority.

Both immutable current edition profiles, route/API/navigation declarations,
and Effects delivery routes remain unchanged. The existing isolated-test
authorizer requires both its test setting and a `test_` database name; never
enable substitute admission for deployment. Test effect admission does not
skip real audit, event, outbox, receipt, or database guard execution.

Applications readiness now retains all earlier protections and checks 40
relations, 134 named triggers, and 27 functions. Its freshly recreated
PostgreSQL 17 catalog has 437 constraints and 303 indexes; checked-in metadata
and definition SHA-256 fingerprints also cover column/collation semantics.
Readiness requires the review integrity/fence migration records and retains
the preceding ownership integrity/fence record checks. Missing, replaced,
misattached, permissive, or partial objects must fail readiness, not be ignored.

The review-stage helper is a stable Boolean evidence query; other Applications
guard functions remain triggers. Do not replace declared semantics with a
table-existence check. A green database proof is neither profile adoption nor
permission to use production personal data.

## Failure and recovery

Stale versions, missing exact seals, insufficient reviews, stale moderation,
conflicts, and incompatible retries refuse the command. No success evidence
survives a failed atomic command. Known command denials emit minimized audit
evidence where possible; infrastructure failure must not be represented as a
successful decision or acknowledgement. Sensitive-read audit failure prevents
the projection from being returned.

Retry a `40001` failure as a whole authenticated command, reusing the same retry
key for that logical intent. An exact committed retry returns retained result
identifiers; changed intent under the same key is a conflict. Do not increment
versions manually or synthesize receipts to force progress.

Reopening or withdrawal makes old review evidence historical. Late recusal or
removal invalidates affected acceptance evidence without altering the final
decision. An accepted/rejected case cannot reopen: submit a genuinely new
revision and open a new case through the owning commands. Request-revision does
not override the lead's edit deadline; resolving a closed intake window is a
separate explicit workflow decision.

With retained evidence, keep compatible code and fix forward. Recovery may
instead restore Applications, Identity, Organizations, Events, Workforce,
Authorization, Audit, Effects/outbox, and migration records from one consistent
database point under the existing recovery procedure. Never partially restore
a proposal seal, current case, rubric, decision, acknowledgement, or receipt.
Re-run schema/function/ACL readiness and isolated synthetic workflow checks
before considering service resumption. Existing retention and data-protection
approvals still apply; there is no review-purge command in this child.
