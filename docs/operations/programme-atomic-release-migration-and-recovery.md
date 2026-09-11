# Programme atomic release migration and recovery

Applies to [#96](https://github.com/martonpornoi/maru/issues/96),
[ADR 0096](../architecture/decisions/0096-atomic-programme-release-and-invalidation.md)
and the [Scheduling contract](../modules/scheduling.md). This extends the
[candidate/Venue baseline](scheduling-migration-and-recovery.md), not its
historical verification claims. Use synthetic data only; no profile, route,
runtime writer, deployment or production recovery is approved here.

## Install the complete owner graph

Stop writers and apply the complete ordinary Django migration graph as the
schema owner. Scheduling 0007–0020 depends on native Audit attribution and the
Identity, Programme, Workforce, Events and Venue source guards. Installing only
the Scheduling tables or migration recorder entries is not sufficient.

The graph retains exact immutable approvals, warning acknowledgements,
placement/dependency selections, releases, mandatory canonical artifacts,
withdrawals and one monotonic edition pointer. Programme additionally owns
immutable exact-public-copy withdrawals and independently reviewed Ready/Live
copy continuation. Neither path reopens private editing or grants a current
profile permission. Audit witnesses retain native transaction attribution, not
an actor capability or business-eligibility assertion.

Provision the exact [runtime role contract](postgresql-runtime-role-provisioning.sql.example).
All new Scheduling relations, Programme copy-withdrawal records and Audit
witnesses remain SELECT-only. The narrow native journal function can append
only a proven owner mutation; it cannot create tracking, approval or release
state. Only it and native Audit capture are the explicitly declared SECURITY
DEFINER exceptions. Runtime receives only listed read helpers, including the
minimized published-host conflict source needed by ordinary Workforce writes.
Do not grant generic release, witness or journal DML or PUBLIC execution.

Check complete runtime-role safety and all participating readiness probes.
Readiness composes pinned migration sources, required recorders, exact schema,
native function definitions, supporting trigger attachments/arguments, owner,
search path and ACLs. A migration record or matching function name alone proves
nothing. Never recalculate accepted hashes from an unexplained live database.

## Reverse only while genuinely unused

Scheduling 0020 is the top-level fence for this release extension. It takes
explicit ACCESS EXCLUSIVE locks and refuses reversal if any retained native
Audit witness, dependency key, reviewed Programme copy, copy withdrawal,
warning, approval, release or pointer exists. This prevents Django's per-migration
commits from partially removing later protections before an older used-evidence
fence refuses. A null active pointer, expired interval or withdrawn copy is
still retained evidence, not an unused installation.

An unused extension can reverse through Scheduling 0011 and reapply the full
current leaves using real committed migrations. Deeper predecessor boundaries
retain their own fences. Record actual applied migrations after any failure;
keep writers stopped until the complete compatible graph is restored.

Once used, retain compatible code and fix forward. Do not fake migrations,
disable triggers, truncate history, reset generations, reissue witnesses or
delete reviews to force a downgrade. Recovery must complete in a separate
committed maintenance transaction before ordinary owner commands resume.

## Recover a consistent database, not isolated release tables

Back up and restore all mutually dependent owner records, immutable receipts,
Audit and witnesses, Effects/outbox, dependency keys and journals, artifacts,
pointers, authorization, extensions and migration records together. Restore
against compatible code and PostgreSQL image; provision the intended runtime
identity and verify readiness before resuming writers or serving results.

The focused #96 physical-backup rehearsal used PostgreSQL 17.11 on the same
digest-pinned image, a real `pg_basebackup` tar with included WAL, and an isolated
tmpfs clone. Native tar extraction restored the cluster without rewriting its
catalog. It passed exact Scheduling readiness, identical checked release and
artifact bytes, a new native copy withdrawal, exact idempotent retry and one
governing journal entry. The original synthetic release remained unchanged.
Earlier clone startup attempts failed because Docker archive-copy handling did
not produce a usable cluster root; those attempts are not passing recovery.

This is same-image synthetic physical recovery, not production backup/PITR,
provider certification, runtime deployment or a logical-restore guarantee.

To repeat that bounded rehearsal, create a synthetic release through the normal
approval/publication commands and retain its checked manifest, artifact digest
and pointer version. In a separately identified same-image disposable environment:

1. Use `pg_basebackup -U OWNER -D - --format=tar --wal-method=fetch --checkpoint=fast`
   inside the source container with its actual backup-authorized owner. Preserve
   stdout as binary bytes; PowerShell text redirection is not a tar transport.
2. Extract with native `tar -xpf - -C /restore` into the clone's initially empty
   tmpfs owned by its PostgreSQL OS account. Never use the source PGDATA as target
   or mount a real convention's persistent volume.
3. Start `pg_ctl` against `/restore`, capture its startup log, and wait for genuine
   readiness on a loopback-only port. A running container is not a ready database.
4. Point only the isolated rehearsal connection at that clone. Check exact native
   readiness and the retained manifest/artifact before performing a fresh native
   copy withdrawal. Verify checked selections are withheld, exactly one journal
   consequence exists and exact retry returns retained evidence.
5. Restore the original rehearsal connection, verify its release is unchanged,
   then stop only the exact ID/label-verified disposable clone. Preserve minimized
   evidence of both successful and failed stages.

Logical `pg_dump`/`pg_restore` currently fails exact schema readiness even on
the same image: PostgreSQL reparses some array cast CHECK expressions into
equivalent but differently rendered catalog definitions. Native functions,
triggers, ACLs and recorders passed the focused diagnostic; schema fingerprints
did not. [#97](https://github.com/martonpornoi/maru/issues/97) owns resolving
that mismatch with negative weakened-constraint tests before activation or the
director pilot. Do not waive readiness or accept arbitrary restored hashes.

## Resume owner behavior and checked reads

Recheck the exact current pointer through the audited release-manifest query.
Missing artifacts, malformed bytes, incomplete dependency ranges, wrong scope
or unavailable owner evidence withhold results; old bytes are no fallback.
A same-transaction native source change governs all matching retained release
dependencies, including releases first committed while the source writer waits.

Operational changes recorded after an immutable obligation end preserve its
approved history; an earlier invalidation stays invalidated. Historical approval
is not proof of attendance or completed work and cannot supply future coverage.
Copy/relationship disclosure withdrawal has no historical expiry. Restore must
not resurrect withdrawn wording or sharing. Changed private working text and a
new reviewed copy do not silently replace an already released exact rendition.

Room or copy invalidation does not cancel a retained confirmed host's commitment.
Ordinary Workforce claims and Programme publication still check combined work
and rest under account serialization. Only governed relationship ending or a
deliberate release replacement/withdrawal changes that published obligation.

Diagnose with minimized readiness outcomes, receipt/correlation identifiers,
pointer versions and authorized history. Never log private calendars, copy,
reasons or source JSON. Role-specific outputs, notifications, on-site fallback
and integrated human acceptance remain later #48 gates, including deferred #92.
