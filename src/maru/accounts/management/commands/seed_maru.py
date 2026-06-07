from __future__ import annotations

from django.core.management.base import BaseCommand

from maru.accounts.access_config import ensure_default_access_configuration
from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import seeded_accounts


class Command(BaseCommand):
    help = "Seed baseline maru access accounts and roles."

    def handle(self, *args, **options):
        ensure_default_access_configuration()
        for account in seeded_accounts():
            grant, _ = AccessGrant.objects.update_or_create(
                email=account.email, defaults={"active": account.active}
            )
            for role in account.roles:
                AccessRole.objects.get_or_create(grant=grant, role=role.value)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {grant.email} with roles: "
                    f"{', '.join(sorted(role.value for role in account.roles))}"
                )
            )
