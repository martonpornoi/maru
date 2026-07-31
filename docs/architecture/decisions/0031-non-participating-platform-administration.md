# ADR 0031: Non-participating platform administration

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0019, ADR 0020, and ADR 0024 only where the bootstrap
  controller previously received organizer membership, convention authority,
  edition participation, or a workforce role
- Requirements: IDN-002, IDN-004, IDN-011, UX-013, UX-014, AUD-001,
  SAF-004

## Context

The page-by-page rebuild begins with one first account that operates Maru
itself. Treating that account as an organizer, convention staff member, or
attendee would pollute rosters and history and would confuse platform support
authority with authority delegated by an independent organizer. Identifying it
only by being the oldest account would also make the rule accidental and
fragile.

The account must be able to discover every organization and provision the
roots needed for a new convention. That global platform role must not bypass
the existing rule that restricted safety and case records require reasoned,
time-limited break-glass access.

## Decision

Classify accounts explicitly as either `person` or `platform_administrator`.
All application superusers are platform administrators, and a platform
administrator must retain staff and superuser privileges. Migrate existing
superusers to the explicit classification; do not infer the classification
from account creation order, email address, or display name.

A platform administrator may be recorded as the actor, creator, reviewer,
approver, or auditor of a platform or bootstrap operation. It may not be the
subject of:

- an organization membership;
- an organization- or edition-scoped capability grant or role assignment;
- edition participation or registration;
- a volunteer application or onboarding-document request; or
- a workforce position assignment.

An active platform administrator receives platform-policy decisions for
code-owned non-self capabilities without storing an organization or edition
grant. This keeps its global operating access explicit while preventing a
false convention relationship. Capability declarations can require
break-glass; that obligation denies ordinary platform-administrator policy and
must be satisfied by a separate time-limited, reasoned path. Self-only
capabilities remain relationship-bound.

The owning models validate this boundary before saving. Later account pickers
must omit platform administrators as convention subjects. Platform support
visibility uses explicit platform policy and audit obligations; it never
manufactures a convention relationship. SAF-004 continues to require
break-glass controls for restricted cases.

The first restored `/admin/` page is a read-only platform organization
inventory. It is available only to active platform administrators. It may show
organization identity, lifecycle, series count, and edition count across the
installation. It does not show convention-owned operational data and creates
no relationship as a side effect. If its query fails, it returns a safe
read-only `503` state and records the technical exception through server
logging.

The preserved context API may project edition identity to a platform
administrator with `participation_status` equal to `not_participating` and no
capacities. It does not manufacture a `Participation` row. The one-shot
workforce bootstrap uses the platform administrator only as its attributed
controller; organization and edition authority, membership, participation,
and the Chair position are created solely for the distinct Chair account.

## Consequences

Platform administration remains visible and accountable without causing the
administrator to appear in convention people, staffing, or registration data.
Ordinary staff accounts cannot use the platform home merely because Django's
staff flag is set.

Application code may still use the administrator as an attributed controller
for exceptional bootstrap operations. That actor evidence is not a
participation record. Direct database repair remains an operator procedure,
not a supported application workflow.

The organization-creation action is intentionally absent from Page 1. It is
introduced only with the separately reviewed Page 2 contract, avoiding a link
to an unfinished page.

## Alternatives considered

- Identify the first-created account as the administrator: rejected because
  ordering is not an authority model and cannot survive imports or recovery.
- Treat the administrator as a member of every organization: rejected because
  it creates false participation and implicit cross-tenant relationships.
- Use only `is_staff`: rejected because ordinary staff status is intentionally
  broader than platform operation and cannot express non-participation.
- Grant convention roles to the administrator for visibility: rejected because
  platform oversight and organizer delegation have different purposes and
  audit meaning.
