# Security policy

## Supported versions

Maru is pre-production and does not yet promise a stable supported release.
Security fixes target the current `main` branch and the latest explicitly
published gold release, if one exists. Release notes will identify any different
support window before the project is used with production personal data.

## Reporting a vulnerability

Do not open a public issue, pull request, discussion, or chat message for a
suspected vulnerability. While the repository is private, contact the repository
owner through GitHub using a private channel. When Maru becomes public, GitHub
private vulnerability reporting will be the preferred intake and this document
will link directly to it.

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
