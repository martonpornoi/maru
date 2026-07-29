# Delivery progress

Last updated: 2026-07-28

This is the compact progress ledger. `CURRENT.md` explains the handoff;
checkpoint files preserve milestone evidence; `BACKLOG.md` defines acceptance.

## Summary

| Area | State | Evidence |
| --- | --- | --- |
| Research and product blueprint | Complete baseline; partner validation pending | stable requirements, 18 personas, 25 vertical slices |
| V00 engineering foundation | Complete | PostgreSQL, settings, CI, API conventions, 36-test checkpoint |
| V01 organization and edition kernel | Complete | Scope/archive guards, self APIs, 79-test checkpoint |
| V02 authority, audit, and effects | Worker boundary complete; activity projections remain | dual-control authority, endpoint isolation, audit, supervised outbox, metrics/replay, restore drill, 246 tests |
| V03 unified shell | Registration-aware Staff Console and attendee inbox foundation; broader search/team inbox remain | ADRs 0006/0015, generated API types, People/My registration/Commerce/Security, 12 frontend tests |
| Registration milestone | Repository safety boundary delivered; target deployment/load/policy gates and selected product gaps remain | ADRs 0007, 0009-0017, 369 backend tests, restore rehearsal, registration runbook |
| V04-V24 | Planned, with selected registration work delivered early | Ordered in `DELIVERY_PLAN.md` |

## Foundation backlog

| Item | State | Notes |
| --- | --- | --- |
| MARU-FND-001-007 | Complete | toolchain, PostgreSQL, quality, deterministic two-convention demo fixture, health, setup |
| MARU-IDN-001-002 | Complete kernel | account, membership, participation, capacity history |
| MARU-TEN-001-003 | Complete reference | scoped tenant structures and reusable endpoint isolation matrix |
| MARU-EVT-001-002 | Complete kernel | series, edition, versioned lifecycle, context, archive guards |
| MARU-AUT-001 | Complete kernel | closed capability catalog |
| MARU-AUT-002 | Complete | audited dual-control root grants and roles, bounded delegation, immediate revocation provenance |
| MARU-AUT-003 | Partial | deterministic scope/field/expiry policy; department/state expansion pending |
| MARU-AUT-004 | Complete foundation | list/detail/search/count/autocomplete/write matrix; fail-closed fields and frozen bulk targets |
| MARU-AUD-001 | Complete kernel | safe writer, protected query, correlation, digest chain, command |
| MARU-EFX-001 | Complete kernel | event registry, transactional outbox, leases, attempts, quarantine |
| MARU-EFX-002 | Complete worker boundary | handler/idempotency/retry, fair supervisor, child hard timeout, safe recovery |
| MARU-API-001 | Registration boundary complete | versioning, problems, correlation, schema, exact-origin browser policy, registration idempotency; platform-wide pagination remains |
| MARU-ACT-001 | Registration boundary complete | participation history, security history, registration timeline, notification inbox; other modules pending |
| MARU-OPS-001 | Complete repository foundation | health/logging, outbox and registration metrics/runbooks, poison coverage, isolated restore evidence; target telemetry installation pending |

## Latest verification

```text
Django 5.2.16 / Python 3.12.13 / PostgreSQL 17
Ruff format: pass
Ruff lint: pass
strict mypy: pass (152 source files)
pytest: 369 passed
branch-aware coverage: 90.03%
Staff Console: 12 tests, generated types, typecheck and production build pass
Django checks: pass
production deployment check: pass
migration apply/drift: pass
OpenAPI 3.1 validation: pass
dependency audits: no known Python or production frontend vulnerabilities
fresh-target PostgreSQL restore rehearsal: pass
documentation validation: see CURRENT.md for the final post-checkpoint count
```

## Current limitation

Maru has a tested security/reliability spine and a repository-complete
registration safety boundary, but is not automatically production-approved.
The concrete provider and infrastructure, supervised workers/telemetry,
representative load proof, approved retention/guardian/refund policies,
seasonal frontend certification, partner validation, and
jurisdiction-specific go/no-go remain. Transfer, product change/repricing,
badge printing/stock custody, and selected operator UX are explicit product
gaps. The service must not receive production data until those gates pass.
