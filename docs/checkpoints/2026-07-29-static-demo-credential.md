# Static local demo credential checkpoint

Date: 2026-07-29  
Scope: Local/test demonstration tooling only; no production product behavior

## Outcome

The synthetic v5 fixture now has one documented default password for every
fixture-owned account:

```text
Z7!maru-demo-fixture-2026
```

Running `seed_demo_data` without `--password` uses that value for newly created
demo accounts. Running it with `--reset-passwords` replaces the password
verifier for each unique stable-ID fixture account and leaves non-fixture
accounts untouched. An explicit `--password` remains available for isolated
local test scenarios.

The existing local dataset was reset successfully: 80 unique synthetic
accounts were updated, including `demo.admin@maru.invalid` and
`danube.convention-chair@demo.maru.invalid`.

## Safety boundary

The credential is intentionally public and exists only to make the local demo
repeatable. The demo application and command are installed only by local/test
settings, and the command refuses any other settings module before password
validation or seeding. It must never be reused for a real person, shared
environment, staging deployment, or production deployment.

## Verification

- All 373 backend tests pass. The focused demo command coverage exercises the
  implicit default, unique-account reset reporting, idempotency, and
  production-settings refusal.
- Ruff formatting/lint and strict mypy pass.
- Direct local verification confirms the documented password for both the demo
  administrator and featured Danube convention chair.
- Django's system check passes and migration drift reports no changes; no schema
  or migration change is required.
- Documentation validation passes for 90 Markdown files and 179 unique
  requirement identifiers.

## Recovery

For a local fixture only, rerun:

```powershell
uv run python src/manage.py seed_demo_data --reset-passwords
```

To use a different isolated local password, pass `--password` together with
`--reset-passwords`. This changes only fixture-owned accounts.
