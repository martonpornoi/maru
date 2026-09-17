# Programme approval storage protected delivery (#108)

[PR #156](https://github.com/martonpornoi/maru/pull/156) delivered dormant immutable
request/terminal-decision storage and its native/readiness/runtime boundaries.
The [schema checkpoint](2026-09-17-programme-operational-approval-schema.md) retains
design, migration observation and deferred-test limits; this file records delivery.

- Exact certified head: `8ec91f607f5c82e75bf53619584bb2b1f303a94e`.
- Base: `86c287fef80080ad69eb4f1cd3023f7b2fcdea7c`.
- Normal protected squash: `d1703f60f9cc15f1d85777819b682e2ad90b3b6f`, merged
  2026-09-17 17:06:27 UTC.
- Equal certified/squash tree: `e9ba1ddc00ec09456191bbffcbe7cf12b0434fc4`.
- Clean local main, origin/main and the protected squash matched exactly after
  fast-forward. Unrelated worktrees/branches and user Docker resources were preserved.

Fresh clean exact-commit local certification passed all eight retained gates in
**366.163 seconds (6m06s)**, including **9,321 units in 55.36s** and **103 frontend
tests**. Schema-v4 receipt: `postgresql_deferred`, zero database instances, null
combined coverage and timing headroom. Receipt SHA-256:
`ab261d435d878e964c0085dda5ddeea80c51b281a82e16fefcc08a167194017d`.
Receipt, plan, JUnit and both packages were archived with matching copy hashes.

Hosted run `35249347990` passed quality in **11m44s**, units in **2m15s**, and PR
gate in **4s**. CodeQL run `35249346437` passed all three languages. Pre-merge
head/base were exact and CLEAN/MERGEABLE, with no reviews, unresolved threads,
pagination remainder or closing-issue references. PostgreSQL jobs were skipped,
not passed. The approved 153.156-second empty-schema metadata observation is
separate evidence, not a native test suite or runtime/workflow acceptance.

#108's existing setup checklist now records only this prerequisite as delivered;
#108 and #48 remain open. New and changed native scenarios are explicitly retained
under [#102](https://github.com/martonpornoi/maru/issues/102#issuecomment-5718129660).
No profile, route, grant or production operation was activated. Next implement
actual independent-approval commands, guarded readers and genuine-person setup
continuation, then the complete isolated fixture. #102/#97/#92/#109 remain gates.
