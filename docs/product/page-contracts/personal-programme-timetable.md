# My hosting and work timetable

- Status: Accepted dormant component contract; #99 implementation in progress.
- Requirements: SCH-006, SCH-010, SCH-012, HR-014, HR-015, UX-007, UX-008,
  UX-013, UX-029, NFR-001, NFR-002, NFR-013.
- Decision: [ADR 0097](../../architecture/decisions/0097-release-derived-programme-output-boundaries.md).
- Dormant route: `/my/<organization_id>/<edition_id>/timetable/`. No production
  include, profile activation or navigation destination is added by this contract.

## Purpose and authority

An authenticated person reads their own approved hosting presence and retained
work together, in the existing My Maru shell, and obtains a complete freshly
checked print-friendly, JSON or calendar copy. There is no other-person selector,
planner grant substitution, public-payload enrichment or attendee dependency.
Each adopted owner authorizes and audits again. An unadopted layer is different
from an empty adopted layer; an adopted but unavailable layer fails closed.

The page has one H1, the shared shell's one main landmark, My Maru breadcrumbs
and computed exact-self Access explanation. Scope identifiers and the edition
time zone remain inspectable. Human-readable edition context must be supplied
through an owning module's minimized reference, not private model imports or
unconditional disclosure of a guessed edition's metadata.

## Content and states

The chronological agenda distinguishes approved required host presence from
surrounding preparation, delivery and teardown context. Hosting invitations and
retained declined/removed/withdrawn relationships without an approved time are
separate records, not commitments inserted into the agenda. Own invitation copy
is private; it does not become reviewed public copy.

Claims are visibly tentative. Confirmed work retains its accepted interval.
Removed/completed work is visibly historical, never attendance. Work briefing,
location, department, position and supervision are labelled current instructions
with their version, not an immutable accepted location or automatic relocation.

Release state, check time and time zone remain immediately visible. Exact source
identities, versions and saved-copy limitations use native disclosures, retained
in print even when closed. Withdrawn/invalidated hosting removes prior presence
and room details while preserving authorized work; the combined calendar is
withheld with HTTP 409 and recovery guidance. JSON and print retain known state.

Denied/foreign/unadopted scope returns uniform 404 without source details.
Malformed, repeated or unknown query arguments return generic 400 without echo.
Incomplete, changing or oversized sources return 503 without a partial timetable.
Anonymous requests use the existing sign-in flow; no source query precedes login.
Only GET/HEAD is accepted. Every format is complete, freshly authorized, bounded,
no-store and safely escaped. Downloads have fixed filenames and explicit MIME
types. Saved copies are private snapshots, not offline continuity guarantees.

## Interaction and acceptance

Use ordinary links and native disclosures, wrapping agenda cards, explicit dates
and UTC offsets. There are no mutations, pointer-only controls, modals or custom
animation. Print hides shell/navigation controls but retains all private work,
hosting, provenance and freshness meaning. Users invoke native printing.

Test real exact-person authorization, each layer independently, fresh downloads,
negative source states, hostile content, complete bounds and route dormancy.
Rehearse narrow/intermediate/wide layouts and keyboard operation. Browser-native
200% zoom, screen-reader and on-site comprehension checks remain separate #92
human acceptance; automated component evidence is not activation permission.
