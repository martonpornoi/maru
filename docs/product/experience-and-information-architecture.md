# Experience and information architecture

Status: Page 1 platform administration home mounted; broader model preserved as
page-by-page backlog
Last updated: 2026-07-31

## Current executable experience

ADR 0030 established the two-page baseline. ADR 0031 restores the first
reviewed page:

1. Sign in at `/accounts/login/`.
2. An authenticated, active-platform-administrator-only organization inventory
   at `/admin/`.

The home shows the signed-in identity, POST-only sign-out, organization name,
slug, lifecycle, series count, and edition count. Its zero-record state names
the next page without presenting an unfinished action. It explains that the
administrator operates Maru but does not participate in a convention. It has
no global menu, edition selector, setup sequence, Django model directory,
embedded application, registration, volunteer, or convention-owned operational
content. `/` redirects to `/admin/`; previous HTML routes return 404. Health
and versioned APIs remain mounted as backend contracts.

Every later page requires UX-013's page contract and product-owner inspection
before another page begins. Preserved source does not make a page current.

## Preserved target model

The material below remains product evidence and a possible future direction,
not a description of currently mounted pages. Maru is one platform expressed
through focused surfaces and must not become one enormous menu containing every
department's nouns.

## Experience model

```text
One identity and notification center
|
+-- My Maru             personal participation and actions
+-- Administration      setup, specialist records, access, and operations
+-- Now Mode            live, time-critical execution
+-- Public Experience   programme, information, registration, content
+-- Focused clients     check-in, kiosk, signage, scanner, relay
```

All surfaces use the same domain APIs, authorization decisions, messages,
published schedule, and activity trail. A focused client is not a separate
account or source of truth.

## Platform identity and annual themes

Maru's stable operational shell uses the owned navy, gold, and ivory identity
documented in [`platform-brand.md`](platform-brand.md). The same identity
connects Convention work, specialist records, local account entry, and the
bundled public reference client without implying that every convention must
look alike.

An annual convention website is a replaceable client. Its team may change
artwork, color, layout, interaction, and editorial presentation while
consuming the same versioned APIs. It must preserve accessible semantics and
cannot override Maru's authorization, availability, price, capacity, payment,
or lifecycle decisions. Edition artwork is convention content, not a mutation
of the platform identity.

## Public registration

The local entry page offers `Register for a convention` without requiring an
account first. The registration surface follows a short, explicit journey:

```text
choose an open convention
  -> sign in or create an account
  -> choose admission
  -> complete fixed identity/contact fields and convention-defined sections
  -> review the edition-owned profile and operational status
```

A returning attendee sees their registrations separately from other open
conventions and deliberately selects the next edition. The newest earlier
same-organization profile may appear as a clearly labeled, editable suggestion.
Submitting it creates a new edition snapshot; older profiles and convention
answers remain unchanged, and public-list consent is never carried forward.

The bundled form is a neutral reference and fallback client. A convention may
replace its artwork, page structure, animation, and seasonal theme by consuming
the versioned public registration definition. Maru remains authoritative for
opening times, eligibility, price, capacity, required answers, reservations,
waitlists, and payment state; a frontend cannot grant itself a discounted or
paid outcome.

The submitted profile separates restricted identity/contact data, structured
pronouns and languages, optional bio/profile image, optional multiple fursuits,
convention-defined answers, and authoritative roles or benefits. New images
remain private for review; an unchanged approved file may be reused within its
owner and organizer boundary. Volunteer departments derive from assigned
capacities and ticket-holder labels derive from entitlements.

A separate public attendee list includes only confirmed or checked-in people
who consented for that edition. Its HTML and JSON renditions expose only
display name, pronouns, bio, spoken languages, fursuit name/species, approved
images, an optional separately entered public country, and broad authoritative
attendee/volunteer/sponsor/guest labels. Status is written as text with color
as a redundant cue. The list disappears when the edition is archived or
cancelled; legal/contact/emergency/product/price/payment data never enters it.

## Global context

The persistent context switcher shows:

`Organization / Convention series / Event edition / Surface`

The edition name, state, local time, and live/draft/archive status remain
visible. Switching context never silently broadens access. Links carry durable
resource identity and resolve safely for authorized viewers.

Archived editions are visually distinct and read-only by default. A correction
requires a separate, reasoned action rather than an ordinary edit button.

The implemented `/admin/` shell and its embedded Convention work preserve an
explicitly selected event edition. Edition-owned lists, details, counts, normal
relationship choices, and new-record defaults follow that context. Specialist
records also offer `All foundation data` for first-time platform setup.
Cross-edition reuse appears only in purpose-named workflows such as
registration template or source-edition selection; it never silently mixes
routine operational rows.

The original `/admin/` home keeps the complete alphabetical directory for
returning operators. ADR 0027 removes the former global Quick Start strip.
Organization, series, edition, Chair identity, guarded first authority,
registration, workforce, and readiness guidance is contextual inside
Convention work's **Setup guide**. An eligible workspace-less superuser
completes the password-confirmed, exact-scope-confirmed leadership ceremony
there; after completion it becomes a read-only explanation rather than a
permanent action. The guide is not a readiness checklist and ordinary
navigation never grants access or marks work complete.

The canonical `/admin/` shell has one collapsible sidebar with Convention work
and Specialist records sections. The embedded workflows do not render another
global navigation or workspace selector; their headings, modules, fields,
tables, buttons, and responsive spacing follow the same language as specialist
record pages. Convention work's Today page keeps published form-driven
workflows in a separate Forms section rather than scattering registration,
volunteer applications, and onboarding documents through unrelated menus.
Existing model pages remain inside the same `/admin/` hierarchy and use the
same sidebar. `/manage/`, `/staff/`, and `/admin/records/` are removed rather
than redirected. Setup guide also presents the current edition lifecycle,
valid next states, consequences, reason entry, and stronger confirmation for
terminal transitions; registration opening remains separate.

## My Maru

The personal surface belongs to the user, not to one department.

### Home

- Next best action
- Deadlines and blockers
- Upcoming schedule and reporting locations
- Unread direct or official messages
- Material changes requiring acknowledgement
- Registration, application, order, and onboarding status
- Quick access to pass or check-in credential

### Events

- Current and upcoming editions
- Invitations and incomplete applications
- Past participation and opted-in achievements
- Receipts, certificates, and permitted retained documents

### My schedule

Programme interests, shifts, host appearances, rehearsals, setup, travel,
breaks, and private calendar blocks appear together with clear visibility
labels. Maru explains conflicts and never publishes a private calendar entry.

### Inbox

Direct conversations, application and service threads, department messages,
official notices, and mentions use one inbox with filters and notification
preferences. Promotional content cannot masquerade as an operational notice.

### Profile and privacy

Global identity attributes, organizer-specific relationships, edition answers,
public profile, emergency or accommodation data, consents, linked identities,
sessions, exports, and deletion requests are visibly separated.

## Administration and Convention work

The original administration shell provides one collapsible global menu:

- **Convention work:** Today, People, Organization structure, My registration,
  Registration, Reports & badges, Setup guide, Security history, and Manage
  access; and
- **Specialist records:** the complete permission-filtered Django record
  directory, with its existing model routes.

Convention work is embedded inside this shell. The Django header provides
edition context and account actions without a second menu or duplicated
selector. Modules may
register actions, search providers, dashboard cards, and permission
requirements without creating another global navigation.

### Access sharing

Every active Convention work page offers **Manage access** only when the
operator holds role-management authority in the selected edition. The same
entry is present in the administration sidebar. The sharing workspace resembles
familiar collaboration tools while retaining Maru's stronger invariants:

- a person is exact-matched by an existing active account email and shown by
  display name plus email;
- familiar groups such as Front Desk, Registration, Board, Treasurer, and
  department roles are immutable scoped role bundles, not Django Groups;
- current page context may recommend groups but never creates a page-local ACL;
- add and change require a reason, optional expiry, and distinct authorized
  approver;
- change is an atomic revoke-and-reassign operation;
- removal is immediate, reasoned, and available only with revocation authority;
  and
- names, labels, slugs, and references lead the UI while UUIDs remain internal
  transport identities unless exact technical evidence is necessary.

Sharing a group grants system capabilities only. A formal volunteer or staff
appointment still uses the workforce position workflow so NDA evidence,
headcount, reporting hierarchy, capacities, and official convention role
remain connected.

The implemented Reports destination starts with one purpose-built
registration preset: attendance totals, country and attendee-level
breakdowns, a badge-data preview, and a minimized CSV export. It is edition
scoped, capability gated, audited, filterable, and explicit about excluded
private fields. It is the first role-oriented report, not yet the general
saved-question/query-builder experience.

### Page orientation

Every active page places one short purpose statement directly below its main
title. It says why the page is useful, what can be done there, and gives one or
two concrete examples. The same guidance remains present in empty, denied, and
failure states so a user is not left to infer the page's purpose from controls
or implementation terminology.

### Department cockpit

Each department receives the same structural view:

- current readiness and evidence;
- assigned and unowned work;
- people and coverage;
- inbox and service level;
- schedule and dependencies;
- spaces, assets, and budget position;
- risks, decisions, changes, and live issues; and
- handover and post-event work.

Domain-specific cards may extend the cockpit without creating a second home
page.

### Object workspace

Opening a person, session, shift, order, case, room, asset, or project presents:

1. identity and current state;
2. important actions;
3. role-specific summary;
4. details grouped by purpose;
5. relationships and dependencies;
6. conversation;
7. files and generated artifacts; and
8. authorized activity timeline.

A side context panel lets an operator inspect a related object without losing
the list, filters, selection, or scroll position.

## Search, query, and command

The command palette supports navigation and permitted actions. Global search
uses human identifiers, aliases, fuzzy matching, and typed results. It never
leaks the existence of unauthorized objects through counts, suggestions, or
timing where practical.

Operational lists share:

- query chips and an explainable natural-language summary;
- visible column and sensitivity metadata;
- saved and shareable views;
- bulk selection across pages with explicit scope;
- preview and undo for reversible bulk actions;
- background execution for large operations; and
- deep links that preserve context.

Natural-language assistance may propose a query but cannot bypass the safe
field catalog or authorization policy.

## Now Mode

Now Mode is an edition-wide operational projection optimized for time pressure,
touch use, unstable connectivity, and rapid handover.

### Personal Now

- current and next assignment;
- check-in or acknowledgement;
- exact place and route hint;
- concise briefing and attachments;
- duty contact and escalation;
- affected changes; and
- `I need help`, `I am delayed`, and `Cannot attend` actions.

### Department Now

- staffed posts and gaps;
- active work queue;
- rooms, assets, and dependencies;
- service demand and ageing;
- live issues, changes, and handover notes; and
- next 30, 60, and 180 minutes.

### Event command

- common operational picture;
- material alerts and accepted risks;
- programme and venue deviations;
- capacity and queue signals;
- welfare and accessibility tasks without overexposure;
- public communication state;
- decision log;
- incident command roles; and
- degraded-mode and recovery status.

Now Mode must avoid decorative dashboards. Every signal identifies its source,
age, owner, consequence, and available action.

## Attention model

Maru uses a common attention object rather than module-specific notification
noise.

| Level | Meaning | Delivery expectation |
| --- | --- | --- |
| FYI | Useful context, no action | Inbox or digest |
| Action | The recipient owns a next step | Action center and chosen reminder |
| Blocking | Another commitment cannot proceed | Prominent to owner and dependency |
| Urgent | Time-sensitive operational harm | Immediate configured channels |
| Emergency | Life safety or major incident protocol | Predefined command procedure |

Urgency is a permissioned action. It expires, may require acknowledgement, and
is audited. Users can tune optional notifications but cannot accidentally mute
properly authorized emergency channels.

## Change impact and publication

Before applying a material change, Maru previews:

- affected people and roles;
- schedule, room, resource, and staffing conflicts;
- public and internal views that will change;
- signage, calendar, API, print, and external-channel consequences;
- acknowledgements or approvals required; and
- integrations currently unable to receive the update.

The operator may revise, schedule, publish, or cancel the change set. Emergency
authority can accelerate the flow while retaining the evidence trail.

## Responsive and accessible interaction

- WCAG 2.2 AA is a release criterion, including staff interfaces.
- Complete keyboard operation is required for high-volume desk workflows.
- Touch targets and contrast support poor light and hurried on-site use.
- Status is never communicated only by color.
- Times always show edition time zone when ambiguity is possible.
- Tables have compact and comfortable density settings.
- Draft input survives navigation and recoverable network failure.
- Essential tasks work at 200% zoom and on a narrow mobile screen.
- Motion is optional and never carries operational meaning alone.

## Speed budgets

With representative edition data and warm application caches:

- navigation shell feedback: within 100 ms;
- common filtered list response: p95 under 500 ms server time;
- object workspace useful content: p75 under 1.5 seconds on supported networks;
- typeahead first useful results: p95 under 300 ms server time;
- local acknowledgement in Now Mode: immediate, with sync state visible; and
- expensive export or planning work: asynchronous with progress and safe retry.

Budgets are targets for validation, not promises that justify hiding failure.

## Avoiding clicking hell

- Put the next permitted actions beside the state they change.
- Keep the previous result set and context after an action.
- Permit inline changes when validation and consequences are local.
- Use reusable command and bulk-action patterns.
- Pre-fill known, purpose-compatible data and explain its source.
- Turn validation errors into linked actions.
- Make ownership transfer one explicit operation.
- Use defaults inherited from reviewed edition templates.
- Prefer one composite workflow over a chain of unrelated CRUD pages.

## Customization boundary

Organizers may configure terminology, fields, pipelines, forms, views,
templates, automation, and brand. They may not configure away tenant isolation,
audit, accessibility semantics, historical integrity, or core lifecycle
invariants.
