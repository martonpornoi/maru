"""Persistent grants and versioned organizer role bundles."""

import re
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from maru.authorization.catalog import ScopeLevel, capability
from maru.core.models import UUIDTimeStampedModel

ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


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


def validate_role_code(value: str) -> None:
    if not ROLE_CODE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use a stable lowercase role code.",
            code="invalid_role_code",
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
        ]

    def clean(self) -> None:
        super().clean()
        definition = capability(self.capability_code)
        if definition is not None:
            if definition.maximum_scope is ScopeLevel.RESOURCE:
                raise ValidationError(
                    {
                        "capability_code": (
                            "This capability is relationship-derived and cannot "
                            "be granted without a resource."
                        )
                    }
                )
            if definition.maximum_scope is ScopeLevel.EDITION and not self.edition_id:
                raise ValidationError(
                    {"edition": "This capability requires edition scope."}
                )
        edition = self.edition if self.edition_id else None
        if (
            edition is not None
            and self.organization_id
            and edition.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"edition": "The grant edition must belong to its organization."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        scope = self.edition if self.edition_id else self.organization
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
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.role_bundle_id
            and self.organization_id
            and self.role_bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"role_bundle": "The role bundle belongs to another organization."}
            )
        edition = self.edition if self.edition_id else None
        if (
            edition is not None
            and self.organization_id
            and edition.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"edition": "The assignment edition belongs to another organization."}
            )
        if self.role_bundle_id:
            definitions = [
                capability(code) for code in self.role_bundle.capability_codes
            ]
            if any(
                definition is not None
                and definition.maximum_scope is ScopeLevel.RESOURCE
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
            if not self.edition_id and any(
                definition is not None
                and definition.maximum_scope is ScopeLevel.EDITION
                for definition in definitions
            ):
                raise ValidationError(
                    {"edition": "This role bundle requires edition scope."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        scope = self.edition if self.edition_id else self.organization
        return f"{self.principal} — {self.role_bundle.name} for {scope}"
