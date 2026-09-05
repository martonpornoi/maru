# Synthetic OCI static delivery rehearsal

- Status: bounded exact-candidate evaluator procedure; synthetic evidence only
- Last updated: 2026-09-05
- Scope: issue [#38](https://github.com/martonpornoi/maru/issues/38), parent
  evaluation [#29](https://github.com/martonpornoi/maru/issues/29), runtime repair
  [#37](https://github.com/martonpornoi/maru/issues/37), UX-029, NFR-001 through
  NFR-004, NFR-011, and ADRs 0021, 0056, 0060, and 0065

## Outcome and boundary

This runbook composes the immutable Maru candidate with a reviewed,
digest-pinned unprivileged reference edge. It serves the candidate's
already-collected files from a read-only volume, rejects runtime media at the
edge, and proxies every other non-static request to the candidate's ordinary
Gunicorn process. It does not run
`collectstatic`, patch the application image, or rebuild any release artifact.

The default identities are:

- candidate `v2026.08.27-rc.1`;
- source `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`;
- application image
  `ghcr.io/martonpornoi/maru@sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
  and
- reference edge image
  `ghcr.io/nginx/nginx-unprivileged:1.30.4-alpine3.24-slim@sha256:3b569ded54fe09ab73dbdb409f403631d55c0bb231e4adc10b7c974beb0dc7be`
  for `linux/amd64`.

The edge image and `scripts/oci-static-edge.conf` are repository-reviewed
evaluator inputs. They do **not** select Nginx as Maru's required production
edge, assign production TLS or WAF ownership, certify a hosting provider, or
replace a deployment architecture decision. A production adapter may use a
different edge while preserving the same static/dynamic, authorization,
cache, exact-release, and no-third-party API-documentation browser-network
boundaries.

Preflight validates the active configuration rather than trusting comments: it
rejects active immutable caching, `autoindex on`, a writable/static fallback,
or another directive that weakens this evaluator contract. Comment text cannot
satisfy or defeat those checks.

This procedure proves only a bounded deployment-shaped static-delivery slice.
It does not prove high availability, service objectives, restore/PITR, load,
provider behavior, production settings, or full UX-029 responsive, zoom,
keyboard, screen-reader, and accessibility acceptance.

## Topology and trust boundary

The evaluator creates exact run-labeled disposable resources:

```text
host loopback ephemeral port -> unprivileged reference edge
                                  |-- /static/* -> read-only exact-candidate volume
                                  |-- /media/* -> edge-owned 404
                                  `-- internal proxy network -> Gunicorn
                                                                  |
                                                    internal database network
                                                                  |
                                                             PostgreSQL
```

Only the edge receives a host port, and that port binds to loopback. Gunicorn
and PostgreSQL remain on distinct internal proxy and database networks;
Gunicorn joins both, while the edge never joins the database network. The edge
receives no Docker socket, provider credential, production configuration, or
writable application filesystem. It runs as the image's unprivileged user with
a read-only root filesystem, all capabilities dropped, `no-new-privileges`, and
an explicitly bounded 64 MiB `/tmp` filesystem with `noexec`, `nosuid`, and
`nodev`.

After preflight, the runner copies the reviewed edge configuration into a new
run-owned volume, mounts the directory read-only, verifies the in-container
SHA-256 digest, and asks Nginx to parse the effective configuration. A later
host-file edit therefore cannot change the active retained topology.

The static volume must be new and empty. Docker initializes it from
`/app/staticfiles` in the exact application image before the edge mounts it
read-only at `/srv/maru/static`. The runner independently inventories the image
directory and populated volume and requires identical normalized paths, file
types, byte lengths, and SHA-256 digests. Symlinks, devices, sockets, missing
required files, a non-empty reused volume, or any manifest drift fail closed.

The edge never falls back from `/static/` to Django. It denies `/media` and
`/media/` at the edge; every other path remains a dynamic application request.
It replaces or clears untrusted forwarded client metadata, does not enable
proxy caching, and preserves Django's private `no-store` contract for the
schema and API references.

## Prerequisites and safety

Run from an exact Maru source checkout containing the candidate commit. You
need:

- Docker Engine with Linux containers and permission to create private
  networks, volumes, and containers;
- Python 3.12 or newer through `uv` or the repository virtual environment;
- a browser for the separate visible acceptance step; and
- network access for the digest-pinned image pulls.

Use only disposable repository-owned synthetic data. Do not provide production
personal data, provider credentials, production settings, an existing
database, or a host-public bind address. The evaluator's active administrator
comes from the local-only `seed_demo_data` fixture solely so the private
Swagger and ReDoc pages can be exercised. The runner generates a unique
per-run password, sends it only on standard input to the fixture helper, and
uses it only from the same in-process HTTP client. It does not use the fixture's
documented default credential or persist a browser-recoverable password. This
compatibility/static path never performs ADR 0044 authority activation and must
not be combined with the exact runtime cutover in the
[synthetic OCI runtime rehearsal](synthetic-oci-runtime-rehearsal.md).

## Run the automated rehearsal

With an existing repository environment:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py
```

On the maintained Windows checkout, the equivalent direct invocation is:

```powershell
& ".\.venv\Scripts\python.exe" scripts/rehearse_oci_static_delivery.py
```

The defaults intentionally bind the published candidate. A later candidate
must supply both immutable identities; a tag-only application reference is
invalid:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py `
  --app-image "ghcr.io/martonpornoi/maru@sha256:<64-lowercase-hex>" `
  --expected-source-revision "<full-40-character-commit>"
```

A reviewed alternative edge may be supplied only by immutable digest:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py `
  --edge-image "ghcr.io/example/reviewed-edge@sha256:<64-lowercase-hex>"
```

The command validates and records that identity; accepting it for a maintained
default still requires repository review. PostgreSQL remains a repository-
locked input rather than an operator override. Before creating resources, the
runner pulls and inspects every image and verifies the application revision
label and every requested repository digest.

## Automated acceptance sequence

The runner stops at the first mismatch. Its executable stage order is:

1. Verify the immutable image/source identities and the exact LF-normalized,
   digest-pinned repository edge configuration.
2. Refuse any pre-existing exact resource name or foreign run label; then create
   the separate networks, disposable volumes, standard-input-only secret
   volumes, and the exact one-file configuration snapshot.
3. Inventory `/app/staticfiles` directly from a short-lived candidate-image
   process, require only regular files, and record its count, total bytes,
   normalized paths, and SHA-256 digests.
4. Populate the fresh labeled static volume from that exact image directory and
   require its inventory to equal the image inventory exactly.
5. Start PostgreSQL, apply the candidate migrations, load the repository-owned
   synthetic fixture, and initialize the ordinary application state.
6. Start Gunicorn without a host port, then start the digest-pinned reference
   edge with the read-only config/static mounts, loopback-only ephemeral port,
   non-root identity, read-only root filesystem, dropped capabilities, bounded
   64 MiB `/tmp`, and no Docker socket or database-network membership.
7. Require the exact build identity through the edge and verify the landing
   page's favicon, Apple touch icon, manifest, brand stylesheet, and wordmark,
   plus both icons referenced by the manifest. Each asset must return `200`,
   the expected MIME type, `nosniff`, and the revalidation cache policy.
8. Require the static bytes, cache policy, conditional response, missing-path,
   mutation-method, and edge-owned media-denial boundaries. Raw dot-segment,
   repeated or encoded slash, and literal or encoded backslash probes for both
   `/static` and `/media` must receive compact edge-owned `404` responses
   without a Django request identifier, even when Nginx normalization would
   otherwise select the dynamic proxy.
9. Sign in as the synthetic active platform administrator through the edge and
   require Swagger, ReDoc, and the OpenAPI 3.1 schema to remain private and
   non-cacheable. Every asset reference discovered in the server-rendered
   Swagger/ReDoc HTML must be same-origin under `/static/`; an off-origin HTML
   reference fails the run. The exact candidate's ReDoc 2.5.3 bundle contains
   one client-side `cdn.redoc.ly` attribution-logo request, and that version has
   no supported option that suppresses its footer image. The edge therefore
   gives that exact JavaScript path a narrow compatibility representation: it
   replaces the one pinned remote URL with an inert transparent `data:` image.
   The visible Redocly attribution text and link remain. The candidate image
   and collected static volume stay byte-for-byte exact; only the served ReDoc
   representation differs. This stage pins both source and edge-response size
   and SHA-256 values, requires exactly one local replacement and no remote
   token, and requires both a range probe and a future `If-Modified-Since`
   probe to return the complete transformed `200` response. Wildcard
   `If-None-Match` probes use RFC 9110 semantics: `GET` and `HEAD` return a
   bodyless `304` without a source validator because the selected
   representation exists, while an unsafe `POST` remains denied by the normal
   static method boundary with `403` or `405`. A concrete stale source ETag
   receives the complete transformed `200`. The transformed response may expose
   no source validator, range, content length, or content encoding header. It
   fetches the remaining referenced static files without
   executing Swagger/ReDoc JavaScript or claiming coverage of script-initiated
   requests. Session cookies, CSRF values, credentials, private HTML, and raw
   schema content never enter the receipt.
10. Inspect exact users, privileges, tmpfs bounds, mounts, loopback publication,
    and network memberships, and recheck the loaded edge configuration.
11. Stop Gunicorn and require static files to remain available while a dynamic
   request becomes unavailable. Restart the same candidate process and require
   the exact build identity to return. Stop the edge and require the external
   endpoint to disappear; restart it, rediscover and validate its current
   ephemeral loopback port, and repeat the static/dynamic smoke.
12. Repeat every required static request and the exact build-identity check.

After those stages, stop retained resources or remove only the exact
run-labeled containers, networks, and volumes, then require the expected final
inventory.

## Required HTTP and cache behavior

The reference configuration uses ordinary MIME mappings and adds
`application/manifest+json` for `site.webmanifest`. CSS, JavaScript, PNG, and
icon responses must retain their correct media types. Every static response
uses:

```text
Cache-Control: public, max-age=0, must-revalidate
X-Content-Type-Options: nosniff
```

The candidate image is immutable, but its collected filenames are not all
content-addressed. Do not add `immutable` or a long freshness lifetime merely
because the OCI digest is fixed. Ordinary static responses use ETag or
Last-Modified validators. The transformed ReDoc representation deliberately
exposes neither source validator nor byte-range semantics: revalidation fetches
the complete, current edge representation instead of aliasing the candidate
file's different bytes. Dynamic and private responses never share the static
cache class; the schema and both API-reference pages retain Django's private
`no-store` behavior.

## Visible browser acceptance

HTTP assertions do not prove that the browser applied the assets. Against the
retained successful topology, use a fresh browser context and record the
browser/version, viewport, exact edge origin, and these bounded observations.
The retained runner stops every owned container before it exits. First verify
the exact run label on `maru-static-<run-id>-postgres`,
`maru-static-<run-id>-web`, and `maru-static-<run-id>-edge`; then start
PostgreSQL, wait for it, start Gunicorn, and finally start the edge. Never start
a similarly named resource whose labels do not match the receipt. Because
Docker may allocate a different ephemeral port after a stop/start, run
`docker port maru-static-<run-id>-edge 8080/tcp` after starting the edge and use
only that freshly reported `127.0.0.1:<port>` origin.

1. Load `/` anonymously through the edge.
2. Confirm `core/brand.css` appears in `document.styleSheets`, the computed
   `--maru-navy-900` value is `#071b3a`, and the rectangular wordmark has a
   positive natural width.
3. Confirm every `/static/` request succeeded and every HTTP(S) request used the
   exact edge origin. Record attributable console and failed-request counts.
4. For the issue's authorized documentation-network criterion, set a unique
   temporary password interactively only inside this disposable retained
   database:

   ```powershell
   docker exec -it maru-static-<run-id>-web `
     python src/manage.py changepassword demo.admin@maru.invalid
   ```

   Do not place that password in command arguments, environment values, shell
   history, the receipt, or screenshots. Sign in through the edge, load both
   `/api/v1/docs/` and `/api/v1/redoc/`, and require every sidecar request to
   return successfully from the exact edge origin with no third-party script,
   stylesheet, font, worker, or schema request. Require each UI to visibly
   render its API reference and observe at least one successful same-origin
   request to the exact `/api/v1/schema` route from each UI. Record only
   aggregate request, schema-request, failure, third-party-origin, visible-UI,
   and attributable console facts.

   ReDoc must expose neither a `cdn.redoc.ly` page asset nor a failed or blocked
   attempt to fetch that logo. The inert `data:` image is acceptable because it
   creates no HTTP request. A content-security block is not a passing
   substitute: the compatibility representation must prevent the remote
   request from being created and leave browser logs and failed-request
   inventory clean.

The automated stage proves the authorized Swagger/ReDoc server HTML references
and referenced same-origin sidecar files; the retained browser step above owns
the complementary script-execution and observed-network evidence. The runner's
generated administrator password is intentionally unrecoverable after it exits.
The interactive replacement is permitted only in this stopped-by-default,
disposable retained database and is destroyed by the required exact-run cleanup.

One declared desktop viewport is sufficient for this issue. Do not infer the
UX-029 width, zoom, keyboard, reduced-motion, screen-reader, disclosure-state,
or full accessibility matrix from this smoke. Do not retain authenticated
screenshots, page source, schema content, cookies, or credentials.

## Evidence, failure, and cleanup

Each run writes one ignored, schema-versioned sanitized receipt below:

```text
.local-ci/oci-static-delivery/<run-id>.json
```

The receipt may contain public image/source identities, reviewed configuration
and static-manifest hashes, count/byte totals, public asset paths,
status/MIME/cache classes, minimized build identity, same-origin request counts,
restart results, container hardening facts, and cleanup status. The separate
browser record may add browser/version, viewport, exact origin, and attributable
console/request counts. Neither may contain credentials, database URLs,
cookies, CSRF tokens, raw private HTML/schema, private response bodies, raw
logs, command output, exception text, or personal data.

On failure, inspect the fixed stage and failure code before requesting a
retained-resource run:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py --retain-on-failure
```

Without `uv` on Windows, use:

```powershell
& ".\.venv\Scripts\python.exe" `
  scripts/rehearse_oci_static_delivery.py --retain-on-failure
```

Retain a successful run for the separate browser acceptance with:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py --retain-resources
```

Without `uv` on the maintained Windows checkout, use:

```powershell
& ".\.venv\Scripts\python.exe" `
  scripts/rehearse_oci_static_delivery.py --retain-resources
```

After the browser check, stop the exact edge, web, and PostgreSQL containers,
then remove the stopped run through its receipt's twelve-character ID:

```powershell
uv run python scripts/rehearse_oci_static_delivery.py `
  --cleanup-retained <run-id>
```

The direct Windows equivalent is:

```powershell
& ".\.venv\Scripts\python.exe" `
  scripts/rehearse_oci_static_delivery.py --cleanup-retained <run-id>
```

Close the authenticated browser context first, stop the edge before the web and
database, run the exact cleanup, and independently require zero run-labeled
containers, networks, and volumes. The separate sanitized browser/cleanup
record must include only the run ID, browser/version, viewport, visible-UI and
aggregate request/schema/failure/third-party/console facts, edge-first stop,
cleanup exit status, and empty-inventory result. A cleanup failure leaves the
criterion open and requires operator remediation; never claim that the
temporary credential was destroyed until the empty inventory is proved.

Cleanup validates every exact label before removing anything and must never use
`docker system prune`, broad name filters, or a Compose project shared with
another environment. Retained resources contain only disposable synthetic
data and remain stopped outside the explicit browser window. Before interactive
rotation they expose no recoverable administrator credential. After rotation,
a failed cleanup leaves a stopped synthetic database with the known temporary
credential until exact-run remediation proves an empty inventory.

Container removal also removes its associated anonymous volumes, including
image-declared PostgreSQL data volumes created by one-shot helpers. Named
volumes still follow the separate exact-name and label-verified cleanup above;
retention deletes neither kind. Previously orphaned, unassociated volumes are
not swept. Follow [local Docker housekeeping](../development/docker-housekeeping.md)
for inventory and separate approval of pre-existing resources.

## Separate evidence boundaries

The [runtime rehearsal](synthetic-oci-runtime-rehearsal.md) owns PostgreSQL
runtime-role, authority-activation, readiness, database restart, and idempotent
bootstrap evidence. This static-delivery rehearsal owns unchanged collected
bytes, edge routing/cache behavior, private same-origin sidecars, browser asset
application, and web/edge restart. Neither receipt replaces the other.

A production deployment still needs an accepted target edge/TLS/WAF adapter,
secret management, production settings, provider and worker supervision,
telemetry, representative load and recovery, security/privacy review, full
accessibility evidence, partner policy, and accountable human go/no-go.
