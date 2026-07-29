# Capability map

Status: Product blueprint  
Last updated: 2026-07-26

This map defines the complete product horizon. It is deliberately broader than
the first implementation. Capabilities are delivered through prioritized
vertical slices, not by scaffolding every module at once.

Priority:

- **Spine:** Required for safe operation of every other capability.
- **Core:** Expected by a professional convention platform.
- **Specialist:** Important to particular departments or event models.
- **Frontier:** Differentiating capability built after trustworthy core data.

## Platform spine

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Identity and account recovery | Spine | One secure account and understandable account history |
| Organizations, series, editions | Spine | Multiple conventions with explicit tenant and year scope |
| Capability-based authorization | Spine | Least privilege by organization, edition, department, object, and field |
| Personal action center | Spine | One inbox for tasks, approvals, payments, forms, messages, and acknowledgements |
| Audit and operational timeline | Spine | Explain who did what, why, and what changed |
| Configurable forms and workflows | Spine | Convention-specific policy without bespoke code for every field |
| Files and document versions | Spine | Contextual documents with classification, expiry, and approval |
| Search and safe query studio | Spine | Authorized staff can answer real questions without SQL |
| Jobs, outbox, notifications | Spine | Reliable slow work and external delivery |
| Import, export, and data quality | Spine | Controlled migration and usable PDF/XLSX/CSV/iCalendar outputs |
| Edition archive and carry-forward | Spine | Accurate history and safer annual reuse |
| Localization, time, currency | Spine | European and international operation |

## Governance and annual planning

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Edition charter and success measures | Core | Shared mandate and measurable outcomes |
| Work breakdown, tasks, milestones | Core | Owners, deadlines, dependencies, and evidence |
| Readiness graph | Core | Honest view of what can prevent opening |
| Risk, issue, decision, action logs | Core | Traceable governance rather than meeting folklore |
| Department and service catalog | Core | Clear ownership, opening hours, dependencies, and escalation |
| Meeting agendas and decisions | Specialist | Decisions become linked actions, not lost minutes |
| Template and checklist library | Core | Reusable but reviewed operating practice |
| Retrospectives and lessons | Core | Learning carries into the next edition |
| Scenario comparison | Frontier | Compare venue, date, capacity, budget, and service options |

## People, HR, and workforce

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Staff and volunteer applications | Core | Structured recruitment and fair review |
| Interview and selection workflow | Core | Ownership, evidence, and consistent decisions |
| Onboarding and offboarding | Core | Training, agreements, access, equipment, and clear progress |
| Organization and edition roles | Core | Current responsibility and historical service |
| Skills, qualifications, certifications | Core | Safe matching and expiry alerts |
| Availability and workload preferences | Core | Better assignments and healthier schedules |
| Workforce demand planning | Core | Departments state required coverage before asking for volunteers |
| Shift marketplace and assignment | Core | Suitable choices, waitlists, swaps, and lead control |
| Check-in, time records, breaks | Core | Reliable coverage and recognition |
| Welfare and fatigue protections | Core | Maximum hours, rest, late-night and accessibility constraints |
| Training sessions and knowledge checks | Specialist | Demonstrable readiness for safety-critical roles |
| Staff benefits, meals, lodging, rewards | Specialist | Entitlements tied to actual policy and service |
| Alumni and portable achievements | Frontier | Consented history without cross-convention surveillance |
| Succession and handover | Core | Role knowledge survives staff turnover |

## Registration, identity verification, and access

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Products, tiers, add-ons, entitlements | Core | Flexible attendance and sponsor offerings |
| Registration workflow and screening | Core | Clear status, exceptions, deadlines, and self-service |
| Fair queue, lottery, quotas, waitlists | Core | Defensible allocation under high demand |
| Orders, payment, refund, transfer | Core | Transactionally safe commerce |
| Badge art and identity presentation | Specialist | Personalized furry-convention credentials |
| Identity and age verification | Core | Record verification outcome without unnecessary document retention |
| Badge design and printing | Core | Versioned templates, reprints, printer health, and audit |
| Check-in and access control | Core | Fast validation, zones, anti-passback rules where justified |
| Day tickets and time entitlements | Core | Correct access by date, time, area, and role |
| Accreditation | Specialist | Crew, press, supplier, guest, dealer, performer, and backstage access |
| Capacity and queue operations | Core | Safe, observable admissions and room access |
| Offline registration desk | Core | Continue critical service during venue network failure |

## Lodging, travel, and hospitality

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Hotel and room inventory | Specialist | Room types, nights, blocks, accessible attributes, and availability |
| Lodging lottery and priorities | Specialist | Fair allocation with explainable policy |
| Roomshare groups and matching | Specialist | Consent-based roommate coordination and complete occupancy |
| Early arrival and late departure | Specialist | Correct nightly inventory and entitlements |
| Accessible-room allocation | Specialist | Restricted, respectful, policy-driven handling |
| Party room and special-space booking | Specialist | Eligibility, lotteries, deposits, agreements, and schedule |
| Guest and performer travel | Specialist | Itineraries, arrivals, transfers, documents, and responsible host |
| Shuttle and transport planning | Specialist | Routes, capacities, drivers, passengers, and live changes |
| Hospitality and green rooms | Specialist | Access, dietary needs, stocking, and service schedule |
| Visa and invitation support | Specialist | Controlled documents and progress tracking |

## Programme and participant management

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Calls and custom submissions | Core | Panels, meetups, shows, games, performances, and special formats |
| Co-host invitations and profiles | Core | Shared ownership without duplicated applications |
| Blinded and phased review | Core | Configurable fair selection |
| Conflict and similarity review | Specialist | Detect duplicate or overlapping programme |
| Acceptance, confirmation, withdrawal | Core | Explicit commitments and deadlines |
| Technical and accessibility requirements | Core | Requirements reach the right production and venue owners |
| Session resources and releases | Core | Slides, media, consent, content warnings, and public assets |
| Rehearsal and soundcheck planning | Specialist | Production readiness connected to the schedule |
| Feedback and attendance signals | Specialist | Useful learning with privacy limits |
| Personal calendar and favorites | Core | Attendees and hosts understand their own convention |

## Scheduling and run-of-show

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Versioned schedule editor | Core | Draft, compare, approve, release, and roll back |
| Multi-resource constraint engine | Core | People, rooms, equipment, access, capacity, and travel constraints |
| Programme, shift, and operational projections | Core | One time model, many views |
| Cross-department dependency view | Core | Setup, security, stage, logistics, and host handoffs are visible |
| Venue and room timeline | Core | Complete use and turnover picture |
| Personal commitment view | Core | No hidden collision between attendance and volunteer duties |
| Call sheets and filtered run sheets | Specialist | Each team sees only relevant timed actions |
| Live cue execution | Specialist | Ready, standby, go, complete, skipped, delayed, and notes |
| Schedule change impact preview | Frontier | Show affected people, signs, shifts, resources, and messages before publish |
| Assisted schedule suggestions | Frontier | Explainable options that respect hard and soft constraints |

## Venue, production, and logistics

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Venue model, maps, rooms, zones | Core | Shared spatial source of truth |
| Floor plans and layouts | Specialist | Tables, queues, accessibility, seating, power, and safety overlays |
| Assets, stock, kits, and custody | Core | Know what exists, where it is, who has it, and when it returns |
| Warehouses and storage | Specialist | Cross-edition inventory and movement history |
| Purchase and rental requests | Core | Need, approval, order, delivery, and return are connected |
| Suppliers and call times | Core | External parties get scoped portals and correct instructions |
| Deliveries, loading docks, vehicles | Specialist | Booked movements and chain of custody |
| Radios, keys, devices, credentials | Core | Issue, return, damage, replacement, and responsible person |
| Maintenance and facility requests | Core | Route venue issues with location, severity, owner, and status |
| Setup and teardown checklists | Core | Sequenced work with dependencies and evidence |
| Network, printer, scanner, signage health | Core | IT sees operational status, not just server uptime |

## Finance, procurement, and commercial operations

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Edition and department budgets | Core | Baseline, forecast, actual, commitment, and variance |
| Approval limits and purchase requests | Core | Fast but accountable spending |
| Supplier quotes and contracts | Specialist | Comparison, deliverables, expiry, and ownership |
| Expenses and reimbursements | Core | Receipt, policy, approval, payment export, and status |
| Invoices, tax evidence, credit notes | Core | Correct operational records and accounting handoff |
| Cash and point-of-sale reconciliation | Specialist | Floats, devices, shifts, totals, and discrepancies |
| Sponsorship pipeline | Specialist | Prospects, tiers, agreements, assets, and payments |
| Sponsor deliverables | Specialist | Logos, booths, mentions, tickets, deadlines, and proof |
| Department financial dashboard | Core | Leads see commitments and remaining authority |
| Accounting export and reconciliation | Core | Integrate with statutory accounting rather than recreate it |

## Dealers, artists, charity, and merchandise

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Reusable vendor profile and portfolio | Specialist | Less repeated data with per-edition consent |
| Dealer and Artist Alley applications | Specialist | Juried review, categories, waitlists, assistants, and fees |
| Table and hall planning | Specialist | Layout, power, access, adjacency, content zone, and capacity |
| Dealer load-in/out and support | Specialist | Call times, credentials, issues, and handover |
| Art Show intake and hanging | Specialist | Artist, piece, medium, price, content class, location, and custody |
| Charity donation intake | Specialist | Selection, bundling, destination, valuation, and donor history |
| Auction and lottery operations | Specialist | Bidders, lots, bids, settlement, collection, and reconciliation |
| Merchandise catalogue and pre-order | Specialist | Variants, quantities, entitlements, and fulfilment |
| On-site inventory and fulfilment | Specialist | Pick, collect, exchange, spoilage, and closing counts |
| Commission pickup and handoff | Frontier | Controlled artist-to-attendee delivery without ad hoc messages |

## Furry-specific attendee experience

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Fursuit profile and optional badges | Specialist | Suit identity, badge art, visibility, and owner privacy |
| Fursuit lounge operations | Specialist | Opening, staffing, water, drying, supplies, lockers, and incidents |
| Headless lounge and restricted access | Specialist | Privacy-respecting locations and entitlement |
| Fursuit parade and group photos | Specialist | Registration, lineup, staging, route, handlers, and media |
| Dance and performance competitions | Specialist | Audition, music, consent, rehearsal, bracket, judging, and results |
| Fursuit first aid and repair requests | Specialist | Triage, supplies, queue, and safe handoff |
| Adult-content zoning | Specialist | Age/access rules for dealers, art, programme, and publication |
| Themed quests and live activities | Specialist | Story, checkpoints, capacity, progress, rewards, and accessibility |
| Quiet, sensory, and social spaces | Specialist | Hours, capacity, supplies, incidents, and discoverability |
| Community memorial and recognition | Specialist | Consented, carefully governed remembrance and credits |
| Virtual/VR participation | Frontier | Linked remote programme and identity where an edition supports it |

## Safety, accessibility, and care

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Safety plan and emergency procedures | Core | Versioned plans, owners, training, and distribution |
| On-call and escalation matrix | Core | Find the responsible person now |
| Incident and welfare cases | Core | Restricted intake, triage, handoff, evidence, and follow-up |
| Medical information boundary | Core | Minimum necessary data and strict access separation |
| Awareness and inclusion support | Core | Trusted requests, quiet-room support, accessibility barriers |
| Personal emergency evacuation plans | Specialist | Individual planning shared only with responders who need it |
| Accessibility requests | Core | Request, assessment, fulfilment, communication, and feedback |
| Event accessibility metadata | Core | Mobility, sensory, lighting, sound, language, seating, and content notes |
| Queue and priority accommodation | Specialist | Discreet entitlement and operational handling |
| Safeguarding and minors | Specialist | Guardian, consent, age policy, restricted roles, and response process |
| Policy acknowledgement and waivers | Core | Version, signature, scope, and evidence |
| Emergency broadcast | Core | Authorized, multi-channel, acknowledgement-aware alerts |

## Communication, content, and service

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Team inbox and contextual threads | Core | Durable professional communication |
| Contact center and request routing | Core | One front door with categories, SLA, ownership, and escalation |
| Knowledge base and policies | Core | Versioned answers linked to forms and workflows |
| Canonical announcements | Core | Compose, approve, target, schedule, publish, and audit once |
| Email, push, web, social adapters | Core | Channel delivery without separate content truth |
| Communication calendar | Core | Campaign ownership, collisions, embargoes, and deadlines |
| Translation and localization workflow | Core | Source, review, locale completeness, and publication |
| Content management | Core | Website, app, signage, help, and public API from structured content |
| Media and press accreditation | Specialist | Application, access, releases, embargoes, and contacts |
| Photo and recording consent | Specialist | Policy, event-specific choices, authorized use, and takedown workflow |
| Feedback and surveys | Core | Contextual, low-friction input linked to improvement actions |
| Crisis communication workspace | Specialist | Facts, approval, audiences, holding statements, and update log |

## Live command and attendee service

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Now mode | Core | Time-aware personal and departmental operating view |
| Event command center | Core | Shared live status, risks, incidents, capacity, and changes |
| Front Desk 360 view | Core | Minimum necessary answer and safe action in one screen |
| Operations request dispatch | Core | Location, urgency, owner, ETA, resolution, and requester feedback |
| Lost and found | Core | Description, custody, match, claimant verification, and disposal |
| Room and service status | Core | Open, delayed, full, moved, closed, and reason |
| Queue and capacity signals | Specialist | Admission decisions and attendee guidance |
| Live handover log | Core | Shift changes preserve active issues and accountable ownership |
| Emergency and degraded mode | Core | Clear behavior when integrations or network fail |
| Director log | Specialist | Timestamped decisions and facts during significant situations |

## Reporting, learning, and intelligence

| Capability | Priority | Product outcome |
| --- | --- | --- |
| Role-specific dashboards | Core | Immediate answers for each department |
| Saved query and report studio | Core | Reusable questions with permission-aware fields |
| Year-over-year comparison | Core | Trends with changed definitions made visible |
| Data quality dashboard | Core | Duplicates, missing owners, stale states, impossible dates, broken links |
| Forecasting | Frontier | Capacity, sales, staffing, inventory, and workload outlook |
| Readiness and dependency analysis | Core | Find the work most likely to block opening |
| Change impact analysis | Frontier | Preview downstream effects before commitment |
| Scenario and contingency simulation | Frontier | Explore room loss, demand surge, staff absence, or weather disruption |
| Natural-language query assistant | Frontier | Explain and build safe queries within the caller's permissions |
| Inbox and handover summarization | Frontier | Reduce reading while linking every claim to source records |
| Recommendation assistant | Frontier | Suggest, never silently decide, staffing and schedule options |
| Post-event narrative | Frontier | Evidence-linked operational report and lessons draft |

## Integration and extension

| Capability | Priority | Product outcome |
| --- | --- | --- |
| OIDC identity integration | Spine | Secure login and future client support |
| Payment adapters | Core | PSP-managed card data and verified webhooks |
| Mail and push adapters | Core | Observable delivery and suppression |
| Social publishing adapters | Core | Channel-specific delivery and health |
| Calendar and schedule feeds | Core | iCalendar, public API, and subscriptions |
| Accounting adapters | Core | Journal-ready handoff and reconciliation |
| Storage and antivirus adapters | Core | Safe files without platform lock-in |
| Webhooks and service accounts | Core | Supported external automation |
| Hardware/edge bridge | Specialist | Printers, scanners, kiosks, and offline relay |
| Extension SDK and marketplace | Frontier | Scoped third-party capability without core forks |
| Import migration kits | Core | Move from spreadsheets and incumbent tools safely |

## The differentiators organizers would notice

### One action center

Every payment, application question, policy acknowledgement, training item,
message, approval, shift, document, and deadline appears in one prioritized
place. It is the strongest antidote to app hell.

### The readiness graph

Maru knows that “badge print test” depends on approved design, current attendee
data, working printer profiles, stock arrival, and trained operators. It shows
the blocking dependency instead of five green department percentages.

### The operational time machine

Authorized users can ask what the plan, assignment, access rule, room, price, or
announcement was at a particular time. This supports incident review,
reconciliation, and historical understanding.

### Change impact before publish

Before moving a show, Maru identifies affected hosts, shifts, stage cues,
equipment, access, signs, print divergence, personal schedules, and queued
communications.

### A professional handover

Roles have responsibilities, recurring tasks, active risks, owned records,
knowledge, access, equipment, and pending conversations. Handover is generated
from live context and accepted by the successor.

### Portable participation without portable surveillance

People may reuse a profile, portfolio, qualifications, accessibility
preferences, and history through explicit sharing. Organizers receive only the
edition-specific data and evidence they are entitled to.

### Maru Relay

A limited local edge node keeps check-in, badge printing, essential schedule,
signage, and operational contacts available when venue connectivity degrades,
then reconciles with traceable conflict rules.

### Rehearsal mode

Teams can run a synthetic event clock, inject a room closure, printer failure,
missing volunteer, delayed delivery, or emergency message, and evaluate whether
plans and permissions work before attendees arrive.

## What Maru should not become

- a generic social feed;
- an unstructured Slack clone;
- a full statutory accounting system;
- a graphical floor-plan editor before basic venue data works;
- an opaque AI decision maker;
- a workflow engine so generic that nobody understands the data;
- a mandatory mobile installation for accessing essential information;
- a platform that measures volunteers to punish them;
- a giant administrator role used to bypass thoughtful authorization.
