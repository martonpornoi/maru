# Clean convention and workforce onboarding checkpoint

Date: 2026-07-29  
Phase: Initial Phase 3 workforce slice on the completed registration boundary  
Requirements: HR-007, HR-008, REG-021, UX-001, UX-003, SEC-001, SEC-003  
Decision: ADR 0019

## Outcome

Maru can now start from a migrated database without demo data and execute the
first convention-organizer and known-volunteer journey:

- a one-shot trust-on-first-use command establishes the first separate
  bootstrap controller and Convention Chair;
- ten common furry-convention position templates and their exact role bundles
  are created;
- authorized staff can register an existing account outside public sale times
  without bypassing payment, policy, eligibility, capacity, or audit;
- the attendee can use a local-only payment simulator, update profile/fursuit
  images, and upload a requested signed NDA;
- organizers can review exact media and PDF evidence with reasons;
- edition departments, reporting lines, position headcount, document
  requirements, applications, and publishable opportunities are represented;
  and
- dual-controlled position activation creates the exact scoped role assignment
  and participation capacities, after which the user can exercise only the
  assigned privilege.

Filled published opportunities remain visible when configured, but stop
accepting applications. Headcount greater than one supports shared positions.

## Decisions

ADR 0019 records the staff-assisted exception boundary, initial-authority
bootstrap, workforce ownership, reviewed PDF evidence, publishable position
opportunities, and position-driven access activation.

The built-in web pages and Django admin remain neutral bootstrap/reference
clients. Public opportunities, self applications, and self onboarding
documents also have versioned REST endpoints so a convention frontend can
replace their presentation without copying domain rules.

## Changed areas

- new `maru.workforce` module, models, services, API, web pages, admin, starter
  catalog, bootstrap command, migrations, scope/immutability triggers, audits,
  events, and outbox handlers;
- staff-assisted registration evidence and sale-window-bounded command;
- local-only reference-profile payment action;
- Staff Console navigation to assisted registration and workforce tasks;
- populated v5 demo examples for every new workforce admin page;
- additive registration migration 0027 and workforce migrations 0001/0002;
- OpenAPI and generated TypeScript contract refresh; and
- module, setup, registration, Staff Console, operations, roadmap, and
  no-demo-database walkthrough documentation.

## Verification

- The integrated PostgreSQL journey signs in as staff and attendee, creates a
  paid staff-assisted registration outside both sale windows, confirms local
  payment, uploads/reviews NDA and two images, creates hierarchy and a
  published opportunity, activates a reviewed assignment, verifies the filled
  public projection, and receives HTTP 200 from the newly authorized
  registration-service API.
- Database-bypass tests reject cross-tenant workforce scope and mutation of
  approved document evidence.
- Direct bootstrap-admin tests cover template defaults, independent-approver
  validation, agreement request/review, and position activation. Saving an
  already approved document or active assignment safely preserves the
  immutable record rather than exposing a database-trigger error.
- Account-page guidance now states that the convention-workspace filter lists
  only existing edition participants and directs organizers to **All
  foundation data** for a newly created platform account.
- Bootstrap admin now records the signed-in administrator when a registration
  template or edition configuration draft is created, keeping the creator
  evidence read-only without blocking clean-database setup.
- A separately named empty PostgreSQL database applied the complete migration
  chain and passed Django checks. The one-shot command then created 11 role
  bundles, 10 templates, one department, one Chair position, four role
  assignments, and one active position assignment without demo seeding. The
  disposable rehearsal database was removed after verification.
- The comprehensive demo seed remains idempotent and every registered
  workforce admin model is populated.
- Ruff formatting/lint, strict mypy, migration drift, OpenAPI 3.1 validation,
  generated TypeScript types, Staff Console typecheck, and all 13 frontend
  tests passed.
- All 382 backend tests pass with 90.14% branch-aware coverage; the complete
  regression result is also recorded in `docs/project/CURRENT.md`.

## Data, migration, and deployment notes

Registration 0027 adds nullable/defaulted provenance fields and does not rewrite
old registrations. Workforce 0001 creates new tables only. Workforce 0002 adds
PostgreSQL scope, immutable-version, evidence, assignment-transition, and
protected-deletion triggers.

Do not reverse the workforce migrations after valuable onboarding or authority
evidence exists. Export and reconcile assignments, role assignments,
participation capacities, private files, and retention obligations first.
Production PDF/image upload still requires a real malware scanner and protected
storage; the debug-only rehearsal scanner is deliberately unavailable under
production settings.

## Known risks and incomplete work

- The current assignment admin selects a separately authorized approver but is
  not yet a separately authenticated approval inbox with approver step-up.
- Qualifications, availability, shifts, work records, assignment ending,
  approval notifications, and purpose-built hierarchy/search UX remain.
- Production payment-provider, scanner/storage, SMTP, workers, telemetry,
  load, partner policy, and go/no-go gates remain unchanged.

## Recommended next actions

1. Have the maintainer follow the walkthrough interactively and report the
   first confusing or failing step.
2. Build the separately authenticated workforce approval inbox before shared
   production administration.
3. Add assignment ending/replacement and notification workflows.
4. Continue Phase 3 with qualifications, availability, shifts, and programme
   scheduling only after the first partner validates terminology and process.
