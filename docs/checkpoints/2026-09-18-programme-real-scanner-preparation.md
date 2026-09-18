# Programme real-scanner preparation

Date: 2026-09-18

## Outcome and scope

Prepare the genuine supporting-file dependency needed by P02 in #108/#109 under
#48. ADR 0104 requires actual ClamAV INSTREAM evidence; no test-clean adapter or
caller-produced clean receipt is introduced. NFR-013, PRG-001/002/006, IDN-014,
AUD-001 and the existing private-file contract remain unchanged. No production
profile, schema, route, scanner service or PostgreSQL-policy change is included.

## Source and resource boundaries

Official Docker Hub metadata was read, not pulled or executed, on 2026-09-18.
`clamav/clamav:1.5.4` resolved to the preloaded-signature image digest
`sha256:9cb27d7660bdf66e9878c832cb433dd8aa152cfbe16f3c2c0084c80b04ae22b4`
(metadata updated 2026-09-14). The prepared launcher uses that immutable pin with
`--pull never`. It does not follow a mutable stable tag or download signatures.
The source selection uses [official ClamAV Docker documentation](https://docs.clamav.net/manual/Installing/Docker.html)
and [official image metadata](https://hub.docker.com/r/clamav/clamav/tags).

The explicit `with_scanner=True` runner option owns a separate nonce-labelled
internal bridge and container, publishes only `127.0.0.1` on a random host port,
uses a non-root daemon and read-only image, drops capabilities, prohibits privilege
gain and bounds CPU/PIDs/memory/tmpfs. No host file mount, retained data volume,
signature updater or milter runs. Actual PING/VERSION replies require exact framing,
engine version and signature age no more than seven days, with bounded clock-skew
tolerance. This is a rehearsal dependency criterion, not a guarantee of benign PDFs
or a production malware-scanning approval. Each upload still uses the unchanged
owner's actual INSTREAM scan and all custody/authorization gates.

Container expiry uses the original fixture deadline translated to an absolute UTC
epoch, then a bounded in-container watchdog; delayed Docker startup does not grant
a fresh lease. Normal teardown verifies full resource IDs, original owner nonce,
image, exact loopback publication and an empty owned network before removal. A
controller crash can leave the labelled empty network after daemon auto-removal;
recover only that exact verified resource, never prune Docker or adopt a shared
network. The complete native lifecycle remains unverified.

Review found a related loopback-transport prerequisite: Docker documents possible
same-L2 access to localhost-published ports before version 28. Both the database
and scanner preparation now reject older, unknown or prerelease engine versions
before creating resources. Each launcher pins subsequent commands to its inspected
local daemon endpoint and strips ambient context/host overrides, preventing a
concurrent default-context change from redirecting creation or cleanup. See
[Docker's port-publishing warning](https://docs.docker.com/engine/network/port-publishing/).

## Verification and continuation

Database-free focused feedback passed 93 cases in 0.48s before the absolute-epoch
expiry refinement. Ownership drift, foreign/nonempty networks, unsafe publications,
bounded health parsing, version/signature freshness, uncertain start cleanup,
optional runner wiring and local daemon pinning are covered with mocks/pure tests.
These are not actual daemon, network, scan, PostgreSQL or browser observations.
One host-only actual daemon/public-preparer case is maintained but uncollected and
unexecuted under #102. Complete iterative database-free feedback passed 10,723 tests
in 59.64s after the expiry refinement, with three existing Django URL-field
transition warnings. Ruff passed. Clean exact-head retained certification and
protected delivery are pending at this snapshot.

Next finish P02–P12's real owner composition and isolation assertions; preserve
the scanner image cache until a deliberate reviewed refresh, and require current
actual signature evidence before execution. Later restore tracked required policy,
run #102/#97/#109 and obtain genuinely human #92 evidence before final promotion.
#108/#48 remain open. No image/container/database/migration/server/browser was run.

## Protected delivery

[PR #172](https://github.com/martonpornoi/maru/pull/172) squash-merged at
2026-09-18 17:29:28 UTC as `4d380854215995d531c7e5a583f0cb15a5dee403`.
Its tree `7d9486287d0f8bb99210470e5c37a98786009942` equals certified head
`f14363907d2eff0e5751a8bde0703feb167c479d` exactly. The separate clean main
worktree fast-forwarded to the same origin/main commit; unrelated repair checkout
`aa1ede69fb880dcb12d627bbfc049fba23166e68` was preserved.

All eight exact-head retained local gates passed in 391.06s (6m31s), including
10,723 units in 63.02s and 103 frontend cases. The v4 receipt explicitly records
`postgresql_deferred`, zero native/database instances and null combined coverage
and measured timing headroom. Five artifacts were archived and hash-verified in
`.tools/certification-evidence/issue108-f143639-deferred/`; receipt SHA-256 is
`DC5458F9C5A4BD0DA33451004708D3F2C8EFBD9C1BEB94D96CBA3106D0E63043`.

Hosted quality passed in 11m13s and units in 1m42s
([run 35373424837](https://github.com/martonpornoi/maru/actions/runs/35373424837)).
The exact-head aggregate PR gate passed, all three processed CodeQL configurations
reported the same commit without errors, and fully paginated review/closing-issue
checks showed no unresolved conversation, blocking review or unintended closure.
Native scanner/P02 acceptance remains unexecuted; this delivery does not close
#108, #109, #102 or #48.
