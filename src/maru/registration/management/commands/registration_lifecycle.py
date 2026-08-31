"""Process payment deadlines, inactive accounts, and automatic waitlist offers."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from maru.events.models import EventEdition
from maru.events.queries import adoption_profile_filter_for_module
from maru.identity.services import apply_due_account_restrictions
from maru.registration.models import RegistrationLifecycleRun
from maru.registration.services import (
    inspect_registration_lifecycle,
    process_registration_lifecycle,
)


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Expire overdue registration reservations, cancel open registrations for "
        "inactive accounts, and promote eligible waitlist entries."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--edition",
            type=UUID,
            help="Process only one event-edition UUID.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report currently eligible records without changing them.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Execute the management command.

        Parameters
        ----------
        *args : object
            Positional arguments forwarded to the framework implementation.
        **options : object
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If a requested edition does not adopt Registration at its exact
            selected manifest version.
        """
        del args
        edition_id = options.get("edition")
        if (
            isinstance(edition_id, UUID)
            and not EventEdition.objects.filter(
                adoption_profile_filter_for_module("registration"),
                id=edition_id,
            ).exists()
        ):
            raise CommandError("The edition is unavailable for Registration lifecycle.")
        if bool(options.get("dry_run")):
            candidates = inspect_registration_lifecycle(
                edition_id=edition_id if isinstance(edition_id, UUID) else None
            )
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: "
                    f"{candidates.expired} would expire, "
                    f"{candidates.inactive_cancelled} inactive-account registrations "
                    "would be cancelled, "
                    f"{candidates.closed_waitlist_cancelled} closed waitlist entries "
                    f"would be cancelled ({candidates.total} total state changes). "
                    "No state was changed and no waitlist offer was sent."
                )
            )
            return
        result = process_registration_lifecycle(
            edition_id=edition_id if isinstance(edition_id, UUID) else None
        )
        restrictions_applied = apply_due_account_restrictions(
            edition_id=edition_id if isinstance(edition_id, UUID) else None
        )
        RegistrationLifecycleRun.objects.create(
            edition_id=edition_id if isinstance(edition_id, UUID) else None,
            ran_at=timezone.now(),
            expired=result.expired,
            inactive_cancelled=result.inactive_cancelled,
            closed_waitlist_cancelled=result.closed_waitlist_cancelled,
            promoted=result.promoted,
            tier_replacements_expired=result.tier_replacements_expired,
            restrictions_applied=restrictions_applied,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Registration lifecycle processed: "
                f"{result.expired} expired, "
                f"{result.inactive_cancelled} inactive-account registrations "
                f"cancelled, {result.closed_waitlist_cancelled} closed waitlist "
                f"entries cancelled, {result.promoted} waitlist places offered, "
                f"{result.tier_replacements_expired} tier replacement holds expired."
                f" {restrictions_applied} scheduled restrictions applied."
            )
        )
