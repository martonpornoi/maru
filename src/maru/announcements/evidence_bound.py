"""Bound complete retained records before acknowledging an announcement write."""

from uuid import UUID

from django.db import connection

from .catalog import MAX_STORED_TEXT_BYTES
from .errors import AnnouncementLimitError


def require_complete_evidence_bound(announcement_id: UUID | None) -> None:
    """Check actual UTF-8 evidence size, including destination snapshots and rules.

    Parameters
    ----------
    announcement_id : UUID | None
        Announcement identifier resolved only inside the admitted scope.

    Raises
    ------
    AnnouncementLimitError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if announcement_id is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH selected AS (SELECT %s::uuid AS id),
            revisions AS (
                SELECT row.* FROM announcements_announcementrevision row, selected
                WHERE row.announcement_id=selected.id),
            copies AS (
                SELECT row.* FROM announcements_announcementvariant row
                JOIN revisions ON revisions.id=row.revision_id),
            rules AS (
                SELECT row.* FROM announcements_announcementsettingsrevision row
                WHERE row.id IN (SELECT settings_revision_id FROM revisions)),
            records AS (
                SELECT to_jsonb(row) AS record FROM revisions row
                UNION ALL SELECT to_jsonb(row) FROM copies row
                UNION ALL SELECT to_jsonb(row)
                    FROM announcements_announcementreview row
                    JOIN revisions ON revisions.id=row.revision_id
                UNION ALL SELECT to_jsonb(row)
                    FROM announcements_announcementpublicationreport row
                    JOIN copies ON copies.id=row.variant_id
                UNION ALL SELECT to_jsonb(row) FROM rules row
                UNION ALL SELECT to_jsonb(row)
                    FROM announcements_announcementcommandreceipt row, selected
                    WHERE row.announcement_id=selected.id
                       OR row.id IN (SELECT command_receipt_id FROM rules)
            ) SELECT coalesce(sum(octet_length(record::text)), 0) FROM records
            """,
            [announcement_id],
        )
        if cursor.fetchone()[0] > MAX_STORED_TEXT_BYTES:
            raise AnnouncementLimitError
