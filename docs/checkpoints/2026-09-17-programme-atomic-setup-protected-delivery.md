# Atomic Programme setup protected delivery (#108)

[PR #154](https://github.com/martonpornoi/maru/pull/154) delivered the dormant
atomic foundation command. Current profiles still deny setup before database work;
no route, operational permission, invitation or profile activation was enabled.

- Certified head: `e531f074a3776e32fc951122d7065d8b0c038055`.
- Base: `216b13253dde15cb59fbbf09bcb6e2752d4e86d2`.
- Normal protected squash: `7441d35243321bd5adbe4b015db01a7c93c07aa9`, merged
  2026-09-16 22:03:02 UTC (2026-09-17 locally).
- Equal certified/squash tree: `23aa3fe4f62c2aede3c73343baee1ce8b80a9cda`.
- Clean local main, origin/main and the protected squash matched exactly;
  unrelated branches, worktrees and containers were preserved.

Fresh local certification passed all eight retained gates in **401.0 seconds
(6m41s)**, including **9,197 units in 73.56s** and **103 frontend tests**.
The schema-v4 receipt is explicitly `postgresql_deferred`, with zero database
instances and null combined coverage/measured headroom. Receipt SHA-256:
`91415c709d86333ed134ebdfc8f99ad34c05983f919469c822f5b1b039096337`.
Receipt, plan, JUnit and both packages were archived with verified copy hashes.

Hosted run `35154385080` passed quality in **12m22s**, units in **1m59s** and PR
gate in three seconds. CodeQL run `35154382932` passed all three languages. Fresh
pre-merge state was CLEAN, exact head/base unchanged, with no reviews or unresolved
conversations and no pagination remainder. Native jobs were skipped, not passed.
Nine maintained native command scenarios remain uncollected/unexecuted under
[#102](https://github.com/martonpornoi/maru/issues/102#issuecomment-5705006776).

Issue #108's checklist now records atomic setup as a delivered prerequisite;
scoped independent authority, genuine-person continuation, the guided surface,
complete isolated fixture and final #102/#97/#92/#109 gates remain incomplete.

## Corrected issue tracking

PR #152 contained a negated closing-keyword phrase that GitHub nevertheless parsed
as an auto-close directive for #108. Its timeline and closing-issue references
confirmed automatic closure immediately after that merge. The historical PR wording
was corrected and #108 reopened with an explanatory comment; PR #154 had no closing
issue references. Do not place a GitHub closing keyword before an unfinished parent
issue even in a sentence that says it should not be closed.
