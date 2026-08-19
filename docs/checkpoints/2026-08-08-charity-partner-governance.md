# Charity partner governance vertical

Date: 2026-08-08
Status: implemented and focused-verified
Requirements: FUR-005, FUR-010, AUD-001, NFR-001, NFR-002, and NFR-009

## Outcome

Maru now has an organizer-owned charity partner directory, governed media,
edition proposal/review decisions, private append-only comments, and a separate
independent publication approval. Confirmed and published selections expose
only an immutable minimized snapshot and current approved media; rejection
reasons, contact details, and private review evidence remain restricted.

The vertical uses exact capability scope and typed selection bindings, denies
platform administrators automatic convention authority, and records closed
idempotent command evidence through audit, domain events, and the outbox. The
strict APIs and same-shell workspace are mounted, and the coherent navigation
registry reauthorizes the edition charity destination and saved pins.

## Verification

- Focused charity integration: 7 passed.
- Final authorization function fingerprint check: 1 passed.
- Ruff and formatting: passed for charity and its touched shared boundaries.
- Focused mypy: 16 source files passed with no issues.
- Django system check: passed with only the existing invitation-encryption
  configuration warning.
- Charity browser/API route reversal and public route resolution: passed.
- `makemigrations --check --dry-run`: no model changes detected.

## Recovery and remaining scope

The capability and binding downgrade fence refuses destructive reversal while
new authority is in use. Partner retirement and publication withdrawal preserve
history. Campaigns, donated value, collected funds, settlement, and financial
public reporting remain future FUR-005 work; this module is not an accounting
ledger.

The smallest next action is to exercise the mounted workspace with realistic
explicit charity grants and add the fundraising/reconciliation slice only
after its ledger and retention contract is designed.
