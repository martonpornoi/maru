# Programme release-source migration and recovery

**Audience:** Maintainers rehearsing the dormant #94 owner-source boundary\
**Outcome:** Preserve exact fit/no-staffing evidence and complete preflight sources\
**Status:** No profile, runtime writer, production release or restore approval

## Additive migration boundary

Programme `0013_placement_decisions` adds one owned append-only relation and two
closed receipt operations. It refines the item-version receipt uniqueness rule
to exclude public rendition and the two independently versioned placement
operations; ordinary item-changing commands still require unique next versions.
It depends on the existing joint Programme/Scheduling/Venue graph and seeds no
item, assessment, grant, profile, worker or cross-owner record.

`0014_placement_decision_integrity` preserves the earlier receipt/item evidence
guards while adding exact-scope, current-source, contiguous-sequence, immutable
decision, no-truncate and reciprocal receipt/audit/event/outbox enforcement.
Operational placement decisions do not advance item versions and do not reopen
private content edits in Ready or Live. Accessibility evidence requires its
Programme delivery source and current physical selection version; immutable
Scheduling placement owns the selection link. No redundant direct Venue foreign
key or physical lock is added across the existing parent-lock boundary.

`0015_placement_decision_downgrade_fence` refuses contraction once any placement
decision exists, before removing guards or schema. All guard functions remain
SECURITY INVOKER with fixed safe search paths and no PUBLIC execution. Bounded
Programme readiness fingerprints the exact live table, constraints, indexes,
functions, triggers, ownership and ACLs, including the refined receipt index.
Runtime receives SELECT only on the new relation and no new executable writer.

## Reversal and recovery

On an isolated synthetic database with no placement decision, use the real
migration executor to reverse to Programme `0012_staffing_downgrade_fence`, then
reapply the actual graph. Preserve earlier Programme, Scheduling, Workforce,
Audit and Effects data. The same-transaction preflights take ACCESS EXCLUSIVE
locks before contraction; never fake history or disable a guard to pass them.
Once a decision exists, the expected result is a fix-forward refusal with
schema, guards and migration evidence retained.

Recover by restoring mutually consistent Programme, Scheduling, Venues,
Workforce, Identity/Authorization, Audit, Effects and migration history from the
same approved backup point, or by a compatible forward correction. Synthetic
round trips and populated-fence tests are not production restore/PITR evidence.
Do not truncate decisions, rewrite source digests, remove receipts, use the
test-only reset escape or run the application as database owner for recovery.

## Operational failures

- Preview compares exact current item/candidate versions and owner sources;
  stale input needs a fresh deliberate preview, not silently rebased versions.
- Record an explicit new satisfied/blocked decision with reason, or withdraw
  using retained exact candidate provenance and current item authority/version.
  History is separately authorized, fixed-ceiling and fifty-row paginated.
  There are 1,000 ordinary decisions plus one terminal withdrawal slot per
  placement/kind. Exhaustion is not permission to delete history.
- Fit requires an explicit delivery revision and complete current physical access
  facts. No declaration or no decision is unavailable, not inferred suitability.
- No-staffing requires no active need and no operative demand anywhere in the
  retained binding lineage. Retiring a requirement cannot cancel volunteer work.
- Preflight returns all ten categories or withholds disclosure on authority,
  required-audit, database or complete-person-closure failure. Later documented
  source absence stays unavailable. Diagnose using closed reason categories and
  correlation IDs, not by logging private source DTOs, reasons or calendars.
- Venue catalog sources are re-read without inverting physical locks. A changing
  source aborts the snapshot; retry only after deliberate source reconciliation.
  Point-in-time preflight does not supply publication's atomic invalidation fence.

## Activation remains separate

The five new owner adapters and separate fields are unpinned in current profiles.
Scheduling's complete preflight is also unpinned. There is no route, public API,
runtime writer, saved approval, warning acknowledgement, release pointer or
artifact. Old planning-warning evidence is not release-warning evidence.
The successor must implement retained independent approval and atomic publication/
invalidation, followed by shared outputs, continuity, setup and #92 human
acceptance. Deferred manual checks are not passed or waived activation gates.
