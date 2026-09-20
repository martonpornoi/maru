# ADR 0109: Keep Programme archive tasks and expiring bytes in owned private custody

- Status: Accepted; implementation pending
- Date: 2026-09-20
- Extends: ADR 0108; preserves ADRs 0081 and 0104
- Requirements: INT-007, QRY-006 through QRY-008, AUD-001, AUD-003,
  PRI-001, PRI-003, NFR-003, NFR-008 and NFR-013
- Issues: #189, #108/P11 and #109 within #48

## Context

The restricted owner collectors now compose one declared complete scope under
canonical locks. The initial database-free codec still permits only 2 MiB per
JSON member and 32 MiB overall. A single valid proposal may already include
64 MiB of files. A usable archive therefore needs the background persistence,
resource limits, requester binding, expiry and disposal decision required by
ADR 0108 before those components are implemented.

Applications already holds its exact clean file bytes in private PostgreSQL
custody. Introducing public media storage, a new object-store vendor or a
general export platform is not needed for this one dormant outcome. Neither a
temporary filename nor a previously successful permission snapshot can become
download authority.

## Decision

### Purpose-specific tasks, not a reporting service

Programme owns one immutable request scope (Organization, edition, actual
requester, contract and idempotency identity), its versioned lifecycle evidence,
and expiring derived artifact chunks. No request is created for another person.
No unrestricted task listing, shared bearer URL, email attachment, privileged
impersonation or cross-organization discovery is introduced.

The explicit states are queued, running, ready, failed, cancelled and expired.
Progress is truthful phase/state, not an invented percentage. A request has a
fixed 24-hour expiry measured by the database clock, including queue time.
Expiry never extends because a browser polls, a worker retries or a download
starts. A deliberate retry is a new idempotent request linked to the old one;
failed or cancelled work is never silently resurrected. A worker crash leaves
no partially successful artifact. Stale running work is failed after its bounded
execution deadline before a user can deliberately retry.

Only one unexpired nonterminal/ready request per edition is retained at a time;
replacement requires deliberate disposal/cancellation first. The initial queue
admits at most four active requests globally and 1,000 retained requests per
edition. Capacity refusal is generic and exposes no other requester's identity,
task or record counts. No automatic source deletion is offered to fit the limit.

A purpose-specific management worker processes one request at a time, using
the original requester's current policies, not the operator's or a service
person's content privileges. Request, worker claim, completion/failure,
cancellation, expiry and artifact disposal retain minimized audit evidence.
Worker execution is identifiable as background work on the retained request;
it does not claim the person clicked a contemporaneous command.

### One bounded larger package, preserving the provisional codec

The supported background envelope retains `programme.exit-archive@1` and the
closed eight `OWNER.programme-exit@1` sections. Its explicit capacity marker is
`programme.exit-background-capacity@1`. The existing smaller in-memory encoder
keeps its original bounds; it is not silently widened.

The background encoder accepts at most 128 MiB per records member, 2 MiB per
schema, 2,000 distinct clean Applications files of at most 10 MiB each, and
1 GiB of total content. Existing stricter owner bounds still apply. ZIP metadata
and the bounded manifest have a separate 2 MiB overhead allowance. These are
hard refusal ceilings, not a guarantee that every combination completes within
the worker budget. No truncated or missing section may be labelled complete.

Encoding writes a deterministic stored (uncompressed) ZIP to a bounded private
sink without creating another complete ZIP buffer. Member paths are generated
from the closed owner vocabulary and opaque file UUIDs. The manifest records
scope, requester, generation time, owner contracts, classification, member sizes
and SHA-256 hashes. It declares historical/private limitations and supported
capacity. It is neither encrypted nor signed, and an editable digest manifest
does not authenticate itself.

The single worker and retrieval process require a deliberately provisioned
memory budget for authorized owner DTOs and source rechecks; initial deployment
guidance reserves 8 GiB per active archive process. Hard size limits, database
statement/lock timeouts and a finite execution deadline fail closed. No parallel
archive workers are enabled merely because more tasks are queued. Measured
synthetic capacity/resource acceptance remains required before deployment.

### Private chunk custody and evidence

Derived bytes remain in Programme-owned PostgreSQL rows, split into at most
1 MiB chunks with contiguous sequence, size and SHA-256 identities. Completion
binds exact total size, chunk count, ordered chunk identity and whole-ZIP digest.
There is no public media path, external storage key or reusable signed link.
Runtime relations remain SELECT-only until final profile/runtime promotion;
application writer boundaries and native guards are separately verified.

The ordinary database/transport/private-volume operational protections apply.
This is restricted C3 derived data, not an encrypted archive product. Operators
must account for database capacity and backup retention of expired copies;
deleting a live row cannot erase historical backups or downloaded copies.

Canonical lock order precedes task mutation and child evidence. State/version,
scope, immutable request identity, chunk completeness and transition evidence
are database-enforced. A downgrade is supported only before retained requests
or lifecycle evidence exist; after use, preserve evidence and fix forward.
Readiness and runtime ACL inventories include every new relation and guard.

### Current execution and actual disclosure checks

Generation uses `exit_composition` under the full Department/person closure and
all independent owner checks. The source identity binds the actual non-Audit
owner bytes, schemas and exact files, including independent versions not covered
by a Programme item cursor. Per-read audit IDs and timestamps are not source drift.

Only the authenticated original requester can inspect private task metadata or
download. Execution, private inspection and actual retrieval require current
archive and required owner source rights. A stored task, role name, worker
success, earlier audit or digest never substitutes for those checks. The initial
correctness path uses fresh owner collection rather than a cached authorization
lease. It may be expensive; unavailable/time-limited checks return no private
result. A later optimized source-version probe needs equivalent owner evidence
and tests, not a freshness interval that silently tolerates revocation.

Retrieval compares fresh source identity with generation, checks exact task
scope/requester and database-clock expiry again, and verifies complete artifact
bytes before disclosure. Denied, changed, missing, corrupt or expired sources
yield no success download. Responses are private/no-store with attachment
disposition and no requester-supplied filename. Cancellation and expiry remove
only derived chunks and retain minimized task/lifecycle evidence; source records,
retention holds, audit and unrelated workflows are untouched. Downloaded copies
remain the requester's accountable private custody, with explicit disposal guidance.

## Acceptance and consequences

This adds no production worker, profile, route, storage grant or deployment by
itself. Request/UI/worker/native migration/recovery and complete P11 acceptance
must be implemented and tested together. Required cases include independent
source/export denial, exact requester and scope, stale source, expiry at actual
retrieval, missing/corrupt chunks, cancellation/running races, crash/retry,
duplicate request identity, capacity overflow, mandatory-audit rollback and
excluded module effects. Ordinary PostgreSQL certification is required, but does
not replace #109's integrated fixture, #97 restore or #92 genuine human acceptance.

A complete archive is portable evidence, not a database restore, writable import,
effective-grant backup or current timetable. Stop-use remains separately accountable
under #190; stopping the module cannot grant a later archive download.
