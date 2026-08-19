# ADR 0049: Coherent navigation, personal surface, and safe access preview

- Status: Accepted
- Date: 2026-08-08
- Supersedes: ADR 0036 only for the folder-like presentation of an already
  selected organization, series, and edition
- Clarifies: ADRs 0023, 0039, 0041, and 0047
- Requirements: UX-019, UX-020, UX-027, UX-028, IDN-009, IDN-011, PRI-001,
  AUD-001, AUD-005, NFR-001 through NFR-004

## Context

The unified `/admin/` shell correctly retains one permission-aware global
navigation surface, but the current rendering separates Convention work,
Selected edition, platform administration, account controls, and specialist
records into folder-like groups. A platform administrator can see more than a
hundred links, Registration may appear more than once, and the only menu
filter searches specialist model records. Ordinary attendees meanwhile use
separate registration URLs and do not receive one focused authenticated home.

Administrators also need to verify authorization changes without logging out
or using a shared demonstration account. Literal impersonation would corrupt
authority and audit attribution, while page-local sharing would contradict the
accepted exact-scope authorization lattice.

## Decision

### One navigation registry and explicit context

Maru uses one code-owned navigation registry for personal and management
destinations. After an organization, series, and edition have been selected,
their authorized destinations appear in one coherent list rather than nested
folder sections. The active organization, series, edition, and lifecycle stay
visible in the page header, breadcrumb, and context control; flattening the
menu never hides or guesses scope.

The menu has one search field that filters every currently authorized
destination by label, description, and stable keywords. Duplicate destinations
are collapsed to one canonical entry. Search never queries or reveals a hidden
tenant, principal, record, or specialist model.

An active person may pin a currently visible destination. A pin stores only a
stable code-owned destination key and safe context locator. Every render
resolves and authorizes it again; expired, revoked, malformed, deleted, or
foreign targets disappear without exposing their former labels. Pins affect
ordering only and never grant authority.

### My Maru

`/my/` is the canonical authenticated personal surface. It shares Maru's
identity, design system, navigation registry, account controls, responsive
behavior, and accessibility contract, but it is not branded as an
administration page. It contains only relationship-authorized personal
destinations such as the person's edition registration, payments, profile,
applications, orders, messages, and attendance history. Organizer and
platform destinations join the same registry only when current capability
decisions permit them.

Existing purpose-specific public and attendee routes may remain canonical
domain endpoints. My Maru links to or embeds their authorized projections; it
does not duplicate their business rules or data.

### Contextual access control

Management records expose a computed **Access** summary. When permitted,
**Manage access** opens the existing scoped person/immutable-role assignment
workflow for the resolved organization, edition, department, or typed
resource. It never persists a page, route, template, or field ACL. Relationship
audiences such as confirmed attendees or public publication are code-owned
projection policies, not organizer role assignments.

Pages with fixed self, public, safeguarding, security, or other purpose-bound
policy may show the explanation while omitting mutation. Named principals are
released only through an independently authorized, audited relationship read.

### Read-only authorization preview

Authorized access managers receive two explicit preview modes:

1. **View as person** evaluates one exact existing person's complete current
   effective access at a resolved scope.
2. **Preview role** evaluates one immutable role-bundle version at an exact
   scope without pretending that a person holds it.

Both modes are policy simulations. They never replace the request principal,
create a session, issue authority, execute a write, bypass step-up, or change
audit attribution. A persistent banner identifies the mode, target, scope, and
evaluation time. Every protected query remains capped by the previewing
administrator's own disclosure authority, and beginning a sensitive preview
is audited with minimized target evidence.

Preview links and forms use closed inputs and trusted scope resolvers. Unknown,
foreign, hidden, stale, or unauthorized targets return non-disclosing errors.
All mutating controls are absent or disabled while preview is active, and
server-side mutation endpoints independently ignore preview state and evaluate
the real request principal.

## Consequences

- Attendees and organizers experience one platform without turning attendees
  into administrators.
- Edition context remains explicit while the left menu stops looking like a
  hierarchy of folders.
- Search and pins improve reachability without becoming authorization data.
- Access preview provides reliable policy QA without unsafe impersonation or
  false audit attribution.
- Navigation, pin, access-summary, preview, tenant-isolation, responsive, and
  accessibility tests become required for every mounted destination.

## Alternatives considered

### Keep progressive folder sections after edition selection

Rejected. Scope remains important, but repeating it as menu depth creates
duplicate and scattered destinations once an edition is already explicit.

### Put ordinary attendees in the Django administration surface

Rejected. It would make a personal relationship look like organizer authority
and would require extensive filtering of specialist administration chrome.

### Store page ACLs behind a Share button

Rejected. Page ACLs cannot express capability, scope, field, lifecycle,
relationship, term, approval, or revocation semantics and would create a
second authorization system.

### Impersonate the selected person

Rejected. It would permit writes or reads under false identity, invalidate
audit attribution, and expose more data than the previewing administrator may
independently inspect.
