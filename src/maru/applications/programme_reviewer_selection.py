"""Purpose-bound named reviewer selection without mutable-email retry rebasing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core import signing
from django.db import transaction

from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference_by_email,
)

from .models import (
    ProgrammeReviewAction,
    ProgrammeReviewAssignment,
    ProgrammeReviewEntry,
    ProgrammeReviewState,
)
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_review_inputs import MAX_STAGE_REVIEWERS
from .programme_review_management_queries import _case, _scope
from .programme_review_queries import ProgrammeReviewReadRequest, _audit
from .programme_review_rules import (
    ProgrammeReviewConflictError,
    is_proposal_contributor,
    revision_is_current,
)

if TYPE_CHECKING:
    from .models import ProgrammeReviewCase
    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_SALT = "applications.programme-reviewer-selection.v1"
MAX_REVIEWER_SELECTION_BYTES = 2048
_MAX_VERSION = 2**63 - 1


@dataclass(frozen=True, slots=True)
class ProgrammeReviewerSelection:
    """Retain one exact known-email selection, never a permission grant.

    Attributes
    ----------
    account_id : UUID
        Exact person selected by the authorized manager.
    display_label : str
        Fresh active-verified-person label or a neutral unavailable fallback.
    person_current : bool
        Whether the exact selected person currently has an admitted label.
    expected_version : int
        Original case version, never implicitly refreshed.
    retry_key : UUID
        Original intent identifier bound to this selected person and scope.
    token : str
        Bounded purpose-signed identifier-only request integrity proof.
    """

    account_id: UUID
    display_label: str
    person_current: bool
    expected_version: int
    retry_key: UUID
    token: str


def _binding(request: ProgrammeReviewReadRequest, case_id: UUID) -> dict[str, str]:
    return {
        "actor": str(request.actor_id),
        "organization": str(request.organization_id),
        "edition": str(request.edition_id),
        "department": str(request.department_id),
        "case": str(case_id),
    }


def _intent(case_id: UUID, expected_version: int, retry_key: UUID) -> None:
    require_programme_uuid(case_id, field="case_id")
    require_programme_uuid(retry_key, field="retry_key")
    if type(expected_version) is not int or not 1 <= expected_version <= _MAX_VERSION:
        raise Denied


def _suitable(case: ProgrammeReviewCase, account_id: UUID) -> bool:
    return not (
        case.created_by_id == account_id
        or is_proposal_contributor(case.proposal, account_id)
        or ProgrammeReviewEntry.objects.filter(
            case_id=case.id,
            actor_id=account_id,
            action__in=(ProgrammeReviewAction.MODERATED, ProgrammeReviewAction.DECIDED),
        ).exists()
        or ProgrammeReviewAssignment.objects.filter(
            case_id=case.id, stage=case.stage, account_id=account_id
        ).exists()
        or ProgrammeReviewAssignment.objects.filter(
            case_id=case.id, stage=case.stage
        ).count()
        >= MAX_STAGE_REVIEWERS
    )


def _projection(
    account_id: UUID, expected_version: int, retry_key: UUID, token: str
) -> ProgrammeReviewerSelection:
    labels = active_verified_person_account_display_labels((account_id,))
    return ProgrammeReviewerSelection(
        account_id,
        labels.get(account_id, "Unavailable person"),
        account_id in labels,
        expected_version,
        retry_key,
        token,
    )


@transaction.atomic
def prepare_programme_reviewer_selection(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    email: str,
    expected_version: int,
    retry_key: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeReviewerSelection | None:
    """Preview one known-email candidate after exact manager and case admission.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department manager requesting only review_context.
    case_id : UUID
        Exact currently open case selected from the authorized queue.
    email : str
        Known exact email, normalized exclusively by Identity and never retained.
    expected_version : int
        Original case version for the prospective assignment intent.
    retry_key : UUID
        Original retry key to preserve through confirmation and recovery.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ProgrammeReviewerSelection | None
        Audited minimized selection, or one empty result for every unsuitable person.

    Raises
    ------
    ProgrammeReviewConflictError
        If the selected case is stale or unavailable for fresh assignment preview.
    """
    _intent(case_id, expected_version, retry_key)
    scope = _scope(request, authorizer)
    case = _case(request, case_id)
    if (
        case.version != expected_version
        or case.state != ProgrammeReviewState.OPEN
        or not revision_is_current(case)
        or not scope.accepts_private_planning_writes
    ):
        raise ProgrammeReviewConflictError
    person = resolve_active_verified_person_reference_by_email(email=email)
    result = None
    if person is not None and _suitable(case, person.account_id):
        token = signing.dumps(
            _binding(request, case_id)
            | {
                "person": str(person.account_id),
                "version": expected_version,
                "retry": str(retry_key),
            },
            salt=_SALT,
        )
        selected = _projection(person.account_id, expected_version, retry_key, token)
        if selected.person_current:
            result = selected
    _audit(request, "reviewer_selection", case_id, authorizer)
    return result


def _decode(
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    token: str,
    expected_version: int,
    retry_key: UUID,
) -> UUID:
    try:
        if (
            not isinstance(token, str)
            or len(token.encode("ascii")) > MAX_REVIEWER_SELECTION_BYTES
            or token.startswith(".")
        ):
            raise Denied
        value = signing.loads(token, salt=_SALT)
        binding = _binding(request, case_id)
        if (
            not isinstance(value, dict)
            or set(value) != {*binding, "person", "version", "retry"}
            or any(value[key] != expected for key, expected in binding.items())
            or type(value["version"]) is not int
            or value["version"] != expected_version
            or value["retry"] != str(retry_key)
            or not isinstance(value["person"], str)
        ):
            raise Denied
        account_id = UUID(value["person"])
        if str(account_id) != value["person"] or not account_id.int:
            raise Denied
    except (signing.BadSignature, ValueError, TypeError) as error:
        raise Denied from error
    return account_id


@transaction.atomic
def read_programme_reviewer_selection(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    token: str,
    expected_version: int,
    retry_key: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeReviewerSelection:
    """Reauthorize the original selected person without resolving mutable email.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact current Department manager requesting only review_context.
    case_id : UUID
        Exact original case, still independently object-authorized.
    token : str
        Original bounded purpose-signed identifier selection, not authority.
    expected_version : int
        Original case version; a newer case does not invalidate receipt recovery.
    retry_key : UUID
        Original exact retry proof, which must match the signed selection.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ProgrammeReviewerSelection
        Fresh minimized label or neutral fallback, preserving the exact person.
    """
    _intent(case_id, expected_version, retry_key)
    _scope(request, authorizer)
    _case(request, case_id)
    account_id = _decode(request, case_id, token, expected_version, retry_key)
    result = _projection(account_id, expected_version, retry_key, token)
    _audit(request, "retained_reviewer_selection", case_id, authorizer)
    return result
