# Checkpoint: V00 engineering foundation

Date: 2026-07-26  
Milestone: Reproducible Django walking skeleton  
Version: `0.1.0a0`

## Delivered

- Python 3.12–3.14 project with uv lockfile.
- Django 5.2 LTS, Django REST Framework, drf-spectacular, and psycopg.
- PostgreSQL 17 development service and successful zero-to-current migration.
- Custom UUID platform account in the first project migration.
- Local, test, and fail-closed production settings.
- Liveness, database readiness, release identity, correlation IDs, safe
  structured logging, and RFC 9457-style problem foundation.
- Generated and validated OpenAPI 3.1 contract.
- Ruff, strict mypy, pytest, branch coverage, migration drift, production
  settings, schema drift, and dependency audit gates.
- Synthetic account factory and development setup guide.
- CI workflow using PostgreSQL rather than SQLite.

## Verification

```text
Ruff format: 33 files formatted
Ruff lint: pass
strict mypy: 23 source files pass
pytest: 36 pass
covered source: 93.99%, threshold 90%
Django system check: pass
Django production --deploy check: pass
initial migrations: applied successfully to PostgreSQL 17
OpenAPI 3.1 generation/validation: pass
pip-audit: no known vulnerabilities; unpublished Maru package skipped
```

## Security notes

- Production requires an explicit strong secret, non-wildcard hosts, and
  PostgreSQL.
- Logs emit an allowlist of technical fields and exception type rather than
  exception message.
- An inbound request identifier is accepted only when it is a UUID; other
  content is replaced.
- Health responses do not expose dependency errors.
- The local email/password account is a bootstrap identity boundary, not the
  final account-recovery or identity-provider decision.

## Incomplete

- The reference factory cannot create two tenants until V01 models exist.
- CI has been defined but not run on a remote GitHub worker.
- Production server, object storage, queue/cache, telemetry provider, and
  identity provider remain deliberately unselected.
- V01 tenant and edition isolation is the next implementation boundary.

## Resume point

Implement MARU-TEN-001, MARU-TEN-002, MARU-EVT-001, MARU-IDN-002, then add the
reference convention and reusable cross-tenant matrix before exposing their
API.
