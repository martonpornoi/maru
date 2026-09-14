# Own reviewer workspace protected delivery

Date: 2026-09-14. Issue #108 within #48. PR #124:
https://github.com/martonpornoi/maru/pull/124

Protected squash `95ed7b847bf942be4ffcc07438d864fdb1b53961` was merged at
2026-09-14 17:39:24 UTC. Certified head
`9f058a3f26972c5ba3987c4e6cf358b3dfbf45d2` and the squash share tree
`f976ed5755b97e90d1ebcddcab3507388d37977f`. Clean local main and origin/main
were fast-forward synchronized to the squash. Unrelated detached repair
worktree and two pre-existing stashes remain untouched.

## Exact local evidence

Fresh canonical `scripts/certify.ps1` passed all eight retained development
gates in **1,074.734 seconds (17m55s)**, completed
2026-09-14T17:12:00.3555061+00:00. It ran **6,975 units in 43.71s** and
**85 frontend tests**. JUnit confirms 6,975 tests, zero failures/errors/skips
and 43.592s report duration. All packaging, locked/security, static/strict
typing, NumPy/semantic/Sphinx, generated/Django, frontend and unit gates passed.
There was no failed canonical attempt or candidate repair.

Schema-4 receipt truthfully reports `postgresql_deferred`, development checks
passed, zero database instances and null combined coverage/headroom. Receipt
SHA-256 is `c140e10c67d53f5f63f50b78eb0b57444211507b73952aac252d6f189503cf08`;
unchanged policy SHA-256 is
`36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
Receipt, plan, JUnit and wheel/source distribution were hash-verified in
`.tools/certification-evidence/issue108-9f058a3-deferred/`, outside the next
disposable certification directory. Earlier evidence was preserved separately.

## Independent hosted acceptance

PR run `34873415112` passed at the exact submitted head. All CodeQL analyses
in run `34873411265` and the CodeQL check passed. Exact-head `PR gate`
job `104083090817` passed, mergeability was CLEAN and the resolved-conversation
query returned no review threads and no additional page before merge.
Normal `--squash --match-head-commit` delivery used no bypass.

- Hosted pytest: **6,975 passed in 55.56s**; unit job `104074771914` took 1m12s.
- Hosted frontend: **85 passed**, verified from the completed quality job log.
- Quality job `104074771736`: **24m30s**, 17:13:48–17:38:18 UTC.
- Warning-fatal documentation: **22m43s**, 17:14:42–17:37:25 UTC.
- PR workflow: **25m04s**, 17:13:20–17:38:24 UTC.
- No hosted repair, rerun, timeout change or acceptance-policy change. The
  observed 5m30s quality margin is not a guarantee; #113 remains open.

## Issue management and continuation

#108's own conflict clearance/recusal, complete rubric scoring and permitted
discussion increment is checked delivered. The complete #108 journey stays open;
dedicated safe file/reference and readable structured-answer viewers are now
explicitly unchecked, alongside moderation, decisions, conversion, host retry,
remaining connections, setup and gated promotion. #48 delivery comment
5668151773 records exact evidence and sequencing.

The maintained native scenario remains **unexecuted #102 debt** (comment
5667838078). Full genuine keyboard, responsive/zoom, screen reader, independent
people and integrated acceptance remain #92 (comment 5667837765). Synthetic
browser evidence is documented in the candidate checkpoint, not native or human
acceptance. PostgreSQL suites were not collected/run and no timing weights were
invented. #97 logical recovery, #109 integrated acceptance and final #102/#92
gates remain prerequisites to promotion. No current profile, production route,
schema, runtime privilege, dependency or writer policy changed.

Next: independent moderation and deliberate stage movement/reopening within
#108, retaining separate decision authority and the current owner's OPEN/
WAITLISTED reopening rules. This delivery does not close #48 or activate Maru.
