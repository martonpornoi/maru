# Synthetic OCI runtime rehearsal

Status: executable exact-image evaluator path; synthetic evidence only
Last updated: 2026-08-29
Scope: issue [#37](https://github.com/martonpornoi/maru/issues/37), parent
evaluation [#29](https://github.com/martonpornoi/maru/issues/29), OPS-008,
NFR-001 through NFR-004, NFR-008, NFR-010 through NFR-013, and ADRs 0044,
0046, 0060, and 0065

## Outcome and boundary

This runbook starts Maru's immutable release-candidate image with isolated
PostgreSQL 17, separates the migration owner from the runtime login, activates
the exact authority-provenance boundary, proves minimized liveness/readiness,
and exercises ordinary web and database restart over one persistent synthetic
volume.

The default inputs are:

- candidate `v2026.08.27-rc.1`;
- source `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`;
- application image
  `ghcr.io/martonpornoi/maru@sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
  and
- reviewed PostgreSQL image
  `postgres:17.11-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`.

The bounded synthetic topology reaches complete application readiness:
`/health/live` and `/health/ready` both return HTTP `200`, and every reported
dependency is `ok`, after exact activation. That is **not** production
readiness. The run deliberately does not certify TLS/edge/static delivery,
SMTP or another provider, workers/schedulers, backup/PITR, restore, load,
accessibility, partner policy, or human go/no-go controls. Static delivery is
tracked separately in [#38](https://github.com/martonpornoi/maru/issues/38).

The topology selects `maru.settings.local` inside an internal Docker network.
No database or web port is published to the host. Health requests execute over
Gunicorn's own container loopback, and local adapters cannot deliver to real
providers. This is more isolated than the development quick start, but it is
still a synthetic evaluator profile, not production settings or production
infrastructure.

## Prerequisites and safety

Run from an exact Maru source checkout containing the candidate commit. You
need:

- Docker Engine with Linux containers and permission to create private
  networks, volumes, and containers;
- Python 3.12 or newer (the repository virtual environment or `uv` is enough);
- network access for the two digest-pinned image pulls; and
- only disposable synthetic data.

Do not provide real provider credentials, production configuration, personal
data, or an existing database. The runner creates a random twelve-hexadecimal
run namespace and refuses any pre-existing exact resource name.

The runner generates three different credentials:

1. a cluster administrator used only for initial PostgreSQL bootstrap;
2. `maru_migration`, which owns the database/schema and applies migrations and
   the controlled cutover; and
3. `maru_runtime`, which is the genuine long-running application login.

Credentials enter mode-`0400` labeled secret volumes through standard input.
They do not enter command arguments, Docker environment values, database URLs,
terminal output, or evidence. PostgreSQL is never published. The runtime login
is created by the exact-source reviewed SQL contract: it owns no database,
schema, relation, sequence, or function; receives no broad/predefined role;
and is never simulated with `SET ROLE` or session-authorization
impersonation.

## Run the rehearsal

With an existing repository environment:

```powershell
uv run python scripts/rehearse_oci_runtime.py
```

On the maintained Windows checkout, the equivalent direct invocation is:

```powershell
& ".\.venv\Scripts\python.exe" scripts/rehearse_oci_runtime.py
```

The defaults intentionally identify the published candidate. For a later
reviewed image, supply both immutable identities; a tag-only reference is
rejected:

```powershell
uv run python scripts/rehearse_oci_runtime.py `
  --app-image "ghcr.io/martonpornoi/maru@sha256:<64-lowercase-hex>" `
  --expected-source-revision "<full-40-character-commit>"
```

PostgreSQL is intentionally not an argument. Updating its locked digest is a
reviewed repository change, not an evaluator override.

Before creating resources, the runner pulls and inspects both images, verifies
the application's OCI revision label and requested repository digest, and
reads
`docs/operations/postgresql-runtime-role-provisioning.sql.example` from that
exact source with `git show`. It refuses a source mismatch, missing commit,
changed SQL digest, or missing least-privilege sentinel. The bootstrap helper
is also hashed into evidence before it is streamed to the immutable image on
standard input; the image filesystem is not patched.

## Executed sequence

The script performs these ordered stages and stops on the first mismatch:

1. Create one internal labeled network, one PostgreSQL data volume, and three
   separate secret volumes. Neither PostgreSQL nor Gunicorn receives a host
   port.
2. Start PostgreSQL, create `maru_migration`, create the `maru` database owned
   by that role, and run `migrate --plan`, `migrate --noinput`, `check`, and
   `makemigrations --check --dry-run` from one-shot owner containers.
3. Start the candidate temporarily through the migration credential without a
   configured runtime role. Liveness is `200`; readiness is `503` with only
   Logistics unavailable. This reproduces and explains issue #29: Logistics
   cannot prove the required genuine least-privilege login when the role name
   is absent.
4. Stop Gunicorn. Apply the reviewed runtime-role SQL from the exact image
   source and inject the separately generated runtime password through SQL
   standard input.
5. Through a **genuine `maru_runtime` connection**, stream the repository-owned
   minimal bootstrap helper. It creates one fixed `.invalid` active platform
   administrator with an unusable password, no organization, and no ordinary
   grant, bundle, or assignment. A rerun verifies the exact row and returns
   `already_present`; any collision or changed login state fails without
   repair.
6. With no web process running, dry-run the provable-only authority backfill,
   apply it with the stopped-writer acknowledgement, and apply it again. Both
   apply reports must be identical. Owner-side readiness must report
   `status=ready`, `activation_status=ready`, `production_status=blocked`, and
   `blocker_total=0`.
7. Start compatibility-mode Gunicorn through the genuine runtime login. Both
   health endpoints return `200`; all current database, bounded-domain, and
   Logistics dependencies report `ok`. Record the immutable build identity,
   then stop Gunicorn and prove its endpoint is unavailable.
8. Start exact-required Gunicorn before the marker exists. Liveness stays
   `200`; readiness is `503` with `database=ok` and
   `authority_provenance=unavailable`. Stop Gunicorn again.
9. Confirm the only running labeled container is PostgreSQL. Activate with
   `MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE=true`, `READ COMMITTED`, the
   non-login synthetic platform actor, and
   `--acknowledge-processes-stopped`. Repeat activation; the results must be
   `activated` then `already_active`. Postflight must report production status
   `ready` with zero blockers.
10. Create a fresh exact-mode Gunicorn container and fresh database pool through
    the genuine runtime login. Both health endpoints return `200`, including
    `authority_provenance=ok` and `logistics=ok`.
11. Stop and start the same web container. The stopped process is unreachable;
    after start, health and exact build identity are unchanged.
12. While web remains running, stop PostgreSQL. Liveness stays `200`; readiness
    becomes `503` with only `database=unavailable`. Stop web, start PostgreSQL
    and wait for it, then start web. Full synthetic readiness returns over the
    same data volume.
13. Stop web, rerun migrations as the owner, and replay the bootstrap through
    the runtime login. Migrations must be a no-op; the bootstrap must return
    `already_present`; and aggregate counts must remain one account, one
    activation marker, and one reserved activation audit. Start a final fresh
    pool and require complete readiness again.

The full educational `seed_demo_data` command is deliberately absent. It
contains ordinary pre-existing role bundles, role assignments, and grants for
browser exploration. Those rows are valid synthetic examples in compatibility
mode but are not historical issuance evidence, so combining that fixture with
an exact ADR 0044 activation would correctly block or fail. Never disable the
guards or manufacture provenance to force it through.

## Expected health matrix

| Stage | `/health/live` | `/health/ready` | Interpretation |
| --- | --- | --- | --- |
| Web stopped | unreachable | unreachable | no application process exists |
| Migration login, runtime role omitted | `200`, `status=ok` | `503`; Logistics unavailable | correct fail-closed reproduction of #29 |
| Genuine runtime login, compatibility mode | `200`, `status=ok` | `200`, `status=ok`; every dependency `ok` | full bounded synthetic readiness before cutover |
| Exact flag true, marker absent | `200`, `status=ok` | `503`; authority provenance unavailable | external recovery fence is working |
| Exact marker active, genuine runtime login | `200`, `status=ok` | `200`, `status=ok`; every dependency `ok` | full bounded synthetic readiness after fresh-pool start |
| PostgreSQL stopped | `200`, `status=ok` | `503`; database unavailable | liveness is dependency-free; readiness denies traffic |

Under the fixed local evaluator profile, successful compatibility readiness
must report exactly `database`, `applications_integrity`,
`charities_integrity`, `catalog_integrity`, `venues_integrity`, and
`logistics`. Exact mode adds exactly `authority_provenance`. Empty, missing,
extra, or renamed dependency maps fail the rehearsal even if their reported
values are `ok`. The production-only invitation-encryption dependency is not
part of this local profile; production settings and provider readiness remain
outside this result.

Public health never reports a role, object, credential, database version, or
database error. Detailed diagnosis remains an authenticated/operator or local
Docker concern.

## Evidence, failure, and cleanup

Each run writes a sanitized receipt below:

```text
.local-ci/oci-runtime-rehearsal/<run-id>.json
```

The ignored receipt contains exact public image/source identities, SQL and
bootstrap hashes, stage results, public minimized health maps, count-only
bootstrap/readiness/activation evidence, restart identity, and cleanup status.
It excludes credentials, database URLs, actor email, raw HTTP bodies, raw
Docker/application logs, correlation IDs, exception text, and command output.

On a mismatch the terminal and receipt report only a fixed stage and failure
code. First inspect that receipt. If container logs are necessary, rerun with:

```powershell
uv run python scripts/rehearse_oci_runtime.py --retain-on-failure
```

That option stops and retains only the exact labeled synthetic run, including
its secret volumes. Treat it as temporary sensitive local material. A successful
run can likewise be retained with `--retain-resources`. Remove one retained run
after inspection with its receipt's twelve-character ID:

```powershell
uv run python scripts/rehearse_oci_runtime.py `
  --cleanup-retained <run-id>
```

Cleanup validates every exact container, network, and volume label before any
removal. It refuses a mismatch and never prunes Docker globally. Deleting the
retained data and credential volumes is irreversible but affects only the
disposable synthetic run. One-shot jobs keep deterministic names and labels
until cleanup so an interrupted process can be rediscovered; retention stops
and preserves those jobs for inspection. Without a retention flag, success and
failure both remove their exact resources and require an empty final namespace
and run-label inventory before recording `removed`.

Standalone cleanup also requires at least one resource in the exact namespace.
A valid-looking but absent or mistyped run ID fails with
`retained_run_not_found`; it never prints a misleading removal success.

Do not use `docker system prune`, broad name filters, `down -v` against another
project, or marker/ledger deletion as a substitute.

## Separate development and production paths

The README/development `runserver` quick start remains the editable local
browser path and may use the comprehensive educational fixture. It is not OCI,
Gunicorn, least-privilege, activation, or release evidence.

This OCI run uses the immutable candidate's Gunicorn default but deliberately
uses synthetic local settings and an internal network. Passing it does not make
those settings production-safe. A production deployment still needs the
[deployment readiness](deployment-and-service-objectives.md),
[authority migration/recovery](authority-provenance-migration-and-recovery.md),
[observability/readiness](observability-and-readiness.md), release, provider,
restore/PITR, static/edge, security/privacy, and human owner gates.
