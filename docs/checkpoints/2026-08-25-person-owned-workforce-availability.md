# Person-owned Workforce Availability

- Date: 2026-08-25
- Outcome: Implemented the first complete person-owned exact-edition
  Availability workflow and minimized organizer planning projection
- Requirements: HR-006, HR-009, HR-014, SCH-001, SCH-003, SCH-005, PRI-001,
  PRI-003, PRI-005, AUD-001, AUD-005, UX-005 through UX-008, UX-020, UX-029,
  and NFR-001 through NFR-004
- Decision: ADR 0077

## Delivered outcome

The Workforce journey now has a real fourth stage:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

A person with a proposed or active Position assignment may enter explicit
workable periods for the exact edition, save them privately, deliberately share
them, share an empty complete set to report that they are unavailable, replace
the complete current statement, or withdraw it. Existing owners retain review
and withdrawal access after their final open assignment ends. Organizers cannot
write on a person's behalf.

An independently capability-authorized organizer receives a separate bounded
projection containing only people with open assignments, their operational
Department and Position labels, current assignment state, current shared
Availability consequence, and current submitted periods. Private drafts and
absent plans are deliberately indistinguishable as **Not shared**. The
projection excludes notes, reasons, previous periods, unrelated people,
onboarding, applications, account security data, and authority provenance.

Shifts remain noninteractive. Availability is explicitly described as planning
input rather than a commitment, assignment to time, attendance record, or
authorization grant.

## Product and browser experience

- **My Workforce** now shows one Availability continuation for each retained
  assignment edition, including state, open Position titles, and whether the
  plan is currently editable.
- **My availability** uses one progressive repeatable-period editor with
  fieldsets, legends, local date-time controls, Available/Preferred labels,
  add/remove/undo controls, complete-replacement guidance, draft/share actions,
  and separately confirmed withdrawal.
- The page explains Unknown, Private draft, Shared periods, explicit empty-set
  unavailability, complete-set semantics, edition dates/time zone, immediate
  withdrawal, and the boundary from Shifts.
- **Workforce availability** uses the same selected-edition administration
  frame as Structure, Positions, and Assignments. It presents a four-state
  planning summary and one semantic row per open-assignment person.
- Availability periods and sharing timestamps render in the edition's stated
  IANA time zone. The authenticated rehearsal exposed and corrected an
  organizer-page UTC presentation defect.
- The Staff Console consumes `can_view_availability` from the strict structure
  response and links the stage and tool only when the complete capability and
  field ceiling are present. Otherwise it says **Access required**. Shifts
  remain **Not available yet**.
- All pages use purpose names. No user-facing documentation or new interface
  introduces a numbered page name.

## Canonical state and time contract

`PersonAvailabilityPlan` owns one optimistic current state per person,
organization, and edition: `draft`, `submitted`, or `withdrawn`.
`PersonAvailabilityWindow` owns up to 64 current half-open intervals. Periods
may touch but cannot overlap, must end after they start, must be Available or
Preferred, and must stay inside the inclusive edition calendar dates in the
edition's IANA time zone.

Browser input accepts local minutes only when the edition time zone resolves
them to one real instant. Daylight-saving gaps and folds are rejected rather
than guessed. API input requires aware timestamps with `Z` or an explicit
numeric offset. Canonical values normalize to instants and project back into
the edition time zone.

The first slice intentionally has no recurrence rule, free-text reason,
calendar import, or organizer override. Superseded and withdrawn exact periods
are deleted rather than retained as historical location/routine data.

## Authorization and disclosure

Authorization migration `0017_workforce_availability_capability` adds:

- exact-edition `workforce.view_availability`, delegable and persistable, with
  the complete `availability_consequences`, `availability_windows`, and
  `holder_display_labels` field ceiling plus mandatory sensitive-read audit;
  and
- relationship-derived, self-only, nonpersistable
  `workforce.manage_self_availability` for the exact owner route.

The existing `workforce.view_self` field ceiling now permits Availability state
on **My Workforce**. Owner adapters require a retained exact-edition
relationship before loading display context and require an open assignment
before parsing replacement input. Organizer adapters authorize the complete
field ceiling before loading names, repeat the decision at response time, and
append a value-minimized audit before returning current periods.

The organizer read audit contains route, method, policy version, scope, and
principal only. It contains no subject identifier, labels, result count, or
period values. Mutation audit and domain-event payloads contain state,
changed-field names, and a generic count only.

## Shared command and API boundary

Browser and API adapters use `save_person_availability` and
`withdraw_person_availability`. The commands use exact scope, canonical lock
order, optimistic `expected_version`, UUID retry keys, keyed request/window-set
digests, and one atomic plan/period/receipt/audit/event/outbox transaction.

The mounted API routes support owner GET/PUT, owner withdrawal POST, and
organizer GET. Top-level and nested payloads are closed, query parameters are
unsupported, mutation methods require an `Idempotency-Key`, and errors use
stable `400`, name-free `403`, state-aware `409`, and generic dependency `503`
contracts. The owner GET includes private drafts; the organizer GET never does.

OpenAPI and generated TypeScript definitions include the new structure action
hint, owner request/result/projection objects, and organizer projection.

## Database and runtime boundary

Workforce migration `0012_person_owned_availability` installs:

- unique exact-scope plan identity and state-evidence constraints;
- person-kind, exact-edition, IANA-time-zone, version-step, open-assignment, and
  protected-deletion plan guards;
- current-version, edition-horizon, replacement-only period guards and a
  PostgreSQL exclusion constraint for overlap;
- immutable exact-result minimized command receipts;
- deferred final period count/version/digest and exact current receipt
  consistency on every plan, period, and receipt write;
- truncate fences that fail closed outside Maru's narrowly bounded test reset;
- IDN-011 account conversion protection; and
- a fix-forward downgrade fence after durable plans, periods, or receipts exist.

The migration creates `btree_gist` only if absent and has a no-op extension
reverse, so rolling back an unused Availability schema cannot try to remove an
extension already owned by Venue or Logistics constraints.

The runtime database role receives select/insert/update on current plans,
select/insert on append-only receipts, and select/insert/delete but not update
on replacement-only periods. The provisioning artifact, privilege probe,
trigger contracts, migration activation set, downgrade-fence set, and function
fingerprints all include the new objects. Trigger functions are revoked from
PUBLIC and are not directly executable by the runtime login.

## Verification

Completed locally:

- 5 Availability integration cases and 8 focused unit cases pass across owner
  commands, interval/DST/formset validation, draft privacy,
  organizer projection, browser adapters, strict API behavior, tenant/edition
  isolation, read audit, edition-local rendering, and raw PostgreSQL guards;
- the complete unit suite passes 1,998 tests after the responsive shell test
  caught and removed a nested `main` landmark;
- the complete runtime-role suite passes 271 cases, including real role
  provisioning, exact mode, genuine login, relation matrices, function
  containment, and the replacement-only period profile;
- the Assignment, Availability, Workforce guard/write-scope, Position HTML, and
  structure API regression selection passes after its expected independent
  Availability decision calls were updated;
- Django system check reports only the expected local invitation-encryption
  warning; migration drift is zero;
- the Availability migration applies, reverses while unused without dropping
  shared `btree_gist`, and reapplies;
- OpenAPI validates with zero errors and the existing deterministic enum-name
  warnings; generated TypeScript definitions are refreshed;
- Staff Console strict TypeScript and production build pass, and all 28 Vitest
  component/accessibility tests pass;
- repository-wide Ruff lint, formatting, and strict mypy over 361 source files
  pass;
- documentation policy passes across 328 Markdown files and 204 unique
  requirement identifiers, full PyDocLint passes, the semantic docstring check
  validates 371 source files, and warning-fatal Sphinx/AutoAPI succeeds;
- a second OpenAPI, generated TypeScript, and production Staff Console build
  leaves all six checked contract/host artifacts byte-for-byte unchanged; and
- an authenticated fictional owner/platform-oversight browser rehearsal passes
  at desktop and 390-by-844 narrow width. It covers explicit empty submission,
  dynamic-row keyboard focus, private draft isolation, deliberate two-period
  sharing, minimized and audited organizer disclosure, edition-local rendering,
  one H1/main landmark, no duplicate IDs, and no horizontal overflow.

## Remaining gates

- Complete the UX-029 matrix across all specified widths, 200 percent zoom,
  keyboard-only use, representative screen readers, reduced motion, and empty,
  failure, stale, read-only, disclosure, and mutation-role states.
- Exercise the explicitly confirmed destructive withdrawal control in a
  disposable synthetic browser dataset. Automated browser-adapter, API,
  command, audit, and database coverage already verifies removal of every exact
  period and the minimized withdrawn projection.
- Approve an organization-specific maximum post-edition retention period,
  legal-hold behavior, disposal worker, observability, and recovery procedure
  before using production personal data.
- Rehearse Availability with a real person account and independently authorized
  organizer session; retain two-human Assignment step-up rehearsal as a
  separate owner acceptance gate.
- Specify and implement Shift demand and commitment without interpreting
  Availability as a promise. Qualifications, claims, confirmation, removal,
  overlap/rest, publication, completion, locking, and recovery remain absent.
- Perform representative stopped-writer cutover, restore/PITR, deployment,
  privacy, load, security, and external owner acceptance before release.
