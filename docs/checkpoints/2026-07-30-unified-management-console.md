# Unified Management Console and scoped access sharing

Date: 2026-07-30
Requirements: IDN-002, IDN-004, IDN-005, IDN-009, AUD-001 through
AUD-003, REG-020, UX-001 through UX-009, UX-011, UX-012
Decision: ADR 0023

## Outcome

Maru now presents recurring work, setup navigation, access management, forms,
and specialist records as one Management Console.

- `/manage/` is the preferred authenticated route.
- `/staff/` remains a compatibility alias.
- `/admin/` is branded and linked as **Advanced records**, not a competing
  console.
- A workspace-less administrator remains in a safe `/manage/` empty state and
  receives an explicit Advanced records link. Platform staff status does not
  imply convention authority.
- Navigation sections are collapsible and grouped by function.
- The home page has a distinct Forms section for implemented registration and
  workforce workflows.
- User-facing labels prefer names, emails, slugs, and domain references; UUIDs
  remain transport or advanced support identities.

## Access sharing

Authorized convention leaders can open **Manage access** from the product
header or Advanced records header.

- Groups are latest immutable Maru role-bundle versions, not Django Groups or
  page-local ACLs.
- Familiar starter groups include Board, Convention Chair, Vice Chair, Front
  Desk, Registration, Treasurer, Department Lead, Profile Media Moderator,
  Staff Member, and Volunteer.
- The target is an exact existing active account email.
- Assignment and replacement require a reason, optional expiry, and a
  distinct independently authorized approver.
- Replacement revokes and creates authority atomically.
- Removal is immediate, reasoned, capability-checked, and audited.
- The workspace is tenant/edition scoped and search/filterable by person,
  email, group, or scope.
- Direct access does not create a workforce position, satisfy an NDA, consume
  headcount, create a reporting line, or add official capacities.

Integration tests cover denial without leakage, latest role versions, friendly
labels, tenant/edition isolation, exact-email matching, dual approval,
cross-tenant denial, atomic replacement, and removal.

## Readiness evidence correction

Testing exposed that `/admin/events/editionreadinessgate/add/` presented
internal scope, reviewer, and timestamp fields as if they were ordinary
configuration.

The corrected workflow is **Management Console → Convention setup → Setup
guide → Edition readiness review**:

- the selected workspace supplies organization and edition scope;
- the operator enters only a human-readable evidence reference and review
  summary;
- the authenticated account becomes the reviewer;
- the server supplies `reviewed_at`;
- the existing capability-checked service performs validation and audit; and
- the Advanced-record list is read-only, suppresses Add, and shows the
  reviewer by display name instead of UUID.

The five closeout gates are Privacy, Finance, Operations, Security, and
Jurisdiction & safeguarding. Evidence references should be recognizable report
names, controlled tickets/checklists, or secure document links rather than
database identifiers.

## Demonstration data

The local/test fixture now installs starter convention role bundles alongside
its operational examples and creates familiar Chair, Board, Registration,
Front Desk, and Treasurer assignments. The featured Chair receives scoped
access-management and revocation authority; the Board Chair can independently
approve access.

The seed command temporarily disables local closure gates only while its single
atomic transaction installs the synthetic historical closure evidence. The
command remains blocked under production settings.

## Documentation

This milestone updates product requirements, ADRs 0006/0008/0023 and their
index, the roadmap/current/progress handoff, the information architecture,
authorization, events, Management Console, registration, demo-data, setup, and
registration-runbook documentation.

## Verification

- `pytest --cov=maru --cov-report=term-missing`: 405 passed; 90.02% coverage.
- Ruff format and lint: pass.
- Strict mypy: pass for 174 source files.
- Management Console: 17 tests, TypeScript typecheck, and Vite production
  build pass.
- Django checks, production-shaped deployment check, migration drift, OpenAPI
  validation, generated types, and documentation validation: pass.
- Browser QA:
  - collapsible desktop and 390-pixel navigation;
  - separate Forms section;
  - access groups, assignments, search, and no visible UUIDs;
  - safe workspace-less administrator state and integrated Advanced records;
  - readiness review with only evidence/summary inputs and automatic
    reviewer/time explanation;
  - no horizontal overflow or runtime console error.
- No database migration was required.

## Remaining work

The unified shell does not make Maru production-approved. Concrete provider,
infrastructure, load, policy, partner, badge-layout/printing, richer workforce,
programme, timetable, team inbox, and other planned-module gates remain as
listed in `docs/project/CURRENT.md`.
