# Page 10 registration configuration lifecycle corrective candidate

Date: 2026-08-03
Status: Author-side corrective gates pass; separate independent acceptance is required
Requirements: REG-001, REG-002, REG-013, REG-019, REG-024, UX-026, AUD-001 through AUD-003
Decision: Implements accepted ADR 0047; no architecture decision is superseded

## Outcome

The configuration preview, review, activation, setup-start replay, and source-
selection boundary now repairs every finding recorded in
`2026-08-03-page10-registration-configuration-lifecycle-adversarial-findings.md`.
This checkpoint is a corrective-candidate handoff, not an independent verdict,
adapter acceptance, stopped-writer activation, or production-readiness claim.

- Review and activation replay prove the exact receipt, target, minimized audit,
  domain event, and outbox graph before returning a historical success.
- Review validity is anchored to the configuration's own last-changed setup
  version. Unrelated profile-definition commands and later policy-catalog
  version advancement do not invalidate a completed review.
- Historical minor-policy review attribution is proved from immutable actor,
  database-time, receipt, target, audit, event, and outbox evidence. A reviewer
  becoming inactive later does not rewrite the historical act.
- Preview and activation recursively validate sections, questions, products,
  sales-window pairs, length ceilings, conditional questions, answer semantics,
  capacity references, and the current minor-policy evidence.
- Complete blank, published-template, and prior-edition configurations require
  exact origin-specific source shape, stamps, canonical digest, current source
  authorization, and their original setup-start binding. Legacy or unstamped
  sources are neither listed nor accepted.
- Setup-start replay verifies its complete evidence graph and immutable source
  binding, uses bounded limit-plus-one reads, and derives copied-row counts from
  the historical target set.

## Database and recovery boundary

Registration migration `0035_configuration_source_binding_guards` adds no
field and depends on registration `0034`. It installs complete-provenance shape
constraints plus deferred pair/evidence checks for configuration and setup
control. Trigger guards freeze the configuration source tuple and setup-control
scope/origin/provenance, reject setup aggregate-version rollback, and block
ordinary update, delete, and truncate attempts that would destroy the binding.
Its trigger-only `SECURITY DEFINER` functions use fixed search paths and revoke
`PUBLIC` execute. Forward migration revalidates every pre-existing complete row
under an exclusive table lock and rolls the migration back if its exact binding
is missing.

A clean database with no complete configuration/control evidence can reverse
`0035`. Once a complete configuration or setup control exists, reversal fails
closed. Recovery is reviewed fix-forward work or a whole-system restore to a
mutually consistent pre-`0035` point; relabelling evidence to force downgrade is
not an accepted recovery path. The migration is additive integrity hardening
and does not install the final Page 10 stopped-writer generation.

## Verification

The following PostgreSQL-backed commands passed on the corrective candidate:

```text
pytest tests/integration/test_registration_setup_start_commands.py tests/integration/test_registration_configuration_lifecycle_commands.py tests/integration/test_registration_configuration_source_binding_migration.py tests/integration/test_registration_setup_schema.py -q --reuse-db
51 passed

pytest tests/integration/test_registration_configuration.py tests/integration/test_registration_setup_definition_commands.py tests/integration/test_registration_setup_section_commands.py tests/integration/test_registration_profile_extension_lifecycle_commands.py tests/integration/test_registration_profile_extension_lifecycle_migration.py tests/integration/test_registration_setup_schema.py -q --reuse-db
78 passed

pytest tests/integration/test_registration_configuration_source_binding_migration.py -q --reuse-db
5 passed
```

Focused fresh-schema probes also passed blank, template-copy, and exact active
prior-edition setup starts and all five `0035` forward/tamper/reverse cases.
Ruff and strict mypy pass for the changed configuration boundary. An earlier
`makemigrations --check --dry-run` reported no drift; a final concurrent rerun
is blocked before drift calculation by unrelated overlength profile-value index
names. Django's system check otherwise reports only the existing development
identity-backend warning.

## Remaining risks and next actions

1. Assign a separate reviewer to rerun the adversarial findings and inspect the
   SQL/Python canonical source-binding parity; do not treat this checkpoint as
   acceptance.
2. Keep configuration successor/retirement and canonical lifecycle HTML/API
   adapters outside this candidate until their own strict contracts and tests
   exist.
3. Reconcile compatibility, fixture, admin, and internal ORM writers before
   installing or claiming the Page 10 stopped-writer generation.
4. Run the eventual repository-wide release, representative migration/restore,
   performance-ceiling, browser, and accessibility gates after the remaining
   Page 10 slices settle.
