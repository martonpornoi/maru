# Security policy

## Supported versions

Maru is pre-production and does not yet promise a stable supported release.
Security fixes target the current `main` branch and the latest explicitly
published gold release, if one exists. Release notes will identify any different
support window before the project is used with production personal data.

## Reporting a vulnerability

Do not open a public issue, pull request, discussion, or chat message for a
suspected vulnerability. Instead, [open a private vulnerability
report](https://github.com/martonpornoi/maru/security/advisories/new) so the
maintainer can assess and coordinate remediation without disclosing the report
publicly.

That GitHub form is Maru's configured private vulnerability channel. The sole
current human repository administrator,
[`@martonpornoi`](https://github.com/martonpornoi), is responsible for response;
notification delivery depends on that account's GitHub settings. The reporter
and any explicitly added advisory collaborators retain access to the private
advisory. Maru does not yet have an independent security rotation. Use the
separate limitations and GitHub abuse-reporting guidance in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community conduct.

Include the affected commit or release, reproduction conditions, impact,
whether sensitive data may be involved, and any safe mitigation you have tested.
Do not access data that is not yours, disrupt a live service, or retain personal
data while investigating.

The maintainer will acknowledge a complete report as soon as practical, keep
the reporter informed, coordinate a private fix and release where warranted,
and credit the reporter unless anonymity is requested. Exact response times are
not promised until a staffed security-response rotation exists.

## Security scope

Particularly important boundaries include tenant and edition isolation,
authorization and privilege escalation, invitation and recovery secrets,
audit integrity, payment evidence, personal-data disclosure, file/media safety,
offline credentials, dependency supply chain, and release provenance.

Maru's current repository evidence is not a production security certification.
The deployment, recovery, partner-policy, and go/no-go gates in the maintained
operations documentation remain mandatory.
