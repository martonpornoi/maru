# Programme staffing migration and recovery

**Audience:** Maintainers rehearsing the dormant HR-015 staffing foundation\
**Outcome:** Retain exact work lineage through governed Shifts without activating Programme\
**Status:** Local #88 continuation; no completed staffing PR or production approval

## Migration boundary

Programme `0010_staffing_requirements` adds the two owned requirement/revision
relations and extends the existing receipt operation vocabulary. It depends on
the already-delivered Scheduling occurrence graph and existing Workforce shape.
Authorization `0028_programme_staffing_capabilities` adds only
`programme.manage_staffing` and `programme.view_staffing` at exact-edition scope.
It creates no grants and changes no adoption manifest.

Programme `0011_staffing_integrity` installs scope, version, lifecycle, complete
work-term, reciprocal receipt/audit/event/outbox and no-truncate guards. It
preserves the existing item, host and accepted-source contracts while extending
the receipt function with closed staffing operations. `0012` places an explicit
reverse fence before any of those protections can be removed.

Workforce `0019_programme_shift_bindings` adds stable requirement-to-demand
lineage and immutable source/retry/effect revisions. `0020` installs exact-source,
uncommitted-work, scope, sequence and reciprocal evidence guards; `0021` places
the populated reverse fence before their removal. One-to-one Shift/cancellation
receipt links prevent reusing a prior owner command as a new binding action.
The authorization readiness catalog pins all six new trigger attachments and
three new function definitions. Neither migration creates authority or activates
the dormant `workforce.programme-staffing@1` adapter.

Use only synthetic data for the current pre-production rehearsal. Apply the
ordinary complete migration graph with compatible code and the separate schema
owner. Update the [runtime provisioning artifact](postgresql-runtime-role-provisioning.sql.example)
and verify all four Programme/Workforce staffing relations remain SELECT-only for the application role;
there is no approved Programme runtime writer. Inspect the exact Programme schema
and function/trigger fingerprints and the current authorization contract before
claiming runtime readiness. Green owner tests are not provisioned runtime proof.

## Retained evidence and reversal

When both staffing tables are empty, the additive Programme graph may be reversed
to `0009` and reapplied in an isolated rehearsal. Existing item and occurrence
records must remain unchanged. A requirement, including a retired one, or any
revision blocks reversal through `0012` before a guard or table is removed.
Retained staffing grants or role-bundle entries independently block contraction
of the authorization vocabulary.

When both Workforce binding tables are unused, their graph may be reversed to
`0018` and reapplied without changing Programme requirements or ordinary Shifts.
Any retained binding or revision blocks `0021` before removal of a guard. The
broader Programme downgrade also traverses these dependent Workforce migrations;
do not infer that an unused Programme layer permits removing retained work lineage.

Once any staffing evidence exists, retain compatible code and fix forward.
Do not fake migrations, disable guards, delete receipts, remove history, or
truncate retained requirements to pass the fence. The test-only cleanup escape
is not an operational recovery mechanism. Follow the normal separately rehearsed
backup/restore procedure if restoration is required; this child does not certify
production restore/PITR or disposal policy.

## Operational change and failure

Requirement revision requires exact item, occurrence, edition and requirement
versions plus a new explicit reason and retry key. Reload stale sources; do not
silently replace the organizer's selection. Same-key same-intent retry returns
the original result identifiers only after current authorization.

Retirement is terminal and retains the previous terms, including their original
Position and work interval. It never cancels a demand or removes/reconfirms a
volunteer. A bounded history reserves one terminal retirement revision after
1,000 ordinary revisions; the item retains at most 128 requirements. Exhaustion
is an explicit unavailable workflow pending a reviewed capacity decision, not
permission to discard evidence.

Binding apply requires its exact authorized impact preview and current authority
after the canonical owner locks. Link only an identical uncommitted draft;
reconcile only a draft with no retained commitments. Replacing a Position requires
a separate successor. A successor explicitly cancels nonterminal old work through
Workforce and leaves all old decisions/history attached to it; already cancelled
or completed predecessors are not cancelled again. New work starts as an
independent draft with no copied claims, confirmations or lock. The required
rationale is Workforce-visible, not a private Programme discussion note.

A late source, authority, audit or effect failure commits none of the adapter's
owner mutations. Reload the complete impact after any changed source, demand
version or retained/active count; a claim can invalidate the preview without
advancing the demand version. Matching retries retain the original command result
after current authorization. Binding history has a separate 1,000-revision bound;
exhaustion requires a reviewed capacity/recovery decision, not history deletion.

Coverage unavailability, source staleness and underfill must not be reported as
current complete staffing. The local composed reader compares exact bound source
and work-term fingerprints; an ordinary Shift lifecycle increment is not itself
a work change. Missing Workforce authority yields withheld null counts, and an
incomplete dependency makes the complete coverage layer unavailable. Retained
binding history has a separately authorized fixed ceiling and bounded cursor;
current requirements or coverage do not grant historical rationale access.
Source-bound commands, coverage/history queries and native controls have focused
local acceptance. A post-command reload failure is uncertain success, not proof
of rollback: keep the original pending intent/retry key and inspect retained
history or retry exactly. Never edit hidden source versions to force a stale form
through. The parent lock order now applies to Programme source and Scheduling
commands/locking reads as well as binding apply; do not restore edition-first
locking or hide deadlocks by extending timeouts.

Full certification and protected #88 delivery remain unfinished. #87, atomic
release, on-site continuity, guided setup and integrated
Programme-only acceptance remain mandatory before activation under #48.
