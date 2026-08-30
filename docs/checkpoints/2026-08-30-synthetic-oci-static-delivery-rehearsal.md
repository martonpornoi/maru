# Synthetic OCI static delivery rehearsal

- Date: 2026-08-30
- Issue: [#38](https://github.com/martonpornoi/maru/issues/38)
- Parent evaluation: [#29](https://github.com/martonpornoi/maru/issues/29)
- Runtime prerequisite: [#37](https://github.com/martonpornoi/maru/issues/37)
- Requirements: UX-029, NFR-001 through NFR-004, NFR-011
- Decisions: ADRs 0021, 0056, 0060, 0065; no new ADR

## Outcome

Maru now has one canonical, executable, deployment-shaped evaluator for the
immutable first release candidate's static-delivery boundary. It composes the
exact candidate with a digest-pinned unprivileged reference edge, copies the
candidate's already-collected files without rebuilding or mutating them,
serves those files from a read-only volume, denies runtime media, and proxies
only dynamic routes to internal Gunicorn.

This closes the default-Gunicorn static `404` finding from issue #29 for one
bounded synthetic adapter. It does not modify the immutable candidate, select
Nginx as Maru's production edge, or certify production infrastructure.

## Implemented boundary

- `scripts/rehearse_oci_static_delivery.py` owns immutable image/source
  validation, exact run-labeled resources, bounded standard-input secrets,
  byte-for-byte static manifests, staged HTTP acceptance, hardening inspection,
  restart checks, sanitized receipts, retention, and exact-label cleanup.
- `scripts/oci-static-edge.conf` is LF-normalized and digest-pinned. It keeps
  static files and runtime media out of the dynamic proxy even for repeated or
  encoded slashes, literal or encoded backslashes, mixed dot segments, and
  percent-encoded namespace characters.
- Static responses use correct MIME types, `nosniff`, and revalidation rather
  than long-lived immutable caching because collected filenames are not all
  content-addressed. Missing static paths never fall back to Django.
- Swagger, ReDoc, and the OpenAPI schema remain authenticated and `no-store`.
  Every server-rendered documentation resource reference must be same-origin
  below `/static/`; a same-origin dynamic resource path fails closed.
- The immutable ReDoc 2.5.3 bundle embeds one `cdn.redoc.ly` logo URL. The
  exact bundle path receives a deterministic edge-only representation that
  replaces that URL once with a transparent `data:` image. Candidate and
  volume bytes remain unchanged, while the visible Redocly attribution text
  and navigation link remain.
- The transformed ReDoc response exposes no source ETag, Last-Modified,
  content length, content encoding, or range semantics. Wildcard
  `If-None-Match` follows RFC 9110: `GET` and `HEAD` return cache-policy-bearing
  bodyless `304`, unsafe methods retain ordinary static denial, concrete stale
  validators receive the complete transformed `200`, and range/future-date
  probes cannot bypass filtering.

## Exact final automated evidence

The authoritative run `c38e0c7d2f93` executed from `2026-08-30T07:01:13Z`
through `2026-08-30T07:03:45Z` with:

- candidate `v2026.08.27-rc.1`;
- source `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`;
- application image
  `ghcr.io/martonpornoi/maru@sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
- PostgreSQL
  `postgres:17.11-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`;
- reference edge
  `ghcr.io/nginx/nginx-unprivileged:1.30.4-alpine3.24-slim@sha256:3b569ded54fe09ab73dbdb409f403631d55c0bb231e4adc10b7c974beb0dc7be`;
  and
- reviewed edge-config SHA-256
  `aca9da2ad29c32e972227ef34e7bef1c0423b6d8d4c63baa822fc30eda5e6b3c`.

All 12 ordered stages passed. The exact application image and populated volume
both contained 196 regular files, 14,846,309 bytes, and manifest SHA-256
`4c8c346be63ed0267060127c2902fc49ac47f10e1995216f304fa378fa516e9f`.
Five landing assets, two manifest icons, 12 static escape probes, nine media
escape probes, missing-path denial, mutation denial, private documentation,
OpenAPI 3.1, and both restart boundaries passed.

The application ran read-only as UID 10001 and the edge read-only as UID 101.
Capabilities were dropped, `no-new-privileges` was set, `/tmp` was a bounded
64 MiB hardened tmpfs, the Docker socket was absent, the edge had no database
network access, and only one loopback edge port was published. Static files
remained available while Gunicorn was stopped; dynamic service recovered with
the same build. Edge stop/start required a freshly discovered port and retained
the same snapshotted config and static manifest.

The candidate ReDoc source was 1,097,271 bytes with SHA-256
`1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0`.
The deterministic served representation was 1,097,309 bytes with SHA-256
`488ad6f335c47d69afe969ab3c9a906d5d2b91695d6b3e0be63ab76f63c94021`.
The receipt ended `result=passed` and `cleanup.status=removed`; independent
exact-label inventory found zero containers, networks, and volumes.

## Final visible browser evidence

Retained run `d38e0c7d2f94` passed the same 12 stages and exact hashes from
`2026-08-30T07:04:00Z` through `2026-08-30T07:06:36Z`. The Codex in-app
browser did not expose a build/version identifier; that limitation is recorded
rather than guessed. At 1,440 by 900 CSS pixels against exact temporary origin
`http://127.0.0.1:59678`:

- the anonymous landing page visibly rendered, had no horizontal overflow,
  applied same-origin `core/brand.css`, computed `--maru-navy-900` as
  `#071b3a`, and loaded the complete 2,918 by 825 wordmark;
- every observed landing HTTP asset was same-origin and the browser console
  contained zero warnings or errors;
- authenticated Swagger visibly rendered `Maru API 0.1.0 OAS 3.1`, loaded its
  two scripts, stylesheet, favicon, and `/api/v1/schema` from the exact edge
  origin, and produced zero console warnings or errors; and
- authenticated ReDoc visibly rendered `Maru API (0.1.0)`, loaded only the
  same-origin bundle, same-origin schema, and favicon as HTTP assets, exposed
  the decorative logo as the expected `data:` image, made no `cdn.redoc.ly`
  request, and produced zero console warnings or errors.

No authenticated screenshot, page source, schema content, cookie, CSRF value,
or credential was retained. The authenticated tab was closed and the temporary
viewport reset before cleanup. The exact edge, web, and PostgreSQL containers
were then stopped in that order. `--cleanup-retained d38e0c7d2f94` succeeded,
and independent exact-label readback returned zero containers, networks, and
volumes. Only then was the one-use synthetic password considered destroyed.

## Corrected historical inference

The append-only
[2026-08-16 interactive API documentation checkpoint](2026-08-16-interactive-api-documentation.md)
correctly recorded that server-rendered templates used local sidecars, but its
inference that the browser could make no CDN request was incomplete. Executing
the immutable candidate's ReDoc bundle exposed the embedded attribution-logo
request. This checkpoint supersedes that inference only for this bounded edge
adapter. ADR 0056's no-third-party disclosure intent remains unchanged, and
every future candidate or production adapter must independently preserve the
browser-network boundary.

## Preliminary failures retained as learning

The final result followed several fail-closed preliminary runs:

- retained browser run `784646fdb5ec` revealed the hidden `cdn.redoc.ly`
  request and was destroyed with empty exact-label inventory;
- run `5c5f5fde90a2` rejected an invalid server-HTML-only `hideLogo` assumption;
- run `6ac286d01f74` passed an early transform but was superseded after a
  wildcard-validator bypass was found;
- run `a38e0c7d2f91` passed the repeated/encoded traversal guards but was
  superseded when literal-backslash raw targets were added; and
- earlier runs `d8819ac62980` and `8725190237e3` exposed host-port inspection
  and restart reallocation assumptions, both of which were corrected and
  cleaned.

These runs are not acceptance evidence. They demonstrate that the evaluator
stopped at mismatches and that browser execution plus independent review found
gaps that server HTML and ordinary happy-path probes could not.

## Verification and limitations

Focused unit coverage protects configuration identity, immutable manifests,
origin/path restrictions, conditional and range behavior, raw namespace
escapes, evidence redaction, hardening, retention, collision refusal, and exact
cleanup. The pinned Nginx image accepted the final configuration with `nginx
-t`; separate raw request-target probes returned compact edge-owned `404` for
literal-backslash, repeated-slash, and percent-encoded forms.

No application models, database schema, or migrations changed. Rolling this
repository change back removes only the evaluator, reference edge
configuration, tests, and documentation; it does not mutate the immutable
candidate. Recovery for an intentionally retained synthetic run remains the
documented exact-label `--cleanup-retained RUN_ID` operation.

This evaluation does not provide an independent vulnerability or package
advisory certification for the reference edge image. Digest identity and
runtime hardening are proven; target-provider image policy, SBOM/advisory
review, TLS/WAF, production settings, secret management, workers, telemetry,
load, recovery, full UX-029 accessibility, privacy/security review, and human
go/no-go remain external gates.

## Smallest next action

Resolve [#39](https://github.com/martonpornoi/maru/issues/39) as its own focused
Assignment authority-interval recovery pull request without changing the
immutable candidate evidence established here.
