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

Derive a new relation's reviewed baseline from a clean, ordinarily migrated
disposable database. A reused development database can retain PostgreSQL's
physical dropped-column slots after reverse/reapply experiments, even when its
visible column names and types match. The #96 certification repair identified
exactly this difference in the release-dependency key: two retired slots had
entered its initial pin. The corrected pin matches clean forward migrations;
negative tests still reject both one- and two-slot variants. This is not
permission to normalize away physical drift or recalculate a deployed pin.

## Reverse only while genuinely unused

The Programme exit extension keeps this whole-generation contract. Events 0017
fences the joined Events 0016 owner graph on retained native Audit witnesses or
Scheduling dependency keys before any exit/stop successor reverses. Empty reversal
is still permitted; exact stop readiness remains false until the required fence
is reapplied. Do not reverse individual newer guards and then interpret a later
predecessor refusal as unchanged recovery. Use the complete graph, preserve used
evidence, and fix forward. The archive also retains its independent native fence.
See the [recovery-fence evidence](../checkpoints/2026-09-21-programme-exit-recovery-fence.md).

Events 0018 extends this preflight to the other frozen retained Programme boundaries,
including grants that were subsequently revoked, role meanings, setup/approval/starter
intent, notices, archive custody and domain history. It invokes original owner
preflights before any successor reverses, retaining their locks and refusal behavior.
Both new source pins are required for stop readiness. Run recovery in offline
maintenance with application writers stopped; never weaken a refusal by deleting
retained evidence, removing recorder entries or bypassing the whole graph. Unused
reversal remains a tested recovery path, not a production uninstall workflow.

Authorization 0030 adds the five operator-purpose read capabilities under
[ADR 0099](../architecture/decisions/0099-purpose-scoped-programme-operator-outputs.md).
It replaces the exact native capability-scope function without changing its
owner, execute ACL or search path. Apply the complete graph and matching
Authorization readiness pin; a recorder entry alone is insufficient. It grants
no capability, activates no profile and introduces no domain tables.

This additive catalog can reverse to 0029 only before any grant or role bundle
has retained one of the five codes. The reverse fence locks both authority
tables and fails before changing the function or migration recorder. Revoked
grants and unassigned retained role bundles still fence reversal: keep the
compatible code/catalog and fix forward rather than deleting authority history.
Successful unused reversal must reapply current leaves before serving the new
operator code. This does not loosen any older Scheduling evidence fence.

Scheduling 0020 is the top-level fence for this release extension. It takes
explicit ACCESS EXCLUSIVE locks and refuses reversal if any retained native
Audit witness, dependency key, reviewed Programme copy, copy withdrawal,
warning, approval, release or pointer exists. This prevents Django's per-migration
commits from partially removing later protections before an older used-evidence
fence refuses. A null active pointer, expired interval or withdrawn copy is
still retained evidence, not an unused installation.

Native owner work can establish this fence before any timetable is approved.
For example, creating an organizer-owned Programme item retains an Audit
witness even without an Applications conversion or release pointer. A later
attempt to remove the conversion predecessor must preserve every current
migration and guard, not partially reverse supposedly unused successors. The
older conversion-specific populated fence also remains in force. Absence of a
published timetable is therefore not permission to downgrade this extension.

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

Logical `pg_dump`/`pg_restore` previously failed exact schema readiness even on
the same image: PostgreSQL reparses some enum array casts into equivalent but
differently rendered catalog definitions. [ADR 0113](../architecture/decisions/0113-logical-restore-enum-cast-canonicalization.md)
recognizes only the documented literal enum-cast equivalence in CHECK,
exclusion and index definitions. Reviewed hashes, physical column positions,
native functions, ACLs and recorders remain unchanged. Authorization's conditional
receipt triggers use the same exact enum rule. [ADR 0114](../architecture/decisions/0114-restore-stable-identity-trigger-predicates.md)
separately pins the two Identity conditional triggers' complete reviewed deparsed
definitions instead of internal cast-format metadata; the trigger predicates and
independent attachment checks remain exact. The focused
schema, populated component and genuine restored-runtime checks pass. The
[pinned populated run](../checkpoints/2026-09-20-programme-pinned-logical-recovery.md)
also rejects an actual backup missing nonempty release-journal data before
restored worker admission. Exact-head protected acceptance remains tracked in
[#97](https://github.com/martonpornoi/maru/issues/97). Do not
waive readiness or accept arbitrary restored hashes.

The maintained isolated Programme rehearsal additionally attempts a complete
custom-format `pg_dump` and `pg_restore --exit-on-error` into a new UUID-named
database in its exact ID/nonce-verified disposable container. It retains owner
and ACL restoration, recreates the explicit database-level runtime CONNECT-only
contract, and does not disable triggers or use data-only restoration. This is a
same-image logical recovery check, not cluster-role backup, production PITR or
a provider restore guarantee.

Before permitting restored commands, compare all copied public-table counts
and fingerprints, run the real worker and candidate-runtime readiness checks,
and validate the current authorized manifest and immutable artifact. Exercise a
new copy withdrawal and its exact retry, inspect the single journal consequence,
and confirm the checked manifest withholds selections. Verify the original
database remains unchanged. Delete only the newly created restore database;
never force-drop sessions, replace the source, or extend the original rehearsal
lease to make a failed restore pass. Preserve failures as failures alongside the
[recovery checkpoint](../checkpoints/2026-09-20-programme-logical-schema-recovery.md).
The [native recovery checkpoint](../checkpoints/2026-09-20-programme-logical-native-catalog-recovery.md)
records the actual restored worker, changed-authority refusal and reversible
clone-only unsafe-ACL/function negatives. Invalidation retains the pointer to
the original immutable release but withholds selections; only explicit release
withdrawal/replacement changes that pointer.

## Resume owner behavior and checked reads

The dormant [release workspace](../product/page-contracts/programme-release-workspace.md)
offers independently admitted exact warning, approval, publication and withdrawal
controls without a new writer or schema. A publication intent retains its original
approval/source digest and observed pointer version; a returned stale/unknown form
must not be automatically rebased or assigned a new retry key. Retry the exact
intent first to recover its canonical receipt. A successful receipt is historical
command evidence, not a guarantee that the current timetable remains available.

When content verification itself is unavailable, the separately authorized
pointer-only owner query can still select deliberate whole-release withdrawal.
It proves only identity/version and never authorizes serving artifact content.
Reasoned withdrawal retains history, advances the pointer and does not restore a
predecessor. Do not use retained approval/history pages as an unsafe-content
fallback. No database migration, runtime privilege grant or schema-only exception
is needed for these HTTP/discovery additions. PostgreSQL checks are restored;
recovery acceptance remains a distinct gate, not replaced by browser or unit
evidence.

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
