# ADR 0117: Standalone announcements with reviewed manual publication

- Status: Accepted
- Date: 2026-10-09
- Extends: ADRs 0003, 0031, 0080 and 0116
- Requirements: ANN-001, ANN-003 through ANN-005, ANN-007 through ANN-009,
  IDN-002, IDN-005, IDN-009, IDN-012, IDN-014, EVT-006, UX-031 and NFR-013

## Context

A convention may already publish through its website, social accounts and chat
channels. Its immediate problem is keeping the approved text, translations,
publication reports and corrections together. Adopting that workflow must not
require moving attendee registration, volunteer management or the timetable.
The architecture assigns canonical announcements to a dedicated module. Existing
Communications is a recipient-specific service inbox and delivery projection;
its records are not an authoring or approval aggregate.

## Decision

### Keep one owner and an explicit adoption boundary

Introduce `maru.announcements` for settings, canonical text, immutable versions,
channel/language variants, review decisions, manual publication reports,
corrections and portable outputs. Other modules use its documented commands,
queries and domain events. Do not import Scheduling's private notice machinery
or stretch Communications messages into announcement records.

`announcements_only@1` contains Announcements and the required Identity,
Organizations, Events, Authorization, Audit, Effects and Privacy foundations.
It creates no Participation, Registration, payment, attendance, Workforce,
Programme or recipient notification records. Effects records minimized domain
facts; no external delivery handler is adopted. Existing exact-version profiles
remain unchanged, including `full_convention@1`.

A new `announcements_operators` representation and immutable
`announcements-operators@1` root describe responsibility for this purpose. They
use the existing two-person invitation, independent self-acceptance, activation,
provenance, containment and recovery controls. Existing Maru operators remain
Workforce operators; their representation and authority are not silently widened.
Existing Executive Board organizations keep their truthful representation.
Platform oversight never makes a platform administrator a convention participant.

Guided setup creates or reuses only the necessary organization, convention series
and event edition. Selecting a person, reviewer or destination never grants access.
Edition-scoped capabilities separate viewing, composing, reviewing, recording
publication, settings management and private evidence export. Current authorization
and the exact adopted profile are checked before private reads and every mutation,
including retries and downloads. Scope selectors and navigation grant no authority.

### Review the exact copy, then report what happened elsewhere

The human journey is **Write announcement -> Request review -> Copy approved text
-> Record publication -> Make a correction -> Download**. A different authorized
person must approve the exact version, including its language and channel variants.
Every person who edited that draft counts as an author for this decision. Saves,
requested changes and resubmission do not reset authorship. A new correction round
starts only from an independently approved version; this lets two operators swap
writer/reviewer roles for later corrections they did not both edit. Even
platform or root authority cannot approve its own text. Review comments remain
private. There is no ordinary-review bypass.

Content versions and decisions are immutable. Changed text needs a fresh review;
a stale decision cannot approve a newer version. A correction under preparation
does not pretend the last approved text has disappeared. Once approved, changed
channel copy shows that an update is needed. Unchanged copy does not manufacture
an additional external publication obligation.

Writing status and publication evidence are separate. A copy, print or download
never publishes anything. A publication report records the reporting person,
report time, claimed publication time, exact approved copy and optional safe post
link. It is an organizer's claim, not provider verification or audience receipt.
A mistaken report is corrected with append-only evidence and a reason. Cancelling
remaining work or stopping use never claims external posts were removed. New writing
and review stop, but authorized operators can still report earlier publication of
approved copy and correct retained reports. Older report corrections never replace
a newer publication status.

### Make configuration understandable and truthful

Everyday pages show the event, writing status, required choices, review boundaries,
errors and channel tasks. Technical identifiers, versions and retry details are
secondary disclosures. No destination is silently selected; no translation or
shortening happens without explicit authored copy. Event language may be selected
automatically only when the event has one configured language.

Before new content is collected, an authorized organizer records the applicable
record-keeping rules in readable terms, their owner and review date, and confirms
that they cover copy, private review notes, publication reports and exports.
The exact settings version and actual confirmation are retained. Draft saves bind
the settings the writer saw, so a changed configuration requires a fresh decision;
an exact authorized retry still recovers its original outcome. Maru records that
confirmation; it does not invent a legal basis, retention period or policy approval.
This bounded workflow does not introduce a general privacy-policy engine or claim
that merely recording a rule executes disposal. Deployment requires the real
organizational policy and its accountable review.

### Preserve portability, failure and recovery

Plain text can be copied into a draft and reviewed before use; no bulk importer or
automatic identity matching is implied. Approved-copy downloads contain only the
selected approved public text and its channel/language meaning. Private handover
exports require separate authority and retain version relationships, decisions,
publication reports and a format/integrity manifest. Print and manual channel
handoff remain usable without JavaScript or provider availability.

Commands use closed inputs, bounded data, optimistic versions, idempotency with
changed-payload rejection, canonical locking and atomic receipt/audit/domain-event
evidence. PostgreSQL enforces scope, immutable history, allowed transitions and
evidence links. Runtime permissions and readiness include only the reviewed new
relations and functions. The additive v5 runtime helper closure preserves frozen
v4 and admits only the two new Announcements-operator assertion helpers; it grants
no new DDL, deletion or cutover authority. Recovery supports unused migration reversal and refuses
to discard durable announcement evidence; used installations fix forward or restore
a mutually consistent database. Stopping new work preserves independently
authorized historical reads and exports under the applicable retention rules.

Automatic sending, scheduling, emergency overrides, private audiences, images,
provider credentials and recipient acknowledgements remain future increments.
Their absence cannot be presented as completed ANN-002, ANN-003 scheduling/emergency
behavior, or ANN-006 targeting. This decision does not activate Programme #48.

## Consequences

A small convention team can adopt one complete manual publishing workflow and keep
its existing external channels. Two authorized people can write, review and record
publication without also becoming attendees or volunteers. Independent review and
honest publication evidence add deliberate actions; clear labels explain why.

The native schema, authority setup and exact profile are a substantial part of this
vertical slice. They are necessary to make standalone adoption real. Automated
checks and assistant-operated browser journeys do not replace independent human
comprehension, specialist accessibility or a deploying team's operational acceptance.

## Alternatives considered

- Reuse the recipient inbox aggregate: rejected because authoring and channel-copy
  approval have different ownership and disclosure contracts.
- Add Announcements to existing profile versions: rejected because catalog growth
  must not change an edition's accepted adoption boundary.
- Treat copying as publication: rejected because Maru cannot observe that external
  act. Provider adapters can add separate evidence in a later explicit increment.
- Require users to invent technical policy-version codes: rejected. Record the
  actual organizational rules with readable labels and retain internal versions.
- Build every channel adapter first: rejected because reviewed manual handoff solves
  a complete bounded need without credentials, provider limits or hidden delivery.
