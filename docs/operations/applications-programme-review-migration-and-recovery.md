# Programme review migration and recovery

## Original decision preview and confirmation

Keep the exact original case version, retry UUID, outcome, recipient text,
private rationale, signed preview and confirmation after an uncertain response.
The proof binds a digest only, not a copy of private text or authority. Never
copy raw proofs or private input into logs, issue reports or support screenshots.
Changed intent requires a new explicit preview; do not replace a failed intent's
version or retry silently. Canonical receipt recovery precedes private-content
reads and still requires current route and owner replay authority. A recovered
receipt is not current acceptance, conversion, delivery or contributor consent.

Proofs have no arbitrary expiry that would break old receipt recovery. Retain
the normal Django signing-key fallback during rotation; unavailable historical
keys make the proof unusable and must not be bypassed or replaced with a fresh
decision. Inspect the retained owner receipt through independently authorized
support before deciding on any new intent. A declined private read never releases
cached preview text. Outgoing decider history retains exact immutable messages
but no recipient directory or other person's acknowledgement state.

This adapter changes no schema or rollback fence. Native preview, wait-list
successor, retained-message paging and old receipt cases are maintained but not
collected/executed during ADR 0100 deferral; #102 owns restoration and native
evidence. #97/#109/#92 remain separate recovery, integration and human gates.

## Original moderation intent and evidence snapshots

Keep the original case/version/retry key, explicit reopen target, rationale and
confirmation after an uncertain moderation response. A canonical original POST
may recover its minimal receipt before reading private case content whose
independence has since changed; current route and owner replay admission still
apply. Do not rebuild the request from a newly loaded evidence page. History
continuations bind the inspected version; 409 means begin a deliberate new
inspection, not silently update the old form. A failed scoped read releases no
cached rationale or evidence. Reopening affects only an open/waitlisted case's
selected current/earlier stage, invalidates that and later moderation and retains
history. It cannot undo a final accepted/rejected/revision-requested case.

The dormant moderation surface changes no schema, runtime privilege or recovery
writer. Leave it unmounted while #102 native acceptance, #97 logical restore,
#109 integrated evidence and #92 genuine human acceptance remain incomplete.

## Retained own reviewer intent

Own reviewer pages bind the URL-selected retained assignment's immutable policy
stage, original case version, retry key, scores/text, rationale and confirmation.
After stage progress, source invalidation or recusal/removal, keep the original
request for canonical receipt recovery. Do not rebuild its rubric from the new
case stage or require a protected answer/evidence read before replay. Scoped
retained metadata is not content authority. A minimal receipt remains distinct
from a fresh write or permission to reopen content. Inspect current state before
starting a deliberately new intent; do not reactivate or rewrite historical
assignments. Existing retention, audit, planning and capability guards apply.

No migration or new runtime privilege is introduced by these dormant views.
Native recovery remains unexecuted #102 debt during ADR 0100; this does not close
logical-restore issue #97 or declare the Programme profile usable in production.

## Retained named-reviewer selections

The dormant manager forms use Django purpose signing for identifier-only named
selection integrity, not authority or a new credential. Preserve configured
`SECRET_KEY_FALLBACKS` during ordinary key rotation when in-flight selections
must remain recoverable. The original selection has no arbitrary age cutoff:
current manager/object/field authority and canonical writer rules still apply.
Do not log or copy raw selections into issue reports, analytics or support logs.
They contain scoped person IDs, not email addresses or cached names.

After an uncertain assignment/removal response, retain the original page and
inspect the independently authorized roster. Retry the exact original intent
to recover its canonical receipt; never silently refresh the case version, person
or retry key. Changed email or an unusable selected person does not rebase the
request. If signing keys are lost, validation must remain closed: a failed
signature is not evidence that the mutation failed. Inspect current relationships
and owner receipts before deliberately creating a different intent. No database
migration or privilege change accompanies this surface; it can remain unmounted
without deleting retained assignment evidence. Full native recovery remains #102.

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
