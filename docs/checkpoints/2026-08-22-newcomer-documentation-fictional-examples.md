# Checkpoint: Newcomer documentation and fictional examples

- Date: 2026-08-22
- Phase: Production consolidation and public contributor onboarding
- Related requirements: HR-011, NFR-002, NFR-003, NFR-012
- Related ADRs: 0042, 0045, 0073, 0074

## Outcome

Maru's contributor site now starts with an honest product summary, three
goal-based routes, and one five-step newcomer journey. Six stable navigation
hubs keep the complete product, architecture, development, operations, API,
research, decision, and checkpoint material available without presenting the
repository as an undifferentiated reading list.

The maintained repository tree now uses MaruCon and MaruDance as its convention
examples. Their organizations, editions, people, accounts, contacts, workflows,
and Workforce structure are repository-owned fictional material. The former
external people-directory surface and source-derived starter were removed.

## Decisions

- ADR 0074 fixes the root navigation at six ordered hubs and keeps the bounded
  newcomer path distinct from complete nested catalogs.
- ADR 0073 requires repository-owned fictional convention examples and forbids
  copied or fetched rosters, people directories, organization charts,
  people-to-role mappings, branding, and operating taxonomies as demonstration
  data.
- The convention-name policy stores irreversible fingerprints rather than
  publishing retired real-event spellings as policy data.
- Existing immutable Workforce receipts are never renamed. Migration `0009`
  accepts only the exact new template identity and otherwise fails closed with
  a non-production rebuild instruction.
- Authority-provenance readiness requires the `0009` migration record and the
  exact replacement receipt-guard fingerprint; deleting the recorder row or
  changing the guard closes both readiness gates.
- One bounded sanitation pass removed unnecessary external convention wording
  from currently rendered historical pages. Public Git history remains intact.

## Changed areas

- Curated Sphinx homepage, Start here journey, six hub pages, nested catalogs,
  responsive semantic route-card styling, and documentation standards.
- Documentation reachability, root-navigation, fictional-identity, and
  live-people-directory validation with focused regression tests.
- Demo fixture identities, tutorials, generated API contracts, frontend tests,
  Workforce forms, serializers, templates, starter taxonomy, migration data,
  and migration preflight coverage.
- Project handoff, roadmap, requirements, module guidance, research boundary,
  ADR catalog, and affected historical terminology.
- Removal of the external-roster parser, compatibility seeding command,
  source-derived research note, and their tests.

## Verification

- Ruff lint and formatting: passed.
- PyDocLint, semantic docstrings, and mypy: passed.
- Focused documentation-policy and migration tests: passed.
- Affected PostgreSQL integration suite: 219 passed.
- Focused Page 9 readiness, authority activation, exact-lineage navigation,
  retired-Department fence, and runtime-role regressions: 92 passed.
- Staff-console typecheck, 20 frontend tests, and production build: passed.
- OpenAPI regeneration and validation: zero errors; 18 pre-existing enum-name
  warnings. The TypeScript API contract was regenerated.
- Python compilation, migration drift, and warning-fatal Sphinx/AutoAPI builds:
  passed.
- Browser review confirmed the curated heading/link structure, keyboard focus,
  complete six-hub navigation, and coherent desktop rendering. The responsive
  auto-fit grid contract is also enforced by a repository test.

## Data, migration, and deployment notes

The fixture identifier is `maru-fictional-two-convention-v6`. The built-in
Workforce starter is `marucon-reference@1`, with one **Convention
Coordination** root, 21 independently authored child Departments, and digest
`55f4091787215fd9eef5cc1266806a1450dd6e5449d50864340601f5ec2398ee`.

Disposable databases containing an earlier fixture or starter must be rebuilt.
No organizer-owned Department tree or immutable receipt is rewritten. Maru is
not approved for production data, and this transition does not claim a
production-data migration path. GitHub Pages receives the new information
architecture only after protected-main acceptance and a successful exact-main
deployment.

## Known risks and incomplete work

- The wider authenticated management experience still needs complete
  responsive, keyboard, screen-reader, and automated-accessibility evidence.
- The fingerprints prevent the specifically retired names from reappearing;
  reviewers must still reject any other real convention identity or
  source-derived dataset introduced under a new name.
- Deployment, restore, worker, provider, load, governance, and operator-training
  gates remain open. Documentation quality does not make Maru production-ready.
- Public Git history preserves prior wording. No destructive history rewrite
  was authorized.

## Recommended next actions

1. Review this bounded transition and require complete hosted acceptance because
   it changes fixture identities, generated contracts, migration behavior, and
   removes compatibility code.
2. After merge, verify the exact-main GitHub Pages deployment and its public
   homepage.
3. Resume the authenticated management-experience accessibility matrix and the
   outstanding production-consolidation gates.
