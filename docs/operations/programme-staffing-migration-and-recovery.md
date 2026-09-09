# Programme staffing migration and recovery

**Audience:** Maintainers rehearsing the dormant HR-015 staffing foundation\
**Outcome:** Retain explicit work history without activating Programme or changing shifts\
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

Use only synthetic data for the current pre-production rehearsal. Apply the
ordinary complete migration graph with compatible code and the separate schema
owner. Update the [runtime provisioning artifact](postgresql-runtime-role-provisioning.sql.example)
and verify both staffing relations remain SELECT-only for the application role;
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

Coverage unavailability, source staleness and underfill must not be reported as
current complete staffing. Source-bound demand reconciliation/successors,
Scheduling coverage UI, browser acceptance and protected #88 delivery remain
unfinished. #87, atomic release, on-site continuity, guided setup and integrated
Programme-only acceptance remain mandatory before activation under #48.
