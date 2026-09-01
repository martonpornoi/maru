# Checkpoint: Applications Programme calls and acknowledged proposals

- Date: 2026-09-01
- Issue: [#63](https://github.com/martonpornoi/maru/issues/63)
- Parent umbrella: [#48](https://github.com/martonpornoi/maru/issues/48)
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-008,
  PRG-009, AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003, NFR-008
  through NFR-010, and NFR-013
- Related decision: ADR 0082

## Outcome

Maru now has a dormant Applications-owned Programme-call and collaborative-
proposal kernel. Programme calls facet the existing typed definition aggregate;
proposals facet the existing submission and reuse append-only answer revisions.
One submission aggregate version serializes every proposal mutation.

One accountable lead manages selection, roster, sealing, reopening, submission,
and withdrawal. Accepted collaborators may edit shared applicant-writable
answers, while each contributor alone owns proposed-public profile and consent
revisions. The exact immutable seal links call schema, selection, answer
revisions or deliberate absences, included roster, contributor profile
revisions, policies, predecessor, and digest. Each included collaborator
acknowledges or declines that exact seal only for themselves.

This is not a usable Programme workflow. No route, API, OpenAPI operation,
template, navigation destination, Django admin writer, worker, handler, delivery,
review, decision, target record, Programme item, host relationship, public copy,
schedule, staffing, publication, setup, or profile activation is added. Both
current literal adoption-profile fingerprints remain unchanged.

## Decisions

- Applications extends its existing form and submission aggregates instead of
  building a parallel Programme form engine.
- Proposal collaboration is a purpose-scoped Applications relationship, not a
  Programme host or co-host relationship. Hosting begins only after a later
  reviewed and accepted Programme transition.
- The submission aggregate version is the sole cursor for answers, selection,
  roster, profiles, invitation transitions, seals, responses, reopening,
  submission, and withdrawal.
- Collaborator states are invited, accepted, declined, left, and removed.
  Expiry is derived; reinvitation appends a reasoned new invitation.
- Sealing freezes exact source revisions. Responses advance the aggregate
  version but do not rewrite the seal, and the lead cannot respond for another
  contributor.
- Every generic review/decision/acceptance/target seam denies or omits the
  reserved `programme_item` kind until its later child. PostgreSQL rejects a
  legacy Programme `ApplicationTargetRecord`.
- Successful commands couple state, a dedicated Programme receipt and version
  proof, minimized audit, dormant event, and outbox evidence atomically. The
  dedicated receipt does not inherit the generic Applications runtime writer.
- New relations are production-runtime `SELECT`-only and integrity functions
  owner-only. Installation is schema readiness, not adoption.
- The closed Applications Programme capability vocabulary advances the
  Authorization policy version to `2026-09-01.1`; this records the exact
  decision catalog and minimum-scope rules without changing profile adoption.
- The current manifest fingerprints remain literal and unchanged:
  `full_convention@1` is
  `e0081b116f8af045fd5a9195c1f4f3295b20d3c57163e8ef0a3547f86861df81`;
  `workforce_only@1` is
  `66ad0e96a641d99e163d735d612dd2138c96ef0af619cfac57839695d09c2ad0`.
- Preview-first call/proposal import is the immediate successor. Structured
  review/decisions and the accepted Programme adapter follow; Programme hosts
  begin only after that accepted transition.

## Changed areas

- Applications call/proposal models, lifecycle, commands, queries, inputs,
  authorization/adoption descriptors, event schemas, legacy-target denial,
  migrations, database guards, dedicated receipts, and writer boundary.
- Authorization capability vocabulary and exact-profile admission checks;
  Events adoption catalogs; Identity/Workforce/Events public reference seams;
  Effects event registry; runtime-role and readiness contracts; and Workforce
  `0016` exact recognition of the Programme-call owner-Department foreign key.
- Static migration-dependency coverage and PostgreSQL successor coverage for
  install, fail-closed reverse, reapply, and Department deletion protection.
- Full-acceptance timing inventory refreshed from exact clean-tree certification;
  the eight isolated shards and complete test-selection boundary are unchanged.
- Product requirements, ADR 0082, domain/module/API/event/security/privacy/
  audit/operations documentation, page/workflow/adoption contracts, roadmap,
  backlog, production ledger, delivery plan, changelog, and current handoff.

## Verification

The protected-PR candidate accumulated the following local evidence:

- The superseded pre-schema-catalog head passed the complete non-test
  repository gate, including locked package build and verification, Python and
  JavaScript dependency audits, migration drift, Django and production-
  settings checks, OpenAPI and generated TypeScript parity, 33 frontend tests,
  and the production frontend build.
- Its documentation validation covered 370 Markdown files, four repository
  skills, and 213 requirement IDs. All 19 documentation-policy tests passed.
- Its Ruff format verification covered all 768 files and Ruff lint passed.
  MyPy passed across 411 source files. PyDocLint passed across `src` and
  `scripts`; the custom docstring validator passed across 425 source files; and
  warning-fatal Sphinx/AutoAPI completed without warnings.
- PostgreSQL repair evidence passed: 102 Authorization activation, readiness,
  catalog, and runtime-fence tests; 65 Page 9, Workforce-successor, and
  Department-protection tests; 33 Registration historical-migration tests; two
  Identity reverse/reapply tests; 22 Workforce historical-migration tests; and
  15 residual readiness and profile-fingerprint tests.
- A later independent contract audit found that Applications readiness did not
  yet prove the documented exact relation, column, collation, constraint, and
  index shape. That head was not merged and its in-progress hosted run was
  cancelled.
- The resulting data-free PostgreSQL 17 catalog covers all 26 managed
  `applications_*` relations, 336 columns, 279 constraints, and 203 indexes.
  Focused evidence passes Ruff format/lint, MyPy, PyDocLint, 25 unit tests, all
  2,581 DB-free unit tests, 49 fresh-PostgreSQL readiness/health tests, and the
  existing complete-draft-call readiness acceptance. Independent review found
  no blocking issue; its optional readiness short-circuit was implemented and
  tested. `git diff --check` passes.
- The only local Django diagnostic was the expected fail-closed `identity.W001`
  missing-invitation-key warning.
- Exact clean-tree certification of the superseded head
  `9fe32e19a4a102eed90d7501f2f918ac9aaf3766` passed all 2,575 unit tests,
  all 2,767 integration tests across eight isolated PostgreSQL 17 instances,
  the complete repository gate, and combined 90-percent branch coverage. The
  exact post-repair commit certification and protected PR #65 gate remain the
  authoritative merge evidence and must both be green for the same head.

An initial complete certification run exposed the migration-history coupling,
stale Authorization readiness fingerprints, the Workforce Department-reference
inventory omission, and stale policy-version literals. The dependency boundary,
Workforce `0016` successor, readiness pins, and assertions were repaired before
the green evidence above.

The first hosted run of that exact repaired feature head passed every non-
database job and integration shards 1, 2, and 4 through 8. The shard 3 log showed
progress into `test_workforce_assignment_commands` without a reported assertion
failure before GitHub cancelled the step at the existing 120-minute job limit,
so no JUnit or coverage artifact could be finalized. The checked-in 2026-08-21
timing map had become stale: it omitted 19 current integration files, retained
one deleted path, and assigned 5,680.7 locally measured seconds to shard 3
despite projecting only 2,533.5. The exact successful eight-shard local JUnit
evidence refreshes all 175 current file weights and balances the deterministic
schedule between 4,525.6 and 4,525.9 seconds. The 120-minute timeout, eight-shard
topology, selected files, serialization, database isolation, no-retry behavior,
and combined coverage requirement remain unchanged. A repository contract now
requires the checked-in timing paths to match the current integration-file
inventory exactly while retaining the median fallback for an initial diagnostic
run that introduces a new file.

The protected pull-request result is authoritative only for the exact pushed
head. Do not replace local evidence with a hosted status from another revision.

## Data, migration, and deployment notes

- Applications `0004` is additive and creates no row. `0005` is the terminal
  consolidated old-plus-new function/trigger catalog required by readiness.
  `0006` refuses populated downgrade before protected evidence can be removed.
- Applications `0004` depends on Workforce only at
  `0006_edition_structure_schema`; it does not pull the later Workforce and
  Registration migration tail into older migration-history tests.
- Workforce `0016_programme_call_department_fk_contract` depends on
  Applications `0004` and Workforce `0015`, then recognizes the exact protected
  `applications_programmecall.owner_department_id` reference. If `0016` is
  absent or reversed while that foreign key exists, Department deletion fails
  closed.
- Identity `0020` and Workforce `0016` are dependent reversals that must be
  removed before Applications `0004`. Coverage preserves the exact dependency
  shape, successor install/reverse/reapply behavior, and deletion protection.
- Authorization's paired additive migration adds only closed capability scope
  vocabulary and its populated downgrade fence. It creates no grant or role.
- Empty reversal is exact. Populated reversal refuses while preserving schema,
  ACL, trigger, receipt, audit, event/outbox, and migration evidence.
- Every new `applications_programme*` relation is `SELECT`-only for the
  production runtime role; the dedicated receipt does not receive the generic
  Applications receipt's `INSERT` grant.
- Recovery fixes forward or performs a mutually consistent whole-database
  restore, explicitly including Applications, Authorization, Identity,
  Workforce, Audit, Effects event/outbox, and migration history from one point.
  It never fabricates a response, seal, review, decision, target, Programme
  item, host, schedule, staffing record, or publication.

## Known risks and incomplete work

- The schema is intentionally unusable under current profiles. No browser or
  API acceptance exists and no production personal-data use is approved.
- Active-use purpose/lawful-basis decisions, field retention and disposal,
  subject rights, legal holds, backup aging, deployment, recovery rehearsal,
  accessibility, load, and owner acceptance remain gates.
- Import must preserve exact mappings and provenance without fabricating seals,
  acknowledgements, review, decisions, or accepted Programme evidence.
- The reserved target kind remains dangerous if any future generic seam omits
  the explicit denial. Static and behavior-level allowlist tests remain
  mandatory as the existing Applications surface evolves.
- Workforce Department retirement must reassign a draft call or retire an
  active call first. Retiring the owner first blocks organizer management and
  new starts while intentionally preserving existing proposal self history;
  [#64](https://github.com/martonpornoi/maru/issues/64) owns the required
  preflight and governed recovery. Workforce `0016` recognizes the foreign key
  exactly but does not implement that preflight, reassignment, retirement, or
  recovery workflow.

## Recommended next actions

1. Add preview-first import for calls and proposals through the public
   Applications commands, with mapping, validation, duplicate policy,
   provenance, dry run, and explicit commit.
2. Add Programme-specific staged review, recusal/conflict, revision requests,
   accountable decisions, and the exact accepted revision contract.
3. Implement the idempotent Applications-to-Programme adapter; only its
   accepted transition may create a Programme item and host/co-host purpose
   relationships.
4. Continue through Scheduling, Venue integration, Workforce staffing,
   release/outputs, on-site continuity, profile activation, and integrated
   browser/recovery acceptance in umbrella order.
