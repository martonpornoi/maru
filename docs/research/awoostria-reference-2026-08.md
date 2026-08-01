# Awoostria reference operating model

Status: Public-source product research  
Observed: 2026-08-01

This note translates public Awoostria structure and workflows into product
needs. It is not an authoritative internal organization chart, legal analysis,
or permission to collect public roster data. Department names and workflow
shapes may inform synthetic templates; names, handles, contact details, and
other personal data must not be scraped into Maru accounts, tests, or fixtures.

## Public sources

- [About Awoostria](https://awoostria.at/about-us)
- [Volunteer departments and roles](https://awoostria.at/about-us/our-volunteers)
- [Open positions](https://awoostria.at/open-positions)
- [Venues](https://awoostria.at/attending/venue)
- [Cape 10 venue](https://awoostria.at/attending/venue/cape-10)
- [Contribution catalogue](https://awoostria.at/contribute/forms)
- [Event submission](https://awoostria.at/contribute/forms/event-submission)
- [DJ application](https://awoostria.at/contribute/forms/dj-application)
- [Conbook contributions](https://awoostria.at/contribute/forms/conbook-contributions)
- [Charity performance application](https://awoostria.at/contribute/forms/fursuit-striptease-application)
- [Dealers' Den policy](https://awoostria.at/policies/dealers-den-policy)
- [Art Show policy](https://awoostria.at/policies/artshow)
- [Privacy policy](https://awoostria.at/policies/privacy-policy)
- [Pretalx schedule editor documentation](https://docs.pretalx.org/user/schedule/)
- [Pretalx API schedule resources](https://docs.pretalx.org/api/resources/)

## Structural signal

The public department taxonomy includes Executive Board and Helper Board plus
Art, Charity, Front Desk, Dealers' Den, Decorations, Events & Programming,
Fursuit Support, Human Resources, Graphics Design, IT, Legal & Compliance,
Logistics, Maid Cafe, Multimedia, Social Media, Registration, Security, Stage
Tech, Story, Ceremonies, and PEER.

The site demonstrates multiple leads, deputies, volunteers, and specialized
roles. Some people publicly hold several roles. The product owner has selected
this template hierarchy for the first Maru rehearsal:

- Executive Board is the organization representation root.
- Helper Board is a child of Executive Board.
- Operational departments report beneath Helper Board by default.
- Every department may nest further and have several leads, deputies, and
  volunteers.
- A person may hold several positions in several departments.

The reporting edges are a configurable Maru template, not a claim that the
public website fully specifies Awoostria's internal authority.

## Workflow signal

The public experience currently spans a separate registration portal,
contribution forms, external form links, email/Telegram coordination, payment
providers, hotel booking, and Art Show submission services. Maru should become
the authoritative record for applications, decisions, assignments, messages,
schedule, evidence, and audit while initially treating delivery and commercial
systems as replaceable adapters.

A single edition visibly has distinct application families:

- community event or panel;
- DJ set;
- performance, competition, or charity show;
- conbook contribution;
- dealer application;
- Art Show submission;
- volunteer position;
- future Maid Cafe and department-specific services.

These processes share forms, revisions, deadlines, review, decisions,
conversations, files, and audit. They differ in eligibility, cardinality,
review, allocation, payments, safety/content policy, and the typed domain record
created after acceptance. They must not be implemented as additional attendee
registrations or one undifferentiated response spreadsheet.

The venue pages show more than one operating site, including a secondary site
described as a short walk from the main hotel. Venue planning therefore needs
travel-time constraints, multiple properties, atomic rooms, and mergeable
space configurations rather than one flat room list.

## Pretalx lessons

Pretalx offers valuable concepts to retain:

- proposals, tracks and reviews;
- room and speaker availability;
- visual room/time scheduling;
- conflict warnings;
- work-in-progress schedules;
- immutable named releases and public API resources.

Maru's differentiator is the convention work envelope and shared operational
layers. A placement separates preparation, effective event time, and teardown;
the preceding teardown may overlap the following preparation in one room while
people, equipment, composite spaces and hard availability remain protected.
Stage Tech, Security, Logistics, staffing, Multimedia, accessibility and other
departments add purpose-scoped layers without cloning the programme item.

## Privacy and visibility signal

Public, signed-in/ticketed, internal, department-confidential, restricted, and
financial/identity-restricted renditions are distinct. The public attendee and
fursuiter experiences indicate ticket and opt-in boundaries rather than a
single “public/private” switch. Page access summaries must not reveal a
restricted membership or case subject to someone who cannot see it.

The Awoostria privacy policy describes identity, contact/address, account,
purchase and usage data and participant rights. Maru must attach purpose,
classification, access policy, retention, export and deletion behavior to
fields and documents; this research note does not determine the lawful basis or
retention period for the organizer.

## Product implications

Build shared primitives once:

- account, organization relationship, edition participation and registration;
- nested departments, positions and time-bounded authority;
- typed applications, forms, reviews and conversations;
- venue spaces, combinations, availability and travel;
- programme items, schedule versions, layers and releases;
- shift demand, availability, commitment and handover;
- documents, policies, versions, acknowledgements and retention;
- storage locations, containers, boxes, assets, stock and movement manifests;
- audit, outbox, stable API projections and replaceable connectors.

Department pages are minimized views of these connected records. They are not
separate applications with duplicated identity, permissions, comments, files,
or history.
