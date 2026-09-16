# Protected integrated rehearsal preparation (#108 / PR #151)

[PR #151](https://github.com/martonpornoi/maru/pull/151) was normally squash-merged
on 2026-09-16 at 19:34:49 UTC after exact-head PR gate, CodeQL and empty resolved
review/thread inventories (both pagination flags false).

- Certified head: `f643d6b278d3e702c49b95ccbcb2f4c4588c38e7`.
- Protected base: `e6f9687cabb7e077e8fcc8b6f6763641fc4f3a13`.
- Protected squash: `ad4ccc1bda8e5b1dcf80e7fb10a8b92fd6db0dd0`.
- Equal certified/squash tree: `49ff47d8e36801ece248b530714376d3df5ec2dd`.
- Clean local main was fast-forwarded and matched origin/main and that result.

All eight retained local gates passed in 354.477 seconds (5m54s): 8,948 units
in 68.54s and 103 frontend tests. Schema-4 receipt records `postgresql_deferred`,
zero databases and null combined coverage/headroom. Receipt SHA-256:
`eaf109c23829231063af5f93d02d31749a8d3d823dd422b9dd56046ac92304f4`.
Receipt, plan, JUnit, wheel and source package were archived outside `.local-ci`
with every copied hash verified before subsequent certification.

[Hosted documentation acceptance](https://github.com/martonpornoi/maru/actions/runs/35140181522)
passed: Relevant quality 11m00s, PR gate 3s. Hosted unit/database jobs were skipped
by documentation-only classification, not claimed as passing runs. All three
[CodeQL analyses](https://github.com/martonpornoi/maru/actions/runs/35140179002)
passed. No rerun, bypass, timeout change or acceptance exception was used.

An initial tool safety review blocked publishing until destination/payload were
verified. Read-only checks confirmed the existing public `martonpornoi/maru`
origin and the single eight-file documentation commit. The ordinary reviewed
retry succeeded; no workaround or alternate destination was used.

The [preparation checkpoint](2026-09-16-programme-integrated-rehearsal-preparation.md)
records the initial unit failure and correction. The new protocol is not an
executable fixture or accepted journey. #108/#109/#92/#48 remain open.

After the preparation commit, the maintainer explicitly approved a bounded,
disposable setup schema-only migration/metadata observation. That supersedes the
earlier pending-approval snapshot, not ADR 0100: PostgreSQL suites stay skipped,
and no production data, runtime grant or Programme activation is authorized.
Continue accountable setup from this protected result, keeping current roots and
profile meanings unchanged and recording native/human work under #102/#92.
