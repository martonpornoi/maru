# ADR 0022: Ordered bootstrap-administration quick start

- Status: Superseded by ADR 0024 (first-authority command-only experience) and
  ADR 0027 (global placement)
- Date: 2026-07-30
- Supersedes: ADR 0020 web first-authority adapter only
- Requirements: AUD-001, IDN-004, UX-001, UX-003, UX-005, UX-006, UX-007,
  UX-008, UX-011, NFR-002

## Context

Bootstrap administration exposes many accurate domain records in an
alphabetical application/model directory. That structure is predictable for
returning operators but does not explain the dependency order for creating a
new convention.

The separate **First convention setup** page compounded the problem. It
presented an exceptional trust-on-first-use authority transaction like an
ordinary admin task, remained visible after setup, and combined the Chair
appointment with starter-role creation under a vague label. The underlying
one-shot service and command are still necessary because an empty organization
cannot authorize its first controller through ordinary scoped workflows.

## Decision

Keep Django admin's complete alphabetical application and model directory
unchanged. Add an ordered **Quick start** section above it:

1. define the accountable organization;
2. create the recurring convention series;
3. create the dated event edition;
4. create a separate Convention Chair account;
5. have the platform operator establish first authority with the documented
   `bootstrap_convention` command;
6. prepare edition registration;
7. build the workforce structure; and
8. review, activate, and operate through Staff Console.

Each step states whether it is performed once per organizer, once per
convention brand, once per edition, or during ongoing operations. Direct links
render only when the signed-in account has the corresponding Django model
permission. Completed records remain available through the alphabetical
directory.

Remove the browser route, form, template, and persistent header link for
**First convention setup**. Preserve the tested one-shot application service
and management command without changing its exact confirmation, scope,
controller separation, audit, and empty-authority checks.

The Quick start is navigation guidance, not a progress tracker. It does not
guess completion from record counts, mark governance work complete, change
authorization, or silently create related records.

## Consequences

New operators see a stable best-practice order without losing the efficient
alphabetical directory used for later maintenance. Setup-frequency labels make
clear which records are durable organizer/brand foundations and which repeat
for each edition.

Self-hosted first-authority creation requires one explicit operator command
after the organization, series, edition, and separate Chair account exist.
This is less convenient than a browser form, but makes the exceptional trust
boundary visible and keeps it out of routine administration. A future
purpose-built, independently reviewed authority ceremony may replace the
command; an ordinary Django form must not.

Because the guide is deliberately not stateful, it cannot become stale or
claim that a convention is ready merely because records exist. Readiness and
activation remain explicit domain workflows.

## Alternatives considered

- Reorder all admin applications/models by setup sequence: rejected because it
  makes later lookup unpredictable and mixes one-time setup with ongoing work.
- Keep the separate wizard and merely move its link: rejected because the
  high-impact trust action would still look routine and remain confusing after
  first use.
- Infer checklist completion from object counts: rejected because existence is
  not approval, readiness, authority, or safe configuration.
- Automatically bootstrap authority when an edition or Chair account is
  created: rejected because it would hide a privileged cross-module
  transaction and remove explicit confirmation and audit intent.
