# First Guides workflow: protected delivery

Date: 2026-10-14

## Outcome

[PR #212](https://github.com/martonpornoi/maru/pull/212) delivered reviewed,
edition-scoped instructions and FAQs through the accepted KNO-010–013 boundaries
and ADRs 0118, 0119 and 0124. The four observed UI defects were repaired and
re-exercised: optional placements, My Maru request discovery, eligible-event
setup discovery and narrow-screen action obstruction.

## Exact delivery evidence

- Candidate: `bb286e8291895a90b5cd21b0e527fb255bbb4a21`.
- Base: `bc09e8b63e4142c712178a067a123c61b0924e2f`.
- Certified and merged tree: `d7aae24c484db3c86170957673bf969d489e83b5`.
- Protected squash commit: `c4a988d0808c6ee054c7ed7c726c5a111e934579`,
  merged at 2026-10-14 07:17:51 UTC, with the expected single base parent.
- Full local certification: ten gates, 14,251 unit cases and 5,247 native cases
  across 88 batches; 91.24 percent combined branch coverage, unchanged 90 percent
  threshold; maximum eight databases; measured headroom passed. Elapsed 4h33m21s.
  All 88 exact owned containers were independently confirmed absent.
- [Hosted run 38496369530](https://github.com/martonpornoi/maru/actions/runs/38496369530)
  passed all 88 PostgreSQL jobs, full unit coverage, combined coverage, Full CI
  gate and PR gate. Three direct targeted-path jobs were intentionally skipped
  because the full path ran. Required PR gate provenance was Actions integration
  15368. No test case was removed to obtain acceptance.
- Exact-head CodeQL accepted Python, JavaScript/TypeScript and Actions with zero
  reported alerts. Copilot review 5512080352 reported zero findings; its broad
  security-sensitive-scope caution is not an independent-human approval.
- Review conversations were resolved (zero threads), current main matched the
  certified base, and mergeability was clean. The owner-reviewed test migration
  rename retained its exact-head label. All branch protections stayed active.
- The designated clean main checkout was fast-forwarded only. Local main,
  origin/main and the returned protected commit matched, including tree identity.

The entire successful local evidence directory was copied into the candidate's
task-local run archive before starting subsequent work; original evidence and all
older failed/interrupted results remain preserved. The Guides monitor was paused
after verified merge and synchronization.

## Browser and acceptance boundaries

The [browser record](2026-10-13-guides-browser-handoff.md) and
[UI repair record](2026-10-13-guides-ui-repairs.md) retain actual synthetic
combined-event and fresh Guides-only journeys, separate accepted responsibilities,
review, reader disclosure, unchanged Announcements evidence, no-script behavior,
narrow pointer actions and measured widths. Fixtures remain stopped and preserved.
Native database success is separate from those browser observations.

Native print, 200 percent zoom, complete keyboard/specialist accessibility,
independent-human, broader paged-decision and operational/production acceptance
remain open. This delivery does not close the document-governance umbrella #53,
activate Programme, or claim production readiness.

## Next bounded outcome

Begin useful ongoing/future fictional Announcements and Guides examples on
`codex/convention-demo`, based on the protected merge. The maintained
[demo contract](../modules/demo-data.md#next-bounded-demo-outcome) owns scope.
The existing seed has not been changed by this checkpoint. No unrelated module
work or agent has resumed.
