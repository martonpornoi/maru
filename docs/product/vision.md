# Product vision

Status: Baseline  
Last updated: 2026-08-26

## The promise

Maru is the calm operating system for recurring community conventions.

It gives every person one trusted place to answer:

- What do I need to do next?
- Where do I need to be?
- What changed?
- Who owns this?
- Are we ready?
- Who needs to know?
- What happened last year?
- What am I allowed to see or change?

For attendees, Maru feels like one convention relationship rather than a maze of
ticket shops, forms, inboxes, schedules, chat groups, and apps. For organizers,
it is one operational picture from the first venue discussion through the final
archive and lessons learned.

## Product thesis

Annual events are not a collection of independent forms. They are a temporal,
interdependent system:

- a registration grants entitlements;
- entitlements affect access, lodging, merchandise, and communications;
- staff roles affect permissions, training, shifts, meals, and accreditation;
- programme decisions affect rooms, stage requirements, signage, staffing, and
  attendee notifications;
- supplier delays affect logistics, budgets, readiness, and run-of-show;
- live incidents affect rooms, schedules, access, and announcements;
- closing decisions affect finance, retention, volunteer recognition, and next
  year's plan.

Maru succeeds when those relationships are explicit and useful. It fails if it
merely places unrelated tools behind one menu.

## Design doctrine

### One platform, many purpose-built surfaces

One login and one data model do not require one enormous interface. Attendee
web, administration, mobile, kiosk, signage, and on-site relay are projections of
the same authorized source of truth.

### Earn trust through progressive adoption

An organization may begin with one complete workflow that solves a current
problem: Workforce, programme and event submissions, communications, a charity
auction, or registration without payments. Maru must coexist with incumbent
systems and provide the imports, exports, print paths, manual fallbacks, and
clear boundaries needed to make that first adoption reversible and credible.

Using one capability must not silently enable another. A volunteer, event host,
bidder, or communications operator account does not imply attendance,
registration, a purchase, payment tracking, or unrelated data collection.
Cross-module benefits appear only when the organization deliberately adopts the
next workflow. Reliability earns that expansion; product architecture must not
demand it upfront.

### One source of truth, not one point of failure

Important state is canonical in Maru, but critical on-site workflows have
controlled offline or degraded modes, reconciliation, printable fallbacks, and
tested recovery.

### Action before storage

The interface should lead with decisions, work, exceptions, deadlines, and
changes. A database browser with attractive cards is not an operations product.

### Context travels with work

A message, task, approval, file, expense, schedule change, and audit entry
should be attached to the event and object they concern. Staff should not have
to reconstruct context from chat history.

### Configure policy, preserve domain meaning

Organizers need configurable forms, workflows, labels, permissions, and
templates. Core concepts remain typed and documented. Maru will not turn every
domain object into an unsearchable generic JSON record.

### Calm communication

Maru reduces notification volume through relevance, priority, digests,
acknowledgement, escalation, and clear ownership. It does not reproduce noisy
group chat inside a new application.

### Human authority remains visible

Automation may prepare, detect, recommend, route, remind, summarize, and
simulate. High-impact actions such as refunds, access revocation, HR decisions,
incident disclosure, or public emergency announcements retain accountable human
approval.

### Privacy is a boundary, not a banner

One account must not become universal staff visibility. Data is separated by
organizer, edition, purpose, resource, field, and retention class.

### History is a product

An annual event learns only if decisions, configurations, outcomes, and
participation survive staff turnover in an understandable form.

## Anti-app-hell test

A new capability may enter Maru only if it satisfies these rules:

1. It uses the platform identity and permission model.
2. It does not ask for data Maru already has without a justified fresh consent
   or verification need.
3. It links actions, conversations, and files to their operational context.
4. It participates in global search, personal action center, audit, reporting,
   and archive where appropriate.
5. It exposes relevant changes to dependent modules rather than requiring manual
   copy and paste.
6. It defines degraded behavior and export or portability.
7. It can be hidden when an organizer does not use it.
8. It can be the organization's only adopted Maru workflow without creating
   records, navigation, authority, notifications, or dependencies in unrelated
   capabilities.

An external specialist service may remain behind an adapter when recreating it
would add risk without improving the user journey. Users should still encounter
one coherent Maru workflow wherever possible.

## Outcomes

### For attendees and participants

- one account and one action center;
- clear registration, lodging, payment, application, and badge state;
- one personal timetable containing programme and commitments;
- self-service changes where policy permits;
- relevant, non-duplicated announcements;
- private, portable participation history;
- transparent privacy and communication controls.

### For volunteers and staff

- a role-aware work queue and personal run sheet;
- no need to monitor dozens of groups to discover assignments;
- accessible training, policies, contacts, and escalation paths;
- conflict-aware shifts that protect rest and convention enjoyment;
- simple handover when ownership changes;
- recognition based on reliable work records rather than memory.

### For department leads

- staffing demand, coverage, qualifications, and gaps;
- deadlines, dependencies, risks, budgets, requests, and readiness evidence;
- team inbox and domain-linked decision history;
- controlled bulk operations and safe delegation;
- live view of what is late, blocked, changed, or at risk.

### For directors

- an honest readiness graph rather than optimistic status meetings;
- organization-wide risk, budget, capacity, safety, and delivery signals;
- change impact before publication;
- incident command and live operational awareness;
- comparable year-over-year outcomes and preserved institutional knowledge.

### For IT

- one identity plane, permission model, audit vocabulary, API, and integration
  health view;
- fewer fragile exports and one-off databases;
- replayable delivery, observable jobs, and documented ownership;
- a modular system that can evolve without becoming a distributed maze.

## North-star experience

When a programme session moves rooms during the convention:

1. The planner sees conflicts and downstream impact before confirming.
2. Stage, room, accessibility, signage, volunteer, and host owners are shown.
3. The authorized planner publishes one versioned change.
4. Affected personal schedules, venue views, signs, call sheets, and public APIs
   update from the same record.
5. Relevant people receive one appropriate notification, not five duplicates.
6. Delivery failures and acknowledgements are visible.
7. The previous state, decision, reason, and actor remain in history.

That is the standard every cross-module workflow should aim for.

## Boundaries

Maru should replace operational spreadsheets, disconnected forms, duplicate
portals, fragmented status tracking, and contextless department email.

Maru should integrate rather than casually replace:

- regulated payment processing;
- statutory accounting and payroll;
- commodity file/object storage;
- identity assurance providers;
- emergency-service radio and life-safety systems;
- specialist creative tools;
- general video conferencing.

The goal is not to own every technology. The goal is that organizers and
participants no longer serve as the integration layer.
