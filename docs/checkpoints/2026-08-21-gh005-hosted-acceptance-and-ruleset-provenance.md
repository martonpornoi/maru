# GH-005 hosted acceptance and ruleset provenance

Date: 2026-08-21
Status: Complete
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decisions: ADR 0066 and ADR 0069

## Outcome

Pull request 9 completed GH-005's event-efficient hosted acceptance boundary.
Corrected head `7b7add029cf8dd22fd95e357dd1f597aaa4e0803` passed authoritative
ready-state run `32504876594`, including locked-input and Action-policy
preflight, repository safety, full Python static analysis, warning-fatal
contributor documentation, Django contracts and frontend verification,
dependency security, unit coverage, all eight PostgreSQL integration shards,
combined coverage, `Full CI gate`, and `PR gate`.

Managed CodeQL run `32504873965` passed its Actions, JavaScript/TypeScript, and
Python analyses at the same head. The accepted `PR gate` check was produced by
the GitHub Actions app with integration ID `15368`. Pull request 9 then
squash-merged to `main` as
`a42358b583b04c4ad0738e05247f2cffedfbe07e`.

## Live ruleset reconciliation

The authenticated pre-read of repository ruleset `21093924` found the sole
strict required status as context-only `PR gate`. Its accepted desired-state
payload already named GitHub Actions integration ID `15368`, but that source
binding was not yet live.

Under separate owner authorization, the complete normalized supported payload
from `.github/rulesets/main.json` was submitted with `PUT` to the existing
ruleset. An independent authenticated `GET` then returned exactly one required
status entry with context `PR gate` and `integration_id: 15368`. GitHub recorded
ruleset history version `47251175` for the update.

The post-read also confirmed that every prior protection remained intact:

- enforcement is active, the bypass list is empty, and
  `current_user_can_bypass` is `never`;
- the status policy remains strict and applies to creation, with `PR gate` as
  its sole required context;
- pull requests remain required with squash-only linear history, zero required
  approvals under the sole-maintainer boundary, resolved conversations, and
  no stale-review, code-owner, or last-push approval requirement;
- deletion and non-fast-forward updates remain prohibited; and
- CodeQL continues to block general errors and security alerts at medium
  severity or higher.

The server-normalized empty reviewer list and extra-approval protection for
unattributed changes also remained unchanged. No runtime behavior, schema,
migration, deployment, or release changed in this closure.

## Repository verification

- All 17 focused workflow and ruleset contracts pass.
- Documentation validation covers 288 Markdown files and 203 unique
  requirement identifiers.
- A fresh Sphinx and AutoAPI build completes with warnings treated as errors.
- `git diff --check` reports no whitespace error.

## Next actions

1. Evaluate GH-006 dependency review for material protection beyond the current
   locked-resolution, audit, Dependabot, and Action-allowlist controls.
2. Implement GH-007's main-only warning-fatal Sphinx Pages publication.
3. Rehearse GH-002's first immutable `rc.1` only after separate authorization
   for the permanent public tag, release, assets, image, and attestations.
