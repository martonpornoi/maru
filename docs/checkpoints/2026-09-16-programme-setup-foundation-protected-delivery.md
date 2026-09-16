# Programme setup foundation protected delivery (#108)

[PR #152](https://github.com/martonpornoi/maru/pull/152) delivered closed setup
inputs and minimized owner references. It did not deliver a setup writer, schema,
authority grant, guided page, integrated fixture or profile activation.

- Certified head: `288fff6164c20001229f72ea8c8fc3873f294f5b`.
- Base: `ad4ccc1bda8e5b1dcf80e7fb10a8b92fd6db0dd0`.
- Protected squash: `6e34e35be129033ac0254c4b99680d21dbbc858d`, merged
  2026-09-16 20:23:36 UTC by normal match-head squash, without bypass.
- Certified and merged tree: `6ccc1565c2b5958515b3265b05d819cf4a690f8d`.
- Clean local main and origin/main matched the protected squash; unrelated
  worktrees and old branches were preserved.

Clean exact-commit local development certification passed all eight retained gates
in 320.788 seconds (5m21s), including 9,104 units in 53.96s and 103 frontend tests.
The schema-v4 receipt is `postgresql_deferred`: zero PostgreSQL instances, null
combined branch coverage and null measured headroom. Its SHA-256 is
`617c7865d9a00bcaf0eaf899f8a4452b479df812663d12143da795d9ed5ac795`.
Receipt, plan, unit JUnit and both package artifacts were archived and copy hashes
verified outside `.local-ci` before the next certification.

Hosted run `35144843861` passed quality in 11m34s, units in 2m11s and PR gate in
four seconds. CodeQL run `35144840869` passed all three languages. The exact-head
pre-merge snapshot was CLEAN with no reviews or unresolved conversations and no
pagination remainder. PostgreSQL jobs were skipped under ADR 0100, not passed.
Six unexecuted native reference cases are recorded on #102.

#108/#48 remain open. The next increment is durable setup receipt/schema and atomic
owner orchestration, followed by explicit operator authority, guided continuation
and the real isolated fixture. The user's separate setup schema-only approval
does not restore PostgreSQL suites or replace #102/#97/#92/#109.
