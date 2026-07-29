"""Registration consequences of organizer-scoped account restrictions."""

from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from maru.identity.models import Account, AccountRestriction
from maru.registration.finance import available_refund_minor
from maru.registration.models import (
    AttendeeRegistrationProfile,
    FinancialOperation,
    Registration,
    RegistrationAdjustment,
)
from maru.registration.services import (
    _append_timeline,
    _promote_waitlist_for_product,
    _publish_registration_transition,
    _record_adjustment,
)


def apply_restriction_consequences(
    *,
    restriction: AccountRestriction,
    actor: Account,
) -> tuple[int, int]:
    """Cancel or hide only the records named by the restriction scope."""

    changed_at = timezone.now()
    registrations = Registration.objects.select_for_update().filter(
        organization_id=restriction.organization_id,
        account=restriction.account,
    )
    if restriction.edition_id:
        registrations = registrations.filter(edition_id=restriction.edition_id)
    cancelled = 0
    hidden = 0
    with transaction.atomic():
        for registration in registrations.select_related("product"):
            if restriction.kind in (
                AccountRestriction.Kind.PUBLIC_PROFILE,
                AccountRestriction.Kind.ATTENDANCE,
            ):
                profile = AttendeeRegistrationProfile.objects.filter(
                    registration=registration
                ).first()
                if profile is not None and profile.directory_visible:
                    profile.directory_visible = False
                    profile.directory_country_code = ""
                    profile.directory_consent_version = ""
                    profile.directory_consent_at = None
                    profile.aggregate_version += 1
                    profile.save(
                        update_fields=(
                            "directory_visible",
                            "directory_country_code",
                            "directory_consent_version",
                            "directory_consent_at",
                            "aggregate_version",
                            "updated_at",
                        )
                    )
                    hidden += 1
            if restriction.kind != AccountRestriction.Kind.ATTENDANCE:
                continue
            if registration.state not in (
                Registration.State.WAITLISTED,
                Registration.State.PAYMENT_PENDING,
                Registration.State.CONFIRMED,
            ):
                if registration.state == Registration.State.CHECKED_IN:
                    registration.entitlements.filter(status="active").update(
                        status="revoked",
                        updated_at=changed_at,
                    )
                continue
            previous_state = registration.state
            registration.state = Registration.State.CANCELLED
            registration.cancelled_at = changed_at
            registration.aggregate_version += 1
            registration.save(
                update_fields=(
                    "state",
                    "cancelled_at",
                    "aggregate_version",
                    "updated_at",
                )
            )
            registration.entitlements.filter(status="active").update(
                status="revoked",
                updated_at=changed_at,
            )
            _record_adjustment(
                registration=registration,
                kind=RegistrationAdjustment.Kind.REGISTRATION_CANCELLED,
                reason=f"Scoped restriction {restriction.reason_code}",
                occurred_at=changed_at,
                actor_kind="account",
                actor_id=actor.id,
                from_state=previous_state,
                to_state=registration.state,
            )
            _append_timeline(
                registration=registration,
                kind="registration_restricted",
                title="Registration access changed",
                summary=restriction.attendee_message,
                occurred_at=changed_at,
                actor_kind="account",
                actor_id=actor.id,
                correlation_id=uuid4(),
            )
            _publish_registration_transition(
                registration=registration,
                event_name="registration.cancelled.v1",
                from_state=previous_state,
                correlation_id=uuid4(),
                actor_kind="account",
                actor_id=actor.id,
            )
            refundable = available_refund_minor(registration)
            if refundable:
                FinancialOperation.objects.create(
                    registration=registration,
                    organization_id=registration.organization_id,
                    edition_id=registration.edition_id,
                    kind=FinancialOperation.Kind.REFUND,
                    amount_minor=refundable,
                    currency=registration.currency_snapshot,
                    requested_by=actor,
                    requested_at=changed_at,
                    request_reason=(
                        "Refund review created by an attendance restriction."
                    ),
                    safe_result_code="restriction_refund_review",
                )
            _promote_waitlist_for_product(
                product=registration.product,
                offered_at=changed_at,
                correlation_id=uuid4(),
            )
            cancelled += 1
        if restriction.kind in (
            AccountRestriction.Kind.ATTENDANCE,
            AccountRestriction.Kind.CREDENTIAL,
        ):
            from maru.accreditation.models import (  # noqa: PLC0415
                Credential,
                CredentialEvent,
            )

            credentials = Credential.objects.filter(
                organization_id=restriction.organization_id,
                registration__account=restriction.account,
                status=Credential.Status.ISSUED,
            )
            if restriction.edition_id:
                credentials = credentials.filter(edition_id=restriction.edition_id)
            for credential in credentials.select_for_update():
                credential.status = Credential.Status.REVOKED
                credential.revoked_at = changed_at
                credential.revoked_by_id = actor.id
                credential.revocation_reason = restriction.attendee_message
                credential.save(
                    update_fields=(
                        "status",
                        "revoked_at",
                        "revoked_by_id",
                        "revocation_reason",
                        "updated_at",
                    )
                )
                CredentialEvent.objects.create(
                    credential=credential,
                    organization_id=credential.organization_id,
                    edition_id=credential.edition_id,
                    kind=CredentialEvent.Kind.REVOKED,
                    occurred_at=changed_at,
                    actor_kind="account",
                    actor_id=actor.id,
                    reason_code="account_restriction",
                )
    return cancelled, hidden
