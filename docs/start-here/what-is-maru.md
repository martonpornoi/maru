# What is Maru?

**Audience:** Product evaluators and new contributors\
**Outcome:** Understand Maru's promise, users, and deliberate boundaries\
**Reading time:** 5 minutes

Maru is intended to be the calm operating system for recurring community
conventions. It gives attendees and organizers one trusted place to understand
what they need to do, what changed, who owns a decision, and what they may see
or change.

Maru treats an event as an interconnected operating system rather than a set of
unrelated forms. Registration affects entitlements; staffing affects access and
schedules; programme changes affect rooms, equipment, signs, and
communications; decisions and outcomes remain understandable after the event.

## Who it serves

- **Attendees and participants** need one account, clear status, relevant
  messages, a personal schedule, and privacy-respecting history.
- **Volunteers and staff** need role-aware work, training, assignments,
  handovers, and safe escalation.
- **Department leads and directors** need ownership, dependencies, readiness,
  capacity, risk, and durable decisions.
- **Technical operators** need one authorization vocabulary, observable jobs,
  stable APIs, recovery procedures, and explicit module ownership.

## The design in one paragraph

Maru is a Django and PostgreSQL modular monolith. Its modules own their data and
communicate through documented commands, queries, and events. Authorization is
deny-by-default and scoped by organization, event edition, Department, object,
and field where needed. External providers remain adapters instead of becoming
the source of truth.

## Deliberate boundaries

Maru does not aim to become a social network, an unstructured chat replacement,
a statutory accounting system, or an opaque automated decision maker. It
integrates specialist services when rebuilding them would add risk without
improving the convention journey.

For more depth, read the [product vision](../product/vision.md), then consult
the [capability map](../product/capability-map.md) only when you need the full
product horizon.

**Next:** [Learn what works today](current-maturity.md).
