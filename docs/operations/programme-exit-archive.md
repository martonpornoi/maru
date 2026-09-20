# Restricted Programme exit archive and worker

Status: Dormant candidate, not deployment approval. Issue #189 supplies the
archive portion of #108/P11 under #48. ADRs 0108/0109, INT-007 and QRY-006–008
govern supported scope, independent source rights and private custody.

## Prerequisites and data boundary

Do not grant runtime writes, include reserved routes, start a persistent service
or activate an adoption profile merely to try this component. Current profiles
exclude `programme.exit-archive@1`. Synthetic owner/adapter tests do not establish
production readiness. Final Programme promotion, real runtime-role acceptance,
#109 integrated P01–P12, #97 logical restore and #92 human acceptance remain gates.

The requester needs the separately approved exact-edition export purpose and all
required independent owner source/history/file rights. Directors and operators
do not inherit those rights from their title. Generation uses the original
requester, never an impersonating service principal. Private inspection and
download perform a fresh complete source collection, not a cached permission
lease. These checks can be expensive; the screen refreshes only on request.

The supported scope is the eight declared owner contracts, not an arbitrary
database dump. Applications includes reviewed proposals and permitted clean
original files; it excludes unsubmitted/private unreviewed drafts and fields
withheld by current stage/anonymity policy. Private host calendars, invitations,
unrelated volunteer identities, credentials and unrelated modules are excluded.
Required missing or denied sources fail the whole artifact, not a hidden section.

## Worker operation after deliberate promotion

The supported entrypoint is:

```powershell
uv run python src/manage.py programme_archive_worker --max-cycles 1
```

One invocation runs at most one request by default; `--max-cycles` permits 1–4
finite child passes. There is no automatic scheduler or service installation.
Use an explicitly supervised operator process with the deployment's approved
application identity, never an owner credential as a workaround for missing
runtime grants. The internal `programme_archive_run_once` entrypoint is only for
the supervisor; invoking it directly omits the outer hard timeout.

The child holds a PostgreSQL session advisory lock across claim, generation and
cleanup, so concurrent supervisors cannot generate in parallel. Each child has
a hard 20-minute wall-clock limit, 120-second statement timeout and 5-second lock
timeout. The supervisor kills and waits for an overlong child; it discards raw
child output. Only closed completed/failed/timed_out/busy/idle results are printed.
Failed and timed-out passes exit nonzero for deployment monitoring. Database
integrity/readiness failure refuses work. Native guards and independent source
policies are still mandatory; the worker lock is not authorization.

Each pass disposes at most 32 due requests before one queued generation.
Cancellation/failure/expiry delete derived chunks only, retaining request scope,
byte identities and append-only lifecycle/audit evidence. A killed process can
leave a running request but no committed partial chunks. On a subsequent pass,
running work beyond its database-clock 20-minute deadline is failed with
`worker_deadline`; deliberate retry creates a new linked request. Startup time
means this deadline may fall shortly after the supervisor's wall-clock timeout.
Do not manually rewrite the task or reuse its idempotency key to resurrect it.

## Capacity and custody

Initial ceilings: one active/unexpired queued/running/ready request per edition,
four globally, and 1,000 retained requests per edition. Refusal reveals no other
requester, tenant or counts. No automatic source/history deletion makes space.
The fixed database-clock 24-hour expiry starts at request, including queue time.
Polling, generation, retrying the same key or starting a download never extends it.

Content ceilings are 128 MiB per records member, 2 MiB per schema, 2,000 files
of at most 10 MiB, and 1 GiB total content plus 2 MiB ZIP/manifest overhead.
Owner limits can be stricter. They are refusal bounds, not a promise that every
permitted combination finishes within the worker deadline. Reserve an initial
8 GiB per active archive process and sufficient database/private backup capacity;
measure the intended synthetic workload before deployment. Do not increase
parallelism or size ceilings to hide an unmeasured resource problem.

The deterministic stored ZIP is written into private Programme-owned chunks of
at most 1 MiB. Completion atomically binds count, total bytes, ordered chunk root,
source digest and whole-ZIP digest. Retrieval checks every chunk and whole identity
before returning any bytes, and checks database-clock expiry again at disclosure.
Source changes independently of the Programme item cursor invalidate download.
The HTTP response is a fixed-name private/no-store attachment, not public media.

The archive is C3 restricted data, not encrypted or signed. Transport, database,
volume and backup protection are deployment responsibilities. Live disposal cannot
erase an already downloaded copy or historical backups. Accountable stop-use is
separate #190; it does not grant a later download after permissions are removed.

## Inspect an authorized synthetic archive locally

Keep the original ZIP in private controlled storage. Inspect the manifest before
extracting anything; never run contained material or upload it to a public checker.
The package contains `manifest.json`, closed `records/<owner>.json` and
`schemas/<owner>.json` members, plus generated opaque Applications file paths.
Reject duplicate members, absolute paths, parent traversal, unexpected owners,
missing members, wrong sizes or SHA-256 mismatches. Check the recorded organization,
edition, requester, generation time, supported contracts and purpose exclusions.
Inspect schemas alongside records; a foreign identifier does not authorize opening
another system's record. Hashes prove consistency with the manifest, not authenticity.
This package is not a database restore, writable import or current public timetable.

## Migration and recovery

Programme `0020_exit_archive_records` adds requester tasks, lifecycle events and
private chunks. `0021_exit_archive_integrity` guards exact scope, immutable request
identity, database clock, transitions, fresh native Audit evidence, bounded capacity,
chunk identity and atomic completion/disposal. Readiness pins actual schema/trigger
metadata and migration sources. The runtime provisioning inventory keeps all three
relations SELECT-only until deliberate full-profile/runtime promotion.

Unused downgrade takes an exclusive preflight and may remove the empty schema.
Once any request, event or chunk exists, reversal refuses before dropping guards or
changing migration-recorder state. Preserve evidence and fix forward; do not fake a
migration, disable guards, truncate tables or edit fingerprints to pass readiness.
Rehearse backup/restore with retained task evidence and derived-custody expiry under
the integrated recovery contract; unit or ordinary native tests do not replace #97.
