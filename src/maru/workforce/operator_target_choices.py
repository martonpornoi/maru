"""Minimal independently admitted Department labels for Programme operator tasks."""

from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.identity.queries import resolve_active_verified_person_reference
from maru.scheduling.command_support import SchedulingUnavailableError

from .models import Department
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)
from .queries import MAX_STRUCTURE_DEPARTMENTS, CurrentDepartmentChoiceReference

_FIELDS = frozenset({"departments"})


class ProgrammeOperatorDepartmentLimitError(ProgrammeStaffingUnavailableError):
    """Complete current Department choices exceed the owner's existing bound."""


def _admit(actor_id: UUID, organization_id: UUID, edition_id: UUID) -> PolicyDecision:
    decision = decide_verified_principal_exact_edition(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="workforce.view_structure",
        requested_fields=_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not decision.fields >= _FIELDS
    ):
        raise ProgrammeStaffingDeniedError
    return decision


def _choices(
    organization_id: UUID, edition_id: UUID
) -> tuple[CurrentDepartmentChoiceReference, ...]:
    rows = tuple(
        Department.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=True,
        )
        .order_by("code", "id")
        .values_list("id", "code", "name")[: MAX_STRUCTURE_DEPARTMENTS + 1]
    )
    if len(rows) > MAX_STRUCTURE_DEPARTMENTS:
        raise ProgrammeOperatorDepartmentLimitError
    return tuple(CurrentDepartmentChoiceReference(*row) for row in rows)


def list_programme_operator_department_choices(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> tuple[CurrentDepartmentChoiceReference, ...]:
    """Read complete current Department labels without loading a personnel tree.

    Parameters
    ----------
    actor_id : UUID
        Actual current verified sender, independently requiring Department fields.
    organization_id : UUID
        Exact expected owner; labels never imply authority to another tenant.
    edition_id : UUID
        Exact adopted Workforce edition, not a caller-supplied permission.
    correlation_id : UUID
        Trusted trace for mandatory positive or empty read evidence.

    Returns
    -------
    tuple[CurrentDepartmentChoiceReference, ...]
        Complete bounded ID/code/name choices for current Departments only.

    Raises
    ------
    ProgrammeStaffingDeniedError
        If scope, current person, profile or independent Department field is denied.
    ProgrammeStaffingUnavailableError
        If labels move or complete/auditable current choices cannot be supplied.

    Notes
    -----
    This single-person owner read finishes before multi-person recipient lookup.
    No positions, holders, hierarchy, work, availability or qualifications are read.
    Source labels are not operator eligibility, a recipient directory or a grant.
    Composing pages repeat the observation before releasing rendered labels.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (
            actor_id,
            organization_id,
            edition_id,
            correlation_id,
        )
    ):
        raise ProgrammeStaffingDeniedError
    try:
        _admit(actor_id, organization_id, edition_id)
        with transaction.atomic():
            lock_programme_staffing_scope(
                organization_id=organization_id, edition_id=edition_id
            )
            if (
                resolve_active_verified_person_reference(account_id=actor_id, lock=True)
                is None
            ):
                raise ProgrammeStaffingDeniedError
            _admit(actor_id, organization_id, edition_id)
            choices = _choices(organization_id, edition_id)
            if _choices(organization_id, edition_id) != choices:
                raise ProgrammeStaffingUnavailableError
            decision = _admit(actor_id, organization_id, edition_id)
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor_id,
                    principal_context_id=None,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    capability_code="workforce.view_structure",
                    operation="workforce.programme_operator_department_choices.read",
                    target_type="workforce.edition_structure",
                    target_id=edition_id,
                    outcome="allow",
                    reason_code=decision.reason_code,
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="programme-change",
                    obligations=tuple(
                        sorted(decision.obligations | {"audit_sensitive_read"})
                    ),
                    safe_metadata={
                        "policy_version": POLICY_VERSION,
                        "access_purpose": "programme_operator_targets",
                    },
                    retention_class="workforce-restricted",
                )
            )
            return choices
    except ValidationError as error:
        raise ProgrammeStaffingDeniedError from error
    except (DatabaseError, SchedulingUnavailableError) as error:
        raise ProgrammeStaffingUnavailableError from error
