# ADR 0068: Public collaboration channels and sole-maintainer continuity

- Status: Accepted
- Date: 2026-08-21
- Requirements: NFR-002, NFR-003, NFR-011
- Implements: GH-004
- Refines: ADR 0060 decision 8 and its public-launch contact/succession
  consequence
- Relates to: ADR 0063, ADR 0064, and ADR 0067

## Context

Maru is public, but some launch-era policy still described a future public
transition, copied brittle test and vulnerability snapshots into README, and
left maintainer inactivity, conduct escalation, support expectations, and
repository metadata ambiguous. The repository already has all core Community
Standards files, yet a file's presence does not make an unspecified contact
usable or create an independent review body.

The repository is owned and maintained by one person. Requiring another
approval, a voting process, an independent moderation rotation, or a successor
who does not exist would create a deadlock or a false assurance. Conversely,
leaving the effect of maintainer inactivity undefined makes contributor and
security expectations unclear.

Description, topics, feature switches, labels, and social preview are GitHub-
hosted state. They need authenticated observation and an explicit decision, but
a documentation commit does not mutate them. Funding links normally come from
committed `.github/FUNDING.yml`, while connecting a recipient or Sponsors
account is separate external stewardship work. External setting changes remain
subject to NFR-011's separate authorization and readback rule.

## Decision

1. Keep `@martonpornoi` as the documented sole maintainer, repository owner,
   release authority, security coordinator, and public-space Code of Conduct
   enforcement authority. No contribution implies any of those authorities.
2. Do not publish the owner's login or historical personal address and do not
   create a placeholder project mailbox. Maru currently provides no private
   project-specific conduct-reporting channel. The Code of Conduct states that
   limitation, warns against putting sensitive reports in public issues, and
   names GitHub's external abuse-reporting path without implying that GitHub
   enforces every project-specific or off-platform conduct rule. Reports
   involving the sole maintainer cannot receive independent internal review.
3. Keep GitHub private vulnerability reporting as the configured private
   security channel. The sole human repository administrator is responsible for
   response; notification delivery depends on account settings, and the
   reporter plus explicitly added advisory collaborators retain access. Do not
   route ordinary support or conduct reports into the security-advisory inbox.
4. Keep support best effort and pre-production. Issues own observable defects
   and scoped proposals; Discussions own setup and design conversation. Maru
   promises no response time, resolution time, private product-support channel,
   or production SLA.
5. Define sole-maintainer continuity now. A planned handoff requires a reviewed
   governance change, explicit acceptance by the successor, and reconciliation
   of repository, release, package, security, environment, documentation, and
   future service authority. If maintenance stops without a successor, no
   response or release is promised; when practicable the owner archives the
   repository, making it read-only, and updates the public policies. Maru-owned
   source remains Apache-2.0, bundled material retains its documented third-
   party licenses, and forks do not inherit official project authority by
   implication.
6. Reserve actual second-maintainer appointment, independent moderation and
   security rotation, CODEOWNER approval, latest-push review, organization
   transfer, and release separation for GH-008. Those controls must be in place
   before another account's authority is relied upon.
7. Accept the existing live topics: `django`, `event-management`,
   `modular-monolith`, `openapi`, `postgresql`, `python`, `react`, and
   `typescript`. Keep Issues and Discussions enabled and Projects, Wiki, Pages,
   and Downloads disabled. Keep the homepage empty until GH-007 publishes and
   verifies Sphinx through Pages; do not create a Wiki mirror.
8. Adopt **Pre-production, security-focused Django and PostgreSQL platform for
   operating multi-convention events.** as the desired repository description.
   Its live update requires separate authorization and post-change readback.
9. Retain GitHub's generated social preview until a purpose-built, owner-
   approved asset exists. Do not add `.github/FUNDING.yml` or connect a funding
   recipient until a real recipient and stewardship decision exist. Do not add
   placeholders merely to fill a Community Profile field.
10. Use `triage` for new bug reports and proposals. Apply `good first issue`
    only to independently bounded work with observable acceptance, synthetic
    inputs, usable setup and verification instructions, no maintainer-only
    access, and no hidden security, migration, or cross-module prerequisite.
    Do not manufacture newcomer issues or add stale-issue automation without
    demonstrated volume.
11. Keep changing evidence out of README. README states the maturity and links
    to `CURRENT.md`, the production-consolidation ledger, and append-only
    checkpoints for exact evidence. Dated security and metadata snapshots
    remain explicitly dated where they are operationally useful.

## Consequences

- Contributors can find the public support routes, confidential security
  channel, and explicit conduct-reporting limitation from README and the Issue
  Form chooser without mistaking a public issue or security advisory for a
  private conduct inbox.
- Sensitive Maru-specific or off-platform conduct concerns have no private
  project route today. That is an accepted, visible limitation until the
  project can operate a durable channel and independent review capacity.
- Governance is honest about one person's authority, lack of independent
  review, and the behavior of an inactive repository without pretending that a
  second maintainer already exists.
- Newcomer labels communicate genuinely prepared work rather than a marketing
  count, and issue labels do not promise scheduling or response times.
- The existing topic and feature configuration needs no churn. The desired
  description has one separately authorized live change; Pages, a homepage,
  custom social media art, funding, and multi-maintainer controls stay in their
  owning milestones.
- Public documentation remains versioned with the repository and future Sphinx
  Pages output instead of splitting policy across a manually synchronized Wiki.

## Alternatives considered

### Use private vulnerability reports for conduct complaints

Rejected. That inbox is actionable, but GitHub presents it as a security-
advisory workflow. Mixing ordinary conduct reports with vulnerability
coordination would obscure purpose, retention, and access expectations.

### Accept public issues as the conduct channel

Rejected because a reporter may need to disclose harassment, identity, or
other sensitive context without publishing it to the community.

### Create a dedicated project mailbox now

Deferred at the owner's direction. A free mailbox or forwarding alias would be
possible without a Maru domain, but it would add a public address, account
recovery, retention, and response responsibility that the project is not
currently prepared to operate. A future channel requires an explicit policy
change rather than an inferred personal address or an unattended placeholder.

### Describe a committee, appeal panel, or automatic successor

Rejected because no such body or successor exists. The policy records the
current owner-conflict limitation and defers independent authority until there
is another qualified person.

### Enable every visible repository feature

Rejected. Wiki duplicates maintained Sphinx source; Projects and structured
Discussion templates lack demonstrated volume; Pages belongs to GH-007; and
funding or social-preview placeholders add polish without governance or
operational value.

### Keep exact test and alert counts in README

Rejected because those values drift on every substantial change. Maintained
handoff and checkpoint documents provide dated, reviewable evidence without
making the repository landing page misleading.

## References

- [GitHub Community Profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
- [GitHub private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)
- [GitHub repository topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)
- [GitHub social preview](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)
- [GitHub reporting abuse or spam](https://docs.github.com/en/communities/maintaining-your-safety-on-github/reporting-abuse-or-spam)
- [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct.html)

## Requirements affected

- NFR-002 requires public contribution, conduct, security, support, governance,
  and repository-readiness documents to agree with the live public state.
- NFR-003 is satisfied by the append-only GH-004 checkpoint and concise current
  handoff.
- NFR-011 keeps external repository mutations separately authorized and read
  back while preserving checked-in desired state and authority boundaries.
