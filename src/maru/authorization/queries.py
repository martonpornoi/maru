"""Minimized, identifier-only reads owned by the authorization module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from django.db.models import Count, Q
from django.utils import timezone

from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)


@dataclass(frozen=True, slots=True)
class DepartmentAuthorityDependencies:
    """Count-only authority dependencies for one exact Department scope.

    Reference counts include every retained row and support protected-deletion
    checks. Effective counts describe access at one instant; current-or-future
    counts additionally include scheduled, unclosed authority and support the
    stricter retirement check.
    """

    resource_binding_count: int
    capability_grant_reference_count: int
    effective_capability_grant_count: int
    current_or_future_capability_grant_count: int
    role_assignment_reference_count: int
    effective_role_assignment_count: int
    current_or_future_role_assignment_count: int

    @property
    def has_resource_binding_history(self) -> bool:
        return self.resource_binding_count > 0

    @property
    def has_effective_capability_grant(self) -> bool:
        return self.effective_capability_grant_count > 0

    @property
    def has_effective_role_assignment(self) -> bool:
        return self.effective_role_assignment_count > 0

    @property
    def has_current_or_future_capability_grant(self) -> bool:
        return self.current_or_future_capability_grant_count > 0

    @property
    def has_current_or_future_role_assignment(self) -> bool:
        return self.current_or_future_role_assignment_count > 0

    @property
    def has_historical_authority_reference(self) -> bool:
        return (
            self.capability_grant_reference_count > 0
            or self.role_assignment_reference_count > 0
        )


def _effective_at(at: datetime) -> Q:
    return (
        Q(effective_from__lte=at)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        & Q(revoked_at__isnull=True)
    )


def _current_or_future_at(at: datetime) -> Q:
    """Select unclosed authority that is effective now or scheduled later."""

    return (Q(expires_at__isnull=True) | Q(expires_at__gt=at)) & Q(
        revoked_at__isnull=True
    )


def department_authority_dependencies(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    at: datetime | None = None,
) -> DepartmentAuthorityDependencies:
    """Return count-only dependencies for one exact persisted scope tuple.

    The caller owns Department resolution and authorization. This boundary
    intentionally queries authorization-owned foreign-key identifiers only;
    it neither imports workforce models nor returns labels, people, reasons,
    capability codes, or authority provenance.
    """

    evaluation_time = at if at is not None else timezone.now()
    if not timezone.is_aware(evaluation_time):
        raise ValueError("The authority dependency evaluation time must be aware.")

    exact_scope = {
        "organization_id": organization_id,
        "edition_id": edition_id,
        "department_id": department_id,
    }
    resource_binding_count = ScopedResourceBinding.objects.filter(
        **exact_scope,
    ).count()
    grant_counts = CapabilityGrant.objects.filter(**exact_scope).aggregate(
        reference_count=Count("id"),
        effective_count=Count("id", filter=_effective_at(evaluation_time)),
        current_or_future_count=Count(
            "id",
            filter=_current_or_future_at(evaluation_time),
        ),
    )
    assignment_counts = RoleAssignment.objects.filter(**exact_scope).aggregate(
        reference_count=Count("id"),
        effective_count=Count("id", filter=_effective_at(evaluation_time)),
        current_or_future_count=Count(
            "id",
            filter=_current_or_future_at(evaluation_time),
        ),
    )

    return DepartmentAuthorityDependencies(
        resource_binding_count=resource_binding_count,
        capability_grant_reference_count=cast(int, grant_counts["reference_count"]),
        effective_capability_grant_count=cast(
            int,
            grant_counts["effective_count"],
        ),
        current_or_future_capability_grant_count=cast(
            int,
            grant_counts["current_or_future_count"],
        ),
        role_assignment_reference_count=cast(
            int,
            assignment_counts["reference_count"],
        ),
        effective_role_assignment_count=cast(
            int,
            assignment_counts["effective_count"],
        ),
        current_or_future_role_assignment_count=cast(
            int,
            assignment_counts["current_or_future_count"],
        ),
    )


def edition_resource_binding_count(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> int:
    """Count retained typed-resource bindings in one exact edition.

    This is the intentionally minimized cross-module boundary used to prove
    that an edition has no workforce authority targets before its first
    structure aggregate is established.  It returns no resource identifiers,
    labels, principals, or authority detail.
    """

    return ScopedResourceBinding.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
    ).count()
