# Event operations landscape

Research date: 2026-07-26  
Purpose: Product discovery, not vendor endorsement

This is a public-source survey of convention and event tooling. Marketing claims
are treated as claims; public documentation and repositories are used to
understand capabilities and operating patterns.

## Furry convention evidence

### Eurofurence

Eurofurence's [public repositories](https://github.com/eurofurence) show separate
identity, registration, dealer, fursuit, volunteer, signage, mobile, and backend
systems in several languages. Its current [staffing
page](https://www.eurofurence.org/EF30/jobs) describes Art Show, ConOps, Info
Desk, lockers, stage, logistics, awareness and inclusion, security, fursuit
support, dealer management, and the Critter shift system.

The [contact center](https://help.eurofurence.org/contact/artshow/application)
exposes the breadth of requests crossing departments: event submissions,
technical equipment, art applications, fursuit help, security concerns,
medical or psychological context, awareness support, logistics deliveries, and
volunteering.

The [accessibility
page](https://www.eurofurence.org/EF30/accessibility) documents accessible
seating, priority access, flashing-light information, mobility support, quiet
and awareness assistance, and coordination among staff, security, and Info
Desk.

The [charity intake](https://charity.eurofurence.org/) shows that a donated item
may be evaluated, bundled, and routed to auction, Art Show, or lottery. This is a
custody and disposition workflow, not simply a donation form.

### NordicFuzzCon

NordicFuzzCon's [registration
terms](https://nordicfuzzcon.org/policies/terms-and-conditions) include payment
deadlines, hotel products, room movement, ticket transfers, badge numbers, ID
matching, and cross-border payment methods.

Its [recruitment portal](https://portal.nordicfuzzcon.org/Recruitment) shows
Dealers' Den and Artist Alley, attendee experience spaces, fursuit activities,
live messages, games, and pre-convention design and construction work. The
[Maid Café workflow](https://nordicfuzzcon.org/sign-up/maid-cafe) explicitly
needs volunteer shifts planned around programme items people want to attend.

The official mobile app provides schedule, maps, dealers, staff, feedback,
achievements, and convention activities, showing how attendee content and
engagement currently become another surface beside registration.

### ConFuzzled

ConFuzzled's [department contact
list](https://confuzzled.org.uk/contact-us/) includes Registration, Convention
Operations, lost and found, Dealers' Den, Art Auction, Events, Fursuit,
Medical, HR, and directors, with separate email queues.

Its [residential registration
description](https://confuzzled.org.uk/2024/08/07/registration-2025/) covers
room-space products, multiple hotels, roomshare partners, early arrival, late
departure, payment deadlines, accessible rooms, and a fairness lottery. Earlier
documentation explains that first-come allocation sold out in minutes and
disadvantaged people with connectivity, work, or longer forms.

The [fire-alarm follow-up](https://confuzzled.org.uk/2024/11/28/fire-alarm-investigation/)
shows why event data and safety planning connect: attendees with accessibility
needs require personal evacuation planning and communication between
Registration, venue, and responders.

### Awoostria

Awoostria's [open positions](https://awoostria.at/open-positions) include panel
room coordination, Dealers' Den, fursuit support, software, dance competition,
and stage lighting. Its department description covers fursuit water, lounges
and lockers, stage technology, charity, IT, and Front Office merchandise.

The [dealer policy](https://2024.awoostria.at/policies/dealers-den-policy.html)
shows assistants, waiting lists, table custody, power requirements, product and
adult-content rules, safety, and edition registration dependencies.

## Specialist systems

### Programme: pretalx

pretalx provides:

- proposals and configurable questions;
- phased and permission-separated
  [reviews](https://docs.pretalx.org/user/review/);
- speaker availability and a versioned, conflict-aware
  [schedule](https://docs.pretalx.org/user/schedule/);
- release comparison and speaker notifications;
- email templates and a reviewable
  [outbox](https://docs.pretalx.org/user/emails/);
- organizer, event, team, submission, person, and schedule module boundaries
  documented in its [architecture](https://docs.pretalx.org/developer/architecture/structure/);
- a broad, permission-aware API.

Important lesson: versioned publication, review separation, organizer/event
scope, and editable outbox are proven patterns worth retaining.

### Ticketing and access: pretix

pretix documents:

- organizer teams and event-spanning
  [reports](https://pretix.eu/about/en/features/admin);
- products, shared quotas, check-in rules, and
  [capacity](https://docs.pretix.eu/guides/products/);
- invitation and quota-reserving
  [vouchers](https://docs.pretix.eu/guides/vouchers/);
- ticket shop, payment, onsite, check-in, and administration stages;
- customer accounts and self-hosted operation.

Its event-series guidance recommends separate singular events for annual
conferences, reinforcing Maru's independently archived edition model.

### Volunteer shifts: Engelsystem

[Engelsystem](https://github.com/engelsystem/engelsystem) is a long-running
open-source shift planning system for Chaos events and is the basis of
Eurofurence's Critter system. Its endurance validates self-service shifts,
qualifications, work logs, and event-specific volunteer operations as a
separate serious domain.

### Convention-wide suites

[Convention Master](https://civetsolutions.com/home) combines registration,
onsite ticketing, kiosks, accounts payable, ConOps, dealers, art auction, badge
printing, analytics, and offline operation.

[Conicler](https://eventforge.io/) markets an integrated flow among
registration, badges, programme, volunteer shifts, mobile schedule, resources,
communications, food service, and analytics. Whether or not its individual
claims are adopted, the product positioning is evidence that disconnected
tools and per-ticket costs are recognized pain.

## Professional event-production patterns

Current event-operations products repeatedly emphasize capabilities often
missing from convention software:

- [Eventication](https://eventication.com/): crew onboarding, accreditation,
  zones, stock assignment, suppliers, and rewards;
- [Cadence](https://cadenceops.app/event-production-software): crew call sheets,
  qualifications, gear, loads, vehicles, run sheets, riders, contracts, and
  compliance;
- [PlanOS](https://www.getplanos.com/): filtered vendor call sheets, run-of-show,
  contracts, floor plans, team context, and offline day-of access;
- [Run of Show](https://www.runofshowapp.com/): staff schedule, live timeline,
  tasks, automation, and in-app collaboration;
- [Smartsheet](https://www.smartsheet.com/content/event-planning-software):
  milestones, dependencies, budgets, vendor deliverables, logistics, forms,
  dashboards, and approvals.

The shared insight is that onsite success depends on production, logistics,
finance, suppliers, credentials, and readiness long before a public schedule
exists.

## Repeated failure modes

### Humans become middleware

People copy an accepted application into registration, a schedule into a mobile
app, a room move into signage, a staff list into badge printing, and a purchase
into finance. Every copy can become stale.

### Channels become databases

Decisions, exceptions, and ownership live in personal email and Telegram
threads. New staff cannot search the history safely, and departing staff take
context with them.

### Status has no evidence

Department traffic-light reports are manually optimistic. Dependencies and
acceptance criteria remain implicit until setup.

### Forms create dead-end records

A Google Form may collect data but does not own review, questions, deadlines,
approvals, payment, scheduling, access, or archival meaning.

### Live operation is a different system

Planning tools often stop at publication. During the event, staff fall back to
radio, chat, paper, and memory because tools do not provide a time-aware
operational view.

### Annual duplication preserves mistakes

Copying last year's spreadsheet or portal settings carries stale owners,
prices, permissions, suppliers, and assumptions into the new edition.

### Integration increases account count

Buying a suite of separate products can improve data movement while leaving
participants with many accounts and inconsistent permission models.

## Product conclusions for Maru

1. The fundamental unit is an independently archived event edition inside a
   lasting organization.
2. The most valuable global feature is a personal action center, not a module
   menu.
3. The most valuable director feature is an evidence-based readiness and live
   command model.
4. Messaging must attach to operational objects and team ownership.
5. Programme, shifts, production, venue, and run-of-show require one time and
   resource model with different projections.
6. Hotels, roomshares, fursuits, adult-content boundaries, art, charity, and
   community care are first-class furry-convention domains.
7. Offline and reconciliation are product requirements, not deployment details.
8. Professional event practices—budgets, contracts, assets, call sheets,
   accreditation, suppliers, and safety evidence—must join attendee-facing
   convention features.
9. Reuse must be selective, reviewed, and versioned.
10. Maru should integrate regulated or commodity specialists while keeping one
    user journey and one source of operational truth.
