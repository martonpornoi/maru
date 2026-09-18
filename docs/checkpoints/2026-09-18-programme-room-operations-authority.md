# Exact-room operations authority correction

Date: 2026-09-18
Scope: #177, an essential P05 prerequisite under #108/#48.

## Contract

IDN-004/012/014, VEN-002, SCH-008, NFR-013 and ADRs 0053/0088/0106 remain
unchanged. Venue physical approval authorizes `venues.manage_space_schedule`,
not publication. The legacy room-approval recipe could not approve; the legacy
room-planning description incorrectly excluded independent approval.

Preserved every byte of the original 27 definition digests and their native
mirror. Added `room-operations@1`, an accurately described resource-only recipe
for `venue.edition_space`: read schedule, manage schedule, read dependencies.
The description explicitly states room-management breadth and excludes own-booking
or source-placement approval. No publication, release, root, platform fallback,
or authority-administration power is added. The isolated candidate pins this new
definition instead of the two misleading historical ones. Both current production
profiles remain unchanged; no grant is created by registration.

Migration 0036 replaces only the frozen recipe function. It imports no mutable
catalog, preserves the original 27 literals, trusted search path and owner-only
execution, and extends source-derived readiness. Relation schema fingerprints and
runtime table ACLs are unchanged. Upgrade takes explicit locks; reverse restores
the original function only without any new-code request or role bundle. Retained
evidence requires fix-forward. No evidence deletion or historical migration edit.

## Verification

Focused database-free checks: 188 passed in 1.21s. They retain the original
aggregate digest, compare both frozen mirrors, validate source-derived readiness
and downgrade shape, and execute the actual owner approval logic with mocked
storage: creator, modifier and source author denied; an independent person uses
management authority without publication. This is not native authorization proof.
Initial Ruff formatting findings were corrected; no test assertion was weakened.
Complete database-free feedback passed 10,847 cases in 61.39s, with three existing
Django URL-field warnings. Exact-head certification is pending at this snapshot.

Two maintained native tests compare every frozen database recipe, exercise unused
reverse/reapply, and require retained new-code role bundles to fence reversal.
They remain uncollected/unexecuted under #102, together with the existing complete
schema downgrade/reapply case. Genuine scoped request/approval and physical-room
acceptance still belong to the integrated fixture. No database, Docker command,
schema-only check or native suite ran for this correction.

Next finish physical reservations/fit and the accountable minimal Volunteer starter
(#175) needed before actual blank-setup staffing. Neither this correction nor its
development merge completes P05, #108, #48 or supported-profile promotion.
