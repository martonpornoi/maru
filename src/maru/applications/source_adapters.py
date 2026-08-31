"""Explicit read adapters for application eligibility and source bindings."""
# ruff: noqa: PLR0911

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from maru.applications.adoption import (
    profile_allows_application_eligibility,
    profile_allows_application_source,
)
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationEligibilityKind,
    ApplicationQuestion,
    ApplicationSourceBinding,
)
from maru.identity.models import Account

if TYPE_CHECKING:
    from datetime import date, datetime

    from maru.registration.models import AttendeeRegistrationProfile


def _registration_profile(
    definition: ApplicationDefinition, account: Account
) -> AttendeeRegistrationProfile | None:
    from maru.registration.models import AttendeeRegistrationProfile  # noqa: PLC0415

    return (
        AttendeeRegistrationProfile.objects.filter(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            account_id=account.id,
        )
        .only("date_of_birth", "telegram_handle")
        .first()
    )


def _age_on(birth_date: date, reference: date) -> int:
    return (
        reference.year
        - birth_date.year
        - ((reference.month, reference.day) < (birth_date.month, birth_date.day))
    )


def applicant_is_eligible(
    *,
    definition: ApplicationDefinition,
    account: Account,
    at: datetime | None = None,
) -> bool:
    """Evaluate only registered, purpose-specific edition relationships.

    Parameters
    ----------
    definition : ApplicationDefinition
        The versioned definition governing the requested behavior.
    account : Account
        The platform account whose state or access is being evaluated.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    bool
        `True` when Evaluate only registered, purpose-specific edition
        relationships; otherwise `False`.
    """
    edition = definition.edition
    if not profile_allows_application_eligibility(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
        definition.eligibility_kind,
    ):
        return False
    if not account.is_active or account.account_kind != Account.Kind.PERSON:
        return False
    evaluation_time = at or timezone.now()
    if definition.minimum_age:
        profile = _registration_profile(definition, account)
        if (
            profile is None
            or _age_on(profile.date_of_birth, definition.edition.starts_on)
            < definition.minimum_age
        ):
            return False
    kind = definition.eligibility_kind
    if kind == ApplicationEligibilityKind.AUTHENTICATED_PERSON:
        return True
    if kind == ApplicationEligibilityKind.EDITION_PARTICIPANT:
        from maru.participation.models import Participation  # noqa: PLC0415

        return (
            Participation.objects.filter(
                organization_id=definition.organization_id,
                edition_id=definition.edition_id,
                account_id=account.id,
            )
            .exclude(status=Participation.Status.CANCELLED)
            .exists()
        )
    if kind in {
        ApplicationEligibilityKind.REGISTERED_ATTENDEE,
        ApplicationEligibilityKind.CONFIRMED_ATTENDEE,
    }:
        from maru.registration.models import Registration  # noqa: PLC0415

        registrations = Registration.objects.filter(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            account_id=account.id,
        )
        if kind == ApplicationEligibilityKind.REGISTERED_ATTENDEE:
            return registrations.exclude(
                state__in=(Registration.State.EXPIRED, Registration.State.CANCELLED)
            ).exists()
        return registrations.filter(
            state__in=(Registration.State.CONFIRMED, Registration.State.CHECKED_IN)
        ).exists()
    if kind == ApplicationEligibilityKind.ACTIVE_VOLUNTEER:
        from maru.workforce.models import PositionAssignment  # noqa: PLC0415

        return (
            PositionAssignment.objects.filter(
                organization_id=definition.organization_id,
                edition_id=definition.edition_id,
                account_id=account.id,
                status=PositionAssignment.Status.ACTIVE,
                effective_from__lte=evaluation_time,
            )
            .filter(
                models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=evaluation_time)
            )
            .exists()
        )
    return False


def source_bound_value(
    *,
    question: ApplicationQuestion,
    account: Account,
) -> object:
    """Return a value bound to its immutable source definition.

    Parameters
    ----------
    question : ApplicationQuestion
        The versioned question defining type, bounds, and ownership.
    account : Account
        The account that owns or authorizes the requested state.

    Returns
    -------
    object
        The normalized value for source bound value.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    edition = question.definition.edition
    if not profile_allows_application_source(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
        question.source_binding,
    ):
        raise ValueError(
            "Question source binding is not admitted by the exact edition profile."
        )
    if question.source_binding == ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME:
        return account.display_name
    if question.source_binding == ApplicationSourceBinding.REGISTRATION_TELEGRAM:
        profile = _registration_profile(question.definition, account)
        return profile.telegram_handle if profile is not None else ""
    raise ValueError("Question does not declare a registered source binding.")
