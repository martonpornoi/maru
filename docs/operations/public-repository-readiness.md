# Public repository readiness

Changing visibility is a deliberate governance and security event. The
repository became public on 2026-08-20. Actions were disabled during the
transition, the persistent workstation runner was unregistered, and Actions
were re-enabled only in exact-allowlist hosted mode.

## Verified transition controls

- The active no-bypass `main` ruleset requires a pull request, an up-to-date
  `PR gate`, resolved conversations, squash-only linear history, and rejects
  deletion and non-fast-forward updates. The active `v*` tag ruleset rejects
  mutation and deletion.
- Repository-level self-hosted runner inventory is empty. Public pull requests
  use only standard GitHub-hosted runners with read-only default permissions.
- Actions run in `selected` mode, require SHA pinning, and allow only the exact
  revisions in `.github/actions-allowlist.json`.
- Secret scanning, push protection, Dependabot security updates, and private
  vulnerability reporting are enabled. GitHub-managed default CodeQL is
  configured for Actions, Python, and JavaScript/TypeScript.
- Merge commits and rebase merges are disabled; squash merge and automatic
  deletion of merged branches are enabled.

## Outstanding public-readiness audit

Visibility changed before every item in the original pre-public checklist had
fresh evidence. Treat these as immediate launch tasks, not optional later work:

- Complete a secret-history scan, remove any exposed credential from history,
  rotate it at the provider, and verify no production or personal data exists.
- Review copyright and third-party assets, dependency licenses, generated
  content, trademarks, examples, fixtures, commit metadata, issue references,
  and historical branches/tags for publishability.
- Replace temporary owner-only conduct and security contact channels with
  durable monitored addresses. Define maintainer succession and moderation.
- Exercise the active rules through a harmless pull request and protected-tag
  refusal. Add a second trusted maintainer, then require one approval and
  CODEOWNER review.
- Secret scanning currently reports no open alert. Triage the twelve initial
  CodeQL findings (three high and nine medium), and confirm push protection
  blocks a synthetic non-secret test pattern without publishing credentials.
- Configure `candidate` and `gold` environments, required reviewers where the
  team permits them, deployment targets, GHCR visibility, and package cleanup.
- Review repository description, topics, social preview, funding/sponsorship,
  discussions, issue triage labels, support expectations, and first-good-issue
  scope.
- Publish an explicit pre-production maturity statement. Do not imply that the
  current repository or a candidate release is safe for production personal
  data.

## Post-transition acceptance

Re-query repository rules and security features rather than assuming settings
survived the transition. Run a documentation-only pull request, a protected
deletion refusal, an ordinary targeted change, a high-risk full change, and a
candidate release in a synthetic environment. Verify forks receive read-only
tokens, untrusted pull requests cannot access secrets or publish packages, and
all Actions remain pinned to immutable commits.

Public source does not require public operational data. Keep vulnerability
reports, incident details, personal data, credentials, production topology, and
partner-confidential material in their separately governed systems.
