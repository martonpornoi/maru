# Programme staffing concurrency and independent personal inputs

- Date: 2026-09-10 (Europe/Budapest).
- Branch: `codex/programme-staffing`; preceding native checkpoint `59c3f4e`.
- Child: [#88](https://github.com/martonpornoi/maru/issues/88), parent #48.
- Focused local evidence only; exact-commit certification and protected delivery
  remain pending. No production profile, route or runtime writer is activated.

## Reproduced concurrency defect and correction

A real two-connection race between Scheduling source movement and first
Workforce binding deadlocked. PostgreSQL reported the source transaction
holding EventEdition while its deferred foreign-key commit waited for the
Organization held by the binding, which was waiting for EventEdition.

Programme source commands and locking reads now use an owner scope seam that
joins the canonical shared boundaries, Organization, series and edition before
narrower rows. Scheduling commands and audited planning reads use the same
public Workforce parent scope. Ordinary preauthorization remains read-only;
Events still owns profile/lifecycle facts. Authority, person ordering and final
reauthorization remain unchanged. The held edition needs no second row-lock
query. This corrects ordering; it does not mask deadlocks with retries, longer
timeouts or weaker database guards.

The readiness regression still asserts exactly two Programme SELECTs, one
edition row lock, three parent locks in canonical order and four advisory
boundaries. Eight fixed scope queries are bounded separately; the prior
application-query budget, including its Events fact read, is unchanged.

## Verification

- Final combined run: **30 tests passed in 112.17s** on the owned disposable
  PostgreSQL fixture, including the final redundant-lock removal.
- Nine real competing-owner cases cover movement, working revision and planning
  reads versus binding; opening versus linking; claim versus successor;
  cancellation versus reconciliation; assignment ending and Availability
  withdrawal versus claim; Position closure/Department retirement versus binding.
  Expected domain conflicts are accepted; database errors and deadlocks fail.
- Native staffing HTTP, stale-authority rollback, foreign item withholding,
  readiness query budget, host sharing/withdrawal/privacy exit, host-removal race,
  Venue reservation lifecycle and scope unit regressions passed in that run.
- Full fast suite before the final redundant-lock removal: **4,252 passed in
  25.53s**, with the same two pre-existing Django URLField warnings. The final
  scope behavior is covered by the combined run above.
- Focused Ruff formatting/lint, strict Mypy for four production files and
  semantic docstrings for three production files passed.

## Personal-work boundary, not integrated profile acceptance

The real executable Workforce-only profile, with no substituted profile or
authorization, accepted explicit Programme-shaped work terms through the
existing Shift owner. A volunteer claimed; a different organizer confirmed;
work was locked. My Shifts retained the exact briefing after Assignment ending,
while another person could not read it. Personal reads selected no Programme,
Scheduling, Registration or Participation tables, and unrelated module records
remained absent.

That test intentionally creates no Programme binding. The separate binding
integration proves bound-demand lifecycle behavior; together these are
compositional owner-boundary evidence, not an activated Programme-only journey.
Integrated synthetic activation remains later work. #87 still owns genuine zoom,
enabled reduced motion and native discard acceptance; the completed scoped
staffing browser evidence is retained in the preceding native checkpoint.
