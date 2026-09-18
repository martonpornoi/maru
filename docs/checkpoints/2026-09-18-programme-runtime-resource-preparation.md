# Programme runtime resource preparation

Date: 2026-09-18
Scope: #108's isolated fixture beneath #48; not a complete runner or native proof.

## Prepared boundary

Added a database-free configuration fence and disposable PostgreSQL transport.
Tracked required policy precedes environment access or Docker discovery. Exact
opt-in, nonzero run identity and a 60–3600-second lease are mandatory. The future
application configuration admits only its run-named loopback database and
`maru_runtime`, without ambient libpq overrides or secret-bearing error output.

The transport uses the existing pinned PostgreSQL 17 image, local socket/pipe,
loopback ephemeral port, tmpfs and auto-removal. Each creation attempt has a
locally cached image prerequisite (`--pull never`, no late image-pull creation)
and a separate random ownership nonce. The nonce prevents cleanup of a concurrent
same-run attempt. Exact name, labels, image and full container ID are rechecked before
forced removal. Ambiguous start can recover its own resource; foreign ownership,
unavailable inspection or unverified cleanup fails closed. No existing container
is adopted and no broad Docker cleanup is added. An internal supervisor requests
fast shutdown at expiry and kills its database child after ten seconds' grace.
Actual timing/process behavior still requires native acceptance.

The returned administrator credential is not an application runtime connection.
Its representation omits the password; callers must not log or serialize the
credential. The nonsecret ownership nonce is retained for exact crash recovery.
No schema, profile, route, runtime ACL, application data or current policy changed.

## Evidence and outstanding work

Focused pure/mocked tests passed **97 cases in 0.38s**. Complete database-free
feedback passed **10,382 cases in 58.96s**, with three existing URLField warnings.
The subsequent ownership-receipt refinement passed all 97 focused cases in 0.36s;
fresh exact-commit certification remains required.
An initial test accidentally replaced Python's shared environment object; it was
corrected to replace only the tested module's OS reference. That failed test run
started no external resources. Static formatting/lint findings were corrected.

Four maintained host-only native cases cover actual database identity/normal
cleanup, exception cleanup, expiry with a live controller and expiry after abrupt
controller exit. They are outside routine collection/the eight-worker application
pool, and refuse explicit collection while tracked policy is deferred. They have
not been collected or executed. Record their exact-head evidence under #102 after
restoration, independently of native schema/command/runtime-role acceptance.

No Docker command, database, server or browser fixture was started during this
preparation. Exact-commit development certification and protected delivery remain
pending. Separate migration/runtime provisioning, exact candidate installation,
guarded application startup, real setup/roles and P01–P12 still need implementation
and evidence. #108/#48 and #102/#97/#92/#109 remain open; this increment grants no
production activation or acceptance exception.
