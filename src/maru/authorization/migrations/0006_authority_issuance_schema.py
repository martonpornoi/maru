"""Add the append-only ADR 0044 authority issuance ledger.

This is the additive compatibility stage.  Existing authority remains valid
without an issuance row until the later writer, reconciliation, and activation
stages.  Rows that are present already have an exact typed target, immutable
identity, and structurally valid controller evidence.
"""

import uuid
from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

IMMUTABILITY_FORWARD_SQL = r"""
CREATE FUNCTION maru_validate_authority_issuance_insert()
RETURNS trigger AS $$
DECLARE
    delegated_parent_id uuid;
    parent_issuance_ordinal bigint;
BEGIN
    IF NEW.capability_grant_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT delegated_from_id INTO delegated_parent_id
      FROM authorization_capabilitygrant
     WHERE id = NEW.capability_grant_id;

    IF delegated_parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT ordinal INTO parent_issuance_ordinal
      FROM authorization_authorityissuance
     WHERE capability_grant_id = delegated_parent_id;

    IF parent_issuance_ordinal IS NULL
       OR parent_issuance_ordinal >= NEW.ordinal THEN
        RAISE EXCEPTION 'delegated grant requires an earlier parent issuance'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_authority_issuance_insert_guard
BEFORE INSERT
ON authorization_authorityissuance
FOR EACH ROW EXECUTE FUNCTION maru_validate_authority_issuance_insert();

CREATE FUNCTION maru_prevent_authority_issuance_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority issuances are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority issuances cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_authority_issuance_immutable
BEFORE UPDATE OR DELETE
ON authorization_authorityissuance
FOR EACH ROW EXECUTE FUNCTION maru_prevent_authority_issuance_mutation();

CREATE FUNCTION maru_prevent_authority_control_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'authority controls are immutable'
            USING ERRCODE = '23514';
    END IF;
    RAISE EXCEPTION 'authority controls cannot be deleted'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_authority_control_immutable
BEFORE UPDATE OR DELETE
ON authorization_authoritycontrol
FOR EACH ROW EXECUTE FUNCTION maru_prevent_authority_control_mutation();

"""


IMMUTABILITY_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_authority_control_immutable
    ON authorization_authoritycontrol;
DROP FUNCTION IF EXISTS maru_prevent_authority_control_mutation();
DROP TRIGGER IF EXISTS authorization_authority_issuance_immutable
    ON authorization_authorityissuance;
DROP FUNCTION IF EXISTS maru_prevent_authority_issuance_mutation();
DROP TRIGGER IF EXISTS authorization_authority_issuance_insert_guard
    ON authorization_authorityissuance;
DROP FUNCTION IF EXISTS maru_validate_authority_issuance_insert();
"""


CONTROL_GUARD_FORWARD_SQL = r"""
CREATE FUNCTION maru_validate_authority_control_insert()
RETURNS trigger AS $$
DECLARE
    target_actor uuid;
    target_approver uuid;
    target_recipient uuid;
    target_organization uuid;
    target_edition uuid;
    target_department uuid;
    target_resource_binding uuid;
    target_effective_from timestamptz;
    target_expires_at timestamptz;
    required_capability varchar;
    issuance_policy_version varchar;
    issuance_evaluated_at timestamptz;
    target_is_delegated boolean;
    target_is_executive_board boolean;
    source_ordinal bigint;
    source_principal uuid;
    source_organization uuid;
    source_edition uuid;
    source_department uuid;
    source_resource_binding uuid;
    source_effective_from timestamptz;
    source_expires_at timestamptz;
    source_revoked_at timestamptz;
    source_capability varchar;
    source_capabilities varchar[];
    source_principal_active boolean;
    source_is_role_bundle boolean;
    representation_organization uuid;
    representation_activator uuid;
    representation_activator_kind varchar;
    representation_activated_at timestamptz;
    appointment_organization uuid;
    appointment_principal uuid;
    appointment_state varchar;
    appointment_role varchar;
    appointment_responded_at timestamptz;
    appointment_representation_activated_at timestamptz;
BEGIN
    SELECT
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN capability_grant.granted_by_id
            WHEN issuance.role_bundle_id IS NOT NULL
                THEN role_bundle.created_by_id
            ELSE role_assignment.granted_by_id
        END,
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN capability_grant.approved_by_id
            WHEN issuance.role_bundle_id IS NOT NULL
                THEN role_bundle.approved_by_id
            ELSE role_assignment.approved_by_id
        END,
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN capability_grant.principal_id
            WHEN issuance.role_assignment_id IS NOT NULL
                THEN role_assignment.principal_id
            ELSE NULL
        END,
        COALESCE(
            capability_grant.organization_id,
            role_bundle.organization_id,
            role_assignment.organization_id
        ),
        COALESCE(capability_grant.edition_id, role_assignment.edition_id),
        COALESCE(capability_grant.department_id, role_assignment.department_id),
        COALESCE(
            capability_grant.resource_binding_id,
            role_assignment.resource_binding_id
        ),
        COALESCE(
            capability_grant.effective_from,
            role_assignment.effective_from
        ),
        COALESCE(capability_grant.expires_at, role_assignment.expires_at),
        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN 'authorization.grant_direct'
            ELSE 'authorization.manage_roles'
        END,
        issuance.policy_version,
        issuance.evaluated_at,
        capability_grant.delegated_from_id IS NOT NULL,
        CASE
            WHEN issuance.role_bundle_id IS NOT NULL
                THEN role_bundle.code = 'executive-board'
            WHEN issuance.role_assignment_id IS NOT NULL
                THEN assignment_bundle.code = 'executive-board'
            ELSE FALSE
        END
    INTO
        target_actor,
        target_approver,
        target_recipient,
        target_organization,
        target_edition,
        target_department,
        target_resource_binding,
        target_effective_from,
        target_expires_at,
        required_capability,
        issuance_policy_version,
        issuance_evaluated_at,
        target_is_delegated,
        target_is_executive_board
    FROM authorization_authorityissuance AS issuance
    LEFT JOIN authorization_capabilitygrant AS capability_grant
      ON capability_grant.id = issuance.capability_grant_id
    LEFT JOIN authorization_rolebundle AS role_bundle
      ON role_bundle.id = issuance.role_bundle_id
    LEFT JOIN authorization_roleassignment AS role_assignment
      ON role_assignment.id = issuance.role_assignment_id
    LEFT JOIN authorization_rolebundle AS assignment_bundle
      ON assignment_bundle.id = role_assignment.role_bundle_id
    WHERE issuance.ordinal = NEW.issuance_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority control requires an existing issuance'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.policy_version IS DISTINCT FROM issuance_policy_version
       OR NEW.evaluated_at IS DISTINCT FROM issuance_evaluated_at THEN
        RAISE EXCEPTION 'authority control evaluation does not match issuance'
            USING ERRCODE = '23514';
    END IF;

    IF target_is_delegated THEN
        RAISE EXCEPTION 'delegated grant issuances must have zero controls'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.role = 'actor' THEN
        IF target_actor IS NULL OR target_actor IS DISTINCT FROM NEW.principal_id THEN
            RAISE EXCEPTION 'authority control target attribution mismatch'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.role = 'approver' THEN
        IF target_approver IS NULL
           OR target_approver IS DISTINCT FROM NEW.principal_id THEN
            RAISE EXCEPTION 'authority control target attribution mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF target_recipient IS NOT NULL
           AND target_recipient = NEW.principal_id THEN
            RAISE EXCEPTION 'authority control approver cannot be authority recipient'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'authority control role is unknown'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM authorization_authoritycontrol AS other_control
         WHERE other_control.issuance_id = NEW.issuance_id
           AND other_control.principal_id = NEW.principal_id
    ) THEN
        RAISE EXCEPTION 'authority controls require distinct principals'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.basis = 'persistent_authority' THEN
        SELECT
            source.ordinal,
            COALESCE(source_grant.principal_id, source_assignment.principal_id),
            COALESCE(
                source_grant.organization_id,
                source_assignment.organization_id,
                source_bundle.organization_id
            ),
            COALESCE(source_grant.edition_id, source_assignment.edition_id),
            COALESCE(source_grant.department_id, source_assignment.department_id),
            COALESCE(
                source_grant.resource_binding_id,
                source_assignment.resource_binding_id
            ),
            COALESCE(source_grant.effective_from, source_assignment.effective_from),
            COALESCE(source_grant.expires_at, source_assignment.expires_at),
            COALESCE(source_grant.revoked_at, source_assignment.revoked_at),
            source_grant.capability_code,
            source_assignment_bundle.capability_codes,
            source_principal_account.is_active,
            source.role_bundle_id IS NOT NULL
        INTO
            source_ordinal,
            source_principal,
            source_organization,
            source_edition,
            source_department,
            source_resource_binding,
            source_effective_from,
            source_expires_at,
            source_revoked_at,
            source_capability,
            source_capabilities,
            source_principal_active,
            source_is_role_bundle
        FROM authorization_authorityissuance AS source
        LEFT JOIN authorization_capabilitygrant AS source_grant
          ON source_grant.id = source.capability_grant_id
        LEFT JOIN authorization_roleassignment AS source_assignment
          ON source_assignment.id = source.role_assignment_id
        LEFT JOIN authorization_rolebundle AS source_assignment_bundle
          ON source_assignment_bundle.id = source_assignment.role_bundle_id
        LEFT JOIN authorization_rolebundle AS source_bundle
          ON source_bundle.id = source.role_bundle_id
        LEFT JOIN identity_account AS source_principal_account
          ON source_principal_account.id = COALESCE(
              source_grant.principal_id,
              source_assignment.principal_id
          )
        WHERE source.ordinal = NEW.source_issuance_id;

        IF source_ordinal IS NULL OR source_ordinal >= NEW.issuance_id THEN
            RAISE EXCEPTION 'persistent authority source must be an earlier issuance'
                USING ERRCODE = '23514';
        END IF;
        IF source_is_role_bundle OR source_principal IS NULL THEN
            RAISE EXCEPTION 'persistent source must target a grant or assignment'
                USING ERRCODE = '23514';
        END IF;
        IF source_principal IS DISTINCT FROM NEW.principal_id THEN
            RAISE EXCEPTION 'persistent authority source principal mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF source_organization IS DISTINCT FROM target_organization THEN
            RAISE EXCEPTION 'persistent authority source organization mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF source_capability IS DISTINCT FROM required_capability
           AND (
               source_capabilities IS NULL
               OR NOT required_capability = ANY(source_capabilities)
           ) THEN
            RAISE EXCEPTION 'persistent authority source capability mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT maru_authorization_scope_contains(
            source_organization,
            source_edition,
            source_department,
            source_resource_binding,
            target_organization,
            target_edition,
            target_department,
            target_resource_binding
        ) THEN
            RAISE EXCEPTION 'persistent authority source scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF source_principal_active IS DISTINCT FROM TRUE
           OR source_effective_from > NEW.evaluated_at
           OR (
               source_expires_at IS NOT NULL
               AND source_expires_at <= NEW.evaluated_at
           )
           OR source_revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'persistent authority source is not current at evaluation'
                USING ERRCODE = '23514';
        END IF;
        IF target_effective_from IS NOT NULL
           AND (
               target_effective_from < source_effective_from
               OR (
                   source_expires_at IS NOT NULL
                   AND (
                       target_expires_at IS NULL
                       OR target_expires_at > source_expires_at
                   )
               )
           ) THEN
            RAISE EXCEPTION 'authority target exceeds source horizon'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NOT target_is_executive_board THEN
        RAISE EXCEPTION 'representation control requires Executive Board authority'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.basis = 'platform_representation_bootstrap' THEN
        SELECT
            representation.organization_id,
            representation.activated_by_id,
            activator.account_kind,
            representation.activated_at
        INTO
            representation_organization,
            representation_activator,
            representation_activator_kind,
            representation_activated_at
        FROM organizations_organizationrepresentation AS representation
        LEFT JOIN identity_account AS activator
          ON activator.id = representation.activated_by_id
        WHERE representation.id = NEW.representation_id;

        IF representation_organization IS NULL
           OR representation_organization IS DISTINCT FROM target_organization
           OR representation_activator IS DISTINCT FROM NEW.principal_id
           OR representation_activator_kind IS DISTINCT FROM 'platform_administrator'
           OR representation_activated_at IS DISTINCT FROM issuance_evaluated_at THEN
            RAISE EXCEPTION 'platform bootstrap control representation mismatch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.basis = 'representation_acceptance' THEN
        SELECT
            representation.organization_id,
            appointment.account_id,
            appointment.state,
            appointment.role,
            appointment.responded_at,
            representation.activated_at
        INTO
            appointment_organization,
            appointment_principal,
            appointment_state,
            appointment_role,
            appointment_responded_at,
            appointment_representation_activated_at
        FROM organizations_representationappointment AS appointment
        JOIN organizations_organizationrepresentation AS representation
          ON representation.id = appointment.representation_id
        WHERE appointment.id = NEW.appointment_id;

        IF appointment_organization IS NULL
           OR appointment_organization IS DISTINCT FROM target_organization
           OR appointment_principal IS DISTINCT FROM NEW.principal_id
           OR appointment_state NOT IN ('accepted', 'active', 'ended')
           OR appointment_role IS DISTINCT FROM 'controller'
           OR appointment_responded_at IS NULL
           OR appointment_responded_at > issuance_evaluated_at
           OR appointment_representation_activated_at
                IS DISTINCT FROM issuance_evaluated_at THEN
            RAISE EXCEPTION 'representation acceptance control appointment mismatch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'authority control basis is unknown'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER authorization_authority_control_insert_guard
BEFORE INSERT
ON authorization_authoritycontrol
FOR EACH ROW EXECUTE FUNCTION maru_validate_authority_control_insert();
"""


CONTROL_GUARD_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_authority_control_insert_guard
    ON authorization_authoritycontrol;
DROP FUNCTION IF EXISTS maru_validate_authority_control_insert();
"""


def refuse_nonempty_issuance_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Keep the additive ledger when any append-only provenance exists."""

    del schema_editor
    issuance = apps.get_model("authorization", "AuthorityIssuance")
    control = apps.get_model("authorization", "AuthorityControl")
    if issuance.objects.exists() or control.objects.exists():
        raise RuntimeError(
            "Cannot reverse authority issuance schema while provenance evidence "
            "exists. Keep compatible code and fix forward, or restore the whole "
            "database to a consistent pre-provenance point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0005_scope_v2_activation"),
        ("organizations", "0012_idn011_convention_subject_guards"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="AuthorityIssuance",
            fields=[
                (
                    "ordinal",
                    models.BigAutoField(primary_key=True, serialize=False),
                ),
                (
                    "public_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("policy_version", models.CharField(max_length=40)),
                ("evaluated_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "capability_grant",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_issuance",
                        to="authorization.capabilitygrant",
                    ),
                ),
                (
                    "role_assignment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_issuance",
                        to="authorization.roleassignment",
                    ),
                ),
                (
                    "role_bundle",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_issuance",
                        to="authorization.rolebundle",
                    ),
                ),
            ],
            options={"ordering": ("ordinal",)},
        ),
        migrations.CreateModel(
            name="AuthorityControl",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "role",
                    models.CharField(
                        choices=[("actor", "Actor"), ("approver", "Approver")],
                        max_length=20,
                    ),
                ),
                (
                    "basis",
                    models.CharField(
                        choices=[
                            ("persistent_authority", "Persistent authority"),
                            (
                                "platform_representation_bootstrap",
                                "Platform representation bootstrap",
                            ),
                            (
                                "representation_acceptance",
                                "Representation acceptance",
                            ),
                        ],
                        max_length=40,
                    ),
                ),
                ("policy_version", models.CharField(max_length=40)),
                ("evaluated_at", models.DateTimeField()),
                (
                    "appointment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_controls",
                        to="organizations.representationappointment",
                    ),
                ),
                (
                    "principal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_controls",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authority_controls",
                        to="organizations.organizationrepresentation",
                    ),
                ),
                (
                    "issuance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="controls",
                        to="authorization.authorityissuance",
                    ),
                ),
                (
                    "source_issuance",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dependent_controls",
                        to="authorization.authorityissuance",
                    ),
                ),
            ],
            options={"ordering": ("issuance_id", "role", "id")},
        ),
        migrations.AddIndex(
            model_name="authorityissuance",
            index=models.Index(
                fields=["evaluated_at", "ordinal"],
                name="auth_issuance_eval_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityissuance",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("capability_grant__isnull", False),
                        ("role_assignment__isnull", True),
                        ("role_bundle__isnull", True),
                    ),
                    models.Q(
                        ("capability_grant__isnull", True),
                        ("role_assignment__isnull", True),
                        ("role_bundle__isnull", False),
                    ),
                    models.Q(
                        ("capability_grant__isnull", True),
                        ("role_assignment__isnull", False),
                        ("role_bundle__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="authorization_issuance_exact_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="authorityissuance",
            constraint=models.CheckConstraint(
                condition=models.Q(("policy_version", ""), _negated=True),
                name="authorization_issuance_policy_required",
            ),
        ),
        migrations.AddIndex(
            model_name="authoritycontrol",
            index=models.Index(
                fields=["principal", "role"],
                name="auth_control_principal_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="authoritycontrol",
            index=models.Index(
                fields=["basis", "principal"],
                name="auth_control_basis_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="authoritycontrol",
            constraint=models.UniqueConstraint(
                fields=("issuance", "role"),
                name="authorization_control_role_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="authoritycontrol",
            constraint=models.UniqueConstraint(
                fields=("issuance", "principal"),
                name="authorization_control_principal_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="authoritycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(("role__in", ("actor", "approver"))),
                name="authorization_control_role_known",
            ),
        ),
        migrations.AddConstraint(
            model_name="authoritycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("appointment__isnull", True),
                        ("basis", "persistent_authority"),
                        ("representation__isnull", True),
                        ("source_issuance__isnull", False),
                    ),
                    models.Q(
                        ("appointment__isnull", True),
                        ("basis", "platform_representation_bootstrap"),
                        ("representation__isnull", False),
                        ("role", "actor"),
                        ("source_issuance__isnull", True),
                    ),
                    models.Q(
                        ("appointment__isnull", False),
                        ("basis", "representation_acceptance"),
                        ("representation__isnull", True),
                        ("role", "approver"),
                        ("source_issuance__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="authorization_control_basis_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="authoritycontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(("policy_version", ""), _negated=True),
                name="authorization_control_policy_required",
            ),
        ),
        migrations.RunSQL(
            IMMUTABILITY_FORWARD_SQL,
            reverse_sql=IMMUTABILITY_REVERSE_SQL,
        ),
        migrations.RunSQL(
            CONTROL_GUARD_FORWARD_SQL,
            reverse_sql=CONTROL_GUARD_REVERSE_SQL,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_nonempty_issuance_downgrade,
        ),
    ]
