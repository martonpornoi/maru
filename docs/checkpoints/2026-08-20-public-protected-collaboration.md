# Public protected collaboration transition

Date: 2026-08-20
Status: Live repository controls applied; candidate documentation and fresh
hosted pull-request acceptance pending publication

## Outcome

Maru changed from private to public visibility. Actions remained disabled while
the trust boundary was changed. The repository-scoped
`maru-local-certifier` was then unregistered, leaving zero self-hosted runners,
and the pull-request and reusable full workflows were restored to standard
GitHub-hosted Linux execution under ADR 0063.

Actions were re-enabled in `selected` mode with SHA pinning. The live allowlist
contains only the exact immutable external revisions referenced by the checked-
in workflows. Workflow tokens default to read-only; only the manual release
boundary retains its explicitly scoped publication permissions.

Two active repository rulesets now provide the server boundary:

- **Protect main** requires a pull request, an up-to-date successful `PR gate`,
  resolved conversations, squash-only linear history, and rejects deletion and
  non-fast-forward updates.
- **Protect release tags** rejects deletion, update, and non-fast-forward
  mutation of `v*` tags.

Both rulesets have empty bypass lists and the live API reports
`current_user_can_bypass: never` for the repository owner. The local pre-push
hook remains defense in depth rather than the authority.

Secret scanning, push protection, Dependabot security updates, and private
vulnerability reporting are enabled. GitHub-managed default CodeQL was started
for Actions, Python, and JavaScript/TypeScript on standard hosted runners.

## Verification

- Repository API: `visibility=public`, default branch `main`.
- Actions API: enabled, `allowed_actions=selected`, SHA pinning required.
- Selected-actions API: GitHub-owned and verified-owner wildcards disabled;
  eleven exact `owner/repository@40-character-SHA` patterns configured.
- Runner API: zero repository-level self-hosted runners.
- Ruleset API: active main rule ID `21093924` and release-tag rule ID
  `21093933`, both without bypass actors.
- Merge settings: squash enabled, merge-commit and rebase disabled, merged
  branches deleted automatically.
- Security API: secret scanning and push protection enabled; Dependabot
  security updates enabled; private vulnerability reporting accepted.
- CodeQL default-setup run `32376332626` passes its Actions, Python, and
  JavaScript/TypeScript jobs. It opened twelve findings against existing
  `main`: three high-severity and nine medium findings require separate review.
- Secret scanning currently reports zero open alerts.
- A `git push --dry-run --no-verify` does not evaluate GitHub rules and therefore
  cannot prove refusal. No real direct push was attempted because an
  enforcement defect would mutate `main`; the live no-bypass ruleset response
  is the safe evidence until a disposable refusal rehearsal is designed.
- actionlint accepts every workflow. The focused workflow/ruleset contract
  passes 8 of 8 tests and now inventories both shorthand and named `uses:`
  steps, rejecting any difference from the exact Action allowlist.
- Live Python and frontend dependency audits report no known vulnerability.
  Ruff formatting/lint passes all 642 files; strict mypy passes 356 source
  files; strict PyDocLint and semantic validation pass 363 production/tooling
  files; and documentation validation passes 268 Markdown files with 202
  unique requirement identifiers.
- The fresh warning-fatal Sphinx/AutoAPI build succeeds. Django migration drift,
  system checks, production-settings verification, OpenAPI validation, generated
  TypeScript parity, frontend typechecking, and production build pass with only
  the expected local invitation warning and 18 existing enum-name diagnostics.
- The broad pass exposed the previously recorded Staff Console report timing
  test as still flaky at its one-second default wait. It now waits up to five
  seconds for the complete mocked report state. Three consecutive complete
  frontend runs pass 20 of 20 tests, and the built static output is unchanged.

## Known limits

- The first hosted `PR gate` after the transition is still pending publication
  of the candidate. The initial CodeQL execution passes, but its twelve findings
  are not yet triaged.
- GitHub accepted secret scanning and push protection but left optional secret-
  validity and non-provider-pattern refinements disabled for this repository.
- The visibility change occurred before a fresh independent history-wide secret,
  copyright, asset, issue, and commit-metadata audit. Complete that review and
  rotate any exposed credential before broad public promotion.
- The repository still has one maintainer, so required approvals remain zero.
  Require one approval and CODEOWNER review when a second trusted maintainer is
  available.
- Rulesets prevent ordinary Git bypass, but an administrator can still change
  repository security settings. Governance, account security, recovery, and
  ownership succession remain necessary controls.

## Smallest next actions

1. Publish this candidate to pull request 2 and inspect its fresh hosted
   `PR gate` and retained artifacts.
2. Complete the history/public-material audit and triage all twelve CodeQL
   findings before announcing the repository broadly.
3. Exercise protected deletion/tag refusal with disposable references and run
   a documentation-only pull request to verify the fast path.
4. Add a second trusted maintainer, succession channel, and one required
   CODEOWNER approval when governance permits it.
