# Run Announcements with your existing channels

Status: Core synthetic browser journey verified; independent and native-print acceptance pending
Last updated: 2026-10-09

Announcements keeps approved text and publication reports together. Your website,
social accounts and chat channels still publish the actual posts. Copying from Maru
does not publish or notify anyone.

## Before a convention uses it

Use the exact standalone Announcements profile and two verified people who are
accountable for operating it. Existing Workforce operators are not automatically
Announcements operators. Platform setup creates or reuses the organization,
convention series and event, then follows the ordinary invitation/acceptance and
activation path. A platform administrator does not become an attendee or operator
merely by setting this up.

The deploying team supplies its actual record-keeping rules, their responsible
owner and a review date. Those rules must cover drafts, review notes, who reported
publication, corrections, downloads, backups and applicable holds. Enter a readable
name and link or description in **Record-keeping rules**. Maru records the authorized
person's confirmation; it does not choose a legal basis or promise automatic deletion.
No content is collected before setup is complete. Expired rules require review before
new writing, while already-approved publication reports and retained history stay
available to currently authorized operators.

Configure each manual channel with the name the team uses and its safe address where
useful. Maru stores no channel password or API token here. Assign responsibility for
publishing and correcting each external channel outside Maru; a recorded claim is
not a provider receipt. Use the event's actual languages and time zone.

## A short synthetic practice journey

Use fictional people, channels and text on an isolated local installation. Never use
this example as a real retention policy or claim an external post was made. The
[checkpoint](../checkpoints/2026-10-09-standalone-announcements.md) records the
assistant-operated journey, scripts-blocked mechanism, actual widths and remaining
print, zoom, specialist and independent-person acceptance gaps.

1. Sign in as the first authorized operator and open **Announcements** for the test
   event. Confirm the event name before writing. Complete the real setup decision
   for that test environment and configure two clearly synthetic channels.
2. Choose **Write an announcement**. Use headline **Art show opening time** and message
   **The art show opens at 10:00 in the Gallery.** Deliberately choose both channels
   and preview their exact language and text. Request review.
3. Try to review as the writer: Maru must explain that another organizer is needed.
   Sign in as the second operator, check both copies, and approve that version.
4. Open **Copy approved text** or download the text. No publication status should
   change. Keep all practice copy within the synthetic test environment.
5. Record a clearly identified synthetic publication report for each channel,
   using the actual practice time. Both channels should show **Publication reported**,
   with the reporter and reporting time. Do not claim a real remote publication.
6. Prepare a correction changing only one channel's message to **The art show opens
   at 10:30 in the Gallery.** The prior approved text remains available while the
   correction is a draft. Have the other person review it. Only the changed channel
   should show **Update needed**; the unchanged channel keeps its existing report.
7. Record the synthetic update. If the earlier report had the wrong time or link,
   correct the report with a reason instead of overwriting it. Read the retained
   history to distinguish changed copy from corrected reporting evidence.
8. Download approved copy and, with the separate permission, **Download full history**. Public copy must contain no review comments or private policy notes.
   Test stopped use: retained history/downloads remain available, and the screen
   explains that external posts are handled in their original channels.

Two people can swap writer/reviewer roles on a new correction they did not both edit.
Within a draft round, editing, requested changes or resubmission never removes a
person from its author history. An assistant using two accounts is synthetic test
evidence, not independent-human acceptance.

## Failures and daily operation

If another operator changed a record, preserve your unsaved text and reload the
current version before deciding what to do. Do not change hidden version or retry
fields. An exact retry can recover its original result; changed input must not reuse
that result. A failed save must not leave half a review or publication record.

When a channel is unavailable, retain the approved copy and complete publication
later through that channel's normal process. Do not record success simply because
copy was downloaded. A corrected time/link or withdrawn report explains a mistaken
claim; neither action removes an external post. Cancelling remaining work has the
same limitation. Keep private review notes out of external messages.

Use printable approved copy when the venue connection is unreliable. Previously
downloaded material can become stale: identify its version and check for corrections
when service returns. This increment provides manual continuity, not an offline write
queue or automatic reconciliation. An authorized operator records what actually
happened after connectivity returns.

## Handover, stopping and recovery

Approved text and private handover evidence are separate outputs. Store private
exports only where the convention's rules allow. Integrity metadata detects content
changes; it is not proof that a recipient read an announcement or that a remote
provider accepted a post. Exported copies and external posts retain their own custody
and correction responsibilities.

Stop new work through the owning settings action, retaining separately authorized
history and export. New writing and review stop; authorized operators can still
record earlier publication of approved copy and correct retained reports. The same
reporting path remains available after cancelling an announcement. Older report
corrections remain in history without replacing a newer publication status. There
is no destructive uninstall, implicit module expansion or
automatic external deletion. Keep access revocation immediate through the ordinary
accountable access workflow. Dispose or minimize retained records only under the
approved procedure, including holds, backups and consistent evidence references.

Deploy migrations with writers stopped and reconcile the exact runtime relation and
function permissions in the [PostgreSQL provisioning example](postgresql-runtime-role-provisioning.sql.example).
The Announcements integrity readiness result must be ready before serving the workflow.
Never use a database owner connection to bypass a runtime failure. Unused migrations
may reverse only through their explicit fence; after durable evidence exists, repair
forward or restore the whole mutually consistent database. Inspect safe error codes,
audit/receipt links and readiness state, without copying announcement text or review
notes into logs or support reports.

[The module contract](../modules/announcements.md) describes the ownership and current
limits. Automatic sending, scheduled posts, emergency overrides, recipient targeting,
images and provider credentials are not part of this first workflow.
