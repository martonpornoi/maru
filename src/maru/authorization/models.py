"""Persistent grants and versioned organizer role bundles."""

import re
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
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
