# Applications same-shell journeys

Date: 2026-08-09
Status: implemented and focused-verified

## Outcome

The typed Applications domain now has complete thin server-rendered journeys
over its existing strict commands and projections:

- organizers can copy an eligible code-owned starter, configure the independent
  draft and exact owner/reviewer assignments, add sections/questions, activate,
  retire, and create a successor;
- applicants can discover all authorized editions without an admin context,
  start one application draft, inspect field purpose/audience and source-bound
  values, append typed answer revisions, and submit; and
- exact named or immutable-role reviewers can open their queue, see only the
  reviewer projection, and record accountable state transitions through typed
  acceptance.

Every page uses the shared admin context. Applicant pages explicitly use the
personal surface, while organizer and reviewer pages retain staff navigation.
The always-available **My applications** destination and My Maru card resolve
to `/my/applications/`; edition discovery never releases a foreign edition and
bounds distinct edition candidates rather than definition rows.

## Input and policy controls

Browser mutation forms reject unknown and duplicate keys, require canonical
UUIDs and base-10 control integers, carry expected aggregate versions, and use
fresh idempotency keys. Definition windows are parsed in the persisted edition
IANA time zone; ambiguous and nonexistent daylight-saving wall times are
rejected. Draft-only controls disappear after activation. Applicant and
reviewer reads use their separate field projections, and sensitive reads remain
audited. Preview state is never accepted by mutation forms or command services.

## Verification

- `tests/unit/test_application_html_forms.py`: strict inputs, explicit edition
  time zone, DST gap/fold rejection, shared-shell templates, and mojibake guard;
- `tests/integration/test_application_html_workflows.py`: five PostgreSQL cases
  covering the rendered organizer lifecycle, personal discovery/navigation,
  source and typed answer flow, tenant/object isolation, named and role reviewer
  provenance, and distinct-edition starvation;
- focused Ruff, Django template compilation, route reverse/resolve, and mypy on
  the new forms, queries, views, and URLs.

The focused PostgreSQL HTML matrix passed 5 tests in 41.97 seconds before this
checkpoint. No schema migration was required for the HTML adapters.

## Recovery and remaining scope

The HTML layer owns no workflow state. It can be disabled or reverted without
rewriting Applications evidence; retries continue through the existing command
receipts. Browser visual/accessibility rehearsal and real external typed target
adapters remain deployment work outside this checkpoint.
