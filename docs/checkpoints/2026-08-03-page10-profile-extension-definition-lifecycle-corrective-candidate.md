# Page 10 profile-definition lifecycle corrective candidate

Date: 2026-08-03

## Status

The first adversarial defect set has been repaired in an author-verified
candidate. This checkpoint does **not** supersede the rejection verdict or call
the lifecycle stable; a different agent is performing the required independent
acceptance audit.

## Corrective behavior

- Existing definitions retain eligible historical template provenance after
  that template is retired, while a new definition still cannot select an
  ineligible source.
- Canonical template/prior-edition source pointers now fail closed until Maru
  can persist an exact source definition identity, generation, and digest.
  Blank definitions remain available and no false container-only provenance is
  recorded.
- Approval, activation, successor creation, direct retirement, and replay prove
  one action-specific immutable target plus the exact audit, event, outbox, and
  persisted effect graph. Approval time is PostgreSQL-attributed and bound to
  its audit; current reviewer liveness and unrelated setup changes do not alter
  historical truth.
- Setup receipts and targets have PostgreSQL update/delete/truncate guards. The
  new SECURITY DEFINER helper has a fixed search path and no PUBLIC execute
  privilege.
- Historical replay validates the immutable policy version recorded at command
  time rather than today's catalog version.
- Migration `0034` refuses populated reversal once successor action or lineage
  evidence exists, while empty reverse and reapplication remain supported.

## Author-side verification

- Fresh focused lifecycle and migration matrix: **33 passed in 81.34 seconds**.
- Separate fresh adjacent definition, value, model-policy, and setup matrix:
  **23 passed in 90.90 seconds**.
- Focused Ruff formatting/lint passes for six lifecycle/migration/test files;
  strict mypy passes for the three changed source modules; Django migration
  drift reports no changes; documentation validation passes for 193 Markdown
  files/198 requirement identifiers; and whitespace checks pass. Repository
  release gates remain outstanding.
- All data is synthetic and uses isolated PostgreSQL databases.

## Remaining gate

The independent reviewer must rerun the original findings and additional
policy-version, strict-time, ACL, downgrade, concurrency, rollback, and
tenant-isolation probes. Only an explicit independent verdict may supersede the
adversarial rejection checkpoint. Lifecycle adapters, profile-value commands,
direct-writer retirement, stopped-writer activation, browser/accessibility,
and deployment recovery remain separate work.
