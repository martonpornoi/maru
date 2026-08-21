# Project governance

Maru uses a maintainer-led governance model. The repository is user-owned and
[`@martonpornoi`](https://github.com/martonpornoi) is currently the sole
maintainer, repository owner, release authority, security coordinator, and
public-space Code of Conduct enforcement authority. No other human account
currently has authority to merge changes, authorize an official Maru release,
represent a security or conduct decision, or appoint another maintainer.
Repository
automation may publish only within an owner-authorized protected workflow; it
does not hold independent governance authority.

## Decisions and contributions

The maintainer is responsible for product scope, architecture decisions,
security response, review, releases, and enforcement of community standards.
Contributors may propose changes through issues and pull requests, participate
in design discussion, and earn broader responsibility through sustained,
constructive, security-conscious contributions.

Durable technical decisions are recorded in architecture decision records.
Product behavior maps to stable requirement identifiers. Repository history is
not used to silently reverse either contract. The maintainer explains material
rejections and moderation decisions when doing so would not expose a reporter,
vulnerability, or other sensitive information.

## Adding or removing a maintainer

Contribution does not automatically confer maintainer status. Before another
person receives write, merge, release, security, or moderation authority, a
public governance change must identify the person, role, scope, and reason.
Repository rules, CODEOWNERS, trusted workflow review, environment access, and
security access must be reconciled in the same milestone before that authority
is relied upon. Access is granted at the least privilege needed and removed
when the role ends or the account can no longer satisfy the project's security
requirements.

While one maintainer remains, appointment and removal decisions belong to the
repository owner. A multi-maintainer nomination, removal, appeal, and voting
process would not provide independent governance today; it must be defined
before the second maintainer can exercise independent authority.

## Continuity and inactivity

Maru has no backup maintainer today. A planned handoff must be recorded in a
reviewed governance change and inventory the repository, release, package,
security, environment, documentation, and any future domain or service
authority being transferred. The incoming maintainer must accept the role
before the current owner relinquishes access.

If maintenance pauses without a successor, Maru-owned source remains licensed
under Apache-2.0 and bundled material retains its documented third-party
licenses, but no response, merge, security-remediation, or release time is
promised. When practicable, the owner will archive the repository, making it
read-only, and update README, SUPPORT, and SECURITY before an extended or
permanent shutdown. Independent forks remain permitted under the applicable
licenses, but a fork does not become an official Maru release or inherit
project authority by implication.

The sole-maintainer model cannot provide independent review of a report about
the owner. The Code of Conduct therefore records that Maru has no private
project-specific conduct channel and names GitHub's external reporting route
for GitHub-hosted abuse without implying that GitHub enforces every off-platform
project rule. Independent moderation, security rotation, approval, and release
separation remain prerequisites for a future multi-maintainer model.

Maru has not adopted separate organization-transfer, trademark, or brand-use
governance. The license controls source-code rights; it does not imply project
endorsement or authority to present a fork as an official Maru release. Any
future brand or organization policy requires its own public governance decision.
