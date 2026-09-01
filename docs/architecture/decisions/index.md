# Architecture decision record catalog

**Audience:** Contributors and maintainers investigating why a durable choice
was made\
**Outcome:** Locate a decision without treating the ADR archive as a reading
list\
**Reading time:** 2 minutes plus the selected record

Use the [ADR status index](README.md) to find decisions by number and current
status. Search this catalog by a domain term, requirement identifier, or file
boundary. Accepted ADRs are historical records: a later change supersedes one
with a new ADR rather than rewriting the original decision. ADR 0073 records a
one-time terminology sanitation of current rendered prose; the original public
evidence remains in Git history and that exception is not a general rewrite
policy.

For present implementation status, use the
[current project state](../../project/CURRENT.md) and
[production-consolidation ledger](../../project/PRODUCTION_CONSOLIDATION.md).

## Current documentation decisions

| ADR | Status | Decision |
| --- | --- | --- |
| [0072](0072-protected-exact-main-sphinx-pages-publication.md) | Accepted | Publish warning-fatal Sphinx output from protected `main` through a least-privilege Pages boundary. |
| [0073](0073-repository-owned-fictional-convention-examples.md) | Accepted | Keep current examples in Maru's fictional namespace and prohibit real convention rosters or copied organization charts as example data. |
| [0074](0074-newcomer-first-curated-sphinx-navigation.md) | Accepted | Present exactly six primary hubs, one five-step newcomer route, and complete maintained material behind reachable catalogs. |
| [0075](0075-governed-position-and-opportunity-management.md) | Accepted | Manage Positions and paired volunteer opportunities through the versioned edition structure boundary and a purpose-oriented owner workflow. |
| [0076](0076-owner-safe-position-assignment-lifecycle.md) | Partially superseded | Govern Position assignments through independent decisions and retained relationship evidence; ADR 0080 makes Participation evidence profile-matched. |
| [0077](0077-person-owned-workforce-availability.md) | Accepted | Keep Availability person-owned, deliberately shared, and separate from commitments. |
| [0078](0078-governed-workforce-shift-journey.md) | Accepted | Connect Position demand, personal claims, organizer decisions, and locked coverage without collapsing their meanings. |
| [0079](0079-repository-scoped-agent-workflow-support.md) | Accepted | Keep always-on repository policy separate from four focused, validated contributor playbooks. |
| [0080](0080-progressive-workforce-only-adoption.md) | Accepted | Make Workforce-only an immutable edition profile with truthful Maru-operator accountability and no unadopted authority or side effects. |
| [0081](0081-composite-programme-operations-adoption.md) | Accepted | Make Programme Operations an exact-version composite profile with one Scheduling-owned Programme release and Workforce-owned staffing. |
| [0082](0082-applications-owned-programme-calls-and-acknowledged-proposal-revisions.md) | Accepted | Keep Programme calls and one-version acknowledged collaborative proposal revisions in Applications without activating review, targeting, or Programme. |

ADR 0073 partially supersedes the example-data and source-derived-template
parts of [ADR 0042](0042-synthetic-only-educational-fixtures.md) and
[ADR 0045](0045-governance-anchored-copy-on-write-edition-structure.md).
Their synthetic-person, copy-on-write, versioning, provenance, authorization,
and structure-management boundaries remain accepted. ADR 0080 partially
supersedes [ADR 0076](0076-owner-safe-position-assignment-lifecycle.md) only
where ADR 0076 requires Participation evidence regardless of profile:
`full_convention@1` keeps its configured capacity lifecycle, while
`workforce_only@1` keeps a null assignment pointer and creates or touches no
Participation evidence. ADR 0076's proposal, dual-control, authority,
headcount, onboarding, revocation, audit, and retained-history boundaries
remain accepted. ADR 0081 partially supersedes
[ADR 0053](0053-reusable-venue-catalog-and-physical-space-occupancy.md) only
for Programme-linked publication: Venues retains physical availability,
capacity, occupancy, and independent approval, while the Scheduling release is
the sole public Programme timing source. Unrelated Venue bookings retain ADR
0053's accepted publication lifecycle. ADR 0081 also extends ADR 0080's
profile-matched Assignment evidence rule to every bounded exact-version
manifest that excludes Participation. ADR 0082 refines the pre-acceptance
Applications boundary: proposal collaborators are not Programme hosts, one
submission aggregate version serializes every mutation, exact sealed revisions
require included-collaborator acknowledgement, and every legacy target/review seam stays
closed until its later adapter child. Use the
[complete status index](README.md) for every decision.

```{toctree}
:hidden:
:maxdepth: 1
:glob:

README
[0-9][0-9][0-9][0-9]-*
```
