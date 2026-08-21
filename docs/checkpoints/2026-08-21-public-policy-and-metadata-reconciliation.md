# Public policy and repository metadata reconciliation

Date: 2026-08-21
Status: GH-004 complete; ready-state hosted acceptance remains
Requirements: NFR-002, NFR-003, NFR-011
Decisions: ADR 0068 and ADR 0070

## Outcome

GH-004 reconciles Maru's public landing page, contribution, support, security,
conduct, governance, issue-intake, and repository-readiness policy with the
actual public sole-maintainer state. It removes stale launch-era and brittle
test/security claims, defines continuity without inventing a committee or
successor, and reconciles the accepted GitHub metadata through authenticated
observation plus a separately authorized mutation and readback.

The owner explicitly chose not to publish a login or historical personal email
and not to create a project mailbox. The policy therefore records that Maru has
no private project-specific conduct-reporting channel, warns against public
disclosure of sensitive reports, and distinguishes GitHub's abuse-reporting
scope from Maru-specific or off-platform conduct. The reviewed repository
description was then changed under separate authorization and read back exactly,
completing the external metadata reconciliation without requesting another
setting mutation.

## Authenticated public-state evidence

The 2026-08-21 read-only GitHub audit observed:

- public visibility, protected `main`, and an empty homepage;
- the live description **Security-focused Django and PostgreSQL platform for
  operating multi-convention events.**;
- the exact accepted topics `django`, `event-management`, `modular-monolith`,
  `openapi`, `postgresql`, `python`, `react`, and `typescript`;
- Issues, Discussions, and public forks enabled, with Projects, Wiki, Pages,
  and Downloads disabled;
- 100 percent Community Profile health and recognition of README, Apache-2.0
  license, CONTRIBUTING, Code of Conduct, and the pull-request template;
- SECURITY, SUPPORT, GOVERNANCE, CODEOWNERS, two Issue Forms, and their chooser
  present; the Community Profile API's singular `issue_template` field was null,
  while direct repository inspection confirmed those form files;
- all 23 live labels, including every label referenced by the Issue Forms and
  automation, with no issue carrying `good first issue` or `help wanted`;
- GitHub's generated default social preview, no funding link, no release or
  tag, and no open issue or Discussion; and
- private vulnerability reporting, standard secret scanning, push protection,
  Dependabot security updates, and managed CodeQL enabled, with zero open
  CodeQL, Dependabot, or secret-scanning alert at that dated boundary.

GitHub user-profile metadata supplied no public private-contact route for the
repository owner. The audit did not reproduce or repurpose an address from Git
history.

After explicit owner authorization, the description-only mutation replaced the
initial wording with **Security-focused Django and PostgreSQL platform for
operating multi-convention events, under active development.** The authenticated
post-change readback returned that exact description, public visibility, and an
empty homepage. The mutation command supplied only the description option; no
topic or feature update was requested or executed.

## Repository policy correction

- README links contribution, support, security, conduct, governance, and
  release policy directly. It now sends changing implementation and acceptance
  evidence to `CURRENT.md` and the production-consolidation ledger instead of
  repeating an obsolete test count and undated vulnerability claim.
- Governance names the current authority, conditions future maintainer access,
  and defines planned handoff, inactive maintenance, archival, and independent-
  fork consequences. GH-008 still owns real second-maintainer and independent-
  review controls.
- SECURITY keeps GitHub private vulnerability reporting as the configured
  private security channel, names the sole human administrator responsible for
  response, and accurately retains reporter/advisory-collaborator access and
  account-dependent notification delivery.
- SUPPORT routes issues and Discussions, states the active-development best-
  effort boundary, and promises no response, resolution, private support, or
  production SLA.
- The Code of Conduct removes the fictitious temporary GitHub channel. It
  records the absence of a private Maru conduct inbox or independent reviewer,
  rejects public sensitive reports and misuse of the security-advisory form,
  and links GitHub Support for GitHub-hosted abuse without broadening GitHub's
  scope.
- CONTRIBUTING defines `triage`, `good first issue`, and `help wanted` without
  manufacturing work or implying a schedule. Newcomer work must be bounded,
  synthetic, documented, and free of hidden sensitive prerequisites.
- The Issue Form chooser now links the private vulnerability form, conduct and
  abuse guidance, support policy, and Discussions. A repository contract
  prevents the old launch wording, an invented conduct email, misuse of the
  security form, missing routes, stale README evidence snapshots, loss of the
  reviewed form fields, or loss of either form's exact label pair from
  returning. Live label existence remains dated server evidence rather than a
  local-test claim.

## Metadata decision and deliberate deferrals

The live accepted description is **Security-focused Django and PostgreSQL
platform for operating multi-convention events, under active development.** ADR
0070 replaces ADR 0068's more ambiguous **Pre-production** wording while
retaining the same maturity boundary. The accepted topics need no change.
Homepage stays empty and Pages stays off until GH-007 publishes and verifies
Sphinx; Wiki remains off rather than duplicating those versioned docs. Projects
and structured Discussion templates remain absent until triage volume
demonstrates a need.

A custom social preview is optional polish and remains deferred until an owner-
approved purpose-built asset exists. Funding remains absent until there is a
real recipient and stewardship decision. `CITATION.cff`, a second maintainers
file, CLA/DCO, stale-issue automation, and manufactured newcomer issues add no
current benefit and remain out of scope.

## Verification

- PR 9's prior-head draft run at `6fedb02` proved the draft-light workflow
  behavior, not GH-004: it intentionally kept `PR gate` red without starting
  expensive acceptance. Its green managed Python CodeQL aggregate still
  omitted Workforce's query module; ADR 0069 records that separate correction.
- PR 9 draft run `32492637097` at `cd26c71` passed classification and kept every
  expensive acceptance lane skipped. Its `PR gate` log says the draft inputs
  passed lightweight preflight and intentionally exits nonzero until the pull
  request becomes ready. Managed CodeQL run `32492635147` passes all three
  languages. This is draft behavior evidence, not ready-state acceptance.
- The pre-edit public-material audit resolved all 65 scoped local Markdown
  links and GitHub reported 100 percent Community Profile health.
- Both focused public-material contracts and all 1,937 unit tests pass. The
  three Issue Form YAML files parse, and the contract verifies the exact
  template inventory, reviewed contact routes, required fields, safety prompts,
  and label pairs.
- Ruff ALL-rule lint and formatting pass for the contract; documentation
  validation passes over 286 Markdown files and 203 requirement identifiers;
  `git diff --check` passes.
- A fresh parallel Sphinx/AutoAPI build with warnings fatal and keep-going
  enabled exits successfully for the final repository candidate. Hosted ready-
  state acceptance remains required before merge.

## Remaining actions

1. Commit and push this authenticated metadata-evidence follow-up only after
   publication is explicitly authorized.
2. Marking the complete pull request ready and starting authoritative hosted
   acceptance remains a separate user decision.
