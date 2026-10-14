"""Exact bounded retained-current inventory shared by resume preview and command."""

from django.db.models import QuerySet

from .catalog import MAX_ITEMS
from .contracts import GuidanceReadRequest
from .errors import GuidanceLimitError
from .inputs import digest
from .models import GuidanceControl, GuidanceItem


def current_copy_rows(request: GuidanceReadRequest) -> QuerySet[GuidanceItem]:
    """Select only current approved content columns, without any working-copy join.

    Parameters
    ----------
    request : GuidanceReadRequest
        Already admitted exact tenant and edition scope.

    Returns
    -------
    QuerySet[GuidanceItem]
        Narrow owner projection; callers separately enforce stopped availability.
    """
    return (
        GuidanceItem.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            withdrawn=False,
            published_revision__isnull=False,
        )
        .select_related("published_revision__review")
        .only(
            "id",
            "published_revision_id",
            "language_code",
            "published_revision__id",
            "published_revision__number",
            "published_revision__title",
            "published_revision__body",
            "published_revision__language_code",
            "published_revision__review_by",
            "published_revision__placements",
            "published_revision__review__id",
            "published_revision__review__revision_id",
            "published_revision__review__occurred_at",
        )
    )


def retained_current_snapshot(
    request: GuidanceReadRequest,
    control: GuidanceControl,
) -> tuple[tuple[GuidanceItem, ...], str]:
    """Bind the complete retained current set while excluding withdrawn guidance.

    Parameters
    ----------
    request : GuidanceReadRequest
        Already admitted manager scope under canonical owner locks.
    control : GuidanceControl
        Exact locked or coherently observed edition control sequence.

    Returns
    -------
    tuple[tuple[GuidanceItem, ...], str]
        Complete bounded approved rows and their deterministic confirmation digest.

    Raises
    ------
    GuidanceLimitError
        If persisted item count exceeds the declared complete-preview budget.
    """
    rows = tuple(
        current_copy_rows(request)
        .defer("published_revision__body")
        .order_by("id")[: MAX_ITEMS + 1]
    )
    if len(rows) > MAX_ITEMS:
        raise GuidanceLimitError
    fingerprint = digest(
        {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
            "control_version": control.sequence,
            "settings_id": control.current_settings_id,
            "items": [(row.id, row.published_revision_id) for row in rows],
        }
    )
    return rows, fingerprint
