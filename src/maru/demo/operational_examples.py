"""Synthetic production-safety records for complete bootstrap-admin exploration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from django.db import transaction

from maru.accreditation.models import (
    Credential,
    CredentialEvent,
    OfflineCheckInOperation,
    OfflineCredentialManifest,
    RelayDevice,
)
from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.models import RoleBundle
from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)
from maru.events.models import (
    ArchiveAmendment,
    EditionClosureManifest,
    EditionReadinessGate,
    EventEdition,
)
from maru.identity.models import (
    Account,
    AccountRestriction,
    AccountSecurityEvent,
    AccountSession,
    IdentityAbuseBucket,
    IdentityChallenge,
    RestrictionAppeal,
)
from maru.privacyops.models import (
    DisposalReceipt,
    PostEditionCorrection,
    RetentionPolicy,
    SubjectRightsRequest,
)
from maru.registration.models import (
    AttendeeRegistrationProfile,
    FinancialLedgerEntry,
    FinancialOperation,
    GuardianConsent,
    MediaSafetyReceipt,
    PaymentException,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentWebhookReceipt,
    ReceiptRecord,
    Registration,
    RegistrationAdjustment,
    RegistrationConfiguration,
    RegistrationLifecycleRun,
    RegistrationTimelineEntry,
    SettlementAllocation,
    SettlementBatch,
)
from maru.workforce.assignment_commands import propose_position_assignment
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.edition_write_scope import (
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    OnboardingDocumentRequest,
    OnboardingDocumentType,
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    Position,
    PositionAssignment,
    PositionAssignmentCommandReceipt,
    PositionDocumentRequirement,
    PositionTemplate,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.structure_commands import create_department

if TYPE_CHECKING:
    from maru.organizations.models import Organization

DEMO_NAMESPACE = UUID("6c4b5775-8251-4f11-98e1-b29e09d8fbe6")


class OwnRecord(Protocol):
    """Describe own record."""

    def __call__(
        self,
        kind: str,
        object_id: UUID,
        *,
        created: bool,
    ) -> None:
        """Invoke the configured operation.

        Parameters
        ----------
        kind : str
            The closed discriminator selecting the requested behavior.
        object_id : UUID
            The object identifier within the requested scope.
        created : bool
            The created evaluated while call.
        """
        ...


def _id(kind: str, key: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"{kind}:{key}")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _own(
    own: OwnRecord,
    kind: str,
    record: object,
    *,
    created: bool,
) -> None:
    own(kind, record.id, created=created)  # type: ignore[attr-defined]


def _seed_governed_assignment_example(
    *,
    convention_key: str,
    organization: Organization,
    edition: EventEdition,
    accounts: dict[str, Account],
    position: Position,
    legacy_assignment_id: UUID,
    own: OwnRecord,
    happened_at: datetime,
) -> None:
    """Seed one current command-backed proposal without rewriting legacy evidence.

    Parameters
    ----------
    convention_key : str
        Stable convention key used to derive idempotency evidence.
    organization : Organization
        Organization that owns the synthetic Position.
    edition : EventEdition
        Exact editable edition receiving the proposal.
    accounts : dict[str, Account]
        Synthetic persona accounts required by the Assignment example.
    position : Position
        Current Position receiving the proposal.
    legacy_assignment_id : UUID
        Stable identifier used by demo fixtures predating governed commands.
    own : OwnRecord
        Collector for deterministic demo ownership and creation counts.
    happened_at : datetime
        Stable synthetic baseline used for the proposed effective time.

    Raises
    ------
    RuntimeError
        If a retained legacy assignment conflicts with its stable demo scope.
    """
    chair = accounts["convention-chair"]
    assigned = accounts["registration-volunteer"]
    governed_candidate = assigned
    governed_retry_key = _id("workforce-assignment-proposal-retry", convention_key)
    legacy_assignment = PositionAssignment.objects.filter(
        id=legacy_assignment_id
    ).first()
    if legacy_assignment is not None:
        legacy_scope = (
            legacy_assignment.position_id,
            legacy_assignment.organization_id,
            legacy_assignment.edition_id,
            legacy_assignment.account_id,
        )
        if legacy_scope != (
            position.id,
            organization.id,
            edition.id,
            assigned.id,
        ):
            raise RuntimeError("Stable demo workforce assignment scope conflicts.")
        # Preserve fixtures created before governed Assignment commands existed.
        # A second synthetic proposal demonstrates the current command path
        # without inventing evidence for that legacy row.
        _own(
            own,
            "workforce_position_assignments",
            legacy_assignment,
            created=False,
        )
        governed_candidate = accounts["volunteer-applicant"]
        governed_retry_key = _id(
            "workforce-assignment-proposal-retry-v2",
            convention_key,
        )

    assignment_result = propose_position_assignment(
        actor=chair,
        organization_id=organization.id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        account_id=governed_candidate.id,
        effective_from=happened_at + timedelta(days=14),
        expires_at=None,
        reason="Propose a synthetic Registration assignment for independent review.",
        retry_key=governed_retry_key,
        correlation_id=_id("workforce-assignment-proposal-correlation", convention_key),
        request_id=_id("workforce-assignment-proposal-request", convention_key),
        source_channel="demo_seed",
    )
    assignment = PositionAssignment.objects.get(pk=assignment_result.assignment_id)
    assignment_receipt = PositionAssignmentCommandReceipt.objects.get(
        pk=assignment_result.receipt_id
    )
    _own(
        own,
        "workforce_position_assignments",
        assignment,
        created=not assignment_result.replayed,
    )
    _own(
        own,
        "workforce_assignment_command_receipts",
        assignment_receipt,
        created=not assignment_result.replayed,
    )


def _seed_availability_example(
    *,
    convention_key: str,
    organization: Organization,
    edition: EventEdition,
    assigned: Account,
    own: OwnRecord,
) -> None:
    """Seed one shared owner plan while preserving later person-made changes.

    Parameters
    ----------
    convention_key : str
        Stable convention key used to derive idempotency evidence.
    organization : Organization
        Organization that owns the synthetic Availability scope.
    edition : EventEdition
        Exact edition whose local calendar bounds the periods.
    assigned : Account
        Synthetic person with an open Position relationship.
    own : OwnRecord
        Collector for deterministic demo ownership and creation counts.
    """
    availability_plan = PersonAvailabilityPlan.objects.filter(
        organization=organization,
        edition=edition,
        account=assigned,
    ).first()
    availability_created = False
    created_receipt_id: UUID | None = None
    if availability_plan is None:
        edition_zone = ZoneInfo(edition.time_zone)
        first_period_start = datetime(
            edition.starts_on.year,
            edition.starts_on.month,
            edition.starts_on.day,
            9,
            tzinfo=edition_zone,
        )
        availability_result = save_person_availability(
            actor=assigned,
            organization_id=organization.id,
            edition_id=edition.id,
            expected_version=0,
            status=PersonAvailabilityPlan.Status.SUBMITTED,
            windows=(
                AvailabilityWindowInput(
                    starts_at=first_period_start,
                    ends_at=first_period_start + timedelta(hours=4),
                    preference=PersonAvailabilityWindow.Preference.PREFERRED,
                ),
                AvailabilityWindowInput(
                    starts_at=first_period_start + timedelta(days=1, hours=5),
                    ends_at=first_period_start + timedelta(days=1, hours=11),
                    preference=PersonAvailabilityWindow.Preference.AVAILABLE,
                ),
            ),
            retry_key=_id("workforce-availability-submit-retry", convention_key),
            correlation_id=_id(
                "workforce-availability-submit-correlation",
                convention_key,
            ),
            request_id=_id("workforce-availability-submit-request", convention_key),
            source_channel="demo_seed",
        )
        availability_plan = PersonAvailabilityPlan.objects.get(
            pk=availability_result.plan_id
        )
        availability_created = not availability_result.replayed
        created_receipt_id = availability_result.receipt_id

    _own(
        own,
        "workforce_availability_plans",
        availability_plan,
        created=availability_created,
    )
    for window in availability_plan.windows.order_by("starts_at", "id"):
        _own(
            own,
            "workforce_availability_windows",
            window,
            created=availability_created,
        )
    for receipt in availability_plan.command_receipts.order_by(
        "resulting_version",
        "id",
    ):
        _own(
            own,
            "workforce_availability_command_receipts",
            receipt,
            created=(receipt.id == created_receipt_id),
        )


@transaction.atomic
def seed_workforce_examples(  # noqa: PLR0915
    *,
    convention_key: str,
    organization: Organization,
    edition: EventEdition,
    accounts: dict[str, Account],
    own: OwnRecord,
    happened_at: datetime,
) -> None:
    """Give every workforce admin page coherent, linked synthetic records.

    Parameters
    ----------
    convention_key : str
        The stable convention key used to authenticate or deduplicate the
        operation.
    organization : Organization
        The organization that owns the requested resource.
    edition : EventEdition
        The event edition that scopes the operation.
    accounts : dict[str, Account]
        The accounts mapping to validate or transform.
    own : OwnRecord
        The own evaluated while seed workforce examples.
    happened_at : datetime
        The timezone-aware timestamp for happened.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    chair = accounts["convention-chair"]
    registration_lead = accounts["registration-lead"]
    applicant = accounts["volunteer-applicant"]
    assigned = accounts["registration-volunteer"]
    scope = lock_workforce_edition_write_scope(
        organization_id=organization.id,
        series_id=edition.series_id,
        edition_id=edition.id,
    )
    role = RoleBundle.objects.get(
        organization=organization,
        code="demo-staff",
        version=1,
    )
    legacy_department_id = _id("workforce-department", convention_key)
    department = Department.objects.filter(pk=legacy_department_id).first()
    created = False
    if department is not None:
        if (
            department.organization_id != organization.id
            or department.edition_id != edition.id
            or department.name != "Registration and Front Desk"
        ):
            raise RuntimeError("Stable demo workforce Department scope conflicts.")
    else:
        retry_key = _id("workforce-department-retry", convention_key)
        retry_exists = EditionStructureCommandReceipt.objects.filter(
            organization=organization,
            edition=edition,
            actor=chair,
            retry_key=retry_key,
        ).exists()
        collision = Department.objects.filter(
            organization=organization,
            edition=edition,
            name__iexact="Registration and Front Desk",
        ).first()
        if collision is not None and not retry_exists:
            raise RuntimeError("Demo workforce Department name is already in use.")
        result = create_department(
            actor=chair,
            organization_id=organization.id,
            series_id=edition.series_id,
            edition_id=edition.id,
            name="Registration and Front Desk",
            description=(
                "Synthetic attendee registration, payment support, and arrival."
            ),
            parent_department_id=None,
            display_order=10,
            expected_version=0,
            reason="Create the synthetic Registration workforce example.",
            retry_key=retry_key,
            correlation_id=_id(
                "workforce-department-correlation",
                convention_key,
            ),
            request_id=_id("workforce-department-request", convention_key),
            source_channel="demo_seed",
        )
        department = Department.objects.get(pk=result.department_id)
        created = not result.replayed
    _own(own, "workforce_departments", department, created=created)
    document_type, created = OnboardingDocumentType.objects.get_or_create(
        id=_id("workforce-document-type", convention_key),
        defaults={
            "organization": organization,
            "edition": edition,
            "code": "volunteer-nda",
            "name": "Volunteer NDA",
            "version": 1,
            "description": (
                "Synthetic signed confidentiality agreement for attendee service."
            ),
            "status": OnboardingDocumentType.Status.ACTIVE,
            "created_by": chair,
        },
    )
    _own(own, "workforce_document_types", document_type, created=created)
    template, created = PositionTemplate.objects.get_or_create(
        id=_id("workforce-position-template", convention_key),
        defaults={
            "organization": organization,
            "code": "registration-team",
            "name": "Registration Team Member",
            "version": 1,
            "description": (
                "Supports registration questions, payment status, and arrival."
            ),
            "default_headcount": 12,
            "default_capacity_codes": ["staff", "volunteer", "registration"],
            "role_bundle": role,
            "status": PositionTemplate.Status.PUBLISHED,
            "created_by": chair,
        },
    )
    _own(own, "workforce_position_templates", template, created=created)
    lock_active_department_write_target(
        scope=scope,
        department_id=department.id,
    )
    position_id = _id("workforce-position", convention_key)
    assignment_id = _id("workforce-position-assignment", convention_key)
    if edition.lifecycle not in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    } and (
        not Position.objects.filter(pk=position_id).exists()
        or not PositionAssignment.objects.filter(
            position_id=position_id,
            organization=organization,
            edition=edition,
        ).exists()
    ):
        raise RuntimeError(
            "Synthetic workforce examples must be created before the edition "
            "leaves Draft or Preparing."
        )
    position, position_created = Position.objects.get_or_create(
        id=position_id,
        defaults={
            "organization": organization,
            "edition": edition,
            "template": template,
            "department": department,
            "role_bundle": role,
            "code": "registration-team-member",
            "title": "Registration Team Member",
            "description": template.description,
            "headcount": 12,
            "capacity_codes": ["staff", "volunteer", "registration"],
            "status": Position.Status.OPEN,
            "created_by": chair,
        },
    )
    _own(own, "workforce_positions", position, created=position_created)
    ensure_workforce_position_binding(position=position)
    position_scope = (
        Position.objects.select_for_update()
        .filter(id=position_id)
        .order_by()
        .values_list(
            "organization_id",
            "edition_id",
            "department_id",
            "template_id",
            "role_bundle_id",
            "code",
        )
        .first()
    )
    if position_scope != (
        scope.organization_id,
        scope.edition_id,
        department.id,
        template.id,
        role.id,
        "registration-team-member",
    ):
        raise RuntimeError("Stable demo workforce Position scope conflicts.")
    requirement, created = PositionDocumentRequirement.objects.get_or_create(
        id=_id("workforce-position-document", convention_key),
        defaults={
            "position": position,
            "document_type": document_type,
        },
    )
    _own(own, "workforce_position_documents", requirement, created=created)

    opportunity_id = _id("workforce-opportunity", convention_key)
    opportunity = VolunteerOpportunity.objects.get(position=position)
    if opportunity.id != opportunity_id:
        if VolunteerOpportunity.objects.filter(id=opportunity_id).exists():
            raise RuntimeError("Stable demo workforce opportunity ID is in use.")
        VolunteerOpportunity.objects.filter(id=opportunity.id).update(id=opportunity_id)
    opportunity = VolunteerOpportunity.objects.get(id=opportunity_id)
    VolunteerOpportunity.objects.filter(id=opportunity.id).update(
        status=VolunteerOpportunity.Status.PUBLISHED,
        headline="Join the Registration Team",
        description=(
            "Help attendees before the event and at Front Desk. The listing "
            "remains visible after all places are filled."
        ),
        visible_when_filled=True,
    )
    opportunity.refresh_from_db()
    _own(
        own,
        "workforce_opportunities",
        opportunity,
        created=position_created,
    )
    application, created = VolunteerApplication.objects.get_or_create(
        id=_id("workforce-application", convention_key),
        defaults={
            "opportunity": opportunity,
            "account": applicant,
            "status": VolunteerApplication.Status.UNDER_REVIEW,
            "motivation": (
                "I enjoy helping attendees and can cover two Front Desk shifts."
            ),
            "submitted_at": happened_at,
            "reviewed_by": registration_lead,
            "reviewed_at": happened_at + timedelta(hours=4),
            "review_reason": "Promising application; agreement still required.",
        },
    )
    _own(own, "workforce_applications", application, created=created)
    document_request, created = OnboardingDocumentRequest.objects.get_or_create(
        id=_id("workforce-document-request", convention_key),
        defaults={
            "organization": organization,
            "edition": edition,
            "document_type": document_type,
            "account": applicant,
            "status": OnboardingDocumentRequest.Status.REQUESTED,
            "instructions": "Download, sign, and upload the synthetic NDA PDF.",
            "due_at": happened_at + timedelta(days=7),
            "requested_by": registration_lead,
            "requested_at": happened_at,
        },
    )
    _own(own, "workforce_document_requests", document_request, created=created)
    _seed_governed_assignment_example(
        convention_key=convention_key,
        organization=organization,
        edition=edition,
        accounts=accounts,
        position=position,
        legacy_assignment_id=assignment_id,
        own=own,
        happened_at=happened_at,
    )
    _seed_availability_example(
        convention_key=convention_key,
        organization=organization,
        edition=edition,
        assigned=assigned,
        own=own,
    )


def seed_operational_examples(  # noqa: PLR0915
    *,
    convention_key: str,
    organization: Organization,
    editions: dict[str, EventEdition],
    configurations: dict[str, RegistrationConfiguration],
    accounts: dict[str, Account],
    registrations: dict[str, Registration],
    administrator: Account,
    own: OwnRecord,
) -> None:
    """Populate every production-safety admin model with safe synthetic evidence.

    Parameters
    ----------
    convention_key : str
        The stable convention key used to authenticate or deduplicate the
        operation.
    organization : Organization
        The organization that owns the requested resource.
    editions : dict[str, EventEdition]
        The editions mapping to validate or transform.
    configurations : dict[str, RegistrationConfiguration]
        The configurations mapping to validate or transform.
    accounts : dict[str, Account]
        The accounts mapping to validate or transform.
    registrations : dict[str, Registration]
        The registrations mapping to validate or transform.
    administrator : Account
        The platform administrator authorizing the privileged action.
    own : OwnRecord
        The own evaluated while seed operational examples.
    """
    current = editions["current"]
    past = editions["past"]
    chair = accounts["convention-chair"]
    registration_lead = accounts["registration-lead"]
    sponsor = registrations["sponsor-attendee"]
    first_time = registrations["first-time-attendee"]
    minor = registrations["volunteer-applicant"]
    checked_in = registrations["guest-of-honour"]
    cancelled = registrations["cancelled-attendee"]
    happened_at = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    provider, created = PaymentProviderAccount.objects.get_or_create(
        id=_id("payment-provider", convention_key),
        defaults={
            "organization": organization,
            "code": "demo-hosted",
            "display_name": "Synthetic Hosted Payments",
            "adapter": "json_hosted",
            "api_base_url": "https://payments.example.invalid/v1",
            "credential_env_var": (
                f"MARU_{convention_key.upper()}_DEMO_PROVIDER_CREDENTIAL"
            ),
            "webhook_secret_env_var": (
                f"MARU_{convention_key.upper()}_DEMO_WEBHOOK_SECRET"
            ),
            "enabled": False,
        },
    )
    _own(own, "payment_provider_accounts", provider, created=created)

    succeeded_intent, created = PaymentIntent.objects.get_or_create(
        id=_id("payment-intent", f"{convention_key}.succeeded"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_account": provider,
            "idempotency_key": _id(
                "payment-intent-idempotency",
                f"{convention_key}.succeeded",
            ),
            "amount_minor": sponsor.price_minor_snapshot,
            "currency": sponsor.currency_snapshot,
            "status": PaymentIntent.Status.SUCCEEDED,
            "provider_reference": f"pi_demo_{convention_key}_paid",
            "checkout_url": (f"https://checkout.example.invalid/{convention_key}/paid"),
            "expires_at": happened_at + timedelta(days=2),
            "last_provider_event_at": happened_at,
            "safe_result_code": "provider_payment_confirmed",
        },
    )
    _own(own, "payment_intents", succeeded_intent, created=created)

    uncertain_intent, created = PaymentIntent.objects.get_or_create(
        id=_id("payment-intent", f"{convention_key}.uncertain"),
        defaults={
            "registration": first_time,
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_account": provider,
            "idempotency_key": _id(
                "payment-intent-idempotency",
                f"{convention_key}.uncertain",
            ),
            "amount_minor": first_time.price_minor_snapshot,
            "currency": first_time.currency_snapshot,
            "status": PaymentIntent.Status.UNCERTAIN,
            "provider_reference": f"pi_demo_{convention_key}_uncertain",
            "checkout_url": (
                f"https://checkout.example.invalid/{convention_key}/uncertain"
            ),
            "expires_at": happened_at + timedelta(days=2),
            "last_provider_event_at": happened_at + timedelta(minutes=3),
            "safe_result_code": "provider_result_uncertain",
        },
    )
    _own(own, "payment_intents", uncertain_intent, created=created)

    webhook, created = PaymentWebhookReceipt.objects.get_or_create(
        id=_id("payment-webhook", f"{convention_key}.applied"),
        defaults={
            "provider_account": provider,
            "organization_id": organization.id,
            "remote_event_id": f"evt_demo_{convention_key}_paid",
            "payload_digest": _digest(f"{convention_key}:paid-webhook"),
            "signature_timestamp": happened_at,
            "received_at": happened_at + timedelta(seconds=4),
            "outcome": PaymentWebhookReceipt.Outcome.APPLIED,
            "safe_result_code": "payment_applied",
            "payment_intent": succeeded_intent,
        },
    )
    _own(own, "payment_webhook_receipts", webhook, created=created)

    payment_exception, created = PaymentException.objects.get_or_create(
        id=_id("payment-exception", f"{convention_key}.provider-timeout"),
        defaults={
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_account": provider,
            "payment_intent": uncertain_intent,
            "kind": PaymentException.Kind.PROVIDER_UNAVAILABLE,
            "status": PaymentException.Status.OPEN,
            "safe_summary": (
                "The synthetic provider timed out after accepting the checkout."
            ),
            "opened_at": happened_at + timedelta(minutes=3),
        },
    )
    _own(own, "payment_exceptions", payment_exception, created=created)

    payment_entry, created = FinancialLedgerEntry.objects.get_or_create(
        id=_id("finance-ledger", f"{convention_key}.sponsor-payment"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_account": provider,
            "kind": FinancialLedgerEntry.Kind.PAYMENT,
            "direction": FinancialLedgerEntry.Direction.INFLOW,
            "amount_minor": sponsor.price_minor_snapshot,
            "currency": sponsor.currency_snapshot,
            "occurred_at": happened_at,
            "provider_reference": f"pay_demo_{convention_key}_sponsor",
            "safe_description": (f"Payment for {sponsor.product_name_snapshot}."),
        },
    )
    _own(own, "financial_ledger_entries", payment_entry, created=created)

    fee_entry, created = FinancialLedgerEntry.objects.get_or_create(
        id=_id("finance-ledger", f"{convention_key}.provider-fee"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_account": provider,
            "kind": FinancialLedgerEntry.Kind.PROVIDER_FEE,
            "direction": FinancialLedgerEntry.Direction.OUTFLOW,
            "amount_minor": 500,
            "currency": sponsor.currency_snapshot,
            "occurred_at": happened_at + timedelta(days=2),
            "provider_reference": f"fee_demo_{convention_key}_sponsor",
            "safe_description": "Synthetic hosted-payment provider fee.",
        },
    )
    _own(own, "financial_ledger_entries", fee_entry, created=created)

    receipt, created = ReceiptRecord.objects.get_or_create(
        id=_id("receipt", f"{convention_key}.sponsor"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "ledger_entry": payment_entry,
            "kind": ReceiptRecord.Kind.RECEIPT,
            "document_number": f"DEMO-{convention_key.upper()}-2026-0001",
            "issued_at": happened_at,
            "amount_minor": sponsor.price_minor_snapshot,
            "currency": sponsor.currency_snapshot,
            "description_snapshot": (
                f"{sponsor.product_name_snapshot} — synthetic receipt"
            ),
        },
    )
    _own(own, "receipt_records", receipt, created=created)

    operation, created = FinancialOperation.objects.get_or_create(
        id=_id("financial-operation", f"{convention_key}.refund-proposed"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "kind": FinancialOperation.Kind.REFUND,
            "status": FinancialOperation.Status.PROPOSED,
            "amount_minor": 5_000,
            "currency": sponsor.currency_snapshot,
            "requested_by": accounts["treasurer"],
            "requested_at": happened_at + timedelta(days=3),
            "request_reason": (
                "Synthetic partial refund awaiting independent approval."
            ),
        },
    )
    _own(own, "financial_operations", operation, created=created)

    settlement, created = SettlementBatch.objects.get_or_create(
        id=_id("settlement", f"{convention_key}.reconciled"),
        defaults={
            "provider_account": provider,
            "organization_id": organization.id,
            "edition_id": current.id,
            "provider_reference": f"set_demo_{convention_key}_0001",
            "currency": sponsor.currency_snapshot,
            "gross_minor": sponsor.price_minor_snapshot,
            "fee_minor": 500,
            "refund_minor": 0,
            "dispute_minor": 0,
            "net_minor": sponsor.price_minor_snapshot - 500,
            "settled_at": happened_at + timedelta(days=2),
            "status": SettlementBatch.Status.RECONCILED,
            "reconciled_at": happened_at + timedelta(days=2, minutes=10),
            "reconciled_by_id": accounts["treasurer"].id,
            "safe_result_code": "settlement_reconciled",
        },
    )
    _own(own, "settlement_batches", settlement, created=created)

    allocation, created = SettlementAllocation.objects.get_or_create(
        id=_id("settlement-allocation", f"{convention_key}.sponsor-payment"),
        defaults={
            "settlement": settlement,
            "ledger_entry": payment_entry,
            "amount_minor": sponsor.price_minor_snapshot,
        },
    )
    _own(own, "settlement_allocations", allocation, created=created)

    if first_time.payment_due_at is not None:
        adjustment, created = RegistrationAdjustment.objects.get_or_create(
            id=_id("registration-adjustment", f"{convention_key}.deadline"),
            defaults={
                "registration": first_time,
                "organization_id": organization.id,
                "edition_id": current.id,
                "kind": RegistrationAdjustment.Kind.PAYMENT_DEADLINE_CHANGED,
                "from_state": Registration.State.PAYMENT_PENDING,
                "to_state": Registration.State.PAYMENT_PENDING,
                "previous_deadline": first_time.payment_due_at - timedelta(days=1),
                "new_deadline": first_time.payment_due_at,
                "actor_kind": "account",
                "actor_id": registration_lead.id,
                "reason": ("Synthetic attendee requested one additional payment day."),
                "occurred_at": happened_at + timedelta(hours=2),
            },
        )
        _own(own, "registration_adjustments", adjustment, created=created)

    infinity, created = sponsor.entitlements.get_or_create(
        code="infinity-ticket",
        defaults={
            "id": _id(
                "registration-entitlement",
                f"{convention_key}.infinity",
            ),
            "organization_id": organization.id,
            "edition_id": current.id,
            "label_snapshot": "Infinity Ticket Holder",
            "granted_at": sponsor.confirmed_at or happened_at,
        },
    )
    _own(own, "entitlements", infinity, created=created)

    last_note_sequence = (
        sponsor.timeline.order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    note_sequence = (last_note_sequence or 0) + 1
    note, created = RegistrationTimelineEntry.objects.get_or_create(
        id=_id("registration-timeline", f"{convention_key}.internal-note"),
        defaults={
            "registration": sponsor,
            "organization_id": organization.id,
            "edition_id": current.id,
            "sequence": note_sequence,
            "kind": "internal_note",
            "title": "Internal registration comment",
            "summary": (
                "Supporter package should be collected together with the badge. "
                "Synthetic staff-only note; no medical or conduct information."
            ),
            "audience": RegistrationTimelineEntry.Audience.STAFF_ONLY,
            "occurred_at": happened_at + timedelta(hours=1),
            "actor_kind": "account",
            "actor_id": registration_lead.id,
            "correlation_id": _id(
                "registration-correlation",
                f"{convention_key}.internal-note",
            ),
        },
    )
    _own(own, "registration_timeline_entries", note, created=created)

    lifecycle, created = RegistrationLifecycleRun.objects.get_or_create(
        id=_id("registration-lifecycle", convention_key),
        defaults={
            "edition_id": current.id,
            "ran_at": datetime(2026, 7, 1, 12, tzinfo=UTC),
            "expired": 1,
            "inactive_cancelled": 1,
            "closed_waitlist_cancelled": 0,
            "promoted": 1,
            "restrictions_applied": 1,
        },
    )
    _own(own, "registration_lifecycle_runs", lifecycle, created=created)

    fursuit = first_time.attendee_fursuits.order_by("position").first()
    if fursuit is not None:
        media_receipt, created = MediaSafetyReceipt.objects.get_or_create(
            id=_id("media-safety", f"{convention_key}.{fursuit.id}"),
            defaults={
                "organization_id": organization.id,
                "edition_id": current.id,
                "account_id": first_time.account_id,
                "media_kind": MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                "media_id": fursuit.id,
                "storage_name": (f"demo/{convention_key}/fursuits/{fursuit.id}.png"),
                "original_sha256": _digest(f"{fursuit.id}:original"),
                "sanitized_sha256": _digest(f"{fursuit.id}:sanitized"),
                "scanner_code": "demo_clean",
                "decoder_version": "pillow-demo",
                "content_type": "image/png",
                "width": 512,
                "height": 512,
                "byte_count": 42_000,
                "scanned_at": happened_at,
            },
        )
        _own(own, "media_safety_receipts", media_receipt, created=created)

    if minor.state == Registration.State.GUARDIAN_PENDING:
        policy = configurations["current"].minor_policy
        consent, created = GuardianConsent.objects.get_or_create(
            id=_id("guardian-consent", convention_key),
            defaults={
                "registration": minor,
                "organization_id": organization.id,
                "edition_id": current.id,
                "policy": policy,
                "guardian_name": "Synthetic Guardian",
                "guardian_email": (f"guardian.{convention_key}@demo.maru.invalid"),
                "relationship": "Parent",
                "notice_version": policy.guardian_notice_version,
                "token_digest": _digest(f"{convention_key}:guardian-token"),
                "status": GuardianConsent.Status.PENDING,
                "requested_at": happened_at,
                "expires_at": happened_at + timedelta(days=7),
            },
        )
        _own(own, "guardian_consents", consent, created=created)

    preference, created = NotificationPreference.objects.get_or_create(
        id=_id("notification-preference", convention_key),
        defaults={
            "account": sponsor.account,
            "organization": organization,
            "operational_email_enabled": True,
            "marketing_email_consent": True,
            "marketing_consent_version": "demo-marketing-v1",
            "marketing_consented_at": happened_at,
        },
    )
    _own(own, "notification_preferences", preference, created=created)

    paid_message, created = NotificationMessage.objects.get_or_create(
        id=_id("notification-message", f"{convention_key}.paid"),
        defaults={
            "account": sponsor.account,
            "organization_id": organization.id,
            "edition_id": current.id,
            "domain_event_id": _id(
                "notification-domain-event",
                f"{convention_key}.paid",
            ),
            "message_type": "registration.payment_confirmed",
            "purpose": NotificationMessage.Purpose.OPERATIONAL,
            "locale": sponsor.account.preferred_language,
            "subject": f"Payment confirmed for {current.name}",
            "body": (
                f"We received {sponsor.price_minor_snapshot / 100:.2f} "
                f"{sponsor.currency_snapshot} for "
                f"{sponsor.product_name_snapshot}."
            ),
            "action_path": (f"/register/{current.id}/profile/"),
            "rendered_at": happened_at,
            "read_at": happened_at + timedelta(hours=3),
        },
    )
    _own(own, "notification_messages", paid_message, created=created)

    paid_delivery, created = NotificationDelivery.objects.get_or_create(
        id=_id("notification-delivery", f"{convention_key}.paid"),
        defaults={
            "message": paid_message,
            "channel": NotificationDelivery.Channel.EMAIL,
            "status": NotificationDelivery.Status.SUCCEEDED,
            "attempt_count": 1,
            "remote_identity": f"demo-mail-{convention_key}-paid",
            "last_attempt_at": happened_at,
            "delivered_at": happened_at + timedelta(seconds=2),
        },
    )
    _own(own, "notification_deliveries", paid_delivery, created=created)

    failure_message, created = NotificationMessage.objects.get_or_create(
        id=_id("notification-message", f"{convention_key}.deadline"),
        defaults={
            "account": first_time.account,
            "organization_id": organization.id,
            "edition_id": current.id,
            "domain_event_id": _id(
                "notification-domain-event",
                f"{convention_key}.deadline",
            ),
            "message_type": "registration.payment_deadline_changed",
            "purpose": NotificationMessage.Purpose.OPERATIONAL,
            "locale": first_time.account.preferred_language,
            "subject": f"Registration update for {current.name}",
            "body": (
                "Your synthetic registration has an updated next step. "
                "Open Maru for the canonical status."
            ),
            "action_path": f"/register/{current.id}/profile/",
            "rendered_at": happened_at + timedelta(hours=2),
        },
    )
    _own(own, "notification_messages", failure_message, created=created)

    failed_delivery, created = NotificationDelivery.objects.get_or_create(
        id=_id("notification-delivery", f"{convention_key}.failed"),
        defaults={
            "message": failure_message,
            "channel": NotificationDelivery.Channel.EMAIL,
            "status": NotificationDelivery.Status.PERMANENT_FAILED,
            "attempt_count": 3,
            "safe_error_code": "demo_mailbox_unavailable",
            "last_attempt_at": happened_at + timedelta(hours=2, minutes=10),
        },
    )
    _own(own, "notification_deliveries", failed_delivery, created=created)

    security_event, created = AccountSecurityEvent.objects.get_or_create(
        id=_id("account-security-event", convention_key),
        defaults={
            "account": sponsor.account,
            "event_type": AccountSecurityEvent.EventType.SIGN_IN,
            "outcome": AccountSecurityEvent.Outcome.SUCCEEDED,
            "occurred_at": happened_at - timedelta(hours=2),
            "source_channel": "demo_browser",
            "detail_code": "demo_password_sign_in",
        },
    )
    _own(own, "account_security_events", security_event, created=created)

    challenge, created = IdentityChallenge.objects.get_or_create(
        id=_id("identity-challenge", convention_key),
        defaults={
            "account": first_time.account,
            "purpose": IdentityChallenge.Purpose.RECOVER_ACCOUNT,
            "token_digest": _digest(f"{convention_key}:recovery-token"),
            "email_snapshot": first_time.account.email,
            "expires_at": happened_at + timedelta(hours=2),
            "consumed_at": happened_at + timedelta(minutes=20),
            "attempt_count": 1,
            "request_fingerprint": _digest(f"{convention_key}:request-fingerprint"),
            "delivery_status": IdentityChallenge.DeliveryStatus.SUCCEEDED,
            "delivery_attempt_count": 1,
            "last_delivery_attempt_at": happened_at + timedelta(seconds=1),
            "delivered_at": happened_at + timedelta(seconds=2),
        },
    )
    _own(own, "identity_challenges", challenge, created=created)

    session, created = AccountSession.objects.get_or_create(
        id=_id("account-session", convention_key),
        defaults={
            "account": sponsor.account,
            "session_key_digest": _digest(f"{convention_key}:session"),
            "label": "Demo laptop · Firefox · Budapest",
            "created_channel": "demo_seed",
            "last_seen_at": happened_at + timedelta(days=1),
            "step_up_verified_at": happened_at + timedelta(days=1),
            "revoked_at": happened_at + timedelta(days=4),
            "revocation_reason": "synthetic_user_revocation",
        },
    )
    _own(own, "account_sessions", session, created=created)

    abuse, created = IdentityAbuseBucket.objects.get_or_create(
        id=_id("identity-abuse", convention_key),
        defaults={
            "flow": "sign_in",
            "subject_digest": _digest(f"{convention_key}:abuse-subject"),
            "window_started_at": happened_at,
            "attempt_count": 8,
            "blocked_until": happened_at + timedelta(minutes=15),
        },
    )
    _own(own, "identity_abuse_buckets", abuse, created=created)

    restriction, created = AccountRestriction.objects.get_or_create(
        id=_id("account-restriction", convention_key),
        defaults={
            "organization": organization,
            "edition": current,
            "account": cancelled.account,
            "kind": AccountRestriction.Kind.REGISTRATION,
            "status": AccountRestriction.Status.ACTIVE,
            "reason_code": "demo_registration_restriction",
            "attendee_message": (
                "Registration is unavailable for this synthetic edition. "
                "You may submit an appeal."
            ),
            "internal_reference": f"DEMO-CASE-{convention_key.upper()}-001",
            "notify_account": True,
            "effective_at": happened_at,
            "expires_at": happened_at + timedelta(days=120),
            "consequences_applied_at": happened_at + timedelta(minutes=1),
            "issued_by": chair,
        },
    )
    _own(own, "account_restrictions", restriction, created=created)

    appeal, created = RestrictionAppeal.objects.get_or_create(
        id=_id("restriction-appeal", convention_key),
        defaults={
            "restriction": restriction,
            "account": cancelled.account,
            "statement": (
                "Synthetic attendee asks the organizer to review the "
                "registration restriction."
            ),
            "status": RestrictionAppeal.Status.OPEN,
            "submitted_at": happened_at + timedelta(days=1),
        },
    )
    _own(own, "restriction_appeals", appeal, created=created)

    subject_request, created = SubjectRightsRequest.objects.get_or_create(
        id=_id("privacy-request", convention_key),
        defaults={
            "account": sponsor.account,
            "organization_id": organization.id,
            "kind": SubjectRightsRequest.Kind.ACCESS,
            "status": SubjectRightsRequest.Status.COMPLETED,
            "requested_at": happened_at,
            "request_summary": (
                "Synthetic attendee requests an export of convention data."
            ),
            "identity_verified_at": happened_at + timedelta(minutes=5),
            "completed_at": happened_at + timedelta(days=2),
            "safe_outcome_summary": (
                "Minimized synthetic export delivered through Maru."
            ),
        },
    )
    _own(own, "subject_rights_requests", subject_request, created=created)

    sponsor_profile = AttendeeRegistrationProfile.objects.get(registration=sponsor)
    correction, created = PostEditionCorrection.objects.get_or_create(
        id=_id("post-edition-correction", convention_key),
        defaults={
            "organization_id": organization.id,
            "edition_id": current.id,
            "account_id": sponsor.account_id,
            "target_type": "registration.attendee_profile",
            "target_id": sponsor_profile.id,
            "status": PostEditionCorrection.Status.APPROVED,
            "changed_fields": {"bio": "Corrected synthetic archival biography."},
            "reason": "Correct a synthetic historical presentation field.",
            "requested_by_id": sponsor.account_id,
            "requested_at": happened_at,
            "decided_by_id": registration_lead.id,
            "decided_at": happened_at + timedelta(days=1),
            "decision_reason": "Safe presentation-only correction approved.",
        },
    )
    _own(own, "post_edition_corrections", correction, created=created)

    retention_policy, created = RetentionPolicy.objects.get_or_create(
        id=_id("retention-policy", convention_key),
        defaults={
            "organization_id": organization.id,
            "jurisdiction_code": "DEMO-EU",
            "data_category": "failed-registration-profile",
            "version": 1,
            "retention_days": 90,
            "disposition": RetentionPolicy.Disposition.MINIMIZE,
            "lawful_basis": (
                "Synthetic demonstration policy; not legal advice or approval."
            ),
            "approved_by_id": administrator.id,
            "approved_at": datetime(2026, 1, 10, 12, tzinfo=UTC),
            "active": True,
        },
    )
    _own(
        own,
        "retention_policies",
        retention_policy,
        created=created,
    )

    cancelled_profile = AttendeeRegistrationProfile.objects.get(registration=cancelled)
    disposal, created = DisposalReceipt.objects.get_or_create(
        id=_id("disposal-receipt", convention_key),
        defaults={
            "organization_id": organization.id,
            "edition_id": current.id,
            "policy": retention_policy,
            "target_type": "registration.attendee_profile",
            "target_id": cancelled_profile.id,
            "disposition": RetentionPolicy.Disposition.MINIMIZE,
            "applied_at": happened_at + timedelta(days=100),
            "applied_by_id": registration_lead.id,
            "safe_result_code": "demo_profile_minimized",
            "downstream_receipts": [
                {
                    "system": "demo-object-storage",
                    "result": "no_media_present",
                }
            ],
        },
    )
    _own(own, "disposal_receipts", disposal, created=created)

    credential, created = Credential.objects.get_or_create(
        id=_id("credential", convention_key),
        defaults={
            "registration": checked_in,
            "organization_id": organization.id,
            "edition_id": current.id,
            "account_id": checked_in.account_id,
            "public_id": f"D{convention_key[:3].upper()}2026GUEST",
            "token_digest": _digest(f"{convention_key}:credential-token"),
            "status": Credential.Status.ISSUED,
            "issue_sequence": 1,
            "label_snapshot": "Invited Guest · All-event access",
            "issued_at": happened_at,
            "issued_by_id": registration_lead.id,
        },
    )
    _own(own, "credentials", credential, created=created)

    credential_event, created = CredentialEvent.objects.get_or_create(
        id=_id("credential-event", convention_key),
        defaults={
            "credential": credential,
            "organization_id": organization.id,
            "edition_id": current.id,
            "kind": CredentialEvent.Kind.ISSUED,
            "occurred_at": happened_at,
            "actor_kind": "account",
            "actor_id": registration_lead.id,
            "reason_code": "demo_credential_issued",
        },
    )
    _own(own, "credential_events", credential_event, created=created)

    device, created = RelayDevice.objects.get_or_create(
        id=_id("relay-device", convention_key),
        defaults={
            "organization_id": organization.id,
            "edition_id": current.id,
            "code": "front-desk-demo-01",
            "label": "Front Desk Demo Scanner 01",
            "signing_secret_env_var": (
                f"MARU_{convention_key.upper()}_DEMO_RELAY_SECRET"
            ),
            "enabled": True,
            "last_sequence": 2,
        },
    )
    _own(own, "relay_devices", device, created=created)

    manifest_payload = {
        "edition_id": str(current.id),
        "sequence": 1,
        "credentials": [
            {
                "public_id": credential.public_id,
                "status": credential.status,
                "label": credential.label_snapshot,
            }
        ],
    }
    manifest_json = json.dumps(
        manifest_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    manifest, created = OfflineCredentialManifest.objects.get_or_create(
        id=_id("offline-manifest", convention_key),
        defaults={
            "organization_id": organization.id,
            "edition_id": current.id,
            "sequence": 1,
            "valid_from": happened_at,
            "valid_until": happened_at + timedelta(hours=8),
            "generated_at": happened_at,
            "generated_by_id": registration_lead.id,
            "credential_count": 1,
            "payload": manifest_payload,
            "payload_digest": _digest(manifest_json),
            "signature": _digest(f"{convention_key}:{manifest_json}:signature"),
        },
    )
    _own(own, "offline_manifests", manifest, created=created)

    offline_operation, created = OfflineCheckInOperation.objects.get_or_create(
        id=_id("offline-operation", convention_key),
        defaults={
            "device": device,
            "organization_id": organization.id,
            "edition_id": current.id,
            "operation_id": _id("offline-operation-id", convention_key),
            "device_sequence": 1,
            "manifest_sequence": manifest.sequence,
            "credential_public_id": credential.public_id,
            "occurred_at": happened_at + timedelta(hours=4),
            "received_at": happened_at + timedelta(hours=5),
            "outcome": OfflineCheckInOperation.Outcome.CONFLICT,
            "safe_result_code": "already_checked_in_online",
            "credential": credential,
        },
    )
    _own(own, "offline_operations", offline_operation, created=created)

    for gate_code in EditionReadinessGate.Code.values:
        gate, created = EditionReadinessGate.objects.get_or_create(
            id=_id("edition-readiness-gate", f"{convention_key}.{gate_code}"),
            defaults={
                "edition": past,
                "organization_id": organization.id,
                "code": gate_code,
                "status": EditionReadinessGate.Status.APPROVED,
                "evidence_reference": (
                    f"DEMO-{convention_key.upper()}-{gate_code.upper()}-2025"
                ),
                "review_summary": (
                    f"Synthetic {gate_code} closure evidence was reviewed."
                ),
                "reviewed_by_id": chair.id,
                "reviewed_at": datetime(2025, 10, 10, 12, tzinfo=UTC),
            },
        )
        _own(own, "edition_readiness_gates", gate, created=created)

    closure_counts = {
        "guardian_pending": 0,
        "payment_pending": 0,
        "waitlisted": 0,
        "guardian_requests_open": 0,
        "payment_exceptions_open": 0,
        "financial_operations_open": 0,
        "settlements_open": 0,
        "delivery_failures": 0,
        "delivery_pending": 0,
        "profile_media_pending": 0,
        "historical_corrections_open": 0,
        "restriction_consequences_due": 0,
        "restriction_appeals_open": 0,
        "offline_conflicts": 0,
        "outbox_unfinished": 0,
    }
    canonical_counts = json.dumps(
        closure_counts,
        sort_keys=True,
        separators=(",", ":"),
    )
    closure, created = EditionClosureManifest.objects.get_or_create(
        id=_id("edition-closure-manifest", convention_key),
        defaults={
            "edition": past,
            "organization_id": organization.id,
            "generated_by_id": chair.id,
            "generated_at": datetime(2025, 10, 11, 12, tzinfo=UTC),
            "counts": closure_counts,
            "manifest_digest": _digest(canonical_counts),
            "recovery_reference": (f"DEMO-RESTORE-{convention_key.upper()}-2025"),
        },
    )
    _own(own, "edition_closure_manifests", closure, created=created)

    amendment, created = ArchiveAmendment.objects.get_or_create(
        id=_id("archive-amendment", convention_key),
        defaults={
            "edition": past,
            "actor_id": chair.id,
            "reason": (
                "Correct a synthetic public-history label without rewriting "
                "the archived source."
            ),
            "summary": ("Corrected the capitalization of a synthetic programme role."),
        },
    )
    _own(own, "archive_amendments", amendment, created=created)
