"""Read an admitted Guidance responsibility task.

Audited activation previews and exact human decision tasks, never an account
directory.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.guidance_authority_queries import (
    guidance_root_sources,
    guidance_team_reference,
)
from maru.events import guidance_setup_readiness
from maru.events.adoption import adoption_profile
from maru.events.guidance_activation_models import GuidanceActivationRequest
from maru.events.guidance_activation_references import guidance_manifest_digest
from maru.events.guidance_setup_queries import require_guidance_setup_actor
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference,
)
from maru.organizations.guidance_activation_references import (
    GuidanceAccountableFoundation,
    guidance_accountable_foundation,
)

_INDEPENDENT_PAIR_SIZE = 2
_MAX_RETAINED_TASKS = 100


@dataclass(frozen=True, slots=True)
class GuidanceOperatorChoice:
    """Retain the exact accepted Guidance responsibility.

    One currently accepted organization controller, exposed only to setup
    oversight.

    Attributes
    ----------
    account_id : UUID
        Identity of the admitted person represented by this choice.
    label : str
        Admitted display label for this specific person.
    """

    account_id: UUID
    label: str


@dataclass(frozen=True, slots=True)
class GuidanceActivationStart:
    """Explain the real foundation state before any Guidance authority exists.

    Attributes
    ----------
    organization_id : UUID
        Exact organization owning this event and its evidence.
    organization_slug : str
        Canonical organization slug for scoped navigation.
    organization_name : str
        Admitted organization display name.
    edition_id : UUID
        Exact event edition within the owning organization.
    edition_name : str
        Admitted event edition display name.
    edition_version : int
        Current event version that a new proposal must bind.
    representation_id : UUID
        Identity of the organization accountable representation.
    representation_state : str
        Current lifecycle state of the accountable representation.
    foundation_ready : bool
        Whether the organization and its accountable representation are active.
    can_propose : bool
        Whether current scope, foundation and root sources admit a new
        ceremony.
    guidance_ready : bool
        Whether the existing team currently has qualified controller authority.
    source_profile_code : str
        Exact adoption profile before the proposed ceremony.
    target_profile_code : str
        Exact adoption profile resulting from the accepted ceremony.
    purpose : str
        Whether the ceremony establishes initial authority or recovers lost
        authority.
    operators : tuple[GuidanceOperatorChoice, ...]
        Accepted current organization-root holders eligible for the initial
        pair.
    """

    organization_id: UUID
    organization_slug: str
    organization_name: str
    edition_id: UUID
    edition_name: str
    edition_version: int
    representation_id: UUID
    representation_state: str
    foundation_ready: bool
    can_propose: bool
    guidance_ready: bool
    source_profile_code: str
    target_profile_code: str
    purpose: str
    operators: tuple[GuidanceOperatorChoice, ...]


@dataclass(frozen=True, slots=True)
class GuidanceActivationRequestView:
    """Retain the exact accepted Guidance responsibility.

    Display the exact responsibility plan before self-acceptance and cross-
    approval.

    Attributes
    ----------
    request_id : UUID
        Opaque identity of the retained immutable request.
    version : int
        Immutable request preview version required for an unchanged decision.
    request_digest : str
        Digest binding the exact immutable request terms.
    organization_id : UUID
        Exact organization owning this event and its evidence.
    organization_slug : str
        Canonical organization slug for scoped navigation.
    organization_name : str
        Admitted organization display name.
    edition_id : UUID
        Exact event edition within the owning organization.
    edition_name : str
        Admitted event edition display name.
    operator_a : GuidanceOperatorChoice
        First named person accepting self-responsibility and approving the
        other.
    operator_b : GuidanceOperatorChoice
        Second named person accepting self-responsibility and approving the
        other.
    source_profile_code : str
        Exact adoption profile before the proposed ceremony.
    target_profile_code : str
        Exact adoption profile resulting from the accepted ceremony.
    purpose : str
        Whether the ceremony establishes initial authority or recovers lost
        authority.
    reason : str
        Private accountable explanation retained with the request.
    expires_at : datetime
        Deadline for completing the original two-person consent ceremony.
    state : str
        Current request state derived from retained decisions and source
        validity.
    own_answer : bool | None
        The viewing person's recorded decision, or None if unanswered.
    accepted_count : int
        Number of named operators whose retained answer accepts the proposal.
    can_answer : bool
        Whether the admitted viewing person may currently answer this request.
    can_apply : bool
        Whether the admitted original proposer may apply both current
        acceptances.
    """

    request_id: UUID
    version: int
    request_digest: str
    organization_id: UUID
    organization_slug: str
    organization_name: str
    edition_id: UUID
    edition_name: str
    operator_a: GuidanceOperatorChoice
    operator_b: GuidanceOperatorChoice
    source_profile_code: str
    target_profile_code: str
    purpose: str
    reason: str
    expires_at: datetime
    state: str
    own_answer: bool | None
    accepted_count: int
    can_answer: bool
    can_apply: bool


def _audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
) -> None:
    if not isinstance(correlation_id, UUID) or correlation_id.int == 0:
        raise ValidationError("Use a non-empty trace.")
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="events.create"
            if actor.is_platform_administrator
            else "organizations.manage_representation",
            operation="events.guidance_adoption.review",
            target_type="events.guidance_activation_request",
            target_id=request_id,
            outcome="allow",
            reason_code="guidance_setup_participant",
            correlation_id=correlation_id,
            source_channel="html",
            obligations=("audit_sensitive_read",),
        )
    )


def load_guidance_activation_start(
    *, actor: Account, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> GuidanceActivationStart:
    """Show inactive foundation next steps to current platform setup oversight.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceActivationStart
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    """
    require_guidance_setup_actor(actor)
    edition = EventEdition.objects.filter(
        id=edition_id, organization_id=organization_id
    ).first()
    foundation = guidance_accountable_foundation(organization_id=organization_id)
    if (
        edition is None
        or foundation is None
        or (edition.adoption_profile_code, edition.adoption_profile_version)
        not in {
            ("guidance_only", 1),
            ("announcements_only", 1),
            ("announcements_guidance", 1),
        }
    ):
        raise PermissionDenied("Guidance setup is unavailable.")
    sources = guidance_root_sources(organization_id=organization_id)
    labels = active_verified_person_account_display_labels(
        account_ids=tuple(source.account_id for source in sources)
    )
    team = guidance_team_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    foundation_ready = (
        foundation.organization_active and foundation.representation_state == "active"
    )
    target_code = (
        "announcements_guidance"
        if edition.adoption_profile_code == "announcements_only"
        else edition.adoption_profile_code
    )
    result = GuidanceActivationStart(
        organization_id,
        foundation.organization_slug,
        foundation.organization_name,
        edition.id,
        edition.name,
        edition.aggregate_version,
        foundation.representation_id,
        foundation.representation_state,
        foundation_ready,
        foundation_ready
        and edition.series.is_active
        and edition.lifecycle in {"draft", "preparing", "ready", "live"}
        and len(sources) >= _INDEPENDENT_PAIR_SIZE
        and not (team and team.ready),
        bool(team and team.ready),
        edition.adoption_profile_code,
        target_code,
        "recovery" if team else "initial",
        tuple(
            GuidanceOperatorChoice(source.account_id, labels[source.account_id])
            for source in sources
            if source.account_id in labels
        ),
    )
    require_guidance_setup_actor(actor)
    _audit(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
    )
    return result


def _admit_request(actor: Account, request: GuidanceActivationRequest) -> None:
    from maru.events.guidance_setup_readiness import (  # noqa: PLC0415
        require_guidance_setup_integrity,
    )

    require_guidance_setup_integrity()
    if actor.is_platform_administrator:
        require_guidance_setup_actor(actor)
        if actor.id != request.proposed_by_id:
            raise PermissionDenied(
                "This setup decision belongs to its original proposer."
            )
    elif (
        actor.id not in {request.operator_a_id, request.operator_b_id}
        or resolve_active_verified_person_reference(account_id=actor.id) is None
        or actor.id
        not in {
            source.account_id
            for source in guidance_root_sources(organization_id=request.organization_id)
        }
    ):
        raise PermissionDenied("This responsibility request is unavailable.")


def _plan_is_current(
    *,
    request: GuidanceActivationRequest,
    edition: EventEdition,
    foundation: GuidanceAccountableFoundation,
) -> bool:
    source = adoption_profile(
        request.source_profile_code, request.source_profile_version
    )
    target = adoption_profile(
        request.target_profile_code, request.target_profile_version
    )
    roots = {
        root.account_id
        for root in guidance_root_sources(organization_id=request.organization_id)
    }
    return bool(
        source is not None
        and target is not None
        and source.key
        == (edition.adoption_profile_code, edition.adoption_profile_version)
        and request.source_manifest_digest == guidance_manifest_digest(source)
        and request.target_manifest_digest == guidance_manifest_digest(target)
        and edition.aggregate_version == request.expected_edition_version
        and edition.adoption_revision == request.expected_adoption_revision
        and foundation.representation_id == request.representation_id
        and foundation.representation_version == request.representation_version
        and foundation.representation_state == "active"
        and foundation.organization_active
        and edition.series.is_active
        and edition.lifecycle in {"draft", "preparing", "ready", "live"}
        and {request.operator_a_id, request.operator_b_id}.issubset(roots)
    )


def load_guidance_activation_request(
    *, actor: Account, request_id: UUID, correlation_id: UUID
) -> GuidanceActivationRequestView:
    """Retain the exact accepted Guidance responsibility.

    Release a named person's exact task after current qualification and final
    recheck.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    request_id : UUID
        Opaque identifier of the original immutable request.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceActivationRequestView
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    """
    from django.db.models import (  # noqa: PLC0415
        Q,
    )

    request = (
        GuidanceActivationRequest.objects.filter(
            Q(proposed_by_id=actor.id)
            | Q(operator_a_id=actor.id)
            | Q(operator_b_id=actor.id),
            id=request_id,
        )
        .only(
            "id",
            "organization_id",
            "edition_id",
            "proposed_by_id",
            "operator_a_id",
            "operator_b_id",
        )
        .first()
    )
    if request is None:
        raise PermissionDenied("This responsibility request is unavailable.")
    _admit_request(actor, request)
    request = GuidanceActivationRequest.objects.get(id=request.id)
    edition = EventEdition.objects.filter(
        id=request.edition_id, organization_id=request.organization_id
    ).first()
    foundation = guidance_accountable_foundation(
        organization_id=request.organization_id
    )
    if edition is None or foundation is None:
        raise PermissionDenied
    labels = active_verified_person_account_display_labels(
        account_ids=(request.operator_a_id, request.operator_b_id)
    )
    if len(labels) != _INDEPENDENT_PAIR_SIZE:
        raise PermissionDenied("The selected people are unavailable.")
    answers = dict(request.decisions.values_list("actor_id", "accepted"))
    applied = hasattr(request, "receipt")
    stale = not _plan_is_current(
        request=request, edition=edition, foundation=foundation
    )
    state = (
        "applied"
        if applied
        else "declined"
        if False in answers.values()
        else "expired"
        if request.expires_at <= timezone.now()
        else "changed"
        if stale
        else "accepted"
        if len(answers) == _INDEPENDENT_PAIR_SIZE
        else "waiting"
    )
    result = GuidanceActivationRequestView(
        request.id,
        1,
        request.request_digest,
        request.organization_id,
        foundation.organization_slug,
        foundation.organization_name,
        request.edition_id,
        edition.name,
        GuidanceOperatorChoice(request.operator_a_id, labels[request.operator_a_id]),
        GuidanceOperatorChoice(request.operator_b_id, labels[request.operator_b_id]),
        request.source_profile_code,
        request.target_profile_code,
        request.purpose,
        request.reason,
        request.expires_at,
        state,
        answers.get(actor.id),
        sum(answers.values()),
        state == "waiting"
        and actor.id in {request.operator_a_id, request.operator_b_id}
        and actor.id not in answers,
        state == "accepted" and actor.id == request.proposed_by_id,
    )
    _admit_request(actor, request)
    _audit(
        actor=actor,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        correlation_id=correlation_id,
        request_id=request.id,
    )
    return result


def list_my_guidance_activation_requests(
    *, actor: Account, correlation_id: UUID
) -> tuple[GuidanceActivationRequestView, ...]:
    """Retain the exact accepted Guidance responsibility.

    List only the current person's bounded responsibility tasks, with no tenant
    scan.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    tuple[GuidanceActivationRequestView, ...]
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    guidance_setup_readiness.GuidanceSetupUnavailable
        If native protection is unavailable for actual participant candidates.
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    from django.db.models import (  # noqa: PLC0415
        Q,
    )

    if not actor.is_active:
        raise PermissionDenied
    ids = tuple(
        GuidanceActivationRequest.objects.filter(
            Q(proposed_by_id=actor.id)
            | Q(operator_a_id=actor.id)
            | Q(operator_b_id=actor.id)
        )
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:101]
    )
    if ids:
        guidance_setup_readiness.require_guidance_setup_integrity()
    if len(ids) > _MAX_RETAINED_TASKS:
        raise ValidationError(
            "Too many retained setup requests; open the exact request.",
            code="guidance_setup_capacity",
        )
    result = []
    for request_id in ids:
        try:
            result.append(
                load_guidance_activation_request(
                    actor=actor, request_id=request_id, correlation_id=correlation_id
                )
            )
        except guidance_setup_readiness.GuidanceSetupUnavailable:
            raise
        except PermissionDenied:
            continue
    if ids:
        guidance_setup_readiness.require_guidance_setup_integrity()
    return tuple(result)


def has_current_guidance_activation_tasks(
    *, actor: Account, correlation_id: UUID
) -> bool:
    """Retain the exact accepted Guidance responsibility.

    Return a content-free personal continuation after current participant
    admission.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    bool
        Whether the complete exact contract is currently satisfied.

    Raises
    ------
    guidance_setup_readiness.GuidanceSetupUnavailable
        If native protection fails during admission or the final candidate check.
    """
    from django.db.models import (  # noqa: PLC0415
        Q,
    )

    if not actor.is_active:
        return False
    candidates = (
        GuidanceActivationRequest.objects.filter(
            Q(proposed_by_id=actor.id)
            | Q(operator_a_id=actor.id)
            | Q(operator_b_id=actor.id),
            expires_at__gt=timezone.now(),
            receipt__isnull=True,
        )
        .exclude(decisions__accepted=False)
        .only(
            "id",
            "organization_id",
            "edition_id",
            "proposed_by_id",
            "operator_a_id",
            "operator_b_id",
        )
        .order_by("created_at", "id")
    )
    bounded_candidates = tuple(candidates[:256])
    for locator in bounded_candidates:
        try:
            _admit_request(actor, locator)
        except guidance_setup_readiness.GuidanceSetupUnavailable:
            raise
        except PermissionDenied:
            continue
        request = GuidanceActivationRequest.objects.get(id=locator.id)
        edition = EventEdition.objects.filter(
            id=request.edition_id, organization_id=request.organization_id
        ).first()
        foundation = guidance_accountable_foundation(
            organization_id=request.organization_id
        )
        if (
            edition is None
            or foundation is None
            or not _plan_is_current(
                request=request, edition=edition, foundation=foundation
            )
        ):
            continue
        own = request.decisions.filter(actor_id=actor.id).exists()
        actionable = (actor.id != request.proposed_by_id and not own) or (
            actor.id == request.proposed_by_id
            and request.decisions.filter(accepted=True).count()
            == _INDEPENDENT_PAIR_SIZE
        )
        if (
            actionable
            and EventEdition.objects.filter(
                id=request.edition_id,
                organization_id=request.organization_id,
                aggregate_version=request.expected_edition_version,
                adoption_revision=request.expected_adoption_revision,
            ).exists()
        ):
            _admit_request(actor, request)
            _audit(
                actor=actor,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                correlation_id=correlation_id,
            )
            return True
    if bounded_candidates:
        guidance_setup_readiness.require_guidance_setup_integrity()
    return False
