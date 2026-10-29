# PR #222: development dependency security repair

Date: 2026-10-25

## Failed attempt retained

The first overnight ordinary Auto attempt pinned clean
`562f439747672be0aa337fcbeff2731fb8979fdd` against protected
`7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b`. Its exhaustive plan contained 111
native shards. The Python audit failed on filelock 3.32.0, reporting
CVE-2026-112907, CVE-2026-112913 and CVE-2026-112940.

After that known failure, the existing `cancel-pool` mechanism stopped the
database pool rather than spending hours on an uncertifiable candidate. Eight
shards were interrupted and 103 were unstarted; all eight task-owned containers
were removed. All 14,433 units passed with eleven existing warnings. The
unchanged original certification command exited 1; no success receipt or combined
coverage exists. Gates following the failed audit were unexecuted.

The wrapper verified unchanged tracked source, head/tree and original container
inventory, with no new containers left. All 1,010 original local-CI files were
moved to fresh ignored preservation storage and independently SHA-256-verified
before a replacement run. The manual-test services, records and source files
were not modified.

## Bounded repair

Upstream [filelock 4.2.1](https://github.com/tox-dev/filelock/releases/tag/4.2.1)
provides the supported fixes. The lock now selects that release, with a
`filelock>=4.2.1,<5` development-tool security constraint. The existing Requests
trust/transport constraints remain in effect. All 107 other Python package
records remain identical. The actual CacheControl file-cache consumer passed
set/get/delete interoperability with the patched filelock; the fresh Python
audit reports no known vulnerabilities.

A pre-restart frontend audit also found undici 7.29.1 advisories
GHSA-4qv8-2p9j-2685, GHSA-f72v-6w45-q472 and GHSA-xjj6-f33q-929c.
The existing security override now targets
[undici 7.30.1](https://github.com/nodejs/undici/releases/tag/v7.30.1).
All 173 other frontend package records, direct dependency specifications and
lock settings remain identical; snapshots change only the undici reference.
Frozen installation and a fresh all-severity frontend audit pass with zero
reported vulnerabilities. All 124 frontend tests pass with the patched tool.
Fresh API generation, frontend types and the normal production build preserve
all six supplied generated files byte-for-byte.
The initial noninteractive install lacked `CI=true` and refused to replace its
own module directory; the corrected invocation verified that exact isolated
directory before the normal frozen install. No manual-test module tree changed.

These are development/audit/browser-test dependencies. No domain writer,
permission, profile, migration, runtime grant, API contract or production data
changes. Preserve the patched floors on future lock regeneration. A source
rollback needs no database migration, but reverting the security fixes would
reintroduce the reported vulnerable tool versions.

## Remaining verification

Focused feedback is not exact-head certification. Commit the documented repair
and freshly run the unchanged complete ordinary Auto path on the clean candidate,
with all required history, normal eight workers, coverage/headroom thresholds
and every repository gate intact. Keep failed originals and draft PR status;
update PR #222 with the actual resulting receipt or precise next blocker.
Human invitation acceptance, browser continuation, independent accessibility,
hosted merge acceptance and production approval remain separate.
