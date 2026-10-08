# What is Maru?

**Audience:** Product evaluators and new contributors\
**Outcome:** Understand Maru's purpose, users, and deliberate boundaries\
**Reading time:** 5 minutes

Maru is open-source operations software being built primarily for furry
conventions. It connects the work of volunteers, programme teams, department
leads, and organizers across recurring event editions. Other community
conventions can use the same foundations.

A room change can affect the programme, volunteer shifts, equipment, signs,
and announcements. Next year's team needs to understand what happened and why.
Maru's aim is to keep those relationships clear without requiring people to
reconstruct them from unrelated forms, spreadsheets, and chat history.

## Begin with one workflow

A convention should be able to use Maru for one complete job while keeping its
existing systems. Volunteer coordination, for example, should not require
moving attendee registration or payments into Maru. A host or volunteer account
must not silently make that person an attendee or collect unrelated data.

That principle guides the architecture; it is not a claim that every proposed
workflow is ready. The [maturity guide](current-maturity.md) distinguishes
current exploration paths from future scope.

## Who it serves

- **Volunteers and staff** need clear assignments, shifts, handovers, and
  explanations of what they can see or change.
- **Programme teams and hosts** need proposals, room and time planning,
  conflict explanations, publication, and usable on-site outputs.
- **Department leads and organizers** need accountable decisions, readiness,
  capacity, and history that survives team turnover.
- **Attendees and other participants** need clear status, relevant information,
  and privacy-respecting relationships with each organizer.
- **Technical operators and contributors** need documented boundaries,
  observable failures, stable APIs, and recovery procedures.

Furry convention needs include dealer and artist workflows, fursuit facilities,
charity activities, and age/content boundaries. These appear in the
[requirements](../product/requirements.md); their presence there describes
product intent, not a promise that each is implemented.

## The design

Maru uses Django and PostgreSQL as a modular monolith. Each module owns its
data and exposes documented commands, queries, and events. Authorization is
deny-by-default and scoped by organizer, event edition, role, object, and field
where needed. One account does not give every organizer access to that person's
information.

Imports, portable exports, printable fallbacks, and explicit stop-use boundaries
make gradual adoption and coexistence with other tools possible. External
providers remain adapters; they do not become Maru's source of truth.

Maru does not aim to become a social network, an unstructured chat replacement,
a statutory accounting system, or an opaque automated decision maker. The
[product vision](../product/vision.md) and [capability map](../product/capability-map.md)
explain the longer-term scope.

**Next:** [Learn what works today](current-maturity.md).
