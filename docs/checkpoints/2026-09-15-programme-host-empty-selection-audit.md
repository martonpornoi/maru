# Required audit for empty host invitation selection

Date: 2026-09-15. Follow-up within PR #128's existing #108 hosting recovery scope.

The original clean candidate `145d46de241e195b8698d7d70c53efefb484debf` passed
all eight retained local gates in 1111.118 seconds (18m31s), completed
2026-09-14 22:49:30 UTC. Units: 7,281 passed in 44.12s; frontend: 85 passed.
The schema-4 `postgresql_deferred` receipt has SHA-256
`72bcefab68680d1e60f7d58bb4611bc8c5fbd1221f10cf21102c2726a0300ca1`, zero
database instances and null combined coverage/headroom. Five artifacts were
archived with hash parity before any successor certification.

Hosted run `34906123176` passed units (7,281 in 79.89s; job 1m42s including setup), classification
and repository safety. CodeQL run `34906120493` passed all analyses. While quality
was building documentation, final review identified a missing negative-result
audit: an unresolved address raised validation inside the loader before the
required query audit. The hosted acceptance run was deliberately cancelled to
avoid spending more work on the superseded candidate. It was not accepted or
merged; original local evidence does not certify the subsequent repair.

The owner selection query now returns either an audited exact selection or an
audited empty match. Both require final admission and minimized audit first;
the empty result records count zero without the supplied email. Only the HTML
adapter then converts the audited empty result into generic validation guidance.
If its audit fails, selection is unavailable and the negative lookup result is
not disclosed. This follows the existing reviewer-selection pattern and does
not alter the canonical host writer, schema, profile or PostgreSQL policy.

Regression cases exercise empty-match audit and reauthorization, audit failure,
and the real view's unavailable rather than negative-result response. The
existing exact-person, immutable retry and optional-navigation behavior is
unchanged. Repair preflight passed 7,284 units in 44.35s, with three existing
URLField warnings; 138 focused cases passed in 1.86s. Ruff, strict typing,
NumPy/semantic docstrings and documentation validation passed. The existing
native host scenario also maintains an empty-match minimized-audit assertion,
without collection or execution. Fresh clean certification and independent
hosted acceptance remain required before merge. Native #102 and human #92 debt, and
the final #97/#109/#48/#108 acceptance boundaries, are unchanged.
