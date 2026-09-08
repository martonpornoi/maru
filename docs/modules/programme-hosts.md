# Programme host relationships and availability

Status: dormant owner boundary; no active profile, invitation delivery, UI or API.
Requirements: PRG-005, PRG-006, PRG-008, IDN-014 and NFR-013. Decision:
[ADR 0087](../architecture/decisions/0087-programme-host-confirmation-and-availability.md).

## Human outcome and ownership

An organizer can deliberately invite an existing active, verified person to
host or co-host an accepted or organizer-created Programme item. Only that
person can confirm or decline the invitation, withdraw confirmed hosting, and
save or share availability for that exact item. Proposal authorship, proposal
collaboration and Workforce relationships are not hosting confirmation.

Programme owns four records: `ProgrammeHostRelationship`, immutable
`ProgrammeHostInvitation`, immutable `ProgrammeHostRevision`, and current
`ProgrammeHostAvailabilityWindow`. One relationship is retained per item/person.
There are at most 100 retained relationships per item, 1,000 ordinary revisions
per relationship, and two additional revisions reserved for withdrawing
availability and ending hosting. Reinvitation stops early enough to permit a
fresh response. Limits fail closed, without truncating history or silently
creating a second relationship.

## Public commands

`maru.programme.host_commands` exposes:

- `invite_programme_host(...)`: host-manager authority, explicit person UUID,
  role, host-visible title and briefing, organizer rationale, current item and
  relationship versions. New relationships use expected host version zero.
- `respond_to_programme_host_invitation(...)`: exact person-owned confirm,
  decline or withdrawal, plus the current invitation sequence and versions.
- `remove_programme_host(...)`: independent manager removal of an invited or
  confirmed relationship, with retained rationale. An inactive subject can
  still be removed; an inactive actor cannot issue the command.
- `replace_programme_host_availability(...)`: the confirmed person's complete
  draft, shared or withdrawn availability replacement with optimistic versions.

Declined, withdrawn and removed relationships grant no current hosting
authority. Reinvitation reuses the relationship identity, retains a new explicit
invitation, clears current periods and requires a fresh personal response.
Changing the host/co-host role cannot silently carry previous confirmation.

Commands join the existing Programme actor/edition retry namespace. Same
normalized intent returns only immutable receipt/result identifiers and
historical versions after current active-person, exact-tenant and adoption
proof. It does not require new management authority or grant fresh content
access. A different intent sharing that key conflicts. Correlation is evidence,
not retry identity; normalized role, copy, versions and source channel are intent.

Edition-first, deterministically ordered person locks and the shared item
version serialize competing changes. Current state, revision, Programme receipt,
minimized audit, domain event and outbox commit together. State/version,
authorization, validation or late publication failure rolls back success state.

## Availability and privacy

Availability belongs to the exact item/person purpose. It is never imported
implicitly from Workforce, another item, or a general personal calendar.
Periods are whole-minute, offset-aware, positive half-open intervals, normalized
to UTC. At most 128 non-overlapping periods may lie inside the edition's local
date envelope; adjacency is allowed. Adapters must resolve local input and
reject ambiguous or nonexistent minutes before using this same command.

Unknown, draft, shared and withdrawn remain distinct to the person. Organizers
see unknown, draft and withdrawn as `not_shared`; missing periods are not free
time. A deliberately shared empty set is `unavailable`. Removal, decline,
withdrawal and reinvitation clear current exact periods. Retained revisions
contain only sharing state/version, period count and a digest, not historical
copies of private windows. Own withdrawal can clear availability after edition
planning closes; this does not reopen ordinary planning or manager mutation.

## Independent read ceilings

`maru.programme.host_queries` accepts a `ProgrammeHostReadRequest` carrying
trusted organization, edition and item routing plus actor/audit attribution.
It is not portable authority. Every read resolves current authority and person
state, fences the item snapshot under the edition lock and audits disclosure.

- `load_programme_host_self`: own deliberately visible invitations, title-free
  response history and own current availability. Only a currently confirmed
  host also receives latest approved item copy. No organizer rationale, other
  host, contact, working text, discussion or review is included. Ended history
  grants no later item-copy access.
- `load_programme_host_roster`: `host_roster` ceiling; current relationship and
  person identifiers/currentness and current related-person display labels,
  without contacts, history or availability. Identity resolves labels only after
  Programme authorizes the bounded roster and locks the canonical person set.
  Inactive/unverified people receive a neutral label; a missing expected current
  label makes the read unavailable. Final authorization and read audit precede
  release. Names are current labels, not historical identity snapshots.
- `load_programme_host_history`: separate `host_history` ceiling; one exact
  relationship's retained rationale, actor and versions, never old exact periods.
- `load_programme_host_dependencies`: `shared_host_availability` ceiling;
  versioned `programme.host-dependencies@1` snapshot. Ended, unconfirmed,
  inactive, not-shared, unavailable, outside-edition and shared consequences
  remain explicit. Only current confirmed active persons' deliberately shared,
  in-envelope periods are returned. An ended relationship is not a current
  scheduling requirement.

Organizer commands/reads use independent `programme.manage_hosts` and
`programme.view_hosts` capabilities. Self view, response and availability
capabilities are non-persistable, nondelegable relationship capabilities.
No account directory, account creation or email invitation sender is introduced.

## Readiness and future consumers

Invitation/response/removal advances host-confirmation and schedule-availability
dependency cursors. Availability changes advance only schedule availability.
Configuring a concern after host history begins uses the latest relevant host
revision. Other delivery concerns and approved public copy remain untouched.

Readiness is not automatically satisfied. A retained satisfied host attestation
is projected stale when current host/person proof is absent; availability also
requires deliberately shared non-empty periods inside current edition bounds.
An item requiring no host must explicitly configure the concern not applicable.
This current-state check discloses no host identity or private period in the
readiness summary. It retains one edition snapshot lock in addition to the
existing constant-size non-host readiness query budget.

Later Scheduling consumes the minimized dependency snapshot and must recheck
versions/currentness at its own commit boundary. This contract neither reserves
an occurrence nor checks an already placed timetable, creates Shifts, approves
release, publishes host profiles, or supplies on-site timetable access.

## Installation and verification boundary

Both existing literal profiles still exclude this workflow and its event
destinations. Runtime relations remain SELECT-only, with owner-only integrity
functions. Installation creates no grants or hosting data. See the
[migration and recovery contract](../operations/programme-host-migration-and-recovery.md)
for additive migrations, exact readiness and populated downgrade refusal.
Focused tests are not protected merge acceptance or production readiness.
