"""Pin the reviewed environment retention policy in the database control plane."""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from maru.identity.invitation_retention import (
    InvitationRetentionConfigurationError,
    activate_configured_invitation_retention_policy,
)


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Activate the exact MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON "
        "policy. Run this with the controlled migration/cutover database role."
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
            If the command cannot complete safely with the supplied state.
        """
        del args, options
        try:
            control = activate_configured_invitation_retention_policy()
        except (DatabaseError, InvitationRetentionConfigurationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Invitation retention policy control is active: "
                f"version={control.policy_version} digest={control.policy_digest}."
            )
        )
