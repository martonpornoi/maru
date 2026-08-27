# Set up Workforce contract

- Status: Implemented, locally certified, and synthetically browser-rehearsed;
  complete owner, representative screen-reader, production-recovery, and
  deployment acceptance remain open
- Route: `/admin/platform/setup/workforce/`
- Requirements: IDN-011, IDN-012, IDN-014, EVT-001, EVT-002, EVT-005,
  EVT-006, UX-014, UX-019, UX-020, UX-024, UX-025, UX-027, UX-029, UX-030,
  NFR-003, NFR-009, and NFR-013
- Decision: ADR 0080

## Purpose and primary user

Let an active Maru platform administrator establish one convention's volunteer
workspace without asking that convention to move attendee Registration,
payments, attendance, or unrelated operations into Maru.

The page creates or reuses only the minimum trustworthy foundation. It does not
make the platform administrator a convention member or participant. A new
organization receives a truthful **Maru operators** representation for the
people responsible for this software; it does not manufacture an Executive
Board.

## Placement and navigation

Platform administration home exposes **Set up Workforce** as a primary focused
action. The page uses the shared administration shell, platform breadcrumbs,
effective-access summary, task framing, form grammar, and responsive patterns.
It does not add a second setup product or global hierarchy.

Existing Workforce-only editions appear first as a bounded **Continue, do not
duplicate** list. Each continuation opens the exact edition's Organization
structure journey.

On successful creation:

- a newly provisioned or still-Provisioning representation redirects to the
  organization's **Representation & access** page so two people can accept and
  activate accountability; and
- an already Active representation redirects to that edition's
  **Organization structure** page.

The subsequent owner sequence is Structure → a safe first Position meaning
when needed → Positions → assignments → Availability → Shifts. These are
purposes, not numbered pages.

## Authorization and disclosure

Only an active account explicitly classified as a platform administrator may
GET or POST the page. Anonymous callers follow the normal sign-in boundary;
ordinary active accounts receive no setup inventory or tenant disclosure.

Selection lists include only reusable Draft or Active organizations and active
series that satisfy the accountable-representation precondition. The command
locks and revalidates selected records. An Active organization without any
representation is rejected before creating a series or edition.

The page does not reveal controller identities, invitation details, authority
provenance, Registration counts, payments, attendance, or records from
unadopted modules.

## Foundation choice

The first radio group asks **What already exists in Maru?** and supports three
closed modes:

| Choice | Reused | Created |
| --- | --- | --- |
| Start a new organization and convention | nothing | Organization, convention series, edition, and Maru operators |
| Use an existing organization | Organization and its representation when present | convention series, edition, and Maru operators only when representation is absent |
| Use an existing convention series | Organization, series, and representation | edition only, plus Maru operators only when representation is absent |

Progressive disclosure enables only the fields that belong to the selected
mode. Disabled or irrelevant reuse fields are ignored by validation and the
idempotency digest. JavaScript improves visibility but does not define the
server contract.

## Explicit input contract

| Field | Bounds and normalization | Used when | Ownership and retention |
| --- | --- | --- | --- |
| `mode` | Exact closed choice | Always | Request control; retained on the append-only setup receipt |
| `organization` | Exact UUID-backed choice from the bounded list | Reuse organization | Trusted again under row lock; retained as receipt scope, not copied text |
| `series` | Exact UUID-backed choice from the bounded list | Reuse series | Trusted again under row lock; retained as receipt scope |
| `organization_name` | 1–160 characters; trim and collapse whitespace | New foundation | C1 tenant identity; stored on Organization |
| `series_name` | 1–160 characters; trim and collapse whitespace | New foundation or reuse organization | C1 recurring convention identity; stored on ConventionSeries |
| `edition_name` | 1–160 characters; trim and collapse whitespace | Always | C1 dated project identity; stored on EventEdition |
| `starts_on` | ISO calendar date | Always | Stored on EventEdition; must be on/before end |
| `ends_on` | ISO calendar date, at most the edition span limit | Always | Stored on EventEdition |
| `time_zone` | Supported IANA identifier | Always | Stored on Organization when new and EventEdition |
| `idempotency_key` | Server-issued UUID hidden field | Always | Internal C1/C2 retry evidence; retained on the receipt, never presented as content |

The form accepts no undeclared POST field. CSRF, method, authenticated-account,
and trusted route checks remain server-owned. New setup records `en` as the
default language and `XXX` as the internal no-currency sentinel. The page does
not ask for currency because this profile does not configure payments.

## Atomic command and evidence

`set_up_workforce_adoption(...)` takes a transaction-scoped PostgreSQL advisory
lock derived from the actor's idempotency key. It then:

1. returns the retained result for an exact replay or rejects a changed replay;
2. creates or locks the selected foundation through module-owned commands;
3. creates a Draft `workforce_only@1` edition through the canonical edition
   command;
4. reuses the organization's existing representation or provisions
   `maru_operators` when none exists;
5. stores an append-only `WorkforceAdoptionSetupReceipt`; and
6. appends minimized correlated audit evidence.

Any validation, authorization, persistence, audit, or outbox failure rolls the
whole setup back. The receipt's organization, series, edition, profile, and
representation scope is checked in PostgreSQL. Update, delete, and ordinary
truncate are refused.

## Accountable access

Maru operators identify software responsibility, not legal office. Initial
activation still requires:

- two distinct active verified person accounts;
- one exact invitation per person;
- each invitee's own versioned acceptance;
- no unanswered invitation;
- current representation version and exact organization-name confirmation;
- independent cross-approved immutable `maru-operators@1` assignments; and
- one atomic activation of representation, memberships, appointments,
  authority, and organization.

The role includes organization setup, edition profile/lifecycle, access
management, security audit, and implemented Workforce capabilities. It does
not include Participation, Registration, payment, attendance, or unrelated
module capabilities. Existing Executive Board representation is reused without
renaming, replacing, or duplicating it.

## Safe first Position meaning

Position creation requires a published organization-owned Position template
whose immutable RoleBundle is valid and compatible with the edition profile.
Once a fresh Workforce-only edition has an active Department, its Positions
page provides **Create the safe Volunteer starter** only when no compatible
template exists and the viewer is an active accountable controller with both
role and structure authority.

The controller enters a different active accountable controller's exact email
and a retained reason. One atomic command creates the code-owned
`workforce-volunteer@1` RoleBundle and Position template with only
`events.view_basic`, `workforce.view_structure`, and the semantic `volunteer`
capacity label. The independent approver is recorded on immutable issuance and
audit evidence. An exact repeat returns the existing starter; a reserved name
or code with different meaning fails as a reconciliation conflict.

The starter grants nobody authority and creates no Position, opportunity,
application, assignment, membership, Participation, Registration, payment,
Availability, or Shift. Templates containing an unadopted capability are not
offered in a Workforce-only Position form. This is a single safe starting
meaning, not a general Position-template authoring surface.

## Adopted and absent behavior

The resulting context, shell, and Staff Console expose:

- Today as a Workforce workspace summary, without attendee or payment metrics;
- Workforce and its Structure, Positions, assignments, Availability, and
  Shifts continuation;
- purpose-matched Setup and Security access; and
- an explicit, collapsed specialist-record gateway when authorized.

They do not expose People attendance summaries, attendee Registration,
Registration desk, payments, reports and badges, or unrelated planned module
pressure. Generic access management omits groups and assignments containing an
unadopted capability and rejects attempts to assign them. Exact-edition policy
returns `module_not_adopted` before considering platform oversight or stored
authority. Public Registration discovery excludes the edition.

An exact Workforce-only edition in a requested management route also becomes
the shell and selector context without requiring an earlier session choice.
Public opportunities, applications, and Workforce documents use focused
Volunteer navigation and explicitly state that the account is not attendee
Registration, attendance, or payment. Personal Workforce routes show My Maru
and My Workforce destinations without unrelated registration, order,
application, schedule, or equipment links.

The setup command and its acceptance tests prove zero rows across the current
unadopted application models. An active Workforce account may have no
Participation row; signing in or receiving a Workforce assignment never
creates one.

## States and recovery

- **Empty:** Explain the narrow boundary and show one blank guided form.
- **Existing profile:** Lead with exact continuation links before creation.
- **Validation:** Keep the submitted mode and safe values; associate errors
  with fields and expose a role-alert summary.
- **Replay:** Reuse the first durable result and destination without duplicate
  foundation or evidence.
- **Conflict:** Explain that the retry key was used for different details and
  leave the database unchanged.
- **Denied:** Release no organization, series, edition, or person inventory.
- **Dependency/persistence failure:** Roll back and show the shared safe retry
  state without database detail.
- **Accountability pending:** Continue to Representation & access.
- **Ready to organize:** Continue to Organization structure.

Migration is additive: existing editions become `full_convention@1`. Profile
and setup-receipt downgrade is refused after durable adoption evidence exists;
operators keep compatible code and fix forward or restore the whole database.
There is no destructive self-service profile removal.

## Coexistence, portability, and operational limits

Incumbent Registration, payment, attendance, programme, communications, and
other systems remain authoritative and require no integration for this profile.
No cross-module automation begins implicitly.

The built-in versioned Workforce structure template and manual editors provide
the current setup path. A general partner bulk importer, whole-profile
continuity export, printable rota, offline reconciliation pack, automated
profile decommissioning, and production retention execution are not yet
implemented. The UI and documentation must present those as gates, never as
capabilities delivered by this setup page.

## Accessibility and responsive acceptance

The page uses one `h1`, semantic sections, a labelled radio group, associated
field help and errors, a polite live mode explanation, a real data table with
caption, visible focus, keyboard-operable controls, and shared narrow card/table
behavior. JavaScript must preserve usable server-rendered fields when absent.

Acceptance covers 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS pixels,
200 percent zoom, keyboard-only mode selection and submission, reduced motion,
screen-reader names and state, empty/populated/validation/denied/replay/failure
states, and no page-level horizontal overflow. Automated accessibility and a
focused browser rehearsal are evidence, not a substitute for representative
assistive-technology and owner acceptance.

## Verification boundary

Focused integration tests cover minimum creation, exact and conflicting
replay, existing Board reuse, active-ungoverned rollback, database immutability,
currency rejection, two-person operators, policy denial before platform
oversight, profile-expansion denial, Participation-free context, focused menus,
profile-compatible access groups and Position templates, independently approved
starter creation and no-side-effect replay, exact-route context, focused public
and personal shells, setup/page disclosure, and platform-only access. Staff
Console tests cover full and Workforce-only projections,
navigation, Today and setup wording, retained volunteer workflows, specialist
disclosure, and automated accessibility.

Hosted pull-request acceptance, representative owner and screen-reader review,
deployment, restore/PITR, retention execution, and production data approval
remain separate gates.
