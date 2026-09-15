# Programme moderation

Status: dormant #108 implementation contract. Applications owns this surface;
PRG-003, PRG-006, AUD-001, QRY-005 through QRY-008 and UX-029 apply under
[ADR 0085](../../architecture/decisions/0085-exact-revision-programme-review-and-decisions.md).
No production route, schema, profile or permission grant changes.

## Purpose and independent disclosure

The reserved review root's `moderation/` discovers exact Department cases using
call and seal labels, excluding leads, all retained collaborators and all retained
reviewer assignments before complete exclusive-UUID pagination. The exact-case
overview exposes content-free policy/stage metadata under independent
`applications.moderate_programme_review` and `review_context` authority. Manager,
reviewer and final-decider authority is neither required nor inherited.

Separate context, answers and evidence tasks independently authorize their field
ceilings and the owner's additional sensitive-review checks. Retained evidence
can remain inspectable after the source ceases to be current; this never permits
fresh mutations. No new identifying lookup or unsafe reference/file viewer is
introduced. Evidence is labelled by action, stage and case version; already
authorized opaque attribution references remain in progressive details, not a
directory. Every retained entry is reachable through complete bounded pagination.
Evidence links pin a snapshot case version; intervening changes return conflict
guidance instead of mixing history pages or silently replacing inspected intent.

## Deliberate moderation and progression

Moderate, advance and reopen are separate reasoned, confirmed actions. The
moderation form accompanies the independently authorized evidence page and binds
its inspected case version. Stage facts show configured quorum, current valid
score count and canonical readiness, without totals, averages or recommendations.
Later review changes or relevant reopening invalidate earlier moderation; fresh
progression is decided only by the existing canonical owner rule.

Advancement moves one configured stage and never makes a final decision. Reopening
explicitly selects a labelled current/earlier stage, preserves history and
invalidates moderation for that and subsequent stages. Only open or waitlisted
cases can freshly reopen; accepted, rejected and revision-requested cases cannot.
Source currency, planning, independent actor and optimistic version guards remain
owner-enforced inside the command transaction.

An original POST reaches canonical receipt handling before any private case or
evidence read. Its strict version, retry key, stage, rationale and confirmation
are never rebased. Successful replay returns only a minimal receipt, even if
fresh case independence has since changed, while current route admission remains
mandatory. Failed requests retain their original fields only when fresh scoped
metadata still permits disclosure; otherwise fail closed without cached content.

## States and acceptance

Use the shared shell and assets, one H1/main, ordinary links and labelled forms,
visible focus, focusable errors, explicit pending-input protection and wrapping
cards. Distinguish empty, readonly, source-stale, final, invalid, conflict,
dependency-failure, denied and receipt states. Revalidate protected projections
before and after rendering; audit failure or overflow releases no partial data.
No read-tracking or claim that a person actually read every history entry is added.

Permitted answers reuse the [typed review presentation contract](programme-reviewer-work.md#readable-typed-answers):
immutable selected choice labels, labelled address components, explicit absence
and plain escaped values. It adds no reference/file access or permission beyond
the existing exact moderator field, classification and source boundary.

Database-free tests cover purpose and field separation, independence before
pagination, snapshot binding, original-intent recovery, closed transport, CSRF,
readonly and final-case restrictions, evidence attribution and render-time
revocation. Native scenarios remain maintained but unexecuted #102 debt under
ADR 0100. Genuine multi-person, keyboard, responsive, native zoom, reduced-motion
and assistive-technology acceptance remains #92. Final decisions, safe structured
answer viewers, conversion and complete navigation remain separate #108 work.
