"""Tenant-bounded projections for organizers, applicants, and reviewers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Prefetch
from django.utils import timezone

from maru.applications.adoption import profile_allows_application_self
from maru.applications.commands import ApplicationAuthorizationDenied, _reviewer_basis
from maru.applications.legacy_targets import (
    LEGACY_APPLICATION_TARGET_KINDS,
    is_legacy_application_target,
)
from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationState,
    ApplicationSubmission,
)
from maru.applications.source_adapters import applicant_is_eligible
from maru.applications.starters import ApplicationStarter, starter_catalog_for_profile
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_self_target,
)
from maru.events.models import EventEdition
from maru.identity.models import Account

if TYPE_CHECKING:
    from uuid import UUID

MAX_REVIEW_QUEUE = 500
MAX_PERSONAL_EDITION_CANDIDATES = 500


def _authorized_edition(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> EventEdition:
    current_actor = Account.objects.filter(id=actor.id, is_active=True).first()
    edition = EventEdition.objects.filter(
        id=edition_id, organization_id=organization_id
    ).first()
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    decision = (
        decide(
            principal=current_actor,
            capability_code=capability_code,
            resource=target,
        )
        if current_actor is not None and target is not None
        else None
    )
    if (
        current_actor is None
        or edition is None
        or decision is None
        or not decision.allowed
    ):
        raise ApplicationAuthorizationDenied
    return edition


def _authorized_self(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str = "applications.view_self",
) -> EventEdition:
    current_actor = Account.objects.filter(id=actor.id, is_active=True).first()
    edition = EventEdition.objects.filter(
        id=edition_id, organization_id=organization_id
    ).first()
    target = (
        resolve_self_target(
            principal=current_actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if current_actor is not None
        else None
    )
    decision = (
        decide(
            principal=current_actor,
            capability_code=capability_code,
            resource=target,
        )
        if current_actor is not None and target is not None
        else None
    )
    if (
        current_actor is None
        or edition is None
        or decision is None
        or not decision.allowed
        or not profile_allows_application_self(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
        )
    ):
        raise ApplicationAuthorizationDenied
    return edition


def authorize_application_edition_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> None:
    """Authorize an exact edition route before an API adapter parses input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    capability_code : str
        The stable capability code required by the operation.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=capability_code,
    )


def authorize_application_self_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> None:
    """Authorize an exact self route before an API adapter parses input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    capability_code : str
        The stable capability code required by the operation.
    """
    _authorized_self(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=capability_code,
    )


def authorize_application_self_submission_api_scope(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> None:
    """Authorize exact applicant ownership without loading answer projections.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    submission_id : UUID
        The submission identifier within the requested scope.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    _authorized_self(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.apply_self",
    )
    if not ApplicationSubmission.objects.filter(
        id=submission_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=actor.id,
        definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
    ).exists():
        raise ApplicationAuthorizationDenied


def authorize_application_review_submission_api_scope(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> None:
    """Authorize exact reviewer assignment without loading sensitive answers.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    submission_id : UUID
        The submission identifier within the requested scope.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
    )
    submission = (
        ApplicationSubmission.objects.select_related("definition")
        .filter(
            id=submission_id,
            organization_id=organization_id,
            edition_id=edition_id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .first()
    )
    if submission is None:
        raise ApplicationAuthorizationDenied
    if submission.definition.is_sensitive:
        _authorized_edition(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.review_sensitive",
        )
    _reviewer_basis(
        actor=actor,
        definition=submission.definition,
        evaluated_at=timezone.now(),
    )


def definition_workspace(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ApplicationDefinition, ...]:
    """Return definition workspace visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[ApplicationDefinition, ...]
        The authorized definition workspace records in deterministic order.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    return tuple(
        ApplicationDefinition.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .prefetch_related(
            "sections__questions",
            "owner_department_links__department",
            "reviewer_roles__role_bundle",
            "reviewer_people__account",
        )
        .order_by("code", "-version", "id")
    )


def application_starters(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ApplicationStarter, ...]:
    """Return starters admitted by the exact authorized edition profile.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[ApplicationStarter, ...]
        The exact profile-pinned starter catalog in deterministic order.
    """
    edition = _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    return tuple(
        starter
        for starter in starter_catalog_for_profile(
            profile_code=edition.adoption_profile_code,
            profile_version=edition.adoption_profile_version,
        )
        if starter.is_external
        or is_legacy_application_target(str(starter.target_adapter_kind))
    )


def definition_detail(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> ApplicationDefinition:
    """Return definition detail visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.

    Returns
    -------
    ApplicationDefinition
        The authorized ApplicationDefinition visible within the requested scope.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    definition = (
        ApplicationDefinition.objects.filter(
            id=definition_id,
            organization_id=organization_id,
            edition_id=edition_id,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .select_related("created_by", "activated_by", "retired_by")
        .prefetch_related(
            "sections__questions",
            "owner_department_links__department",
            "reviewer_roles__role_bundle",
            "reviewer_people__account",
        )
        .first()
    )
    if definition is None:
        raise ApplicationAuthorizationDenied
    return definition


def available_applications(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ApplicationDefinition, ...]:
    """Return available applications visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[ApplicationDefinition, ...]
        The available applications.
    """
    _authorized_self(
        actor=actor, organization_id=organization_id, edition_id=edition_id
    )
    now = timezone.now()
    candidates = (
        ApplicationDefinition.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=ApplicationDefinitionStatus.ACTIVE,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
            opens_at__lte=now,
            closes_at__gt=now,
        )
        .select_related("edition")
        .prefetch_related("sections__questions")
    )
    return tuple(
        definition
        for definition in candidates
        if applicant_is_eligible(definition=definition, account=actor, at=now)
        and ApplicationSubmission.objects.filter(
            definition=definition, account_id=actor.id
        ).count()
        < definition.max_submissions_per_person
    )


def my_submissions(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ApplicationSubmission, ...]:
    """Return my submissions visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[ApplicationSubmission, ...]
        The authorized my submissions records in deterministic order.
    """
    _authorized_self(
        actor=actor, organization_id=organization_id, edition_id=edition_id
    )
    latest = ApplicationAnswerRevision.objects.select_related("question").order_by(
        "question_key", "-sequence", "-id"
    )
    return tuple(
        ApplicationSubmission.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=actor.id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .select_related("definition")
        .prefetch_related(
            Prefetch("answer_revisions", queryset=latest),
            "review_decisions",
        )
        .order_by("-created_at", "id")
    )


def my_submission_detail(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> ApplicationSubmission:
    """Return my submission detail visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    submission_id : UUID
        The identifier of the submission.

    Returns
    -------
    ApplicationSubmission
        The authorized my submission detail records in deterministic order.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    _authorized_self(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    latest = ApplicationAnswerRevision.objects.select_related("question").order_by(
        "question_key", "-sequence", "-id"
    )
    submission = (
        ApplicationSubmission.objects.filter(
            id=submission_id,
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=actor.id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .select_related("definition")
        .prefetch_related(
            Prefetch("answer_revisions", queryset=latest),
            "definition__sections__questions",
            "review_decisions",
        )
        .first()
    )
    if submission is None:
        raise ApplicationAuthorizationDenied
    return submission


def my_application_editions(*, actor: Account) -> tuple[EventEdition, ...]:
    """Discover personal application editions before an admin context exists.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.

    Returns
    -------
    tuple[EventEdition, ...]
        The matching my application editions records in deterministic order.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    if not Account.objects.filter(
        id=actor.id,
        is_active=True,
        account_kind=Account.Kind.PERSON,
    ).exists():
        raise ApplicationAuthorizationDenied
    now = timezone.now()
    own_scopes = set(
        ApplicationSubmission.objects.filter(
            account_id=actor.id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .values_list("organization_id", "edition_id")
        .distinct()[:MAX_PERSONAL_EDITION_CANDIDATES]
    )
    available_scopes: set[tuple[UUID, UUID]] = set()
    candidate_scopes = tuple(
        ApplicationDefinition.objects.filter(
            status=ApplicationDefinitionStatus.ACTIVE,
            opens_at__lte=now,
            closes_at__gt=now,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .order_by("organization_id", "edition_id")
        .values_list("organization_id", "edition_id")
        .distinct("organization_id", "edition_id")[:MAX_PERSONAL_EDITION_CANDIDATES]
    )
    profile_editions = {
        (edition.organization_id, edition.id): edition
        for edition in EventEdition.objects.filter(
            id__in={edition_id for _, edition_id in own_scopes | set(candidate_scopes)}
        ).only(
            "id",
            "organization_id",
            "adoption_profile_code",
            "adoption_profile_version",
        )
    }
    for organization_id, edition_id in candidate_scopes:
        edition = profile_editions.get((organization_id, edition_id))
        if edition is None or not profile_allows_application_self(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
        ):
            continue
        target = resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        decision = (
            decide(
                principal=actor,
                capability_code="applications.view_self",
                resource=target,
            )
            if target is not None
            else None
        )
        if decision is None or not decision.allowed:
            continue
        definitions = ApplicationDefinition.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=ApplicationDefinitionStatus.ACTIVE,
            opens_at__lte=now,
            closes_at__gt=now,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        ).select_related("edition")
        for definition in definitions:
            if (
                applicant_is_eligible(definition=definition, account=actor, at=now)
                and ApplicationSubmission.objects.filter(
                    definition=definition,
                    account_id=actor.id,
                ).count()
                < definition.max_submissions_per_person
            ):
                available_scopes.add((organization_id, edition_id))
                break
    authorized_ids: set[UUID] = set()
    for organization_id, edition_id in own_scopes | available_scopes:
        edition = profile_editions.get((organization_id, edition_id))
        if edition is None or not profile_allows_application_self(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
        ):
            continue
        target = resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        decision = (
            decide(
                principal=actor,
                capability_code="applications.view_self",
                resource=target,
            )
            if target is not None
            else None
        )
        if decision is not None and decision.allowed:
            authorized_ids.add(edition_id)
    return tuple(
        EventEdition.objects.filter(id__in=authorized_ids)
        .select_related("organization", "series")
        .order_by("-starts_on", "name", "id")
    )


def application_shell_profile_pairs(*, actor: Account) -> tuple[tuple[str, int], ...]:
    """Return fail-closed exact profiles for the personal Applications shell.

    Parameters
    ----------
    actor : Account
        Active account whose purpose-scoped Applications editions are queried.

    Returns
    -------
    tuple[tuple[str, int], ...]
        Distinct exact profile pairs, or an empty tuple when personal
        Applications discovery is unavailable.
    """
    try:
        editions = my_application_editions(actor=actor)
    except ApplicationAuthorizationDenied:
        return ()
    return tuple(
        sorted(
            {
                (
                    edition.adoption_profile_code,
                    edition.adoption_profile_version,
                )
                for edition in editions
            }
        )
    )


def review_queue(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ApplicationSubmission, ...]:
    """Return review queue visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[ApplicationSubmission, ...]
        The authorized review queue records in deterministic order.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
    )
    now = timezone.now()
    latest = ApplicationAnswerRevision.objects.select_related("question").order_by(
        "question_key", "-sequence", "-id"
    )
    candidates = tuple(
        ApplicationSubmission.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
            state__in=(
                ApplicationState.SUBMITTED,
                ApplicationState.UNDER_REVIEW,
                ApplicationState.CHANGES_REQUESTED,
            ),
        )
        .select_related("definition", "account")
        .prefetch_related(
            Prefetch("answer_revisions", queryset=latest), "review_decisions"
        )
        .order_by("submitted_at", "id")[:MAX_REVIEW_QUEUE]
    )
    allowed: list[ApplicationSubmission] = []
    for submission in candidates:
        if submission.definition.is_sensitive:
            target = resolve_edition_target(
                organization_id=organization_id, edition_id=edition_id
            )
            sensitive = (
                decide(
                    principal=actor,
                    capability_code="applications.review_sensitive",
                    resource=target,
                )
                if target is not None
                else None
            )
            if sensitive is None or not sensitive.allowed:
                continue
        try:
            _reviewer_basis(
                actor=actor, definition=submission.definition, evaluated_at=now
            )
        except ApplicationAuthorizationDenied:
            continue
        allowed.append(submission)
    return tuple(allowed)


def review_submission_detail(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> ApplicationSubmission:
    """Return review submission detail visible to the caller.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    submission_id : UUID
        The identifier of the submission.

    Returns
    -------
    ApplicationSubmission
        The authorized ApplicationSubmission visible within the requested scope.

    Raises
    ------
    ApplicationAuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    _authorized_edition(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
    )
    latest = ApplicationAnswerRevision.objects.select_related("question").order_by(
        "question_key", "-sequence", "-id"
    )
    submission = (
        ApplicationSubmission.objects.filter(
            id=submission_id,
            organization_id=organization_id,
            edition_id=edition_id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .select_related("definition", "account")
        .prefetch_related(
            Prefetch("answer_revisions", queryset=latest),
            "definition__owner_department_links",
            "definition__reviewer_roles",
            "definition__reviewer_people",
            "review_decisions__reviewer_role_bundle",
        )
        .first()
    )
    if submission is None:
        raise ApplicationAuthorizationDenied
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if submission.definition.is_sensitive:
        sensitive = (
            decide(
                principal=actor,
                capability_code="applications.review_sensitive",
                resource=target,
            )
            if target is not None
            else None
        )
        if sensitive is None or not sensitive.allowed:
            raise ApplicationAuthorizationDenied
    _reviewer_basis(
        actor=actor,
        definition=submission.definition,
        evaluated_at=timezone.now(),
    )
    return submission
