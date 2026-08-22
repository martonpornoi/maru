# Page 9a.1 structure mutation adapters

Checkpoint status: Final repository checkpoint; implementation, focused
adapter evidence, and the definitive full-suite/coverage gate are recorded.
Authenticated browser, accessibility, owner, and deployment acceptance remain
separate release gates.

Date: 2026-08-02
Branch: `codex/full-platform-consolidation`
Decision: ADR 0045 remains authoritative; no new durable architecture decision
was required.

## Outcome recorded

Page 9a.1 now exposes the stopped-writer edition-structure command boundary
through one canonical browser workflow and versioned API. The Executive Board
remains the separate OrganizationRepresentation governance anchor. Applying
`marucon-reference@1` copies Convention Coordination plus 21 independently
authored operational Departments
into one edition and creates no person, Position, assignment, participation,
registration, role, or authority relationship.

The browser workflow adds same-shell child GET pages for template application,
Department creation, and one active Department record. Separate POST actions
apply the template, create a Department, completely update/reparent/reorder it,
retire it, or delete an unused leaf. Every action calls the shared application
service; Specialist Department records remain inspection-only.

The browser boundary uses closed forms, strict integer and canonical UUID
inputs, server-created retained retry keys, expected aggregate versions, CSRF,
POST/Redirect/GET success, and private no-store rendered form/name-bearing
responses. Validation and conflict rerenders retain submitted controls and
require explicit reload when stale. Overview and child pages keep one current
Organization structure navigation item. The source summary distinguishes an
unchanged built-in copy from a **Reference copy changed** edition.

The mounted API operations are:

```text
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure/template-applications
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments
PUT    /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}/retire
DELETE /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}
```

Template application and creation require a caller-supplied canonical UUID
`Idempotency-Key`, return `201` initially, and return `200` for an identical
replay. Update, retirement, and deletion return `200`; DELETE requires a closed
JSON body. Untrusted route locators are resolved and authorized from persisted
scope before the header or body is parsed. Missing authority and unavailable
route scope share a non-disclosing `403`; only an authorized caller may receive
the name-free `404` for an unavailable Department or parent. Typed mutation
problems use `400`, `403`, applicable `404`, `409`, and `503` boundaries.

Every name-bearing overview/child render repeats final view authorization and
persists `workforce.structure.read` before disclosure. Audited POST rerenders
record the actual resolved action route and POST method rather than inventing a
GET provenance. Audit failure returns the generic name-free dependency state.

## Verification recorded

- The committed command/database baseline passes all 1,471 tests in 1,538.40
  seconds on a fresh isolated PostgreSQL database at 90.13 percent branch
  coverage. This predates the HTTP adapter additions and is not their full gate.
- The strict mutation API focus passes 48 tests. It covers exact
  authorization/non-disclosure, closed JSON and native types, caller-retained
  idempotency and replay conflicts, Department/parent availability,
  version/lifecycle/dependency conflicts, deactivation and audit/event/outbox
  rollback, request correlation, CSRF/method handling, and OpenAPI responses.
- A fresh isolated PostgreSQL combined Page 9 gate passes 159 tests in 102.89
  seconds. It covers core forms, the bounded Page 9 read, HTML mutations,
  mutation and adjacent workforce APIs, exact-lineage navigation, and unified
  routing.
- Adapter hardening adds 118 targeted cases: 59 HTML adapter cases, 50 API and
  contract cases, and 9 immutable-template invariant cases. The focused HTML
  selection passes 59 tests with 27 deselected in 28.13 seconds. The adjacent
  API/contract batch passes 152 tests in 73.90 seconds.
- The definitive adapter-expanded repository invocation passes all 1,693 tests
  in 1,653.43 seconds (27:33) and reaches 90.50 percent total branch-inclusive
  coverage.
- Ruff check and format pass across 369 files; strict mypy passes across 218
  source files; Django system and migration-drift checks pass.
- Deploy-shaped production settings pass both exact-authority checks with zero
  issues.
- OpenAPI validation and deterministic regeneration pass. A final independent
  contract review added closed request-object schemas and canonical lowercase,
  hyphenated UUID patterns for body fields and `Idempotency-Key`. The schema
  SHA-256 is
  `2E38F52D467E94DB248BBB99C695D0D606B531EA1E68E5BC5215086EEE669C05` and
  generated-client SHA-256 is
  `B381BC5F0432655E593C04EEE45F07C39F4B7FFBED65C67E5C9F6B710CEDFF48`.
- Staff Console type checking, all 19 frontend tests, and the production build
  pass. Python and production Node dependency audits report no known
  vulnerabilities; `pip-audit` skips only the local `maru` package.
- Documentation validation passes for 181 Markdown files and 198 unique
  requirement identifiers.
- Chrome was unavailable to the current desktop browser automation. No new
  authenticated desktop or 390-pixel visual QA result is claimed.

Focused invocations overlap and must not be added together.

## Residual release evidence

- authenticated desktop and 390-pixel empty, populated, diverged, read-only,
  validation, stale, protected, denied, limit, and dependency states;
- keyboard traversal and automated accessibility evidence; and
- owner tutorial, representative deployment authority reconciliation and load,
  stopped-writer/runtime-role cutover, and whole-database restore/PITR evidence.

## Migration, rollback, and recovery note

This adapter slice adds no schema migration. It makes the existing workforce
`0006`/`0007` write protocol reachable. Once a structure command commits, an
older application that writes Departments directly is incompatible with the
database evidence handshake. Roll forward with compatible adapters or restore
the whole workforce, authorization, audit, events, outbox, and migration state
to one mutually consistent pre-write point; never reverse only the structure
control or receipt tables and never fabricate template provenance.

## Smallest continuation

1. Exercise the authenticated desktop/390-pixel and accessibility state matrix.
2. Rehearse the owner tutorial and representative deployment/recovery gates.
3. Keep Page 9b Position management separate until its authority-bearing
   dual-control and recovery contract is accepted.
