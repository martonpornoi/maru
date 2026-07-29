"""Documented read contracts exposed by registration to other modules."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from maru.registration.models import Registration


@dataclass(frozen=True, slots=True)
class RegistrationNotificationContext:
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
