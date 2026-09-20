# Programme offline scanner: actual runtime correction

Date: 2026-09-20. #109/#108 supporting acceptance within #48; local, not delivered.

## Observed failures and correction

The complete fixture initially lacked its exact cached ClamAV image. The official
1.5.4 digest was explicitly pulled unchanged. Actual Docker Desktop 29.7.2 returned
`3310/tcp: []` for the internal-only bridge, so the planned publication was not a
working endpoint. No external network was attached to the scanner to evade this.

The corrected fixture keeps the daemon on its owned internal-only bridge with no
published container ports. A separately owned host-loopback listener forwards only
PING, VERSION and bounded INSTREAM through fixed Docker exec to the exact daemon.
Two exchanges maximum, 10 MiB data/64 KiB overhead, 1,024-byte replies, bounded
input/exec/lifetime deadlines, hidden Windows process, no raw output logging and
stdin-only private bytes constrain this test transport. Unsupported commands fail
closed; the normal Applications scanner retains its tighter deadline and exact
clean-response contract. No fake scanner verdict or changed product adapter exists.

The real daemon then reported signatures 28122 dated 2026-09-13 06:26:25 UTC,
correctly outside the seven-day limit on September 20 afternoon. Both official
`stable` and `1.5.4` resolved to the existing immutable digest. Freshness was not
relaxed. Explicit `MARU_PROGRAMME_SCANNER_REFRESH=isolated` now prepares one owned
public-signature volume with a separate bounded non-root FreshClam updater. Only
that updater has temporary networking; it receives no private file, credential or
host mount and exits before the scanner mounts the volume read-only. Default runs
still perform no download. Exact nonce/ID ownership governs cleanup; existing or
changed resources are never adopted/pruned. An interrupted controller can require
later exact owned-volume cleanup; it is not a production persistent service.

The immutable base is still
`clamav/clamav:1.5.4@sha256:9cb27d7660bdf66e9878c832cb433dd8aa152cfbe16f3c2c0084c80b04ae22b4`.
The [Docker port/network documentation](https://docs.docker.com/engine/network/port-publishing/)
informed the transport correction; actual local observations, not the documentation
alone, establish the failed publication and subsequent real daemon result.

## Evidence and next boundary

The unmodified host-only scanner/public-preparer test passed in **15.81s** with
explicit refreshed signatures and verified owned-resource cleanup. Sixty-one
focused mocked/pure/loopback transport tests passed in **0.88s**, covering opt-in,
private-data exclusion, fixed commands, bounded protocol, ownership changes and
uncertain updater cleanup. Ruff and documentation checks passed.

Before the local milestone commit, the complete fast suite passed **12,646** tests
in **72.77s**, with three existing Django URL-field transition warnings.

The actual populated Programme fixture now passes scanner/startup/setup, then fails
inside P02 proposal composition (229.45s). Content-free child diagnostics are next;
no full P01–P12, populated archive, browser/human, logical restore, exact-head
certification or production approval is claimed. The earlier standalone empty-owner
archive runtime pass remains separate evidence.
