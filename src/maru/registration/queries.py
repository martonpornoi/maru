"""Documented read contracts exposed by registration to other modules."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from maru.registration.models import Registration


@dataclass(frozen=True, slots=True)
class RegistrationNotificationContext:
    """Describe registration notification context.

    Attributes
    ----------
    account_id
        The platform account identifier within the requested scope.
    email
        The normalized email address used for delivery or identity matching.
    locale
        The locale retained in this immutable projection.
    organization_id
        The organization identifier that owns the requested resource.
    edition_id
        The event edition identifier that scopes the operation.
    edition_name
        The human-readable edition name shown to authorized readers.
    edition_time_zone
        The IANA time-zone name used for localization and validation.
    registration_id
        The attendee registration identifier within the edition scope.
    reference
        The reference retained in this immutable projection.
    state
        The lifecycle state to evaluate or expose.
    product_name
        The human-readable product name shown to authorized readers.
    amount_minor
        The amount minor retained in this immutable projection.
    currency
        The supported ISO 4217 currency code for monetary values.
    payment_due_at
        The timezone-aware timestamp for payment due.
    support_path
        The support path retained in this immutable projection.
    registration_path
        The registration path retained in this immutable projection.
    """

    account_id: UUID
    email: str
    locale: str
    organization_id: UUID
    edition_id: UUID
    edition_name: str
    edition_time_zone: str
    registration_id: UUID
    reference: str
    state: str
    product_name: str
    amount_minor: int
    currency: str
    payment_due_at: datetime | None
    support_path: str
    registration_path: str


def notification_context(
    *,
    registration_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
) -> RegistrationNotificationContext | None:
    """Return notification context visible to the caller.

    Parameters
    ----------
    registration_id : UUID
        The identifier of the registration.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    RegistrationNotificationContext | None
        The matching notification context, or ``None`` when it is unavailable.
    """
    registration = (
        Registration.objects.filter(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("account", "edition")
        .first()
    )
    if registration is None:
        return None
    return RegistrationNotificationContext(
        account_id=registration.account_id,
        email=registration.account.email,
        locale=registration.account.preferred_language,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        edition_name=registration.edition.name,
        edition_time_zone=registration.edition.time_zone,
        registration_id=registration.id,
        reference=registration.reference,
        state=registration.state,
        product_name=registration.product_name_snapshot,
        amount_minor=registration.price_minor_snapshot,
        currency=registration.currency_snapshot,
        payment_due_at=registration.payment_due_at,
        support_path="/support/registration/",
        registration_path=f"/register/{registration.edition_id}/profile/",
    )
