# ADR 0075: Govern Position and opportunity management with structure evidence

- Status: Accepted
- Date: 2026-08-23
- Extends: ADRs 0019, 0028, 0041, 0044, 0045, and 0055
- Requirements: HR-007, HR-010, HR-011, HR-012, UX-005 through UX-008,
  UX-012, UX-020, UX-029, AUD-001, AUD-005, INT-001, and NFR-008

## Context

Maru already models organization-owned Position templates, edition-owned
Positions, one volunteer opportunity per Position, exact typed-resource
bindings, onboarding prerequisites, and independently approved assignments.
The bounded Workforce projection can explain the current Department hierarchy,
Position purpose and reporting, approved headcount, and minimized active
holders. Department changes also have one versioned aggregate, strict shared
commands, immutable receipts, audit/outbox evidence, and stopped-writer
PostgreSQL enforcement.

Position and opportunity changes nevertheless remained behind generic Django
model forms. That exposed implementation nouns and let different adapters make
different choices about scope, template/role meaning, opportunity creation,
reporting cycles, concurrency, and administrative rationale. It also sent a
non-staff organizer from the purpose-oriented Workforce journey toward a screen
they could not use. Treating a Position as a standalone CRUD row would weaken
the exact Department/resource scope on which assignment authority depends.

Position creation cannot be detached from its immutable role bundle or typed
resource binding. Opportunity publication must not be confused with accepting
a volunteer or granting access. Position closure must retain applications,
assignments, authority history, and reasons while refusing to orphan current
dependencies. These invariants require one explicit product workflow and one
transaction boundary.

## Decision

### Extend the edition structure aggregate

Position and paired-opportunity mutations use the existing exact-edition
workforce structure aggregate and `workforce.manage_structure` capability.
They do not introduce a page-local access list, a second aggregate version, or
a new broad capability. A manager must also retain
`workforce.view_structure`; authorization occurs before request parsing or
name-bearing lookup.

Every effective mutation advances the aggregate exactly once and atomically
persists:

- the Position and, where applicable, its paired opportunity;
- an immutable command receipt naming the affected Position and directly
  inspectable organizer reason;
- a minimized `workforce.structure.change` audit record; and
- a registered `workforce.structure.changed.v1` event plus outbox message.

Normalized no-ops write none of those records. Position creation is idempotent
through a canonical UUID retry key. HTML and API adapters call the same command
services and use the same optimistic `expected_version` fence.

### Make creation one paired operation

Creation requires one published Position template owned by the organization.
The template's immutable RoleBundle must have valid historical authority
issuance provenance under the transaction lock. The manager selects one active
same-edition Department and an optional current same-edition reporting
Position, then supplies a human-readable title, purpose, bounded headcount, and
reason.

The command atomically creates:

1. a `planned` Position whose code, role bundle, and capacity codes derive from
   the selected template;
2. a private `draft` volunteer opportunity using the Position title and
   purpose as its initial applicant-facing copy; and
3. the exact `workforce.position` resource binding used by narrower authority.

If any row, audit, event, outbox write, or binding fails, the entire operation
rolls back. The legacy post-save opportunity hook remains only for historical
or fixture writers whose Position has no structure-command version; governed
commands create the opportunity explicitly.

The separately controlled legacy empty-organization recovery bootstrap has one
narrow exception to the historical RoleBundle check because no issuance proof
can exist before that one-time authority ceremony. It applies only to an active
platform administrator creating the first `convention-chair` Position at
structure version 1 from the exact template and independently approved
RoleBundle that administrator just created. The exception relaxes only the
pre-existing provenance lookup: the Position, opportunity, binding, version 2
receipt, audit, event, and outbox evidence still use this same command. It is
not exposed by the Position HTML or API adapters.

### Separate immutable meaning from editable operations

After creation, organization, edition, Department, Position template, RoleBundle,
code, capacity-code mapping, creator, and creation version are immutable. A
current Position may replace its title, purpose, approved headcount, and
reporting Position. The reporting graph must remain bounded and acyclic.
Headcount cannot fall below the number of proposed and active assignments.

The paired opportunity has explicit `draft`, `published`, `closed`, and
`withdrawn` states. Draft is private. Publishing may move a `planned` Position
to `open`; it does not create a person relationship, accept an application, or
grant authority. A closed opportunity may be republished while its Position is
current. Withdrawal is final. Application opening and closing timestamps must
form a valid aware interval, and visibility after filling remains explicit.

### Close with retained history

Position closure is one-way and requires the current title exactly plus a
reason. It is refused while any proposed or active assignment, nonclosed direct
report, or current/future Position-scoped CapabilityGrant or RoleAssignment
depends on the Position. Successful closure records actor and time, retains all
related records and identifiers, and closes a paired opportunity unless that
opportunity is already closed or withdrawn. Closed Positions cannot be edited
or reopened.

### Mount one purpose-oriented workflow

The selected-edition Structure area owns **Position management**: a bounded
overview, a creation page, and one Position detail page containing separate
sections for operational details, volunteer-opportunity publication, protected
closure, and newest-first change reasons. The Workforce journey links managers
to this workspace and keeps a read-only in-page Position summary for viewers.
Generic Django Position and VolunteerOpportunity records become
inspection-only.

The HTTP API adds strict closed request objects for create, complete update,
complete opportunity replacement, and closure. Unknown input fails, transport
identifiers remain out of human labels, authorized missing targets use a
name-free `404`, and current-state conflicts use typed `409` problems. The
structure read includes only a fresh `can_manage_positions` action hint; the
destination and every command authorize again.

### Keep assignment, availability, and shifts separate

This decision does not replace the independently approved assignment command,
make the staff-only assignment record form an owner workflow, or weaken
dual-control activation. It does not collect availability or create shifts.
Those remain separate requirements and future purpose-built journeys.

## Consequences

- A non-staff organizer with exact structure authority can manage Position
  meaning and recruitment without entering generic model administration.
- Department and Position changes share one coherent optimistic version and
  one directly inspectable reason history.
- Position scope and future assignment authority cannot drift from the
  immutable template, RoleBundle, Department, or typed resource binding.
- Existing Positions without structure-command versions remain readable and
  may begin governed Position or opportunity history at their first real
  change. Their creation version remains null, and no fake historical receipt
  or actor is backfilled. Production reconciliation fixes inconsistent
  template/role rows before the guard migration proceeds.
- PostgreSQL guards reject direct Position and opportunity writes that lack the
  current aggregate version and exactly one matching immutable receipt.
- Closing a Position may require ending assignments, reports, or authority in
  their owning workflows first. The Position screen explains the conflict but
  does not bypass those boundaries.
- The next Workforce product slice is assignment proposal and independent
  approval. Availability and scheduling remain later domain work.

## Alternatives considered

### Keep generic Django model forms as the management workflow

Rejected because they expose implementation structure, cannot present the full
human journey coherently, and do not provide one shared HTML/API concurrency,
reason, and evidence contract.

### Give Positions a separate aggregate and capability

Rejected because Department placement and reporting are part of the same
edition-owned structure, and a second version could permit internally mixed
reads and conflicting changes. The existing capability catalog already defines
structure management to include Positions and publication settings.

### Create opportunities lazily when organizers publish

Rejected because HR-007 requires one opportunity per Position and lazy creation
would introduce missing-state branches into applications, public discovery,
closure, and recovery. A private draft is truthful and harmless.

### Allow moving a Position to another Department or template

Rejected because either move changes exact authorization scope or immutable
authority meaning. Organizers close the old Position with history and create a
new one instead.

### Implement assignment approval in the same change

Rejected because genuine independent approval requires a separately
authenticated approver journey, prerequisite visibility, step-up and recovery
decisions. Position management should not pretend that selecting another
person in one session proves independent approval.
