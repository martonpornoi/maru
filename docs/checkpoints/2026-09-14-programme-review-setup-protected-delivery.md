# Protected review-policy setup delivery

PR [#121](https://github.com/martonpornoi/maru/pull/121) was protected squash-merged
at 2026-09-14 13:32:40 UTC to `848f1246a8663e84a8799e5e7b4edbd695ff7efc`.
Its tree equals exact certified head `a94be56067205c029c9aa94195f418bcd63d3e8f`.
Clean local main and origin/main were verified and fast-forward synchronized;
the unrelated detached worktree and stashes remain untouched.

## Verification

- All eight retained local gates passed in 997.653 seconds (16m38s).
- 6,733 database-free units passed in 40.26s; the XML records zero failures,
  errors and skips. Three existing URLField warnings remain.
- Schema-4 receipt: `postgresql_deferred`, development passed, zero databases,
  null combined coverage/headroom. No native database acceptance is claimed.
- Receipt SHA-256: `de9a2d318e6a19b998ca6f25475dcc847c6d3cb5fea382f046ee55ade25d4a37`.
- Policy SHA-256: `36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
- Exact local receipt, unit XML, plan and distributions were archived outside
  the next certification directory before continuing.
- Hosted [run 34846794384](https://github.com/martonpornoi/maru/actions/runs/34846794384)
  passed units in 67.25s, quality in 27m41s and documentation in 25m42s.
  Workflow elapsed time was 28m09s. Exact-head PR gate and CodeQL passed without
  hosted repair or rerun. All review conversations were resolved.

The observed 2m19s quality margin is not guaranteed future headroom; #113 remains
open. No schema, dependency, production route, profile or PostgreSQL policy
changed. Native setup and selected-seal/replay cases remain unexecuted #102 debt;
genuine human checks remain #92. See the [implementation checkpoint](2026-09-14-programme-review-setup.md)
for focused failures, repairs and synthetic browser limits.

## Continuation

#108 records only policy composition/history as delivered, not its complete
Applications journey. Next are labelled exact-seal case opening, named manager
assignment, reviewer/moderator/decision and accepted-item conversion, followed by
the remaining labelled connections and setup. #109 integrated acceptance,
#102 PostgreSQL restoration, #97 recovery and #92 human acceptance precede final
separately verified profile promotion. #48 remains the priority umbrella.
