# Public repository readiness

Changing visibility is a deliberate governance and security event. The
repository is prepared for collaboration, but must remain private until every
item below has an owner and evidence.

## Before changing visibility

- Complete a secret-history scan, remove any exposed credential from history,
  rotate it at the provider, and verify no production or personal data exists.
- Review copyright and third-party assets, dependency licenses, generated
  content, trademarks, examples, fixtures, commit metadata, issue references,
  and historical branches/tags for publishability.
- Replace temporary owner-only conduct and security contact channels with
  durable monitored addresses. Define maintainer succession and moderation.
- Apply and test `main` and release-tag rules. Add a second trusted maintainer,
  then require one approval and CODEOWNER review.
- Enable private vulnerability reporting, Dependabot alerts and security
  updates, secret scanning and push protection, and GitHub's recommended CodeQL
  default setup. Default setup supplies pull-request, protected-branch, and
  weekly scans without a repository-maintained advanced workflow.
- Configure `candidate` and `gold` environments, required reviewers where the
  team permits them, deployment targets, GHCR visibility, and package cleanup.
- Review repository description, topics, social preview, funding/sponsorship,
  discussions, issue triage labels, support expectations, and first-good-issue
  scope.
- Publish an explicit pre-production maturity statement. Do not imply that the
  current repository or a candidate release is safe for production personal
  data.

## After changing visibility

Re-query repository rules and security features rather than assuming settings
survived the transition. Run a documentation-only pull request, a protected
deletion refusal, an ordinary targeted change, a high-risk full change, and a
candidate release in a synthetic environment. Verify forks receive read-only
tokens, untrusted pull requests cannot access secrets or publish packages, and
all Actions remain pinned to immutable commits.

Public source does not require public operational data. Keep vulnerability
reports, incident details, personal data, credentials, production topology, and
partner-confidential material in their separately governed systems.
