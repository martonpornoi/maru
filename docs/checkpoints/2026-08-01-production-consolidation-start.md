# Production consolidation started

Date: 2026-08-01  
Branch: `codex/production-consolidation`  
Base commit: `327a7d63574d0118356a0fd11ca5a316d78b2aed`

## Outcome

Maru now has one crash-safe, fictional-example-first plan for turning the retained
domain kernel and accepted Pages 1 through 4 into a production candidate. ADR
0037 changes the delivery unit from a mandatory pause after every isolated page
to a complete executable milestone while preserving page contracts, evidence,
authorization, and owner review.

The branch census established that `main`, the pre-reset branch, the controlled
rebuild, and every local Page 1 through Page 4 branch are strict ancestors of
the selected base. No local merge or cherry-pick is required. The two remote
legacy refs have unrelated history and remain behavior-only references for
applications, rooms, timetable, shifts, exports, and signage.

## Decisions and requirements

- Added ADR 0037, including the single-shell, progressive-scope,
  command/API-parity, access-transparency, shared-primitives, and legacy-use
  rules.
- Added SCH-009 and SCH-010 for three-phase work envelopes and
  access-controlled schedule layers.
- Added UX-020 for a computed effective-access header.
- Added REG-023 for one attendee registration plus separate typed applications.
- Added LOG-008 for validated storage containment and append-only whereabouts.
- Added KNO-008 and KNO-009 for a governed document library and typed
  application portfolio.
- Added NFR-009 for explicit input contracts and layered validation.

## Documentation

- Added `docs/project/PRODUCTION_CONSOLIDATION.md` as the live capability
  ledger, information architecture, domain design, milestone checklist,
  recovery instructions, and external production-gate inventory.
- Added public-source workflow research without copying personal roster data
  or retaining convention brands as product examples.
- Marked the old progress/backlog documents as historical and updated the
  architecture overview, module index, roadmap, delivery-plan status, README,
  and current handoff.

## Verification

- `python scripts/validate_docs.py`: passed, 144 Markdown files and 195 unique
  requirement identifiers.
- `git diff --check`: passed.
- No runtime code, migrations, database records, or external systems changed in
  this checkpoint.

## Known risks and incomplete work

- The current browser still stops after series creation; no series record or
  edition creation journey is mounted.
- Event-edition creation is not yet a shared audited application service.
- Department/resource authorization scope and the effective-access explanation
  do not exist yet.
- Programme, venue, timetable, logistics, generic applications, governed
  documents, and conversations remain absent modules.
- Registration, workforce, accreditation, and other rich HTML workflows remain
  intentionally unmounted even though substantial backend code exists.
- Production infrastructure and partner approval gates remain external work.

## Next smallest milestone

Implement the Edition workspace spine:

1. Page 5 convention-series record;
2. Page 6 audited edition creation;
3. shared HTML/API edition-creation command with tenant, rollback, audit, and
   outbox behavior;
4. Page 7 edition record/home and persistent context;
5. progressive navigation and the first truthful platform-authority access
   header;
6. desktop, 390-pixel, integration, isolation, migration, API, and documentation
   verification.
