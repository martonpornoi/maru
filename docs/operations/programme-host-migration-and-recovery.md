# Programme hosting migration and recovery

Applies to issue [#79](https://github.com/martonpornoi/maru/issues/79),
[ADR 0087](../architecture/decisions/0087-programme-host-confirmation-and-availability.md)
and the dormant [host owner contract](../modules/programme-hosts.md).
Use synthetic data; this is not activation or deployment approval.

## Additive installation

Authorization `0026_programme_host_capabilities` preserves the preceding
capability catalog and adds only exact-edition manager/read vocabulary. It
creates no grant or role. Person-owned self capabilities remain non-persistable.

Programme `0007_host_relationships` adds four owner tables and expands the
shared receipt's closed host-operation catalog. `0008_host_integrity` installs
scope, version, immutable invitation/history, personal response, interval,
reciprocal receipt/audit/event/outbox and dependency guards. It retains accepted
conversion and other information-layer guards. Closed-edition updates require
exact personal withdrawal evidence; ordinary writes remain closed. `0009`
fences populated downgrade before any host protection is removed.

No migration derives hosts from proposal collaborators, copies availability,
changes literal profiles, sends invitations, grants authority, or creates a
Programme route. Apply the ordinary reviewed migration process with the schema
owner, then provision runtime ACLs from
[`postgresql-runtime-role-provisioning.sql.example`](postgresql-runtime-role-provisioning.sql.example).
All four host tables must remain SELECT-only for runtime and PUBLIC must have
no write grants. Integrity functions remain owner-only, SECURITY INVOKER and
fixed-search-path. Do not grant runtime direct writer or trigger privileges.

## Acceptance checks

`programme_database_integrity_is_ready()` fingerprints exact PostgreSQL 17
relations, columns/collations, complete constraint and index definitions, guard
functions and trigger attachments, recorder dependencies, owners and execution
ACLs. Authorization readiness independently pins the new min-scope function.
Renaming an object back, reinstalling a same-named function with a different
body, or dropping an evidence constraint is not repair.

Focused acceptance covers real invitation/response and availability commands,
ceilinged self/organizer reads, closed planning, stale and concurrent requests,
current person and readiness dependencies, raw SQL denials, atomic rollback,
unused schema round-trip and retained-history refusal. Complete exact-commit
local certification and independent hosted protected acceptance remain required.
Neither a ready schema nor green CI activates Programme Operations.

## Reversal and recovery

Unused host tables may reverse to the prior accepted-item graph and reapply
exactly. `0009` locks the complete host graph in ACCESS EXCLUSIVE mode and
refuses while any relationship, invitation, revision or current window remains.
Ending hosting or withdrawing periods does not make retained history unused.
Reversing Authorization also refuses retained host grants or role-bundle
vocabulary, even when a grant is no longer active.

Django commits a migration plan one migration at a time. A broader downgrade
can therefore remove this unused host extension before an older populated
accepted-conversion fence refuses further contraction. Conversion records and
their exact guards remain protected, but current-code host-inclusive readiness
correctly fails. Keep writers stopped, inspect the actual recorder state and
reapply the complete current graph before expecting current readiness. With
retained host history, the earlier host fence refuses before any host guard or
migration recorder is removed. Never treat a refused multi-migration plan as
proof that every unused successor migration is still installed.

On refusal, retain compatible code and fix forward. Do not fake migration
history, remove guards, delete retained evidence, or reset counters to force a
downgrade. Restore Programme, Identity, Events, Organizations, Authorization,
Audit, Effects event/outbox and migration history from a mutually consistent
point if recovery requires restore; include Applications when accepted-source
items exist. Review the preceding
[accepted-conversion recovery contract](programme-conversion-migration-and-recovery.md)
as well.

Person withdrawal removes current exact availability periods; historical
receipts/revisions retain only minimized intent evidence. Recovery must not
reintroduce withdrawn periods as current state or infer a new confirmation from
an old invitation. Diagnose a full history budget as a bounded conflict, not an
instruction to discard history; the two reserved ending revisions remain for
privacy exit, not renewed editing.
