# Guided Programme call workspace

- Status: Dedicated dormant #108 surface; no production route or profile activation
- Reserved route: `/admin/applications/programme-calls/<organization>/<edition>/<department>/`
- Call task: the same route followed by `<call>/<task>/`
- Requirements: IDN-014, PRG-001, PRG-002, PRG-008, PRG-009, PRG-011,
  AUD-001, AUD-003, PRI-001, UX-005 through UX-008, UX-019, UX-020,
  UX-027, UX-029 and NFR-013
- Decisions: ADRs 0051, 0082, 0084, 0085 and 0100

## Purpose and authority

Give the exact Department's call editor a labelled call inventory, complete
configuration preview and small explicit editing tasks. Applications owns every
query and command. The existing typed form engine, immutable graph validation,
call aggregate cursor and dedicated receipt namespace remain authoritative.
This is not the generic Applications definition studio or a second form engine.

`applications.manage_programme_calls` must admit the current verified person
at the exact current Department, organization and edition. Context, hierarchy,
Programme item access and Workforce structure access do not substitute. The
Department name comes from a minimized Workforce reference only after exact
Applications authorization, with reauthorization and required protected-read
audit before disclosure. No holders, other Departments, proposals, answers,
contributor values, invitation data, review counts or decision history are loaded.

## Bounded increments

The initial workspace increment provides selection among the complete bounded
Department call list, read-only complete configuration, metadata/policy edits,
explicit deadline replacement, track/format/contributor-field catalog tasks,
and deliberate lifecycle actions. Creation, section/question/condition controls,
cross-Department selection and reassignment, contributor self-service, reviews
and conversion remain #108 work until individually implemented and verified.
Unavailable future tasks have no executable-looking links. The preceding setup
task will supply the admitted Department context; a URL never grants permission.

Every edit reconstructs all untouched typed values from the complete protected
configuration. The originally submitted aggregate cursor must match that source;
the adapter never rebases onto a newer graph. Whole-graph validation rejects
duplicate stable codes, broken earlier-question conditions, unsupported policy,
empty required catalogs, and removal of the required lead public-name field.
Explicit position inputs provide a non-drag ordering operation. The owner command
rechecks scope, lifecycle, cursor and retry evidence under its existing locks.

Metadata edits preserve stored deadlines, including sub-minute precision.
Changing the window is a separate confirmed replacement of all three instants
with whole-minute values in the edition's own displayed IANA zone. Nonexistent
or ambiguous daylight-saving times are refused, never guessed or rounded.

## Lifecycle and outcomes

- Draft configuration may be edited only while private planning writes are open.
- Activation makes the domain call immutable; it does not publish, discover,
  mount a route, enable a profile or guarantee admission of proposals.
- Retirement is explicit and does not erase submitted or historical evidence.
- The existing successor command requires a retired source. Its complete copied
  graph becomes an independent draft; the old call is never reopened or edited.
- Ownership reassignment is not an ordinary configuration input. Orphan recovery
  gets no ordinary navigation, discovery or writer.

## Failure, privacy and interaction

All routes require login and deny missing, foreign, retired-Department and
unauthorized scope with the same non-disclosing response. GET does not mutate.
POST requires CSRF, closed single-valued fields, bounded text, the original
cursor, canonical retry key and an inspectable reason. No submitted scope or
generic visibility/eligibility override is accepted. Sensitive input is omitted
from diagnostic reports and responses use private no-store, CSP and same-origin
form controls. No browser storage or autosave is introduced.

Validation and conflict responses retain bound input and its original evidence.
An obsolete request may already have succeeded before a lost response: the page
must tell the editor to inspect the current call before a fresh attempt, not
promise that no earlier attempt committed. Never silently refresh a stale cursor.
Dependency, required audit, overflow or integrity failures release no partial
configuration. Reauthorize before redisplaying protected content after refusal.

The shared shell supplies one main landmark; this page supplies one H1, labelled
fields and errors, explicit consequences, status text and ordinary navigation.
Long catalog and question content wraps into cards, not page-level horizontal
scroll. Read-only and empty states explain the current boundary. The complete
configuration preview is manager information, not an applicant preview or public
copy. Unsaved changes receive the established pending-input guard.

## Verification and remaining gates

Database-free tests cover exact query ordering, label minimization, input
cardinality, lossless composition of every supported type, original version
fences, whole-graph policy, deadline precision and DST, lifecycle dispatch,
denials and retained errors. Maintained native owner integration remains
unexecuted #102 debt under ADR 0100. Browser fixture evidence must be identified
as synthetic; genuine zoom, widths, keyboard, screen reader and native discard
confirmation remain explicit unchecked #92 tasks. No production activation or
end-to-end Programme readiness follows from this incremental surface.
