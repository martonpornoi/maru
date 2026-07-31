# ADR 0035: Organization-scoped convention-series creation

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0020 only for the current browser creation adapter
- Requirements: IDN-011, EVT-001, EVT-003, UX-013, UX-014, UX-017,
  UX-018, AUD-001, AUD-002, PRI-001

## Context

Page 3 maintains the accountable organization but deliberately does not create
its recurring public convention brands. The preserved administration exposed a
generic Convention Series model form with name, slug, organization,
description, website, contact email, and active status. Its field vocabulary is
useful, but choosing a parent tenant and editing a technical slug in a generic
model page obscured the normal setup journey.

The controlled rebuild now needs the next single step: create a series for the
organization currently being inspected. It must not silently advance into the
edition, governance, or participation parts of convention setup.

## Decision

Page 3 gains a **Convention series** section before the long organization
profile. It lists series scoped to that organization and provides **+ Add
series**. Page 4 lives at
`/admin/organizations/<organization_slug>/series/new/`; organization context is
taken only from the authorized URL lookup and is displayed but never accepted
from posted data. The global navigation remains the single
**Organizations**/**+ Add** row because series belong inside an organization,
not beside tenants in platform navigation.

Only series name is required operator input. The form also accepts a bounded
public description, HTTPS-default website, public contact email, and initial
availability. Availability defaults to Active and means that future editions
may be created under the brand; it neither publishes the series nor creates an
edition. Maru normalizes the name and generates a stable, bounded,
case-insensitively unique slug within the selected organization. The same
human-readable name may therefore exist in different organizations, while
collisions within one organization receive deterministic numeric suffixes.

During the controlled rebuild, only an authenticated active platform
administrator may load or submit Page 4. Authorization precedes organization
lookup and the application service repeats it. The service locks the parent,
refuses a Closed organization, validates the complete series, creates it, and
appends value-minimized audit evidence in one transaction. Draft, Active, and
Suspended organizations may retain or prepare brand records; Closed is the
terminal boundary. A later lifecycle decision may further restrict Suspended
organizations without changing the tenant-scoped identity model.

Success redirects to Page 3, where the new row and a one-time confirmation are
visible. Creation produces no event edition, organization membership,
Executive Board, authority grant, participation, registration, volunteer,
onboarding, or workforce relationship. Page 5 will own an existing series
record and any later edit/deactivation behavior.

## Consequences

The normal setup journey becomes explicit: organization first, recurring
convention identity second, dated edition later. Tenant ownership cannot be
crafted in POST data, series slugs remain stable implementation identities, and
Maru's platform administrator remains outside the convention.

Once a series exists, Page 3's protected organization deletion necessarily
refuses to erase the tenant. A future Page 5 and closure workflow must manage
series lifecycle and history instead of treating creation as reversible model
administration.

## Alternatives considered

- Restore the preserved generic Django model form: rejected because it exposes
  parent and slug choices and breaks the reviewed setup journey.
- Put Convention series in the global sidebar: rejected because a series is
  organization-owned and global placement makes it look like another tenant.
- Create the first edition at the same time: rejected because identity, dates,
  locale, lifecycle, and inherited configuration require Page 6's separate
  contract.
- Require an Active organization: rejected for this rebuild interval because
  IDN-012 deliberately keeps newly created organizations Draft until governance
  exists, while their setup must still be able to progress.
