# Page 10 registration configuration lifecycle adversarial findings

Date: 2026-08-03

## Verdict

The first registration configuration lifecycle core is **not accepted**. Its
original focused and adjacent suites remain useful regression evidence, but an
independent fresh-PostgreSQL review reproduced seven direct adversarial probes
covering six correctness defects. This checkpoint supersedes the stability
implication of the earlier lifecycle-core checkpoint without rewriting that
historical record.

## Confirmed defects

1. Review and activation accept a matching-looking receipt and target without
   the required audit event, domain event, outbox message, exact target
   cardinality, actor/time binding, or persisted state transition. A forged
   activation replay reported an active version while the stored configuration
   remained draft. Receipt and target rows also lack PostgreSQL
   update/delete/truncate immutability.
2. A published template or prior-edition source with `legacy_unknown`
   provenance can be copied and the target is silently stamped `complete`.
   Unknown source history therefore becomes authoritative without an explicit
   repair ceremony.
3. A draft's supposedly exact source tuple can be rebound after setup start.
   Lifecycle validation trusts the newly claimed source and does not prove the
   original receipt-bound branch, digest, or prior-edition eligibility.
4. Activation does not validate sections and lacks required Page 10 bounds for
   question help and product descriptions. It also permits a one-sided product
   sales window. A draft with an empty section title and all three malformed
   definition cases previewed clean and activated.
5. Minor-policy review validity depends on the historical reviewer still being
   active. Immutable review evidence must remain attributable after an account
   is disabled and must bind reviewer and server time to the policy generation.
6. Review resolution is anchored to the shared setup aggregate rather than the
   configuration's own last-changed generation. An unrelated profile-field
   command therefore makes an unchanged active configuration appear
   unresolved.

## Independent evidence

- Focused lifecycle baseline: **25 passed in 67.32 seconds**.
- Lifecycle plus adjacent setup/configuration baseline: **73 passed in 132.86
  seconds**.
- Direct adversarial matrix: **7 of 7 probes reproduced** on a separate fresh
  PostgreSQL database using only synthetic data.
- Transaction rollback, exact-scope authorization, and same-key/distinct-key
  activation concurrency remained green. Two concurrency-test database
  sessions lingered at teardown and remain a test-harness cleanup concern.

## Required repair gate

- Verify one complete, action-specific receipt/target/audit/event/outbox/state
  graph on both execution and replay, and install database immutability guards.
- Require exact complete source provenance at selection and lifecycle time;
  preserve the original source tuple immutably and recheck branch eligibility.
- Validate every nested definition and encode all Page 10 field and sales-window
  constraints at the model or lifecycle boundary.
- Resolve policy reviews from immutable evidence independent of present account
  liveness, with reviewer and database time bound to the reviewed generation.
- Anchor configuration review truth to its own last-changed generation while
  retaining the shared aggregate only for concurrency.
- Add a regression for every reproduced defect and obtain a new independent
  verdict before adapters, compatibility cutover, or production activation.
