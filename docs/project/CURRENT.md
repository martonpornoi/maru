# Current project state

Last updated: 2026-08-22
Phase: Production consolidation, management-experience recovery, and public
contributor onboarding.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Latest working outcome

The current branch makes the public contributor documentation approachable and
removes real-convention example dependencies from the maintained repository
tree.

### Newcomer-first contributor documentation

- The Sphinx homepage now offers three goal-based routes and one finite
  five-step journey: understand Maru, judge current maturity, run it locally,
  follow a fictional product tour, and prepare a first contribution.
- Root navigation has exactly six stable hubs: **Start here**, **Product**,
  **Architecture & security**, **Build & contribute**, **Operate Maru**, and
  **Reference & history**.
- Product contracts, runbooks, modules, research, ADRs, checkpoints, and the
  generated Python API remain published and searchable through nested catalogs
  without competing for newcomer attention.
- A repository validator rejects root navigation drift, root globs, direct
  archive placement, and orphaned maintained Markdown. Responsive route cards
  remain semantic ordinary links and use accessible light/dark colors without
  adding a theme, Sphinx extension, or JavaScript dependency.

### Ethical fictional examples

- Repository-controlled examples use **MaruCon** and **MaruDance**, synthetic
  people, and reserved contact domains. They are fictional documentation and
  test identities, not customers, partners, endorsements, or a claim of global
  trademark clearance.
- The retired public-roster URL, parser, compatibility command, and their tests
  are removed. Current fixtures, tutorials, contracts, and research do not
  fetch, copy, or rename a real convention roster, people directory,
  organization chart, people-to-role mapping, brand, or operating taxonomy.
- The demo fixture is `maru-fictional-two-convention-v6`; its organizations,
  series, editions, slugs, accounts, and contacts use the fictional namespace.
- The built-in Workforce starter is `marucon-reference@1`: one **Convention
  Coordination** root and 21 independently authored operational Departments.
  Its exact canonical digest is
  `55f4091787215fd9eef5cc1266806a1450dd6e5449d50864340601f5ec2398ee`.
- Necessary attribution for software, standards, dependencies, licenses, and
  security advisories remains accurate. An authorized organizer may still use
  its own real identity in a governed deployment.

### Data and migration boundary

- Workforce migration `0009` locks immutable template receipts before
  installing the new database guard. It accepts only the exact current code,
  version, and digest; any retired or malformed template receipt fails closed
  with an explicit non-production rebuild instruction.
- Authority-provenance readiness pins the replacement receipt guard's exact
  definition and requires the `0009` migration record. A missing migration
  record or a modified function therefore blocks activation and the downgrade
  fence even when similarly named database objects remain installed.
- The migration never relabels receipt evidence or rewrites an organizer's
  copied and potentially edited Department tree.
- Existing disposable databases seeded with an earlier demo dataset or starter
  must be rebuilt. There is no production-data migration because Maru is not
  approved for production data.
- Current rendered historical prose received a one-time terminology sanitation
  recorded by ADR 0073. Public Git history remains unchanged and contains the
  exact earlier wording; no destructive history rewrite is authorized.

## Established repository and product baseline

- Protected public collaboration uses pull requests, squash-only history, an
  up-to-date no-bypass `PR gate`, resolved conversations, tag and branch
  deletion protection, non-fast-forward prevention, immutable Action pinning,
  Dependabot security updates, dependency review, secret scanning, push
  protection, private vulnerability reporting, and managed CodeQL.
- Complete local certification remains pre-review evidence; GitHub independently
  verifies the merge candidate. Draft pull requests are intentionally cheap and
  non-green until ready for review. High-risk changes fail closed to complete
  hosted acceptance.
- GitHub Pages publishes the warning-fatal Sphinx output from exact protected
  `main` through a least-privilege environment. The currently public site does
  not receive this branch's navigation until the change is merged and Pages
  succeeds.
- NumPy docstrings, strict PyDocLint, Ruff's complete catalog with bounded
  exemptions, semantic docstring validation, mypy, generated OpenAPI/TypeScript
  contracts, frontend verification, migration checks, unit coverage, and
  PostgreSQL integration shards remain repository gates.
- Maru retains one administration shell, deny-by-default scoped authorization,
  audit and outbox evidence, governed organization/edition/workforce records,
  registration and profile slices, typed applications, catalog and admission
  commerce, charity, venue, and bounded Logistics capabilities. Consult the
  production-consolidation ledger before treating any slice as complete.

## Decisions

- [ADR 0073](../architecture/decisions/0073-repository-owned-fictional-convention-examples.md)
  requires repository-owned fictional convention examples, removes the retired
  external-roster surface, replaces the source-derived starter, and preserves
  immutable provenance through a fail-closed rebuild boundary.
- [ADR 0074](../architecture/decisions/0074-newcomer-first-curated-sphinx-navigation.md)
  establishes six curated documentation hubs, one bounded newcomer journey,
  nested complete catalogs, and executable discoverability/accessibility
  contracts.
- ADRs 0042 and 0045 are partially superseded. Their synthetic-person,
  offline-fixture, copy-on-write, versioning, provenance, authorization, and
  structure-management boundaries remain accepted.
- NFR-012 records the ethical fictional-example and purpose-governed research
  requirement. No accepted authorization, privacy, audit, or production-safety
  decision is weakened.

## Verification for this working outcome

Completed locally:

- documentation policy: 317 Markdown files and 204 requirement identifiers;
- focused documentation-policy tests: 10 passed;
- warning-fatal fresh Sphinx/AutoAPI HTML build: passed;
- Ruff lint and formatting: passed;
- PyDocLint over `src` and `scripts`: passed;
- focused documentation, Workforce-template, migration, validation, and safety
  unit tests: 147 passed across the recorded batches;
- regenerated and validated OpenAPI: zero errors (18 pre-existing enum-name
  warnings); regenerated TypeScript API contract;
- affected PostgreSQL integration suite: 219 passed;
- focused Page 9 readiness, authority activation, exact-lineage navigation,
  retired-Department fence, and runtime-role regressions: 92 passed;
- staff-console typecheck, 20 frontend tests, and production build: passed;
- migration drift: no changes detected; Python compilation passed;
- mypy: 354 source files passed; semantic docstrings: 364 source files passed;
- browser desktop review confirmed the curated semantic headings, links,
  keyboard focus, six-hub navigation, and coherent presentation; the responsive
  auto-fit grid contract is covered by a repository test;
- final documentation-policy and repository diff checks: passed;
- warning-fatal fresh Sphinx/AutoAPI build after the milestone checkpoint:
  passed.

No hosted GitHub result exists yet for this working-branch outcome;
protected-main acceptance remains required.

## Known risks and incomplete work

- Maru still lacks complete authenticated responsive, keyboard, screen-reader,
  automated-accessibility, and accountable-owner evidence across its management
  experience.
- Representative deployment, stopped-writer cutover, runtime-role activation,
  restore/PITR, worker supervision, provider certification, load, telemetry,
  legal/privacy/finance/safeguarding governance, and operator training remain
  production gates.
- The first immutable CalVer release candidate remains a separate maintainer
  decision and release pull request. A green repository does not make the OCI
  image or application production-ready.
- Managed CodeQL does not analyze every fork/Dependabot context. Public workflow
  changes still require careful human review under the current sole-maintainer
  model.
- The current-tree convention-name guard uses irreversible fingerprints. The
  retired spellings are absent from maintained documentation, examples,
  fixtures, generated contracts, policy source, and application behavior.

## Smallest sensible next actions

1. Review this bounded documentation/example transition through a pull request
   and require complete hosted acceptance because it changes a migration,
   generated contracts, fixture identities, and deletes compatibility code.
2. After merge, verify the exact-main Pages deployment and public homepage.
3. Resume the authenticated management-experience accessibility matrix and the
   deployment/recovery gates before considering the first release candidate.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, the production-consolidation ledger,
ADRs 0073–0074, NFR-012, and the owning module/runbook for the next change. Use
only synthetic data. Preserve organization and edition scope, authorize before
parsing untrusted input, keep fixed/self/public audiences separate from
assignable authority, and do not treat repository or Pages success as
deployment, recovery, accessibility, release, or production approval.
