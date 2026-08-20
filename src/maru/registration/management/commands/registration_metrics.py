"""Emit tenant/edition-scoped registration safety metrics."""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import models
from django.db.models import Count
from django.utils import timezone

from maru.communications.models import NotificationDelivery
from maru.effects.models import OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import AccountRestriction
from maru.registration.availability import OCCUPIED_REGISTRATION_STATES
from maru.registration.models import (
    AdmissionProduct,
    FinancialOperation,
    PaymentException,
    PaymentIntent,
    Registration,
    RegistrationConfiguration,
    RegistrationLifecycleRun,
)
from maru.registration.services import inspect_registration_lifecycle


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Emit Prometheus registration lifecycle and capacity safety metrics."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--organization", type=UUID, required=True)
        parser.add_argument("--edition", type=UUID, required=True)
        parser.add_argument("--fail-on-drift", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the management command.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **options : Any
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
        del args
        organization_id: UUID = options["organization"]
        edition_id: UUID = options["edition"]
        if not EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
        ).exists():
            raise CommandError("The edition is unavailable in this organization.")
        candidates = inspect_registration_lifecycle(edition_id=edition_id)
        now = timezone.now()
        oldest_due = (
            Registration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                state=Registration.State.PAYMENT_PENDING,
                payment_due_at__lte=now,
            )
            .order_by("payment_due_at")
            .values_list("payment_due_at", flat=True)
            .first()
        )
        oldest_overdue = (
            max(0, int((now - oldest_due).total_seconds())) if oldest_due else 0
        )
        last_run = (
            RegistrationLifecycleRun.objects.filter(edition_id=edition_id)
            .order_by("-ran_at")
            .values_list("ran_at", flat=True)
            .first()
        )
        configuration_drift = 0
        for configuration in RegistrationConfiguration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status="active",
        ):
            occupied = Registration.objects.filter(
                configuration=configuration,
                state__in=OCCUPIED_REGISTRATION_STATES,
            ).count()
            configuration_drift += max(0, occupied - configuration.capacity)
        product_drift = 0
        products = AdmissionProduct.objects.filter(
            configuration__organization_id=organization_id,
            configuration__edition_id=edition_id,
        ).annotate(
            occupied=Count(
                "registrations",
                filter=models.Q(registrations__state__in=OCCUPIED_REGISTRATION_STATES),
            )
        )
        for product in products:
            product_drift += max(0, product.occupied - product.capacity)
        values = {
            "registration_lifecycle_candidates": candidates.total,
            "registration_expiry_candidates": candidates.expired,
            "registration_oldest_overdue_seconds": oldest_overdue,
            "registration_lifecycle_last_success_age_seconds": (
                max(0, int((now - last_run).total_seconds())) if last_run else -1
            ),
            "registration_capacity_drift": configuration_drift + product_drift,
            "registration_payment_exceptions_open": PaymentException.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=PaymentException.Status.OPEN,
            ).count(),
            "registration_payment_intents_uncertain": PaymentIntent.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status__in=(
                    PaymentIntent.Status.UNCERTAIN,
                    PaymentIntent.Status.MISMATCH,
                    PaymentIntent.Status.LATE,
                ),
            ).count(),
            "registration_financial_operations_open": (
                FinancialOperation.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    status__in=(
                        FinancialOperation.Status.PROPOSED,
                        FinancialOperation.Status.APPROVED,
                        FinancialOperation.Status.PROVIDER_PENDING,
                    ),
                ).count()
            ),
            "registration_due_restrictions_unapplied": (
                AccountRestriction.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    status=AccountRestriction.Status.ACTIVE,
                    consequences_applied_at__isnull=True,
                    effective_at__lte=now,
                )
                .filter(
                    models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
                )
                .count()
            ),
            "registration_delivery_failures": NotificationDelivery.objects.filter(
                message__organization_id=organization_id,
                message__edition_id=edition_id,
                status=NotificationDelivery.Status.PERMANENT_FAILED,
            ).count(),
            "registration_outbox_quarantined": OutboxMessage.objects.filter(
                organization_id=organization_id,
                event__event_edition_id=edition_id,
                status=OutboxMessage.Status.QUARANTINED,
            ).count(),
        }
        for name, value in values.items():
            self.stdout.write(f"{name} {value}")
        if options["fail_on_drift"] and values["registration_capacity_drift"]:
            raise CommandError("Registration capacity drift detected.")
