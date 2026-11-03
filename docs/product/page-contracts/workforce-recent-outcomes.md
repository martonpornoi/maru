# Recent governed Shift outcomes on Home

- Status: Optional component delivered through PR #236 with independent local
  and hosted verification. Live browser and specialist accessibility acceptance
  remain open.
- Parent: #35; accepted contract #233; bounded implementation #235
- Host: Existing `/admin/`, exact `workforce_only@1` selected organization/edition
- Requirements: UX-033, UX-029, UX-031, AUD-003–005, NFR-001–003 and NFR-013
- Decisions: ADRs 0078, 0080, 0126, 0128 and 0132

## Human outcome and current evidence

An authorized organizer can find a few recent retained Shift outcomes and open
their ordinary decision history. The list answers what Maru recorded recently;
it does not score people, prove work happened or establish convention readiness.

Existing `ShiftDemandCommandReceipt` records are append-only, organization/edition
scoped and unique per demand/resulting version. Their closed actions include
locking, reopening, completion and cancellation. The current organizer Shift
detail independently authorizes the existing complete read boundary and shows
retained history. Home keeps its existing next actions and adds this separate
optional receipt list. Django administration log entries remain omitted.

The public `operating_home.load_workforce_home_guidance` result includes a closed
immutable `recent_outcomes` component. Core maps it to ordinary detail links;
there is no second provider call after the owner has finalized its other areas,
and no cross-module private model import.

## Admission and disclosure

Filter the exact adopted profile before asking Workforce for facts. Resolve the
real principal and exact organization/edition through documented public owner
boundaries. Require `workforce.view_shifts` and every field in the existing
`SHIFT_ORGANIZER_REQUIRED_FIELDS`, matching the ordinary organizer destination.
No role, field exception or global platform shortcut is added.

The existing ordinary Workforce policy can return `platform_administration`
before considering scoped organizer grants. This component withholds that
decision: platform oversight by itself cannot establish its exact organizer
admission. A separately admitted organizer account can use the panel. Existing
platform tools, their policy and all account/grant definitions are unchanged.

| Principal/state | Result |
| --- | --- |
| Organizer with the complete existing Shift-read boundary | Eligible for bounded current-scope outcomes; management is unnecessary. |
| Management-only or incomplete/denied read fields | Omit the panel and all facts; management is not read authority. |
| Volunteer/personal account without organizer read | No organizer outcome list; existing own My shifts remains separate. |
| Platform/staff account without exact organizer read | No convention facts or inferred membership. |
| Wrong organization/edition, revoked/expired/inactive account | No rows, labels, times, targets or hidden counts. |
| Other/unknown profile or no selected edition | No provider call or new setup pressure; existing host recovery applies. |
| Admitted source/audit unavailable | Generic unavailable panel; no partial rows or source identities. |

Each visible row may contain only the current authorized Shift label, one closed
outcome label, recorded time in the named edition time zone and an exact ordinary
Shift-detail link. Include no actor/volunteer, reason, contact, person identifier,
Availability value, headcount, retry/correlation key, request digest or raw receipt.
Use no free-text source field except the already-readable current Shift label.
That label can contain organizer-supplied text: normal escaping and the current
field ceiling are required; the panel cannot promise the text contains no names.
Do not retain a new label snapshot. The destination authorizes again.

## Eligible outcomes and fixed bounds

| Latest exact receipt/current state | Wording and meaning |
| --- | --- |
| `locked` / locked | **Coverage locked** — the existing command recorded planning coverage; no attendance claim. |
| `completed` / completed | **Shift completed** — retained planned-work closeout; no reported/verified actual-time claim. |
| `cancelled` / cancelled | **Shift cancelled** — retained cancellation; no organizer rationale in Home. |
| Other action, newer parent version or different current status | Exclude the old outcome; do not imply a reopened Shift remains locked. |

Only existing trusted demand commands can supply receipts. Parent row presence,
`updated_at`, a Django log row, an audit read or a failed/replayed submission alone
cannot prove an outcome. Exact replay supplies the same retained receipt and
must not duplicate an item or change its time. No commitment receipt is counted
again as a second demand outcome.

The horizon is the preceding seven elapsed UTC days, with the lower boundary
included. Convert time only for display. Capture a trusted aware check instant;
future/incoherent receipt time or a backward clock makes the component unavailable.
Never backdate, alter the clock, or substitute a Shift's scheduled end for receipt
time. Fence the earliest displayed/candidate receipt's expiry from this window.

Probe at most 128 distinct current candidate demands with minimal exact receipt
metadata; a 129th detects overflow and releases no list. Candidate selection must
also detect missing/inconsistent matching evidence for a candidate instead of
inner-joining corruption away into an apparent empty result. Implementation must
prove candidate completeness using bounded owner queries and existing indexes;
an unbounded receipt/history scan or count query is not an acceptable shortcut.
Do not resolve people or select rationale while probing. If a supported coherent
query cannot establish those facts within the bound, return unavailable.

After complete metadata validation, return at most five distinct demands, sorted
by recorded UTC time descending, receipt identifier descending and demand
identifier descending. Identifiers are internal stable tie-breakers, not visible
reference strings. Resolve only the selected current labels under admission.
The display is explicitly **Recent Shift outcomes · past 7 days · up to 5 Shifts**;
it is neither a complete history nor a count of hidden/older work. There is no
pagination, hidden total or automatic polling. The 128-candidate ceiling can make
this optional panel unavailable at a busy convention; do not silently sample it.

### Bounded owner implementation

Each coherent source read first loads only parent ID, command version and status
under the existing 1,024-demand foundation ceiling, with a 1,025th overflow probe.
Within that bounded parent set, correlated point lookups use the existing unique
`(demand, resulting_version)` receipt index. Candidate selection includes recent
current outcomes **and** missing/inconsistent evidence, so an inner join cannot
turn corruption into an apparent empty result. It returns at most 129 minimal
candidate rows. Only the selected five current labels are then loaded. No count,
arbitrary historical scan, people lookup or rationale selection is needed.

A five-second optional-component **release budget** covers both permitted whole
attempts and the other areas' final checks. Short read-only source snapshots set
a transaction-local one-second statement timeout. Elapsed and observed wall-clock
movement are checked after source probes, after audit and at aggregate release;
an expired budget releases no rows. This is not a promise that the HTTP request
or an unavailable external dependency is forcibly terminated at five seconds.
The original Home had row/version bounds, not an elapsed deadline to inherit.
No existing certification, worker, timing, coverage or database policy is relaxed.

## Coherence, lifecycle and audit

Keep the existing four-area next-step projection and its priority unchanged.
The optional outcome list follows the attention list and precedes other tools.
It never becomes the primary action or a fifth guidance area.

Bind the complete bounded cohort, membership/order, matching receipt version,
action/status/time, current parent/version/label and exact owner scope in a short
read-only coherent snapshot. Current owner lifecycle governs whether retained
history is readable; a closing/archived phase grants no new read or mutation.
Repeated public scope/lifecycle projections create no cross-owner private access.

Compare the complete signature in fresh reads, with one whole-component retry
on movement. Reauthorize principal, exact profile, lifecycle and fields before
audit, after audit and at aggregate release after other areas finish. A later
provider/audit must not leave an earlier revoked outcome visible. Check the
existing bounded deadline and window-expiry boundary **after** the final source
probe; crossing either requires a new coherent attempt or unavailability.
Do not relabel old facts with a later checked time.

Before any fact is released, implementation registers and persists minimized
`workforce.shift_outcomes.read` evidence through Audit's public service. Its
purpose is existing operational Shift continuity, with the existing
`workforce-personal` retention class and no newly invented duration. Use current
principal, exact scope, policy version, route/method and request correlation only.
Do not log displayed labels, outcome rows, reasons, activity frequency or people
as analytics. No raw Audit-table scan or new retention store is involved.
Mandatory audit failure withholds all component facts, including a prepared list.

## Visible states, failure and recovery

- **Present:** Semantic ordered list, current labels, closed outcome text,
  localized recorded times and ordinary links. Show check time separately.
- **Empty:** **No recent Shift outcomes in this checked scope.** State the seven-day
  horizon; this is not no work, complete staffing, full history or event readiness.
- **Unavailable:** **Recent Shift outcomes are unavailable. Refresh or use Shifts.**
  No stale rows, hidden counts, exception details or private scope-existence hints.
- **Not admitted:** Omit the component. Do not offer an action-shaped permission
  dead end or turn absence into a readiness statement.

Return private/no-store request-local results. Preserve other independently
admitted guidance and tools on component failure. Offer the existing authorized
Shift-planning destination when available; its ordinary detail history remains
the direct fallback. Every destination reauthorizes. A refresh is a new read,
not a background mutation, repair or automatic retry loop.

Keep one host H1/main, labelled list/section, visible focus and ordinary link
operation. Outcome meaning cannot depend on color. Exercise seven UX-029 widths,
real 200% browser zoom, long synthetic labels, empty/unavailable/denied states,
keyboard, themes/reduced motion and representative announcements. No new modal,
drawer, personal timeline, notification or screen-reader acceptance is implied.

## Observable implementation acceptance and stopping point

Before runtime delivery, prove:

1. Unit tests for all actions, latest-version exclusion, replay/deduplication,
   deterministic ties, seven-day/DST/window crossing, future/backward time,
   exact 128/129 and five-item bounds, and no partial result on every failure.
2. Native exact-tenant/edition/full-field admission, denied/manage-only/platform/
   self-only/revoked roles, complete candidate/receipt integrity, concurrent
   command/source movement, label and policy loss before/after audit and final
   release, current lifecycle, audit failure and direct destination authorization.
3. No domain receipt/write, unrelated module row, grant/profile expansion,
   notification or identifying audit payload caused by reading Home. Measure
   bounded rows, query cost, deadline and resource behavior without relaxing
   existing certification, coverage, time or worker limits.
4. Maintained ongoing/future fictional scenarios through supported commands,
   including separate operators, locked/completed/cancelled/reopened work and
   denial. Preserve every existing preview/manual record and real timeline.
5. Rendered component and real-browser role/state/width/keyboard evidence, then
   separately recorded specialist, representative owner, recovery, operational
   and production gates. Synthetic receipts do not supply human acceptance.

The implementation adds this optional projection/presentation and its registered
read-audit operation. It adds no migration, runtime ACL, permission or adoption
profile. Source rollback removes the optional contribution while preserving all
domain receipts, their retention and direct Shift workflows. Verification results
and remaining browser/human gates belong in CURRENT and the implementation
checkpoint; implementation does not itself constitute activation or acceptance.
#35, #23 and #42 remain open; actual-time/handover and full continuity remain separate.
