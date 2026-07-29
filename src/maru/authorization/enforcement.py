"""Reusable enforcement primitives for projections and bulk target sets."""

from collections.abc import Callable, Sequence
from typing import cast
from uuid import UUID

from django.db import connection, models
from django.db.models import QuerySet

from maru.authorization.policy import PolicyDecision


class FieldProjectionDeniedError(Exception):
    """The policy ceiling does not contain the complete API projection."""


class BulkTargetUnavailableError(Exception):
    """At least one requested target is absent from the trusted base query."""


class BulkTargetDeniedError(Exception):
    """At least one frozen target is outside the principal's authority."""

    def __init__(self, *, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("At least one bulk target is not authorized.")


def require_complete_projection(
    *,
    required_fields: frozenset[str],
    permitted_fields: frozenset[str],
) -> None:
    """Fail closed rather than return a partially accidental serializer shape."""

    if not required_fields.issubset(permitted_fields):
        raise FieldProjectionDeniedError


def freeze_bulk_targets[TargetT: models.Model](
    *,
    trusted_queryset: QuerySet[TargetT],
    target_ids: Sequence[UUID],
    authorize: Callable[[TargetT], PolicyDecision],
) -> tuple[TargetT, ...]:
    """Lock, resolve, and authorize an exact target set before any mutation.

    The caller owns the tenant/edition filtering of ``trusted_queryset`` and
    must open a transaction. Missing and out-of-scope identifiers are treated
    identically because neither can appear in the trusted base query.
    """

    if not connection.in_atomic_block:
        raise RuntimeError("Bulk target freezing requires an atomic transaction.")
    if not target_ids or len(target_ids) != len(set(target_ids)):
        raise ValueError("Bulk target identifiers must be non-empty and unique.")

    requested_ids = tuple(target_ids)
    requested_set = frozenset(requested_ids)
    locked_targets = tuple(
        trusted_queryset.select_for_update().filter(pk__in=requested_set).order_by("pk")
    )
    targets_by_id = {cast(UUID, target.pk): target for target in locked_targets}
    if frozenset(targets_by_id) != requested_set:
        raise BulkTargetUnavailableError

    ordered_targets = tuple(targets_by_id[target_id] for target_id in requested_ids)
    for target in ordered_targets:
        decision = authorize(target)
        if not decision.allowed:
            raise BulkTargetDeniedError(reason_code=decision.reason_code)
    return ordered_targets
