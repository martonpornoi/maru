# Page 10 profile-definition lifecycle accepted

Date: 2026-08-03

## Outcome

An independent reviewer accepted the repaired profile-extension definition
lifecycle command core after two adversarial rejection cycles. This milestone
supersedes neither findings checkpoint; those files remain the historical
record of why the final invariants exist.

## Accepted boundary

- Exact-edition approval, activation, successor creation, and retirement use
  locked aggregate versions, scope-bound retry evidence, current authorization,
  and atomic audit/event/outbox evidence.
- Historical source retirement or normal edition-date movement cannot rewrite
  valid prior evidence or strand a successor.
- New unsupported container-only source claims fail closed; historical source
  pointers are immutable.
- A predecessor has at most one non-retired successor in the command, model,
  and PostgreSQL. Activation requires the exact canonical successor-origin
  graph and refuses ambiguous lineage.
- Abandoned retired successors do not exhaust versions; retired generations
  are terminal and remain available as history.
- Empty reverse/reapply is supported, while populated lineage or successor
  semantics fence downgrade and ambiguous populated forward migration fails
  closed.

## Independent verification

- Fresh lifecycle and migration matrix: **38 passed in 66.78 seconds**.
- Fresh adjacent definition/value/model-policy/setup matrix: **23 passed in
  73.97 seconds**.
- Direct concurrency, replay, source-binding, ACL, truncate, rollback,
  model/raw SQL, missing-origin, terminal-retirement, and populated-forward
  probes passed.
- Strict mypy passed for the three changed source files; Ruff lint/format and
  Django migration drift passed. Documentation validation passed for 196
  Markdown files and 198 requirement identifiers.
- All test identities and data are synthetic.

## Residual scope

This accepts only the profile-definition lifecycle command core. Profile-value
commands and bounded reads, lifecycle/value HTML and API adapters, direct-
writer retirement, stopped-writer readiness, browser/accessibility acceptance,
and deployment recovery remain separate release gates.
