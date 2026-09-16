# Programme setup receipt protected delivery (#108)

[PR #153](https://github.com/martonpornoi/maru/pull/153) delivered dormant receipt
storage, native provenance/retention guards and purpose-specific readiness. It did
not deliver an executable profile, command, route, authority or integrated fixture.

- Certified head: `1dbfd77ca026a35c9ad7429b4580f3435844d9d1`.
- Base: `6e34e35be129033ac0254c4b99680d21dbbc858d`.
- Protected squash: `216b13253dde15cb59fbbf09bcb6e2752d4e86d2`, merged
  2026-09-16 21:17:14 UTC by normal match-head squash.
- Equal head/squash tree: `096e1b8364239e1831b986a85e714ef6b703798c`.
- Clean local main and origin/main matched the squash; unrelated worktrees,
  old branches and user containers remained untouched.

All eight retained exact-commit local gates passed in 389.08 seconds (6m29s),
including 9,141 units in 67.54s and 103 frontend tests. The schema-v4 receipt is
`postgresql_deferred`: zero database instances during certification, null combined
coverage and null measured native headroom. Receipt SHA-256:
`24df3bccfaa596b11a02d0c184c2ff964af632a705ae8ca5af4532a85d2569bc`.
Receipt, plan, JUnit and both package artifacts were archived and copy-hash verified.

Hosted run `35150173240` passed quality in 11m23s, units in 2m04s and PR gate in
five seconds. CodeQL run `35150167728` passed all languages. The direct exact-head
snapshot was CLEAN, with no reviews or unresolved conversations and no pagination
remainder. The watcher's stale pending output was not treated as current evidence.
Native jobs were explicitly skipped, not passed.

The separately approved forward schema/metadata observation and exact container
cleanup remain in the [schema checkpoint](2026-09-16-programme-setup-receipt-schema.md).
Twenty-seven native schema scenarios remain uncollected/unexecuted on #102. #108's
body and #48 distinguish delivered prerequisites from incomplete atomic setup,
authority, UI, fixture and final #102/#97/#92/#109 acceptance gates.
