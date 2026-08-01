"""Persistent grants and versioned organizer role bundles."""

import re
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models

from maru.authorization.catalog import ScopeLevel, capability
from maru.core.models import UUIDTimeStampedModel
from maru.identity.policies import validate_convention_subject

ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class AuthorizationScopeWriteFence(models.Model):
    """Internal durable marker that makes scope-v2 downgrade fail closed."""

    singleton = models.BooleanField(
        primary_key=True,
        default=True,
        editable=False,
    )
    first_written_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "authorization_scopev2writefence"
        default_permissions = ()

    def __str__(self) -> str:
        return "Authorization scope-v2 writes exist"


def validate_capability_code(value: str) -> None:
    if capability(value) is None:
        raise ValidationError(
            "Use a capability declared by the platform.",
            code="unknown_capability",
        )


def validate_capability_codes(values: list[str]) -> None:
    if not values:
        raise ValidationError(
            "A role bundle must contain at least one capability.",
            code="capability_required",
        )
    if len(values) != len(set(values)):
        raise ValidationError(
            "Role capability codes must be unique.",
            code="duplicate_capability",
        )
    for value in values:
        validate_capability_code(value)
        definition = capability(value)
        if definition is not None and not definition.persistable:
            raise ValidationError(
                "Relationship-derived capabilities cannot be stored in a role bundle.",
                code="non_persistable_capability",
            )


def validate_role_code(value: str) -> None:
    if not ROLE_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable lowercase role code.",
            code="invalid_role_code",
        )


class ScopedResourceBinding(UUIDTimeStampedModel):
    """Immutable, typed authorization anchor for one domain-owned resource."""

    class ResourceKind(models.TextChoices):
        WORKFORCE_POSITION = "workforce.position", "Workforce position"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="authorization_resource_bindings",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="authorization_resource_bindings",
    )
    department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="authorization_resource_bindings",
    )
    resource_kind = models.CharField(max_length=80, choices=ResourceKind)
    resource_id = models.UUIDField()

    class Meta:
        ordering = ("organization_id", "edition_id", "department_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("resource_kind", "resource_id"),
                name="authorization_resource_binding_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(resource_kind="workforce.position"),
                name="authorization_resource_kind_known",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "department"),
                name="auth_binding_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError(
                {"edition": "The resource edition must belong to its organization."}
            )
        if self.department_id and (
            self.department.organization_id != self.organization_id
            or self.department.edition_id != self.edition_id
        ):
            raise ValidationError(
                {
                    "department": (
                        "The resource department must belong to its exact edition."
                    )
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Scoped resource bindings are immutable; create a new binding.",
                code="immutable_resource_binding",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Scoped resource bindings are immutable and cannot be deleted.",
            code="immutable_resource_binding",
        )

    def __str__(self) -> str:
        return f"{self.resource_kind}:{self.resource_id} — {self.department}"


def _validate_persistent_scope(
    *,
    organization_id: Any,
    edition_id: Any,
    department_id: Any,
    resource_binding_id: Any,
    edition: Any,
    department: Any,
    resource_binding: Any,
) -> None:
    if department_id and not edition_id:
        raise ValidationError({"department": "Department scope requires an edition."})
    if resource_binding_id and not department_id:
        raise ValidationError(
            {"resource_binding": "Resource scope requires a department."}
        )
    if edition_id and edition.organization_id != organization_id:
        raise ValidationError(
            {"edition": "The scope edition must belong to its organization."}
        )
    if department_id and (
        department.organization_id != organization_id
        or department.edition_id != edition_id
    ):
        raise ValidationError(
            {"department": "The department must belong to the exact edition scope."}
        )
    if resource_binding_id and (
        resource_binding.organization_id != organization_id
        or resource_binding.edition_id != edition_id
        or resource_binding.department_id != department_id
    ):
        raise ValidationError(
            {
                "resource_binding": (
                    "The resource binding must belong to the exact department scope."
                )
            }
        )


def _validate_capability_scope(
    *,
    capability_code: str,
    edition_id: Any,
    department_id: Any,
    resource_binding_id: Any,
) -> None:
    definition = capability(capability_code)
    if definition is None:
        return
    if not definition.persistable:
        raise ValidationError(
            {
                "capability_code": (
                    "This capability is relationship-derived and cannot be stored."
                )
            }
        )
    required_field = {
        ScopeLevel.EDITION: (edition_id, "edition", "edition"),
        ScopeLevel.DEPARTMENT: (
            department_id,
            "department",
            "department",
        ),
        ScopeLevel.RESOURCE: (
            resource_binding_id,
            "resource_binding",
            "an exact resource",
        ),
    }.get(definition.maximum_scope)
    if required_field is not None and not required_field[0]:
        _, field_name, scope_label = required_field
        raise ValidationError(
            {field_name: f"This capability requires {scope_label} scope."}
        )


def _validate_revocation_evidence(
    *,
    revoked_at: Any,
    revoked_by_id: Any,
    revocation_reason: str,
) -> None:
    if revoked_at is None:
        if revoked_by_id is not None or revocation_reason != "":
            raise ValidationError(
                {
                    "revoked_at": (
                        "Revocation evidence is allowed only on a revoked authority."
                    )
                }
            )
        return
    if revoked_by_id is None or not revocation_reason.strip():
        raise ValidationError(
            {
                "revocation_reason": (
                    "A revoked authority requires a revoker and nonblank reason."
                )
            }
        )


class CapabilityGrant(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="capability_grants",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capability_grants",
    )
    department = models.ForeignKey(
        "workforce.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capability_grants",
    )
    resource_binding = models.ForeignKey(
        ScopedResourceBinding,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capability_grants",
    )
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="capability_grants",
    )
    capability_code = models.CharField(
        max_length=120,
        validators=[validate_capability_code],
    )
    effective_from = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="capability_grants_issued",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capability_grants_approved",
    )
    delegated_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delegations",
    )
    reason = models.CharField(max_length=240)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="capability_grants_revoked",
    )
    revocation_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("organization_id", "principal_id", "capability_code", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(expires_at__isnull=True)
                    | models.Q(expires_at__gt=models.F("effective_from"))
                ),
                name="capability_grant_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        department__isnull=True,
                        resource_binding__isnull=True,
                    )
                    | models.Q(edition__isnull=False, department__isnull=False)
                ),
                name="authorization_grant_scope_shape_v2",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization",
                    "edition",
                    "department",
                    "resource_binding",
                ),
                name="auth_grant_scope_v2_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.principal_id:
            validate_convention_subject(self.principal, field_name="principal")
        _validate_capability_scope(
            capability_code=self.capability_code,
            edition_id=self.edition_id,
            department_id=self.department_id,
            resource_binding_id=self.resource_binding_id,
        )
        _validate_persistent_scope(
            organization_id=self.organization_id,
            edition_id=self.edition_id,
            department_id=self.department_id,
            resource_binding_id=self.resource_binding_id,
            edition=self.edition if self.edition_id else None,
            department=self.department if self.department_id else None,
            resource_binding=(
                self.resource_binding if self.resource_binding_id else None
            ),
        )
        _validate_revocation_evidence(
            revoked_at=self.revoked_at,
            revoked_by_id=self.revoked_by_id,
            revocation_reason=self.revocation_reason,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        scope = (
            self.resource_binding
            if self.resource_binding_id
            else self.department
            if self.department_id
            else self.edition
            if self.edition_id
            else self.organization
        )
        return f"{self.principal} — {self.capability_code} for {scope}"


class RoleBundle(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="role_bundles",
    )
    code = models.CharField(max_length=80, validators=[validate_role_code])
    name = models.CharField(max_length=120)
    version = models.PositiveIntegerField()
    capability_codes = ArrayField(
        models.CharField(max_length=120),
        validators=[validate_capability_codes],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_bundle_versions_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_bundle_versions_approved",
    )
    reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("organization_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code", "version"),
                name="role_bundle_version_unique_within_organization",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Role bundle versions are immutable; create a new version.",
                code="immutable_role_version",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} v{self.version} — {self.organization}"


class RoleAssignment(UUIDTimeStampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    department = models.ForeignKey(
        "workforce.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    resource_binding = models.ForeignKey(
        ScopedResourceBinding,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    role_bundle = models.ForeignKey(
        RoleBundle,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    effective_from = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="role_assignments_issued",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments_approved",
    )
    reason = models.CharField(max_length=240)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments_revoked",
    )
    revocation_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("organization_id", "principal_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(expires_at__isnull=True)
                    | models.Q(expires_at__gt=models.F("effective_from"))
                ),
                name="role_assignment_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        department__isnull=True,
                        resource_binding__isnull=True,
                    )
                    | models.Q(edition__isnull=False, department__isnull=False)
                ),
                name="authorization_role_scope_shape_v2",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization",
                    "edition",
                    "department",
                    "resource_binding",
                ),
                name="auth_role_scope_v2_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.principal_id:
            validate_convention_subject(self.principal, field_name="principal")
        if (
            self.role_bundle_id
            and self.organization_id
            and self.role_bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"role_bundle": "The role bundle belongs to another organization."}
            )
        _validate_persistent_scope(
            organization_id=self.organization_id,
            edition_id=self.edition_id,
            department_id=self.department_id,
            resource_binding_id=self.resource_binding_id,
            edition=self.edition if self.edition_id else None,
            department=self.department if self.department_id else None,
            resource_binding=(
                self.resource_binding if self.resource_binding_id else None
            ),
        )
        if self.role_bundle_id:
            definitions = [
                capability(code) for code in self.role_bundle.capability_codes
            ]
            if any(
                definition is not None and not definition.persistable
                for definition in definitions
            ):
                raise ValidationError(
                    {
                        "role_bundle": (
                            "Relationship-derived capabilities cannot be assigned "
                            "through a role bundle."
                        )
                    }
                )
            for code in self.role_bundle.capability_codes:
                _validate_capability_scope(
                    capability_code=code,
                    edition_id=self.edition_id,
                    department_id=self.department_id,
                    resource_binding_id=self.resource_binding_id,
                )
        _validate_revocation_evidence(
            revoked_at=self.revoked_at,
            revoked_by_id=self.revoked_by_id,
            revocation_reason=self.revocation_reason,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        scope = (
            self.resource_binding
            if self.resource_binding_id
            else self.department
            if self.department_id
            else self.edition
            if self.edition_id
            else self.organization
        )
        return f"{self.principal} — {self.role_bundle.name} for {scope}"


class AuthorityIssuance(models.Model):
    """Append-only provenance root for one persistent authority target."""

    ordinal = models.BigAutoField(primary_key=True)
    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    policy_version = models.CharField(max_length=40)
    evaluated_at = models.DateTimeField()
    capability_grant = models.OneToOneField(
        CapabilityGrant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authority_issuance",
    )
    role_bundle = models.OneToOneField(
        RoleBundle,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authority_issuance",
    )
    role_assignment = models.OneToOneField(
        RoleAssignment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authority_issuance",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("ordinal",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        capability_grant__isnull=False,
                        role_bundle__isnull=True,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        capability_grant__isnull=True,
                        role_bundle__isnull=False,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        capability_grant__isnull=True,
                        role_bundle__isnull=True,
                        role_assignment__isnull=False,
                    )
                ),
                name="authorization_issuance_exact_target",
            ),
            models.CheckConstraint(
                condition=~models.Q(policy_version=""),
                name="authorization_issuance_policy_required",
            ),
        ]
        indexes = [
            models.Index(
                fields=("evaluated_at", "ordinal"),
                name="auth_issuance_eval_idx",
            )
        ]

    def __str__(self) -> str:
        return f"Authority issuance {self.ordinal} — {self.target}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Authority issuances are immutable; create a new issuance.",
                code="immutable_authority_issuance",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Authority issuances are immutable and cannot be deleted.",
            code="immutable_authority_issuance",
        )

    def clean(self) -> None:
        super().clean()
        targets = (
            self.capability_grant_id,
            self.role_bundle_id,
            self.role_assignment_id,
        )
        if sum(target is not None for target in targets) != 1:
            raise ValidationError(
                "Authority issuance requires exactly one typed target.",
                code="authority_issuance_target_shape",
            )
        if not self.policy_version.strip():
            raise ValidationError(
                {"policy_version": "Authority issuance requires a policy version."}
            )
        capability_grant = self.capability_grant if self.capability_grant_id else None
        if capability_grant is not None and capability_grant.delegated_from_id:
            delegated_parent = capability_grant.delegated_from
            if delegated_parent is None:
                raise ValidationError(
                    {
                        "capability_grant": (
                            "A delegated grant requires its parent's earlier issuance."
                        )
                    }
                )
            try:
                _ = delegated_parent.authority_issuance
            except ObjectDoesNotExist as error:
                raise ValidationError(
                    {
                        "capability_grant": (
                            "A delegated grant requires its parent's earlier issuance."
                        )
                    }
                ) from error

    @property
    def target(self) -> CapabilityGrant | RoleBundle | RoleAssignment:
        """Return the one typed target guaranteed by the ledger shape."""

        for target in (
            self.capability_grant,
            self.role_bundle,
            self.role_assignment,
        ):
            if target is not None:
                return target
        raise ValidationError(
            "Authority issuance requires exactly one typed target.",
            code="authority_issuance_target_required",
        )


class AuthorityControl(UUIDTimeStampedModel):
    """One immutable actor or approver proof for an authority issuance."""

    class Role(models.TextChoices):
        ACTOR = "actor", "Actor"
        APPROVER = "approver", "Approver"

    class Basis(models.TextChoices):
        PERSISTENT_AUTHORITY = "persistent_authority", "Persistent authority"
        PLATFORM_REPRESENTATION_BOOTSTRAP = (
            "platform_representation_bootstrap",
            "Platform representation bootstrap",
        )
        REPRESENTATION_ACCEPTANCE = (
            "representation_acceptance",
            "Representation acceptance",
        )

    issuance = models.ForeignKey(
        AuthorityIssuance,
        on_delete=models.PROTECT,
        related_name="controls",
    )
    role = models.CharField(max_length=20, choices=Role)
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authority_controls",
    )
    basis = models.CharField(max_length=40, choices=Basis)
    source_issuance = models.ForeignKey(
        AuthorityIssuance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dependent_controls",
    )
    representation = models.ForeignKey(
        "organizations.OrganizationRepresentation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authority_controls",
    )
    appointment = models.ForeignKey(
        "organizations.RepresentationAppointment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="authority_controls",
    )
    policy_version = models.CharField(max_length=40)
    evaluated_at = models.DateTimeField()

    class Meta:
        ordering = ("issuance_id", "role", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("issuance", "role"),
                name="authorization_control_role_unique",
            ),
            models.UniqueConstraint(
                fields=("issuance", "principal"),
                name="authorization_control_principal_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("actor", "approver")),
                name="authorization_control_role_known",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        basis="persistent_authority",
                        source_issuance__isnull=False,
                        representation__isnull=True,
                        appointment__isnull=True,
                    )
                    | models.Q(
                        basis="platform_representation_bootstrap",
                        role="actor",
                        source_issuance__isnull=True,
                        representation__isnull=False,
                        appointment__isnull=True,
                    )
                    | models.Q(
                        basis="representation_acceptance",
                        role="approver",
                        source_issuance__isnull=True,
                        representation__isnull=True,
                        appointment__isnull=False,
                    )
                ),
                name="authorization_control_basis_shape",
            ),
            models.CheckConstraint(
                condition=~models.Q(policy_version=""),
                name="authorization_control_policy_required",
            ),
        ]
        indexes = [
            models.Index(
                fields=("principal", "role"),
                name="auth_control_principal_idx",
            ),
            models.Index(
                fields=("basis", "principal"),
                name="auth_control_basis_idx",
            ),
        ]

    @staticmethod
    def _target_principals(
        target: CapabilityGrant | RoleBundle | RoleAssignment,
    ) -> tuple[Any, Any, Any]:
        if isinstance(target, CapabilityGrant):
            return target.granted_by_id, target.approved_by_id, target.principal_id
        if isinstance(target, RoleAssignment):
            return target.granted_by_id, target.approved_by_id, target.principal_id
        return target.created_by_id, target.approved_by_id, None

    @staticmethod
    def _target_organization_id(
        target: CapabilityGrant | RoleBundle | RoleAssignment,
    ) -> Any:
        return target.organization_id

    @staticmethod
    def _is_executive_board_target(
        target: CapabilityGrant | RoleBundle | RoleAssignment,
    ) -> bool:
        if isinstance(target, RoleBundle):
            return target.code == "executive-board"
        if isinstance(target, RoleAssignment):
            return target.role_bundle.code == "executive-board"
        return False

    def _validate_basis(self) -> None:
        pointers = (
            self.source_issuance_id,
            self.representation_id,
            self.appointment_id,
        )
        expected_pointer: int | UUID | None = None
        if self.basis == self.Basis.PERSISTENT_AUTHORITY:
            expected_pointer = self.source_issuance_id
        elif self.basis == self.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP:
            expected_pointer = self.representation_id
        elif self.basis == self.Basis.REPRESENTATION_ACCEPTANCE:
            expected_pointer = self.appointment_id
        if (
            expected_pointer is None
            or sum(value is not None for value in pointers) != 1
        ):
            raise ValidationError(
                {"basis": "Choose exactly the evidence required by the control basis."}
            )
        if (
            self.basis == self.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
            and self.role != self.Role.ACTOR
        ) or (
            self.basis == self.Basis.REPRESENTATION_ACCEPTANCE
            and self.role != self.Role.APPROVER
        ):
            raise ValidationError(
                {"role": "The special representation basis does not match this role."}
            )

    def _validate_target_identity(self) -> None:
        target = self.issuance.target
        if isinstance(target, CapabilityGrant) and target.delegated_from_id:
            raise ValidationError(
                {"issuance": "Delegated grant issuances must have zero controls."}
            )
        actor_id, approver_id, recipient_id = self._target_principals(target)
        expected_id = actor_id if self.role == self.Role.ACTOR else approver_id
        if expected_id is None or self.principal_id != expected_id:
            raise ValidationError(
                {"principal": "The controller must match the target attribution."}
            )
        if self.role == self.Role.APPROVER and self.principal_id == recipient_id:
            raise ValidationError(
                {"principal": "An authority recipient cannot approve their own record."}
            )
        if (
            self.issuance_id
            and type(self)
            .objects.filter(
                issuance_id=self.issuance_id,
                principal_id=self.principal_id,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {"principal": "Actor and approver controls must be distinct people."}
            )

    def _validate_persistent_basis(self) -> None:
        source = self.source_issuance
        if (
            source is None
            or self.issuance_id is None
            or source.ordinal >= self.issuance_id
        ):
            raise ValidationError(
                {"source_issuance": "Use an earlier persistent authority issuance."}
            )
        if source.role_bundle_id is not None:
            raise ValidationError(
                {
                    "source_issuance": (
                        "A role definition is not a persistent authority source."
                    )
                }
            )
        source_target = source.target
        if not isinstance(source_target, (CapabilityGrant, RoleAssignment)) or (
            source_target.principal_id != self.principal_id
        ):
            raise ValidationError(
                {
                    "source_issuance": (
                        "The source issuance must grant authority to this controller."
                    )
                }
            )
        target = self.issuance.target
        required_capability = (
            "authorization.grant_direct"
            if isinstance(target, CapabilityGrant)
            else "authorization.manage_roles"
        )
        source_capabilities = (
            {source_target.capability_code}
            if isinstance(source_target, CapabilityGrant)
            else set(source_target.role_bundle.capability_codes)
        )
        if required_capability not in source_capabilities:
            raise ValidationError(
                {
                    "source_issuance": (
                        "The source issuance lacks the required control capability."
                    )
                }
            )
        target_scope = (
            target.organization_id,
            target.edition_id if not isinstance(target, RoleBundle) else None,
            target.department_id if not isinstance(target, RoleBundle) else None,
            (
                target.resource_binding_id
                if not isinstance(target, RoleBundle)
                else None
            ),
        )
        source_scope = (
            source_target.organization_id,
            source_target.edition_id,
            source_target.department_id,
            source_target.resource_binding_id,
        )
        if not self._scope_contains(parent=source_scope, child=target_scope):
            raise ValidationError(
                {"source_issuance": "The source does not contain the target scope."}
            )
        if (
            not self.principal.is_active
            or source_target.effective_from > self.evaluated_at
            or (
                source_target.expires_at is not None
                and source_target.expires_at <= self.evaluated_at
            )
            or (source_target.revoked_at is not None)
        ):
            raise ValidationError(
                {"source_issuance": "The source issuance is not current at evaluation."}
            )
        if isinstance(target, (CapabilityGrant, RoleAssignment)) and (
            target.effective_from < source_target.effective_from
            or (
                source_target.expires_at is not None
                and (
                    target.expires_at is None
                    or target.expires_at > source_target.expires_at
                )
            )
        ):
            raise ValidationError(
                {"source_issuance": "The target exceeds the source authority horizon."}
            )

    @staticmethod
    def _scope_contains(
        *,
        parent: tuple[Any, Any, Any, Any],
        child: tuple[Any, Any, Any, Any],
    ) -> bool:
        parent_organization, parent_edition, parent_department, parent_resource = parent
        child_organization, child_edition, child_department, child_resource = child
        return parent_organization == child_organization and (
            parent_edition is None
            or (
                parent_edition == child_edition
                and (
                    parent_department is None
                    or (
                        parent_department == child_department
                        and (
                            parent_resource is None or parent_resource == child_resource
                        )
                    )
                )
            )
        )

    def _validate_representation_basis(self) -> None:
        target = self.issuance.target
        if not self._is_executive_board_target(target):
            raise ValidationError(
                {
                    "basis": (
                        "Representation evidence is reserved for Executive Board "
                        "authority."
                    )
                }
            )
        target_organization_id = self._target_organization_id(target)
        if self.basis == self.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP:
            representation = self.representation
            if representation is None or (
                representation.organization_id != target_organization_id
                or representation.activated_by_id != self.principal_id
                or not self.principal.is_platform_administrator
                or representation.activated_at != self.issuance.evaluated_at
            ):
                raise ValidationError(
                    {
                        "representation": (
                            "Use the exact platform-operated Executive Board "
                            "activation."
                        )
                    }
                )
            return
        appointment = self.appointment
        if appointment is None or (
            appointment.representation.organization_id != target_organization_id
            or (appointment.representation.activated_at != self.issuance.evaluated_at)
            or appointment.account_id != self.principal_id
            or appointment.responded_at is None
            or appointment.responded_at > self.issuance.evaluated_at
            or appointment.state
            not in {
                appointment.State.ACCEPTED,
                appointment.State.ACTIVE,
                appointment.State.ENDED,
            }
        ):
            raise ValidationError(
                {
                    "appointment": (
                        "Use this controller's exact accepted representation "
                        "appointment."
                    )
                }
            )

    def clean(self) -> None:
        super().clean()
        if not self.policy_version.strip():
            raise ValidationError(
                {"policy_version": "Authority control requires a policy version."}
            )
        if self.issuance_id and (
            self.policy_version != self.issuance.policy_version
            or self.evaluated_at != self.issuance.evaluated_at
        ):
            raise ValidationError(
                {"issuance": ("Control policy and evaluation must match the issuance.")}
            )
        self._validate_basis()
        self._validate_target_identity()
        if self.basis == self.Basis.PERSISTENT_AUTHORITY:
            self._validate_persistent_basis()
        else:
            self._validate_representation_basis()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Authority controls are immutable; create a new issuance.",
                code="immutable_authority_control",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Authority controls are immutable and cannot be deleted.",
            code="immutable_authority_control",
        )

    def __str__(self) -> str:
        return f"{self.get_role_display()} control for issuance {self.issuance_id}"
