# Scheduling certification and planner-handover corrections

Date: 2026-09-07
Issue: [#81](https://github.com/martonpornoi/maru/issues/81), child of
[#48](https://github.com/martonpornoi/maru/issues/48).
Status: focused corrections verified; corrected-head full certification pending.

## First complete run

Clean candidate `3f04efd0f2f9100a4f235b5c74786abf42489ea8` ran the default eight
isolated PostgreSQL shards. Of 6,535 Python tests, 6,533 passed and two failed.
All non-database gates and 33 frontend tests passed. The combined coverage gate
was not reached, so this run is not successful certification or delivery.
Integration shards took 76m17s to 95m43s; these are observations, not a speedup
claim. The script removed its own eight temporary containers afterward.

The closed event-registry test exposed an omitted explicit dormant classification
for `scheduling.planning.changed.v1`. It now joins the acknowledged dormant set
without installing a handler or effect route. The real runtime-login readiness
test reached a healthy HTTP 200 response but its exact expected dependency map
omitted `scheduling_integrity`. The corrected assertion retains genuine password
authentication, privilege, decision, persistent-replica rejection, and credential
disclosure checks.

## Retained draft handover

New regression cases reproduced a Venue binding guard incorrectly requiring the
historical placement author to remain active and verified. Both an inactive and
an unverified author blocked a different authorized reserver. ADR 0088 and the
Scheduling owner contract now explicitly distinguish retained attribution from
current mutation authority. The guard still locks both retained accounts, checks
the exact original source identity, and requires a current active verified
reserver. The source author's identity remains excluded from independent Venue
approval, including after account recovery.

An ordinary reverse of the unused Venue integrity successor and joint downgrade
fences, followed by full forward migration, passed on isolated PostgreSQL 17.
No fake migration, production database, retained-data deletion, or gate bypass
was used. Current-actor invalidation immediately before binding creation is
separately rejected by PostgreSQL and rolls back the complete physical hold.

## Focused verification and handoff

The two original failures, Scheduling catalog, reservations, handover, binding
guards, and readiness group passed 92 tests in 93.51 seconds. After adding two
late current-actor invalidation cases, the complete continuity and binding-guard
files passed 15 tests in 39.56 seconds. These groups overlap; neither replaces
complete exact-head certification. Lint, formatting, and whitespace checks passed
for the changed source/tests. The experience contract now accurately describes
installed dormant kernels without claiming a routable Programme journey.

Commit the corrected candidate, run full local certification, obtain exact-head
hosted acceptance and CodeQL, then perform protected delivery and reconcile the
issue. Continue the accessible editor and remaining #48 children afterward.
