# Workforce rota integrity review repair

- Date: 2026-10-29
- Scope: #223 / PR #224, child of #22; HR-016 and ADR 0127.
- Original head: `beecadaf04e14f44f82ff2d42cea7e8eaeb83166`.
- Protected base: `968607e93b92bc5dbb9acca52fd6e7cb6854c935`.

## Supported findings and repair

The single automated review identified four defects in the first implementation.
An ordinary ZIP end record could conceal a ZIP64 locator whose real directory
exceeded the checked limit. The standard ZIP member reader could truncate output
to a forged declared size and accept a hash-matching prefix, including a manifest
prefix or content whose complete inflation exceeded 16 MiB. Opening a FIFO could
wait for a writer before regular-file validation. Default argument errors could
echo a rejected personal pathname or option.

New regressions against that unchanged implementation recorded 17 failures and
one passing Windows directory refusal. The size cases demonstrated actual false
success for stored and deflated content, a hidden inflation overflow and a hidden
oversized manifest. The ZIP64 case reached entry construction despite a real
directory over 4 KiB. The argument cases demonstrated actual rejected-value output.
Windows cannot exercise a real Unix FIFO: the descriptor-flag regression exposed
the missing nonblocking open, while the conditional live FIFO case remains for
the Linux hosted runner.

The repaired reader rejects the ZIP64 locator before constructing entries and
ZIP64 extra fields in either header. Local headers, central metadata and contiguous
member extents must agree. Stored contents or raw-deflate streams are bounded by
the remaining complete-package limit; deflate must reach its actual end with no
unconsumed or trailing bytes. Complete lengths and CRCs are checked independently
of declared output size before manifest interpretation or hash acceptance. Data
descriptors and flags other than UTF-8 filename encoding are unsupported; current
seekable exporter output needs neither. The exact 16 MiB boundary remains valid.

The same opened descriptor is checked as regular after nonblocking opening where
supported. Invalid command arguments keep exit status two and fixed guidance,
without echoing values. There is no new dependency, format version, route, tenant
query, grant, migration, write, extraction, schema execution or network operation.
On failure retain the original copy and obtain a fresh authorized export.

## Evidence boundary

The first head independently passed all ten ordinary Auto gates: 14,497 unit
cases with eleven existing warnings; 5,173 required native cases across 21 current
shards and 15,519 setup/call/teardown phases; 128 frontend cases; both audits;
fresh warning-fatal documentation; exact generated assets; and 91.17494290590399%
combined coverage. All 3,270 source and nine changed hashes, plan/selection/JUnit
identities and outcomes, peak eight, measured headroom and exact cleanup matched.
All 12,155 original local outputs remain sealed in the retained checkout. Its
three exact-head CodeQL analyses were clean. Those facts remain first-head
evidence and do not accept the repaired source. The obsolete application run was
cancelled after the review; no partial hosted subset is called success.

After repair, all 89 focused checker and existing exporter cases pass, including
83 checker cases. Coverage includes complete stored/deflated prefixes, actual
inflation and manifest limits, stream end/trailing bytes, false CRCs, ZIP64 locator
and extra fields, unchanged maximum size, descriptor flags and minimized real CLI
errors. Existing early-boundary tests now observe the actual member-reading
boundary rather than the removed ZIP reader. Their refusal assertions and limits
remain unchanged.

Earlier static feedback retained two new-test style findings and one strict type
finding for the integer returned by binary unpacking. The fixed literal regex,
separate assertions and explicit integer return preserve the same behavior; those
failed feedback outputs remain separate from subsequent checks.
A later docstring check also required indirect parser exit behavior to be
documented as a note rather than as an explicit raise in the overriding method.

Whole-source Ruff, strict types over 893 files, both docstring checks and
documentation policy over 780 Markdown files, four skills and 223 requirement IDs
pass. Clean-commit ordinary Auto and new exact-head hosted acceptance/review
disposition remain required. Preserve earlier outputs;
do not repeat the consumed review request or treat the earlier head as acceptance.
Human/browser/accessibility, recovery-owner, operational and production gates,
the separate manual-test environment and #22's remaining continuity scope are
unchanged. Maintained interactive demos are unaffected by this file-only command.
