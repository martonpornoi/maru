"""Collect exact Department call configuration and complete immutable policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, TypedDict

from django.db import transaction

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .models import ProgrammeReviewPolicy
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from .programme_queries import (
    ProgrammeCallConfigurationProjection,
    get_managed_programme_call_configuration,
    list_managed_programme_calls,
)
from .programme_review_authorization import MANAGE_REVIEW
from .programme_review_queries import ProgrammeReviewReadRequest, _audit, _locked_scope
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_review_setup_queries import (
    ReviewSetupPolicy,
    get_programme_review_setup_policy,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer

    from .programme_authorization import ApplicationsProgrammeAuthorizer

MAX_EXIT_POLICIES_PER_CALL: Final = 1_000
MAX_EXIT_POLICIES_PER_DEPARTMENT: Final = 5_000
_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


class _CallArguments(TypedDict):
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    correlation_id: UUID
    source_channel: str
    authorizer: ApplicationsProgrammeAuthorizer


@dataclass(frozen=True, slots=True)
class ProgrammeExitCall:
    """One authorized call definition and complete original policy sequence.

    Attributes
    ----------
    configuration, policies
        Existing closed owner projections, without proposals or person discovery.
    """

    configuration: ProgrammeCallConfigurationProjection = field(repr=False)
    policies: tuple[ReviewSetupPolicy, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProgrammeExitConfiguration:
    """Complete configuration for exactly one currently authorized Department.

    Attributes
    ----------
    department_id
        Exact source scope; does not assert whole-edition coverage.
    calls
        All retained call definitions in the owning reader's stable order.
    """

    department_id: UUID = field(repr=False)
    calls: tuple[ProgrammeExitCall, ...] = field(repr=False)


def _policy_inventory(
    request: ProgrammeReviewReadRequest, call_id: UUID
) -> tuple[tuple[UUID, int], ...]:
    rows = tuple(
        ProgrammeReviewPolicy.objects.filter(
            call_id=call_id,
            call__organization_id=request.organization_id,
            call__edition_id=request.edition_id,
            call__owner_department_id=request.department_id,
        )
        .order_by("version")
        .values_list("id", "version")[: MAX_EXIT_POLICIES_PER_CALL + 1]
    )
    if len(rows) > MAX_EXIT_POLICIES_PER_CALL or any(
        version != index + 1 for index, (_identifier, version) in enumerate(rows)
    ):
        raise ProgrammeReviewUnavailableError
    return rows


@transaction.atomic
def load_programme_exit_configuration(
    *,
    request: ProgrammeReviewReadRequest,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitConfiguration:
    """Collect complete call and policy configuration through both source purposes.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Actual requester with exact Department manage-review/setup authority.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independent Applications policy, also requiring call-management permission.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional bulk-purpose authority, never a source permission replacement.

    Returns
    -------
    ProgrammeExitConfiguration
        Bounded complete retained configuration for the one exact Department.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the declared purpose, scope or independent owner permission is denied.
    ProgrammeReviewUnavailableError
        If policy continuity, bounds or final source comparison fails.

    Notes
    -----
    Canonical owner locks serialize configuration writers. A larger cross-owner
    archive must establish its complete Department/person closure before calling
    this audited component. It grants no access to proposal or review bodies.
    """
    if (
        type(request) is not ProgrammeReviewReadRequest
        or request.capability_code != MANAGE_REVIEW
        or request.requested_fields != frozenset({"review_setup"})
        or request.department_id is None
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError

    def purpose() -> None:
        authorize_programme_archive_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    purpose()
    _locked_scope(request, authorizer)
    arguments: _CallArguments = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "department_id": request.department_id,
        "correlation_id": request.correlation_id,
        "source_channel": request.source_channel,
        "authorizer": authorizer,
    }
    summaries = list_managed_programme_calls(**arguments)
    calls = []
    inventory = {}
    total = 0
    for summary in summaries:
        configuration = get_managed_programme_call_configuration(
            call_id=summary.call_id, **arguments
        )
        if configuration.summary != summary:
            raise ProgrammeReviewUnavailableError
        versions = _policy_inventory(request, summary.call_id)
        total += len(versions)
        if total > MAX_EXIT_POLICIES_PER_DEPARTMENT:
            raise ProgrammeReviewUnavailableError
        policies = tuple(
            get_programme_review_setup_policy(
                request=request,
                call_id=summary.call_id,
                version=version,
                authorizer=authorizer,
            )
            for _identifier, version in versions
        )
        if tuple((policy.policy_id, policy.version) for policy in policies) != versions:
            raise ProgrammeReviewUnavailableError
        inventory[summary.call_id] = versions
        calls.append(ProgrammeExitCall(configuration, policies))
    if list_managed_programme_calls(**arguments) != summaries:
        raise ProgrammeReviewUnavailableError
    for call in calls:
        call_id = call.configuration.summary.call_id
        if (
            _policy_inventory(request, call_id) != inventory[call_id]
            or get_managed_programme_call_configuration(call_id=call_id, **arguments)
            != call.configuration
        ):
            raise ProgrammeReviewUnavailableError
    purpose()
    _audit(request, "exit_configuration", request.department_id, authorizer)
    return ProgrammeExitConfiguration(request.department_id, tuple(calls))
