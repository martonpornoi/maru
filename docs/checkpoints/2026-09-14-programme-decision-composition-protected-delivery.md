# Decision composition protected delivery

Date: 2026-09-14. Scope: #108/#48's bounded independent decision increment.
[Implementation checkpoint](2026-09-14-programme-decision-composition.md).

## Exact protected result

[PR #126](https://github.com/martonpornoi/maru/pull/126) was normally squash-merged
at **2026-09-14 20:37:35 UTC**, protected result
`2722dab90155527dbf6fdd02837530255ebc970a`. Certified head
`15e00d8a5488a413e9dd31ef53dced523eb427e0` and squash have the same tree
`b8e9c2f4730c6206ee1c9c43841ae93e255e8b6f`.
The ready main-targeting PR was CLEAN, all exact-head required checks were green,
and its complete review-thread query returned no unresolved threads before
`--match-head-commit` squash. Clean local main fast-forwarded to origin/main and
the protected result; the detached repair worktree and both saved stashes remain
untouched. The next bounded branch begins from that main, not the feature commit.

## Local exact-head acceptance

All eight retained gates passed in **1589.955s (26m30s)**, completed
2026-09-14 20:10:19 UTC. Canonical units: **7,175 passed in 63.99s** with three
existing URLField warnings; JUnit records 7,175/0 failure/0 error/0 skip and
63.797s. Frontend: **85 passed**. Locked inputs, package/legal assets, security,
Ruff, typing, NumPy/semantic docs, fresh warning-fatal Sphinx, static Django and
generated contracts all passed. Static checks truthfully retain the deliberately
unreachable database and unavailable invitation-encryption warnings; they are
not evidence of native database behavior. No canonical failure or repair.

Schema-4 receipt SHA256
`3140c67b44b7bcbbea3ca370d1030d44be20018c8ea1f87ef211efab8c108665`;
policy SHA256 `36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
The receipt says `postgresql_deferred`, development checks passed, zero database
instances and null combined coverage/headroom. Five artifacts were archived and
hash-verified: receipt 803 bytes, plan 247, JUnit 1,230,889, wheel 5,107,408 and
sdist 4,492,265. They certify this head only, not later changes.

## Independent hosted acceptance

[Workflow 34891469879](https://github.com/martonpornoi/maru/actions/runs/34891469879)
and [CodeQL 34891465024](https://github.com/martonpornoi/maru/actions/runs/34891465024)
passed for the exact head without hosted repair/rerun.

- Units job 104135067084: **1m09s**, actual pytest **54.92s**, all 7,175 passed.
- Quality job 104135067109: **23m37s**, 20:12:32–20:36:09 UTC.
- Contributor documentation: **21m44s**, 20:13:32–20:35:16 UTC.
- Frontend: all **85 passed** in the completed quality log.
- Aggregate PR gate 104143042244: passed at 20:36:15 UTC; overall workflow from
  20:12:10 creation to that gate: **24m05s**. CodeQL and all analyses passed.

The observed quality margin is **6m23s**, not a future guarantee. Local full
timing was slower than PR #125 while this hosted job was faster; these are not
interchangeable machines or an isolated source-growth experiment. #113 remains
recorded, with no timeout extension, cache substitution or gate reduction.

## Remaining work

#108's decision-composition checkbox is delivered; its parent journey and #48
remain open. One maintained real-owner native scenario is unexecuted #102 debt.
The bounded synthetic browser evidence does not replace genuine #92 acceptance.
No current manifest, production route, schema, canonical writer, item conversion,
host or delivery effect was activated. Continue with exact accepted conversion
and remaining guided connections; #102/#97/#109/#92 still gate final promotion.
