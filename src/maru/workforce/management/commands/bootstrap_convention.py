"""Establish the first convention chair and starter workforce catalog."""

import json
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.bootstrap import bootstrap_organization_workforce


class Command(BaseCommand):
    help = (
        "Recovery-only one-time bootstrap for an empty active organization's "
        "Draft or Preparing edition, convention chair, Page 9 leadership "
        "Department, and position templates."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument(
            "--edition",
            required=True,
            help="Draft or Preparing edition slug.",
        )
        parser.add_argument(
            "--controller-email",
            required=True,
            help="Existing active Django superuser.",
        )
        parser.add_argument(
            "--chair-email",
            required=True,
            help="Existing distinct active account to become convention chair.",
        )
        parser.add_argument("--reason", required=True)
        parser.add_argument(
            "--confirm-organization",
            required=True,
            help="Repeat the exact organization slug to authorize the one-shot action.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        _ = args
        slug = str(options["organization"]).strip().lower()
        if str(options["confirm_organization"]).strip().lower() != slug:
            raise CommandError(
                "--confirm-organization must exactly match --organization."
            )
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError("The organization is unavailable.")
        edition = EventEdition.objects.filter(
            organization=organization,
            slug=str(options["edition"]).strip().lower(),
        ).first()
        if edition is None:
            raise CommandError("The edition is unavailable.")
        controller = Account.objects.filter(
            email__iexact=str(options["controller_email"]).strip()
        ).first()
        chair = Account.objects.filter(
            email__iexact=str(options["chair_email"]).strip()
        ).first()
        if controller is None or chair is None:
            raise CommandError("Both named accounts must already exist.")
        try:
            result = bootstrap_organization_workforce(
                organization=organization,
                edition=edition,
                controller=controller,
                chair=chair,
                reason=str(options["reason"]),
                correlation_id=uuid4(),
                source_channel="management_command",
            )
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        self.stdout.write(
            json.dumps(
                {
                    "organization": organization.slug,
                    "edition": edition.slug,
                    "controller": controller.email,
                    "chair": chair.email,
                    "created": result,
                },
                indent=2,
                sort_keys=True,
            )
        )
