"""Small accessible reference forms for workforce self-service."""

from typing import Any

from django import forms
from django.db.models import Exists, OuterRef

from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization


class AccountChoiceField(
    forms.ModelChoiceField,  # type: ignore[type-arg]
):
    def label_from_instance(self, obj: Account) -> str:
        label = obj.display_name.strip() or "Unnamed account"
        return f"{label} — {obj.email}"


class ConventionBootstrapForm(forms.Form):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.none(),
        help_text="The independently governed organizer receiving its first authority.",
    )
    edition = forms.ModelChoiceField(
        queryset=EventEdition.objects.none(),
        help_text="The first non-closed edition led by the Convention Chair.",
    )
    chair = AccountChoiceField(
        queryset=Account.objects.none(),
        help_text=(
            "A distinct active account. This account does not become a superuser."
        ),
    )
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Permanent audit evidence explaining the initial appointment.",
    )
    confirm_organization = forms.SlugField(
        label="Type the organization slug to confirm",
        max_length=80,
    )
    controller_password = forms.CharField(
        label="Confirm your administrator password",
        strip=False,
        widget=forms.PasswordInput,
        help_text="Required immediately before creating the first trust relationship.",
    )

    def __init__(
        self,
        *args: Any,
        controller: Account,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.controller = controller
        authority_roles = RoleBundle.objects.filter(organization_id=OuterRef("pk"))
        authority_assignments = RoleAssignment.objects.filter(
            organization_id=OuterRef("pk")
        )
        direct_grants = CapabilityGrant.objects.filter(organization_id=OuterRef("pk"))
        eligible = (
            Organization.objects.filter(lifecycle=Organization.Lifecycle.ACTIVE)
            .annotate(
                _has_roles=Exists(authority_roles),
                _has_assignments=Exists(authority_assignments),
                _has_grants=Exists(direct_grants),
            )
            .filter(
                _has_roles=False,
                _has_assignments=False,
                _has_grants=False,
            )
            .order_by("name")
        )
        organization_field = self.fields["organization"]
        if isinstance(organization_field, forms.ModelChoiceField):
            organization_field.queryset = eligible
        edition_field = self.fields["edition"]
        if isinstance(edition_field, forms.ModelChoiceField):
            edition_field.queryset = (
                EventEdition.objects.filter(
                    organization__in=eligible,
                )
                .exclude(
                    lifecycle__in=(
                        EventEdition.Lifecycle.ARCHIVED,
                        EventEdition.Lifecycle.CANCELLED,
                    )
                )
                .select_related("organization")
                .order_by("organization__name", "-starts_on", "name")
            )
        chair_field = self.fields["chair"]
        if isinstance(chair_field, forms.ModelChoiceField):
            chair_field.queryset = (
                Account.objects.filter(is_active=True)
                .exclude(id=controller.id)
                .order_by("display_name", "email")
            )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        organization = cleaned.get("organization")
        edition = cleaned.get("edition")
        if (
            isinstance(organization, Organization)
            and isinstance(edition, EventEdition)
            and edition.organization_id != organization.id
        ):
            self.add_error(
                "edition",
                "Choose an edition owned by the selected organization.",
            )
        if isinstance(organization, Organization):
            confirmation = str(cleaned.get("confirm_organization", "")).strip()
            if confirmation.casefold() != organization.slug.casefold():
                self.add_error(
                    "confirm_organization",
                    f"Type {organization.slug} exactly to confirm.",
                )
        password = str(cleaned.get("controller_password", ""))
        if password and not self.controller.check_password(password):
            self.add_error(
                "controller_password",
                "The administrator password is incorrect.",
            )
        return cleaned


class VolunteerApplicationForm(forms.Form):
    motivation = forms.CharField(
        label="Why would you like to help in this position?",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Describe relevant interests or experience. Do not include medical, "
            "conduct, identity-document, or unrelated sensitive information."
        ),
    )


class OnboardingDocumentUploadForm(forms.Form):
    document = forms.FileField(
        label="Signed PDF",
        help_text=(
            "PDF only, up to the limit shown for the request. The file remains "
            "private until retention removes it."
        ),
    )
