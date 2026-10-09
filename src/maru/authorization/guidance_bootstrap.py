"""One ordered, qualified two-person Guidance ceremony using ordinary provenance."""

from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.mutation_evidence import audited_mutation
from maru.authorization.guidance_audit import guidance_authority_audit
from maru.authorization.guidance_authority_queries import guidance_root_sources
from maru.authorization.guidance_catalog import GUIDANCE_ROLE_RECIPES
from maru.authorization.guidance_writer import _guidance_authority_writer
from maru.authorization.issuance import create_persistent_dual_control_issuance
from maru.authorization.models import (
    AuthorityIssuance,
    GuidanceAuthoritySetupReceipt,
    GuidanceRecipeQualification,
    GuidanceTeam,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.provenance import role_bundle_provenance_is_historical
from maru.events.guidance_activation_references import guidance_activation_qualification
from maru.identity.models import Account


def establish_guidance_responsibilities(*, activation_id: UUID) -> UUID:
    """Issue controllers before their independently approved content roles.

    Issue exact controllers first, then cross-approved content, inside Events apply.

    Parameters
    ----------
    activation_id : UUID
        Exact retained adoption receipt qualifying this issuance.

    Returns
    -------
    UUID
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    from maru.authorization.guidance_readiness import (  # noqa: PLC0415
        require_guidance_authority_integrity,
    )

    require_guidance_authority_integrity()
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError(
            "Guidance qualification requires the adoption transaction."
        )
    activation = guidance_activation_qualification(activation_id=activation_id)
    if activation is None:
        raise PermissionDenied(
            "The accepted Guidance responsibility plan is unavailable."
        )
    sources = {
        source.account_id: source
        for source in guidance_root_sources(
            organization_id=activation.organization_id, lock=True
        )
    }
    if not {activation.operator_a_id, activation.operator_b_id}.issubset(sources):
        raise PermissionDenied(
            "Both selected people must still hold their accepted "
            "organization responsibility."
        )
    actor = Account.objects.get(id=activation.operator_a_id)
    root_a = AuthorityIssuance.objects.get(
        ordinal=sources[activation.operator_a_id].issuance_ordinal
    )
    root_b = AuthorityIssuance.objects.get(
        ordinal=sources[activation.operator_b_id].issuance_ordinal
    )
    receipt_id = uuid4()
    output_ids = {
        key: uuid4()
        for key in ("controller_a", "controller_b", "content_a", "content_b")
    }
    with (
        audited_mutation(
            guidance_authority_audit(
                actor=actor,
                organization_id=activation.organization_id,
                edition_id=activation.edition_id,
                operation="authorization.guidance.setup",
                target_type="authorization.guidance_setup_receipt",
                target_id=receipt_id,
                correlation_id=activation.correlation_id,
                capability_code="organizations.manage_representation",
            )
        ) as audit,
        _guidance_authority_writer(),
    ):
        team = GuidanceTeam.objects.filter(
            organization_id=activation.organization_id, edition_id=activation.edition_id
        ).first()
        if (team is None) != (activation.purpose == "initial"):
            raise ValidationError(
                "Use the current initial or recovery responsibility plan."
            )
        if team is None:
            team = GuidanceTeam.objects.create(
                organization_id=activation.organization_id,
                edition_id=activation.edition_id,
                original_activation_id=activation_id,
            )
        receipt = GuidanceAuthoritySetupReceipt.objects.create(
            id=receipt_id,
            activation_id=activation_id,
            team=team,
            root_a=root_a,
            root_b=root_b,
            source_audit_id=audit.audit_id,
            correlation_id=activation.correlation_id,
            **{f"{key}_id": value for key, value in output_ids.items()},
        )
        roles = {}
        evaluated_at = timezone.now()
        for recipe in GUIDANCE_ROLE_RECIPES.values():
            role = RoleBundle.objects.filter(
                organization_id=activation.organization_id,
                code=recipe.code,
                version=recipe.version,
            ).first()
            if role is None:
                role = RoleBundle(
                    organization_id=activation.organization_id,
                    code=recipe.code,
                    name=recipe.name,
                    version=recipe.version,
                    capability_codes=list(recipe.capability_codes),
                    created_by_id=activation.operator_a_id,
                    approved_by_id=activation.operator_b_id,
                    reason=activation.reason,
                )
                GuidanceRecipeQualification.objects.create(
                    setup=receipt, role_bundle_id=role.id
                )
                role.save(force_insert=True)
                create_persistent_dual_control_issuance(
                    target=role,
                    actor_source=root_a,
                    approver_source=root_b,
                    evaluated_at=evaluated_at,
                )
            elif (
                tuple(role.capability_codes) != recipe.capability_codes
                or role.name != recipe.name
                or not role_bundle_provenance_is_historical(
                    bundle=role, evaluated_at=evaluated_at, lock=True
                )
            ):
                raise ValidationError(
                    "A retained Guidance recipe differs from its accepted meaning."
                )
            roles[recipe.code] = role
        controllers = {}
        for suffix, principal, approver, own_root, other_root in (
            ("a", activation.operator_a_id, activation.operator_b_id, root_a, root_b),
            ("b", activation.operator_b_id, activation.operator_a_id, root_b, root_a),
        ):
            assignment = RoleAssignment.objects.create(
                id=output_ids[f"controller_{suffix}"],
                organization_id=activation.organization_id,
                edition_id=activation.edition_id,
                principal_id=principal,
                role_bundle=roles["guidance-access-controller"],
                effective_from=evaluated_at,
                granted_by_id=principal,
                approved_by_id=approver,
                reason=activation.reason,
            )
            controllers[suffix] = create_persistent_dual_control_issuance(
                target=assignment,
                actor_source=own_root,
                approver_source=other_root,
                evaluated_at=evaluated_at,
            )
        # These earlier controller ordinals satisfy the explicitly accepted
        # conditional instruction.
        for suffix, other, principal, approver in (
            ("a", "b", activation.operator_a_id, activation.operator_b_id),
            ("b", "a", activation.operator_b_id, activation.operator_a_id),
        ):
            assignment = RoleAssignment.objects.create(
                id=output_ids[f"content_{suffix}"],
                organization_id=activation.organization_id,
                edition_id=activation.edition_id,
                principal_id=principal,
                role_bundle=roles["guidance-operator"],
                effective_from=evaluated_at,
                granted_by_id=principal,
                approved_by_id=approver,
                reason=activation.reason,
            )
            create_persistent_dual_control_issuance(
                target=assignment,
                actor_source=controllers[suffix],
                approver_source=controllers[other],
                evaluated_at=evaluated_at,
            )
    return receipt.id
