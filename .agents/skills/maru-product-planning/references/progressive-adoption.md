# Progressive modular adoption

Maru earns trust by running one bounded workflow reliably before asking a
convention to replace the rest of its infrastructure. Partial adoption is a
supported product mode, not a temporary installation mistake.

## Foundation versus adopted capability

Every adoption profile declares the smallest trustworthy shared foundation it
needs: platform identity, organization and edition scope, authorization,
audit, recovery, export, and any genuinely required communication or storage
service. A shared foundation does not imply that Registration, payments,
Programme, Workforce, Communications, or another product module is adopted.

For each profile, define:

- enabled tasks, navigation destinations, roles, and account purposes;
- records and side effects that may be created;
- integrations, imports, exports, print artifacts, and manual fallbacks;
- degraded behavior, observability, recovery, and data-removal boundaries;
- what remains authoritative outside Maru;
- the explicit action and evidence needed to add the next module.

Unadopted modules create no records, navigation, authority, notifications,
payment obligations, registration state, or hidden operational dependency.

## Complete workflows before breadth

A bounded profile must work end to end, including setup, ordinary operation,
exceptions, history, export, and recovery. Useful first proofs include:

- **Workforce only:** structure, Positions, Assignments, Availability, Shifts,
  and later check-in/work records without attendee Registration or payments;
- **Programme only:** host intake plus organizer-created core events, internal
  planning notes, timetable operation, and publication/export without making
  Maru the attendee portal;
- **Communications only:** canonical approved content, channel variants,
  images, copy packages, delivery evidence, and manual fallbacks for providers
  without a suitable API;
- **Charity auction only:** item intake, bidder-purpose accounts, printable bid
  sheets and tables, label/plotter output, bids, reprints, closeout, and export
  without unrelated convention participation;
- **Registration without payments:** registration status may remain external,
  imported, or deliberately absent when the organizer does not authorize Maru
  to collect or reconcile money.

These are acceptance recipes, not promises that every workflow already exists.
Check current requirements and implementation status before describing one as
available.

## Purpose-bounded identity

One platform account may support several relationships, but creating a bidder,
host, volunteer, organizer, or communications account does not silently make
that person an attendee, payer, member, employee, or participant in another
module. Collect only data justified by the adopted purpose and expose broader
sharing as an explicit person- or organizer-owned action.

## Coexistence and exit

Treat incumbent infrastructure as a normal integration boundary. Prefer
preview-first import, reconciliation, portable export, printable operation,
and observable manual handoff over a forced big-bang cutover. A convention must
be able to stop using one module, recover its records, and understand retained
audit or legal evidence without making unrelated Maru capabilities unusable.

Evaluate every proposal with one question: **Could a cautious decision maker
adopt this as Maru's only workflow, operate it reliably, and understand exactly
what did and did not change?**
