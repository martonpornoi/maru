# Page 10 configuration lifecycle v2 corrective candidate

Date: 2026-08-03
Status: Author-side corrective candidate; separate independent acceptance is required
Requirements: REG-001, REG-002, REG-013, REG-019, REG-024, UX-026, AUD-001 through AUD-003
Decision: Implements accepted ADR 0047; no architecture decision is superseded

## Outcome

This second corrective pass addresses the six findings that rejected the first
configuration candidate. It does not claim independent acceptance, canonical
adapter cutover, stopped-writer activation, or production readiness.

- `publish_registration_template` is the canonical, version-fenced,
  idempotent publication ceremony. It validates the complete bounded template,
  reauthorizes under locks, advances the catalog exactly once, stamps every
  child generation, and atomically writes the receipt, target, minimized audit,
  domain event, and internal outbox message.
- Template source listing, setup start, and configuration lifecycle validation
  require that exact complete publication graph. A model-only row that merely
  looks published or complete is not selectable.
- Prior-edition source selection proves the source setup-start plus exact review
  and activation receipt, target, audit, event, and outbox graphs. A raw
  Draft-to-Active update is excluded from both listing and import.
- Import-time source eligibility is retained after the successful command.
  Later mutable source-edition dates do not strand the imported draft.
- Same-organization cross-series minor-policy imports prove historical policy
  evidence using the source edition's actual series scope.
- Activation replay remains exact after a later edition rename because the
  immutable stored request digest is authoritative; a caller replay still has
  to supply the original normalized request.

The browser route regression reported against the live configuration detail is
also pinned: the `registration-setup-minor-policy` name is mounted, the detail
template renders that scoped URL, and the destination returns successfully.
The running development server must be restarted after URL-table changes so it
does not retain an older in-memory resolver.

## Database and recovery boundary

Registration migration `0037_template_catalog_and_activation_evidence` installs
fixed-search-path, UTC `SECURITY DEFINER` assertions and deferred graph guards
for complete template publication and complete active configurations. `PUBLIC`
execute is revoked. Complete catalog movement is exactly `+1`; publication
receipts and targets are immutable and retained; raw promotion, mutation,
delete, and truncate fail closed. The activation guard requires exact review
and activation evidence for newly complete active rows.

Legacy template rows remain explicitly legacy compatibility evidence. Their
historical retirement transition is not mislabeled as a complete publication;
only complete published/retired templates receive the new immutable guard.
Reversal is available on an empty recovery database and fails closed after a
template publication or activation receipt exists. Populated recovery is
fix-forward or a whole-system restore to a mutually consistent pre-`0037`
point.

## Verification

The author-side gates recorded while this checkpoint was prepared are:

```text
focused setup-start/configuration/template command and migration matrix
56 passed

pytest tests/integration/test_registration_template_lifecycle_migration.py -q --reuse-db
2 passed

five repaired adjacent cases plus the live minor-policy route regression
6 passed

expanded adjacent registration matrix
79 test bodies passed; 7 teardown errors while restoring unrelated concurrent
registration migration 0036 because its SQL contained an unterminated dollar-
quoted block
```

Ruff format/check and strict mypy pass for the v2 command, query, lifecycle,
migration, and focused-test files. `makemigrations --check --dry-run` reports no
model drift other than the existing development identity-backend warning.

## Remaining risks and next actions

1. Repair the independently owned migration `0036` SQL and rerun the expanded
   adjacent matrix so teardown restores the current graph cleanly.
2. Assign a separate reviewer to reproduce all six rejection findings and
   inspect Python/SQL evidence parity before accepting this candidate.
3. Keep template retirement/successor commands, configuration scalar update,
   successor/retirement, canonical lifecycle adapters, compatibility-writer
   reconciliation, and stopped-writer activation as explicit later gates.
4. Restart the local development server before browser verification of newly
   mounted URL names.
