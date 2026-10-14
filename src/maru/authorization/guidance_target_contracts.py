"""Closed target qualification shared by writers and historical/current lineage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Never

from django.core.exceptions import ValidationError
from django.db.models import Q

from maru.authorization.guidance_catalog import (
    GUIDANCE_BOOTSTRAP_CAPABILITY,
    GUIDANCE_CONTROL_CAPABILITY,
    GUIDANCE_CONTROLLER_ROLE_CODE,
    GUIDANCE_OPERATOR_ROLE_CODE,
    GUIDANCE_PROTECTED_CAPABILITIES,
    GUIDANCE_ROLE_RECIPES,
)

_INDEPENDENT_PAIR_SIZE = 2

if TYPE_CHECKING:
    from maru.authorization.models import (
        CapabilityGrant,
        RoleAssignment,
        RoleBundle,
    )


@dataclass(frozen=True, slots=True)
class GuidanceTargetQualification:
    """An exact retained source pair, not reusable grant authority.

    Attributes
    ----------
    capability_code : str
        Purpose-specific control capability required for this exact target.
    actor_source : int
        Exact original issuance ordinal authorizing the issuing actor.
    approver_source : int
        Exact original issuance ordinal authorizing the independent approver.
    """

    capability_code: str
    actor_source: int
    approver_source: int


def _invalid() -> Never:
    raise ValidationError(
        "Guidance access requires its exact accepted responsibility evidence.",
        code="guidance_qualification_required",
    )


def guidance_target_qualification(  # noqa: PLR0912 - Closed target-kind and issuance-slot proof.
    target: CapabilityGrant | RoleAssignment | RoleBundle,
) -> GuidanceTargetQualification | None:
    """Reject unqualified protected targets; return their exact retained source pair.

    Parameters
    ----------
    target : CapabilityGrant | RoleAssignment | RoleBundle
        Persisted scoped authority target and its exact retained provenance.

    Returns
    -------
    GuidanceTargetQualification | None
        The admitted immutable result; it grants no additional authority.
    """
    from maru.authorization.models import (  # noqa: PLC0415
        CapabilityGrant,
        GuidanceAccessDecision,
        GuidanceAuthoritySetupReceipt,
        GuidanceRecipeQualification,
        RoleBundle,
    )
    from maru.events.guidance_activation_references import (  # noqa: PLC0415
        guidance_activation_qualification,
    )

    if isinstance(target, CapabilityGrant):
        if target.capability_code in GUIDANCE_PROTECTED_CAPABILITIES:
            _invalid()
        return None
    bundle = target if isinstance(target, RoleBundle) else target.role_bundle
    if (
        not GUIDANCE_PROTECTED_CAPABILITIES.intersection(bundle.capability_codes)
        and bundle.code not in GUIDANCE_ROLE_RECIPES
    ):
        return None
    recipe = GUIDANCE_ROLE_RECIPES.get(bundle.code)
    if (
        recipe is None
        or bundle.version != recipe.version
        or bundle.name != recipe.name
        or tuple(bundle.capability_codes) != recipe.capability_codes
    ):
        _invalid()
    if isinstance(target, RoleBundle):
        qualification = (
            GuidanceRecipeQualification.objects.select_related("setup__team")
            .filter(role_bundle_id=bundle.id)
            .first()
        )
        setup = qualification.setup if qualification is not None else None
    else:
        if (
            target.edition_id is None
            or target.department_id is not None
            or target.resource_binding_id is not None
        ):
            _invalid()
        setup = (
            GuidanceAuthoritySetupReceipt.objects.select_related("team")
            .filter(
                Q(controller_a_id=target.id)
                | Q(controller_b_id=target.id)
                | Q(content_a_id=target.id)
                | Q(content_b_id=target.id)
            )
            .first()
        )
    if setup is not None:
        activation = guidance_activation_qualification(
            activation_id=setup.activation_id
        )
        if (
            activation is None
            or setup.team.organization_id != target.organization_id
            or setup.team.edition_id != activation.edition_id
            or activation.organization_id != target.organization_id
        ):
            _invalid()
        if isinstance(target, RoleBundle):
            if (
                bundle.created_by_id != activation.operator_a_id
                or bundle.approved_by_id != activation.operator_b_id
            ):
                _invalid()
            return GuidanceTargetQualification(
                GUIDANCE_BOOTSTRAP_CAPABILITY, setup.root_a_id, setup.root_b_id
            )
        if target.edition_id != setup.team.edition_id:
            _invalid()
        is_a = target.id in (setup.controller_a_id, setup.content_a_id)
        own = activation.operator_a_id if is_a else activation.operator_b_id
        other = activation.operator_b_id if is_a else activation.operator_a_id
        if (
            target.principal_id != own
            or target.granted_by_id != own
            or target.approved_by_id != other
            or target.expires_at is not None
        ):
            _invalid()
        if target.id in (setup.controller_a_id, setup.controller_b_id):
            if bundle.code != GUIDANCE_CONTROLLER_ROLE_CODE:
                _invalid()
            return GuidanceTargetQualification(
                GUIDANCE_BOOTSTRAP_CAPABILITY,
                setup.root_a_id if is_a else setup.root_b_id,
                setup.root_b_id if is_a else setup.root_a_id,
            )
        if bundle.code != GUIDANCE_OPERATOR_ROLE_CODE:
            _invalid()
        from maru.authorization.models import (  # noqa: PLC0415
            AuthorityIssuance,
        )

        sources = dict(
            AuthorityIssuance.objects.filter(
                role_assignment_id__in=(setup.controller_a_id, setup.controller_b_id)
            ).values_list("role_assignment_id", "ordinal")
        )
        if len(sources) != _INDEPENDENT_PAIR_SIZE:
            _invalid()
        return GuidanceTargetQualification(
            GUIDANCE_CONTROL_CAPABILITY,
            sources[setup.controller_a_id if is_a else setup.controller_b_id],
            sources[setup.controller_b_id if is_a else setup.controller_a_id],
        )
    if isinstance(target, RoleBundle) or bundle.code == GUIDANCE_CONTROLLER_ROLE_CODE:
        _invalid()
    decision = (
        GuidanceAccessDecision.objects.select_related("request")
        .filter(assignment_id=target.id, accepted=True)
        .first()
    )
    if decision is None:
        _invalid()
    request = decision.request
    if (
        decision.actor_id != request.approver_id
        or decision.request_digest != request.request_digest
        or decision.created_at > request.decision_deadline
        or target.organization_id != request.organization_id
        or target.edition_id != request.edition_id
        or target.principal_id != request.recipient_id
        or target.granted_by_id != request.requested_by_id
        or target.approved_by_id != request.approver_id
        or target.role_bundle_id != request.role_bundle_id
        or target.effective_from != request.effective_from
        or target.expires_at != request.expires_at
        or target.reason != request.reason
    ):
        _invalid()
    return GuidanceTargetQualification(
        GUIDANCE_CONTROL_CAPABILITY, request.actor_source_id, request.approver_source_id
    )


def required_target_control_capability(
    target: CapabilityGrant | RoleAssignment | RoleBundle,
) -> str:
    """Validate the retained Guidance qualification.

    Keep generic targets unchanged and qualify only the closed Guidance target set.

    Parameters
    ----------
    target : CapabilityGrant | RoleAssignment | RoleBundle
        Persisted scoped authority target and its exact retained provenance.

    Returns
    -------
    str
        The admitted immutable result; it grants no additional authority.
    """
    from maru.authorization.models import (  # noqa: PLC0415
        CapabilityGrant,
    )

    qualification = guidance_target_qualification(target)
    if qualification is not None:
        return qualification.capability_code
    return (
        "authorization.grant_direct"
        if isinstance(target, CapabilityGrant)
        else "authorization.manage_roles"
    )


def guidance_control_source_matches(
    *,
    target: CapabilityGrant | RoleAssignment | RoleBundle,
    role: str,
    ordinal: int | None,
) -> bool:
    """Retain the exact accepted Guidance responsibility.

    Retain the exact approved ancestor; equivalent current authority never rebinds
    it.

    Parameters
    ----------
    target : CapabilityGrant | RoleAssignment | RoleBundle
        Persisted scoped authority target and its exact retained provenance.
    role : str
        Actor or independent approver slot in the dual-control issuance.
    ordinal : int | None
        Original source issuance ordinal; equivalent authority is not substituted.

    Returns
    -------
    bool
        Whether the complete exact contract is currently satisfied.
    """
    try:
        qualification = guidance_target_qualification(target)
    except ValidationError:
        return False
    return qualification is None or ordinal == (
        qualification.actor_source if role == "actor" else qualification.approver_source
    )
