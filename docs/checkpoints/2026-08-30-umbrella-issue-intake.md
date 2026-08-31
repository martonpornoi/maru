# Umbrella issue intake

- Date: 2026-08-30
- Phase: Progressive adoption and pre-production release evaluation
- Outcome: Added a bounded umbrella-proposal intake contract with explicit
  child relationships and integrated completion evidence
- Requirements: NFR-002, NFR-003, and NFR-011
- Decisions: Extends accepted ADRs 0060 and 0068; no new ADR

## Outcome

Maru's public issue intake distinguishes three shapes: safe defect reports,
one independently closable feature proposal, and one bounded end-to-end
umbrella that must be delivered through multiple child issues. The umbrella
form is planning evidence and does not authorize implementation or creation of
its children.

The form captures the current Maru boundary, affected roles and states,
complete human journey, adoption and coexistence behavior, ordered child
outcomes, integrated acceptance, explicit non-goals, requirements and decision
traceability, domain ownership and overlap, security, privacy, retention,
degraded operation, export, recovery, risks, and alternatives. It retains the
existing private-security, support, conduct, and exploratory-Discussion routes
and introduces no new label or Project.

## Decisions

- Keep the bug and feature forms focused; do not turn the ordinary feature form
  into a conditional umbrella questionnaire.
- Do not add a separate child template. A child uses the existing bug or
  feature form according to its outcome.
- Use GitHub's native parent/sub-issue relationship as membership and progress
  truth. Each child also cites its exact umbrella checklist item, owned
  acceptance, prerequisites, successors, and inherited non-goals.
- Keep the umbrella body as scope and dependency truth. Replace checklist items
  with child links, update decomposition before detached work is created, and
  leave the umbrella open through final integrated acceptance.
- Apply only `proposal` and `triage` automatically. More specific feature,
  security, documentation, or other labels remain a triage decision.

## Changed areas

- `.github/ISSUE_TEMPLATE/umbrella.yml`
- `CONTRIBUTING.md`
- repository-governance and public-readiness documentation
- exact issue-form schema, field, route, and label tests
- current-state handoff and changelog

## Verification

Verification on the completed branch passed:

- 20 focused issue-form, public-repository-material, and documentation-policy
  tests;
- repository documentation validation across 360 Markdown files, four
  repository skills, and 207 requirement identifiers;
- Ruff lint and format checks for the changed Python test;
- a fresh warning-fatal Sphinx and AutoAPI HTML build;
- `git diff --check`; and
- independent review after resolving the reviewer's three intake-contract
  findings.

Full exact-commit certification and protected `PR gate` acceptance are separate
delivery evidence. The hosted gate remains the merge authority for the exact
pull-request head.

## Data, migration, and deployment notes

This change adds no Django model, database migration, API, browser route,
runtime database permission, production-data handling, package, release, or
application deployment. It commits desired repository metadata only; the live
default-branch chooser changes after protected merge, not when this branch is
created.

## Known risks and incomplete work

- Contributors may select an umbrella for an early or unbounded idea. Chooser
  and form wording redirect that work to Discussions and require a bounded
  outcome plus independently closable children.
- Native sub-issue progress and body checklists can drift. The contribution
  contract assigns membership/progress to the hierarchy and scope/dependencies
  to the body, while requiring checklist links to be maintained.
- The form is not live until protected merge. No hosted acceptance or live
  chooser readback is claimed by this checkpoint.

## Recommended next actions

1. When delivery is authorized, certify the exact clean commit and push it for
   protected pull-request review.
2. Require a green `PR gate` for that exact head before merge.
3. After merge, read back the default-branch form and render the live chooser
   before treating the contributor experience as active.
