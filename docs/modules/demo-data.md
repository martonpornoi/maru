# Synthetic demonstration data

Status: Implemented repository-owned fictional fixture; roster importer removed
Last updated: 2026-08-25

## Purpose and requirements

`maru.demo` provides representative, synthetic data for MARU-FND-005,
MARU-FND-007, IDN-001 through IDN-004, EVT-001 through EVT-005, ARC-001,
ARC-002, UX-004, and the V00-V02 acceptance fixture. It composes public model
and service boundaries for development; it owns no production data.

The application is installed only by local and test settings. The production
settings do not expose its management command.

## Dataset

`seed_demo_data` creates fixture version
`maru-fictional-two-convention-v6`:

- Maru Community Events (Demo), operating MaruCon;
- Maru Arts Collective (Demo), operating MaruDance;
- archived 2025, preparing 2026, and draft 2027 editions per convention;
- one demo administrator and 79 persona accounts;
- organizer governance, convention leadership, operational department leads,
  volunteers, ordinary and sponsor attendees, hosts, dealers and assistants,
  a guest of honour, performer, photographer, invited volunteer, cancelled
  attendee, and former board member;
- three accounts participating across both independent organizer tenants;
- active, invited, and ended memberships;
- completed historical, confirmed or pending current, and interested future
  participation;
- multiple capacities per person with explicit public-history opt-ins for
  selected public roles;
- four legacy authority examples plus ten familiar furry-convention access
  groups per organizer, with organization- or edition-scoped assignments;
- distinct MaruCon and MaruDance registration sections, questions, and products;
- one honest legacy setup control per seeded edition, so the canonical
  Registration page is readable without inventing complete Registration setup and account onboarding provenance,
  source digests, actors, or command receipts;
- two immutable published registration templates;
- reviewed active 2026 full-demo configurations with volunteer, early-bird,
  normal, Infinity supporter, and invited-guest products, plus inherited
  review-required 2027 drafts with source provenance;
- sixteen current-edition registrations on a fresh database, covering every
  lifecycle state: guardian pending, waiting, payment pending, confirmed,
  checked in, expired, and cancelled;
- immutable submitted-answer snapshots, complete edition-owned profiles,
  multiple fursuits, a guardian request, internal staff-only comments, active
  entitlements, an Infinity ticket holder, reviewed profile-extension
  definitions and append-only values, and online check-in;
- directory consent examples and restricted contact, address, age,
  emergency-contact, Telegram, pronoun, language, bio, and fursuit data;
- multiple internal and separately consented public country codes plus
  attendee, volunteer, guest, and Infinity/super-sponsor report labels;
- successful and uncertain hosted-payment examples, authenticated webhook
  evidence, payment exceptions, operational ledger movements, receipts,
  proposed refund, provider fee, settlement, and allocation;
- canonical inbox/email success and failure, preferences, identity recovery,
  session revocation, abuse limiting, organizer restriction and appeal;
- media-safety, privacy-request, historical-correction, retention, and disposal
  evidence;
- one command-backed current Position proposal per organizer, one deliberately
  shared person-owned Availability plan with two edition-local periods, and
  one governed opening-day Shift demand with immutable minimized command
  evidence;
- credential issue/event, relay device, signed offline manifest, offline
  conflict, readiness gates, closure manifest, and archive amendment; and
- authorized lifecycle and configuration transitions with correlated audit,
  domain-event, and outbox records.

The current-edition Workforce examples are seeded before lifecycle progression.
Each fresh Department is created through the Organization structure command
with a deterministic retry key and immutable receipt. Its Position and public
opportunity are created through their governed commands beneath the canonical
edition mutex and active-Department lock, and the Position receives its typed
resource binding. The synthetic chair then proposes a known person through the
governed Assignment command, and the assigned synthetic person deliberately
shares two Availability periods through the owner command. Finally, the chair
creates the opening-day Shift demand and opens it only while it is future work.
These operations produce the same immutable audit, event, outbox, and minimized
receipt evidence as their browser and API adapters.

A rerun replays deterministic Department, Position, opportunity, Assignment,
and Shift evidence and preserves an existing person-owned Availability plan
rather than overwriting later demo exploration. A future fixed-date demand is
opened for suitable claims. Once that date has ended, the fixture preserves an
honest organizer-visible draft instead of manufacturing expired published
work. Complete examples remain verifiable after the edition becomes read-only,
but the fixture refuses to create a missing Position or assignment after
Draft/Preparing. Existing legacy demo Department identifiers and pre-command
Assignment rows are preserved for upgrade compatibility; a current
command-backed proposal is added without inventing historical evidence for the
legacy row.

Every ordinary Maru data model registered under `/admin/` has at least one
deterministic example after seeding. Operational liveness evidence is the
deliberate exception: the fixture never fabricates a
`PlatformInvitationSchedulerRun`, because doing so would make readiness report
a scheduler that has not actually run. The registration detail page is a person-focused
read-only dossier: it renders the actual submitted questions and answers,
account/restriction status, organizer roles and convention capacities,
entitlements and Infinity status, payment totals, internal comments, and links
to all attached registration records. The account detail page summarizes the
same person's organizer-managed relationships and registration history.

Stable UUIDv5 identifiers, slugs, emails, dates, role codes, and capacity codes
make the fixture deterministic across databases. Created and total counts are
emitted as JSON.

## Command and credentials

Run under local settings:

```powershell
uv run python src/manage.py seed_demo_data
```

Sign in to Django admin with `demo.admin@maru.invalid`. Convention-chair
accounts are highlighted in the command output for authorized API exploration.
`marucon.standard-attendee@demo.maru.invalid` is highlighted for the unregistered
MaruCon attendee walkthrough. Use `marucon.convention-chair@demo.maru.invalid`
for configuration and Front Desk views.
The chair can open **Manage access** with Front Desk, Registration, Board,
Treasurer, and the other starter groups already populated. A separate synthetic
Board Chair has approval authority for a two-person sharing rehearsal.
All fixture accounts use the static local-only password
`Z7!maru-demo-fixture-2026` on first creation.

Rerunning is idempotent and does not change passwords. The explicit
`--reset-passwords` option replaces the password verifier only for accounts
whose stable IDs are owned by the fixture, using the same documented default:

```powershell
uv run python src/manage.py seed_demo_data --reset-passwords
```

The optional `--password` argument supports deliberate local test overrides.
The default is intentionally public and must never be reused for any real
account or environment.

## Removed public-roster rehearsal

ADR 0073 removes the former roster parser, external URL, and compatibility
management command. There is no repository-owned command, parser, or supported
adapter that can read a public convention directory into example data.

Use `seed_demo_data` for every local educational journey. It creates only
synthetic `.invalid` identities and establishes active Executive Boards through
the real Representation & access services. **Representation & access**,
is the supported first-authority handoff; the platform administrator is the
operator and never a convention subject.

## Safety and failure behavior

- All email addresses end in `.invalid`; no real provider or personal data is
  used.
- The command refuses any settings module other than `maru.settings.local` or
  `maru.settings.test`.
- Stable identifiers and natural-key checks fail closed when a non-demo record
  collides with a reserved email, organization slug, convention slug, edition
  slug, membership, participation, capacity, role, or assignment.
- The complete load is atomic. A failure cannot leave a partly seeded dataset.
- Existing v6 fixture rows are verified and preserved. No row or volume is
  deleted, and user edits are not silently rewritten. Versions before v6 used
  different convention identities and must not be upgraded in place. Create a
  new disposable local/test database and seed v6; the command fails closed on
  conflicting stable identities or slugs.
- Lifecycle state is advanced through `transition_edition`, preserving its
  authorization, audit, event, outbox, and version behavior. Because archived
  examples and their synthetic readiness/manifest evidence are built in one
  atomic fixture, the local/test-only command temporarily disables the archive
  gate during that construction. It still installs complete deterministic
  readiness and manifest rows before commit; production settings cannot expose
  the command.

The synthetic accounts deliberately share one password for convenient role
exploration. The default is checked into source and
documentation so the demo remains reproducible. That is acceptable only in a
replaceable local/test database and is never a production credential pattern.

## Permission and module boundary

The fixture distinguishes organizational relationships, participation
capacities, and executable authority:

- board oversight is organization-scoped;
- edition directors can view, transition, read minimized participant
  summaries, and the featured Chair has organization-scoped role-management
  and immediate-revocation authority;
- the Board Chair has organization-scoped role-management authority for
  independent sharing approval;
- operations staff can view edition metadata and minimized participant
  summaries;
- volunteers receive edition-scoped basic metadata access; and
- attendees, external hosts, dealers, guests, and performers receive no staff
  authority merely because of their capacity label.

Direct model creation remains explicitly limited to synthetic bootstrap data
for aggregates that still lack audited commands. Department, Position,
opportunity, Assignment, Availability, and Shift examples use their canonical
commands; lifecycle changes use the implemented events service.

## Tests and observability

The integration test runs the command twice and verifies:

- exact tenant, account, edition, role, registration, template, lifecycle,
  profile, section, audit, event, and outbox structure;
- non-empty examples for every Maru model registered in Django admin;
- every registration state, a multiple-role staff account, an Infinity
  entitlement, received-payment ledger evidence, and a staff-only comment;
- report-capable chair/registration-lead accounts and a populated country,
  attendee-level, and badge-export dataset;
- readable registration, submission-answer, and account-history admin
  dossiers;
- representative and overlapping capacities;
- shared identity without tenant collapse;
- an executable edition-director policy decision;
- familiar Convention work access groups, current assignments, exact-person
  display, chair revocation authority, and independent approval authority;
- password authentication;
- deterministic Department, Position, opportunity, Assignment, Availability,
  and Shift command evidence, Organization structure versions, Position
  bindings, and idempotency after the editable lifecycle; and
- refusal under production settings.

The command reports created rows separately from fixture totals. Lifecycle
outbox messages remain pending because the supervised effects worker is not yet
implemented.

## Limitations

Qualifications, programme items, dealer tables, accommodation, cases, assets,
and lost-and-found belong to later vertical slices. The fixture includes the
implemented departments, positions, opportunities, applications, onboarding
agreements, position assignments, person-owned Availability, and governed
Shift demand. It starts with no synthetic claim so a human can rehearse the
person-owned claim and independent organizer decision themselves, and uses
durable capacity codes for other not-yet-implemented domains.
Provider, mail, media, credential, and offline records are intentionally inert
synthetic evidence: `.invalid` hosts, disabled provider accounts, hashed
placeholder tokens, and no reusable secret or real stored image are included.
