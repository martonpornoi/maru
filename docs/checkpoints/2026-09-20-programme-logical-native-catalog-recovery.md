# Programme logical restore: exact native catalog recovery

- Date: 2026-09-20
- Scope: #97 within #48; local Programme exit bundle, not protected delivery
- Decisions: ADRs 0113 and 0114

The first maintained populated restore attempt failed in **951.93s**. Every
preceding maintained proposal-through-archive phase passed; the restore phase
copied and compared the complete source data, then failed genuine restored-worker
native readiness in 12.062s. This is a failed overall run, not acceptance.

Two stopped-foundation diagnostics localized the refusal to native readiness.
A separate same-image data-free round-trip compared owner catalogs and identified
the exact remaining differences:

- Older Applications/Programme/Logistics definition readers used pretty CHECK
  rendering, which has the same enum-cast reparse without the non-pretty
  parentheses. They now use the same narrowly selected canonicalization mode;
  definition/catalog hashes and all other metadata stay unchanged.
- Two Workforce receipt trigger definitions inspected by Authorization contain
  the same enum-array predicate. Their original complete reviewed definitions
  remain pinned, with the narrow pretty cast normalization only.
- Two Identity conditional delivery triggers retain identical readable DDL but
  differ in internal `RelabelType.relabelformat` flags, from implicit 2 to explicit
  1. Source-location normalization did not explain the difference and was not
  adopted. ADR 0114 instead pins complete exact readable definitions derived
  from Identity 0018's finalized guards, preserving all independent attachments,
  function, ACL, timing and retention checks.

The schema/pretty regression suite passed **61 cases in 16.31s**. The next native
suite passed **194 cases in 34.06s**, including real trigger recreation, altered
predicates/events/timing and the existing invitation readiness contract. The
full logical schema round-trip then passed in **6.86s**, with identical compared
owner catalog outcomes before and after. The three previously documented
physical dropped-column layouts remain different and are not normalized.

The complete fast suite before the trigger correction passed **12,746 cases in
71.78s**, with three existing URL-field warnings; this is not a full-suite receipt
for later changes. Changed-file lint and documentation validation pass.

The next maintained journey was interrupted during setup after spotting a
model-dependent import before Django initialization in the new negative-probe
child. Only its exact ID/nonce-verified tmpfs container was stopped and removed;
its synthetic contents were discarded. This is not a passing test. The child
initialization order now has regression coverage: ten focused fault/probe tests
pass in 0.27s. A new full journey, with unsafe-ACL/function and actual restored-
authority revocation checks, is running. No restored-runtime acceptance is yet
claimed, and #97/#109/#108/#48 remain open.

Evidence: `.tools/programme-populated-runtime-native-15.xml` (failed),
`.tools/programme-logical-schema-native-2.xml`,
`.tools/programme-logical-schema-native-3.xml`,
`.tools/programme-logical-schema-probe-10.xml`, and
`.tools/programme-exit-bundle-units-19.xml`. The interrupted run16 produced no
passing report; run17 is the new active attempt. Historical failed diagnostics
are retained separately. Partial-backup/journal denial, full integrated stop-use,
human/browser evidence and exact-head protected delivery remain separate gates.

## Genuine restored-runtime result

Maintained run17 subsequently **passed in 934.27s (15m34s)**, including all prior
populated Programme phases and **38.437s** for logical restore. The real restored
worker and candidate runtime passed readiness. Granting database CREATE to the
clone's runtime and changing the clone's reviewed function to SECURITY DEFINER
each made startup unavailable; reverting each exact fault restored readiness.
No source-database ACL or function was changed.

The restored planner's real login read the current authorized release; the
unadmitted proposal lead was denied. A native copy withdrawal and exact retry
withheld checked selections while retaining the same pointer and historical
artifact bytes. The real controller then revoked the restored planner's exact
edition assignments through ordinary owner commands, and the same credentials
could no longer read the release. Final native readiness still passed. All
original database row fingerprints and excluded-owner comparisons remained
unchanged. The owned restore target and rehearsal container were disposed of;
the labelled rehearsal-container inventory was empty afterward.

Archive generation in this run took 15.532s for 157,233 bytes, with 2,986,272
bytes tracked Python peak (not RSS). The complete fast suite after the trigger
correction passed **12,749 cases in 84.67s**. The existing native missing-journal
read-denial regression passed in 9.18s. Evidence:
`.tools/programme-populated-runtime-native-17.xml`,
`.tools/programme-exit-bundle-units-20.xml`, and
`.tools/programme-logical-missing-journal-1.xml`.

A subsequent maintained partial-backup phase intentionally omits only release-
journal table data in a separate full custom-format dump. It requires nonempty
source journal data and the exact copy-mismatch refusal before worker startup,
with original-source comparison and clone disposal. It has 30 focused harness
checks (0.35s), but was added after run17 started and **was not executed by that
run**. It remains an explicit next-run requirement, not a passing recovery claim.
Run17 was development evidence, not exact-head whole-repository certification.
