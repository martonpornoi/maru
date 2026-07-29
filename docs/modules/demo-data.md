# Synthetic demonstration data

Status: Implemented local-development support  
Last updated: 2026-07-29

## Purpose and requirements

`maru.demo` provides representative, synthetic data for MARU-FND-005,
MARU-FND-007, IDN-001 through IDN-004, EVT-001 through EVT-005, ARC-001,
ARC-002, UX-004, and the V00-V02 acceptance fixture. It composes public model
and service boundaries for development; it owns no production data.

The application is installed only by local and test settings. The production
settings do not expose its management command.

## Dataset

`seed_demo_data` creates fixture version
`maru-synthetic-two-convention-v5`:

- Pannon Paws Foundation (Demo), operating Danube Furry Convention;
- Northern Tails Association (Demo), operating Aurora Tails;
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
- four immutable role-bundle versions per organizer and organization- or
  edition-scoped assignments; and
- distinct Danube and Aurora registration sections, questions, and products;
- two immutable published registration templates;
- reviewed active 2026 full-demo configurations with volunteer, early-bird,
  normal, Infinity supporter, and invited-guest products, plus inherited
  review-required 2027 drafts with source provenance;
- sixteen current-edition registrations on a fresh database, covering every
  lifecycle state: guardian pending, waiting, payment pending, confirmed,
  checked in, expired, and cancelled;
- immutable submitted-answer snapshots, complete edition-owned profiles,
  multiple fursuits, a guardian request, internal staff-only comments, active
  entitlements, an Infinity ticket holder, and online check-in;
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
- credential issue/event, relay device, signed offline manifest, offline
  conflict, readiness gates, closure manifest, and archive amendment; and
- authorized lifecycle and configuration transitions with correlated audit,
  domain-event, and outbox records.

Every Maru model registered under `/admin/` has at least one deterministic
example after seeding. The registration detail page is a person-focused
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
`danube.standard-attendee@demo.maru.invalid` is highlighted for the unregistered
Danube attendee walkthrough. Use `danube.convention-chair@demo.maru.invalid`
for configuration and Front Desk views.
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

## Safety and failure behavior

- All email addresses end in `.invalid`; no real provider or personal data is
  used.
- The command refuses any settings module other than `maru.settings.local` or
  `maru.settings.test`.
- Stable identifiers and natural-key checks fail closed when a non-demo record
  collides with a reserved email, organization slug, convention slug, edition
  slug, membership, participation, capacity, role, or assignment.
- The complete load is atomic. A failure cannot leave a partly seeded dataset.
- Existing fixture rows are verified and preserved. No row or volume is
  deleted, and user edits are not silently rewritten. Upgrading an older
  fixture adds new v5 records without repurposing an existing registration or
  rewriting its historical state. V5 enriches only untouched synthetic
  current-profile defaults with varied reporting countries and the new
  consent-version/public-country example.
- Lifecycle state is advanced only through `transition_edition`, preserving its
  authorization, audit, event, outbox, version, and archive behavior.

The synthetic accounts deliberately share one password for convenient role
exploration. The default is checked into source and
documentation so the demo remains reproducible. That is acceptable only in a
replaceable local/test database and is never a production credential pattern.

## Permission and module boundary

The fixture distinguishes organizational relationships, participation
capacities, and executable authority:

- board oversight is organization-scoped;
- edition directors can view, transition, and read minimized participant
  summaries for their assigned editions;
- operations staff can view edition metadata and minimized participant
  summaries;
- volunteers receive edition-scoped basic metadata access; and
- attendees, external hosts, dealers, guests, and performers receive no staff
  authority merely because of their capacity label.

Direct model creation remains explicitly limited to synthetic bootstrap data
while V02 lacks audited creation commands for these aggregates. Lifecycle
changes use the implemented application service.

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
- password authentication;
- idempotency; and
- refusal under production settings.

The command reports created rows separately from fixture totals. Lifecycle
outbox messages remain pending because the supervised effects worker is not yet
implemented.

## Limitations

Departments, positions, applications, onboarding, shifts, programme items,
dealer tables, accommodation, cases, assets, and lost-and-found belong to later
vertical slices. The fixture uses durable capacity codes and summaries for
those not-yet-implemented domains. Provider, mail, media, credential, and
offline records are intentionally inert synthetic evidence: `.invalid` hosts,
disabled provider accounts, hashed placeholder tokens, and no reusable secret
or real stored image are included.
