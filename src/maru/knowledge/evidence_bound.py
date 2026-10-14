"""Bound actual retained Guidance rows before acknowledging a privileged mutation."""

from uuid import UUID

from django.db import connection

from .catalog import (
    MAX_CONTROL_HISTORY,
    MAX_EXPORT_BYTES,
    MAX_HISTORY,
    MAX_REVISIONS,
    MAX_STORED_TEXT_BYTES,
    WITHDRAWAL_RECEIPT_RESERVE_BYTES,
)
from .errors import GuidanceLimitError


def require_complete_evidence_bound(item_id: UUID | None) -> None:
    """Keep complete evidence within its cap, reserving one future withdrawal.

    Parameters
    ----------
    item_id : UUID | None
        Exact already-admitted item, absent for edition-wide control operations.

    Raises
    ------
    GuidanceLimitError
        If evidence or its still-required withdrawal reserve exceeds the cap.
    """
    if item_id is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH selected AS (SELECT %s::uuid AS id),
            revisions AS (
                SELECT row.* FROM knowledge_guidancerevision row, selected
                WHERE row.item_id=selected.id),
            rules AS (
                SELECT row.* FROM knowledge_guidancesettingsrevision row
                WHERE row.id IN (SELECT settings_revision_id FROM revisions)),
            records AS (
                SELECT to_jsonb(row) AS record FROM revisions row
                UNION ALL SELECT to_jsonb(row) FROM knowledge_guidancereview row
                    JOIN revisions ON revisions.id=row.revision_id
                UNION ALL SELECT to_jsonb(row) FROM rules row
                UNION ALL SELECT to_jsonb(row)
                    FROM knowledge_guidancecommandreceipt row, selected
                    WHERE row.item_id=selected.id
                       OR row.id IN (SELECT command_receipt_id FROM rules)
            ) SELECT coalesce(sum(octet_length(record::text)), 0),
                (SELECT status FROM knowledge_guidanceitem
                 WHERE id=(SELECT id FROM selected)) FROM records
            """,
            [item_id],
        )
        retained_bytes, status = cursor.fetchone()
        reserve = 0 if status == "withdrawn" else WITHDRAWAL_RECEIPT_RESERVE_BYTES
        if status is None or retained_bytes + reserve > MAX_STORED_TEXT_BYTES:
            raise GuidanceLimitError


def require_complete_export_bound(
    *, organization_id: UUID, edition_id: UUID, item_id: UUID
) -> None:
    """Bound complete guide and edition-control evidence before loading private text.

    Parameters
    ----------
    organization_id : UUID
        Organization independently admitted for the private evidence export.
    edition_id : UUID
        Exact event whose control history is included under its owning lock.
    item_id : UUID
        The sole guide whose private content and command history are included.

    Raises
    ------
    GuidanceLimitError
        If any complete-history row count or retained UTF-8 byte budget is exceeded.

    Notes
    -----
    Other guides and their commands are excluded. SQL aggregates bounded samples
    only; an extra row refuses the whole export before Python materializes content.
    The final serialized envelope is checked separately against the artifact limit.
    """
    limits = {
        "revisions": MAX_REVISIONS,
        "reviews": MAX_REVISIONS,
        "settings": MAX_CONTROL_HISTORY,
        "controls": MAX_CONTROL_HISTORY,
        "commands": MAX_HISTORY,
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH scope AS (SELECT %s::uuid organization_id,
                                  %s::uuid edition_id, %s::uuid item_id),
            revisions AS (
                SELECT row.* FROM public.knowledge_guidancerevision row, scope
                WHERE row.organization_id=scope.organization_id
                  AND row.edition_id=scope.edition_id AND row.item_id=scope.item_id
                LIMIT %s),
            reviews AS (
                SELECT row.* FROM public.knowledge_guidancereview row, scope
                WHERE row.organization_id=scope.organization_id
                  AND row.edition_id=scope.edition_id
                  AND row.revision_id IN (SELECT id FROM revisions) LIMIT %s),
            settings AS (
                SELECT row.* FROM public.knowledge_guidancesettingsrevision row, scope
                WHERE row.organization_id=scope.organization_id
                  AND row.edition_id=scope.edition_id LIMIT %s),
            receipts AS (
                SELECT row.* FROM public.knowledge_guidancecommandreceipt row, scope
                WHERE row.organization_id=scope.organization_id
                  AND row.edition_id=scope.edition_id
                  AND (row.item_id=scope.item_id OR row.item_id IS NULL) LIMIT %s),
            records AS (
                SELECT 'revisions' kind,to_jsonb(row) record FROM revisions row
                UNION ALL SELECT 'reviews',to_jsonb(row) FROM reviews row
                UNION ALL SELECT 'settings',to_jsonb(row) FROM settings row
                UNION ALL SELECT CASE WHEN item_id IS NULL THEN 'controls'
                                      ELSE 'commands' END,to_jsonb(row)
                    FROM receipts row
            ) SELECT kind,count(*),sum(octet_length(record::text))
                FROM records GROUP BY kind
            """,
            [
                organization_id,
                edition_id,
                item_id,
                MAX_REVISIONS + 1,
                MAX_REVISIONS + 1,
                MAX_CONTROL_HISTORY + 1,
                MAX_HISTORY + MAX_CONTROL_HISTORY + 1,
            ],
        )
        counts = cursor.fetchall()
    if (
        any(count > limits[kind] for kind, count, _size in counts)
        or sum(size for _kind, _count, size in counts) > MAX_EXPORT_BYTES
    ):
        raise GuidanceLimitError
