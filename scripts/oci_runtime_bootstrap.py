"""Create the one non-login actor used by the synthetic OCI rehearsal.

The OCI runner streams this file to the immutable application image on standard
input.  The helper therefore uses only APIs already present in that image and
does not alter its filesystem.  Its output is deliberately count-only.
"""

from __future__ import annotations

import json
import os
import sys
from uuid import UUID

ACTOR_ID = UUID("77089b79-12ee-5c56-b7a7-08a771b66033")
ACTOR_EMAIL = "oci.runtime.rehearsal.admin@maru.invalid"
ACTOR_DISPLAY_NAME = "OCI Runtime Rehearsal Administrator"
ALLOWED_SETTINGS_MODULES = frozenset({"maru.settings.local", "maru.settings.test"})


class RuntimeBootstrapConflictError(RuntimeError):
    """Signal that the reserved synthetic identity is not exact."""


def _write_result(payload: dict[str, object]) -> None:
    """Write one canonical count-only result.

    Parameters
    ----------
    payload : dict[str, object]
        The bounded result to emit on standard output.
    """
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def _environment_is_safe() -> bool:
    """Return whether the explicit synthetic-only environment is selected.

    Returns
    -------
    bool
        ``True`` only for Maru local/test settings with the rehearsal fence.
    """
    return (
        os.environ.get("DJANGO_SETTINGS_MODULE", "") in ALLOWED_SETTINGS_MODULES
        and os.environ.get("MARU_SYNTHETIC_OCI_REHEARSAL", "").casefold() == "true"
    )


def _bootstrap() -> dict[str, object]:
    """Create or verify the exact synthetic platform actor atomically.

    Returns
    -------
    dict[str, object]
        Count-only creation and invariant evidence.

    Raises
    ------
    RuntimeBootstrapConflictError
        If any existing account, organization, authority, or reserved identity
        differs from the isolated rehearsal contract.
    """
    from django.db import transaction  # noqa: PLC0415

    from maru.authorization.models import (  # noqa: PLC0415
        CapabilityGrant,
        RoleAssignment,
        RoleBundle,
    )
    from maru.identity.models import Account  # noqa: PLC0415
    from maru.organizations.models import Organization  # noqa: PLC0415

    with transaction.atomic():
        account_by_id = Account.objects.select_for_update().filter(pk=ACTOR_ID).first()
        account_by_email = (
            Account.objects.select_for_update()
            .filter(email__iexact=ACTOR_EMAIL)
            .first()
        )
        if account_by_id is not None and account_by_email != account_by_id:
            raise RuntimeBootstrapConflictError
        if account_by_email is not None and account_by_id != account_by_email:
            raise RuntimeBootstrapConflictError
        if Account.objects.exclude(pk=ACTOR_ID).exists():
            raise RuntimeBootstrapConflictError
        if Organization.objects.exists():
            raise RuntimeBootstrapConflictError
        if (
            CapabilityGrant.objects.exists()
            or RoleAssignment.objects.exists()
            or RoleBundle.objects.exists()
        ):
            raise RuntimeBootstrapConflictError

        created = account_by_id is None
        if created:
            account = Account.objects.create_superuser(
                id=ACTOR_ID,
                email=ACTOR_EMAIL,
                password=None,
                display_name=ACTOR_DISPLAY_NAME,
                preferred_language="en",
            )
        else:
            if account_by_id is None:  # pragma: no cover - narrowed above
                raise RuntimeBootstrapConflictError
            account = account_by_id

        expected = (
            account.id == ACTOR_ID
            and account.email == ACTOR_EMAIL
            and account.login_handle == ""
            and account.display_name == ACTOR_DISPLAY_NAME
            and account.preferred_language == "en"
            and account.account_kind == Account.Kind.PLATFORM_ADMINISTRATOR
            and account.is_active
            and account.is_staff
            and account.is_superuser
            and account.invitation_provisioning_origin_id is None
            and not account.has_usable_password()
            and not account.groups.exists()
            and not account.user_permissions.exists()
        )
        if not expected:
            raise RuntimeBootstrapConflictError

        return {
            "schema_version": 1,
            "status": "created" if created else "already_present",
            "synthetic_only": True,
            "login_enabled": False,
            "created": {"platform_administrators": int(created)},
            "totals": {
                "accounts": Account.objects.count(),
                "platform_administrators": Account.objects.filter(
                    account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                ).count(),
                "organizations": Organization.objects.count(),
                "ordinary_authority_records": (
                    CapabilityGrant.objects.count()
                    + RoleAssignment.objects.count()
                    + RoleBundle.objects.count()
                ),
            },
        }


def main() -> int:
    """Run the guarded synthetic bootstrap and emit only bounded JSON.

    Returns
    -------
    int
        Zero on success or a stable non-zero failure code.
    """
    if not _environment_is_safe():
        _write_result({"status": "failed", "code": "environment_invalid"})
        return 2

    try:
        import django  # noqa: PLC0415
        from django.db import DatabaseError, IntegrityError  # noqa: PLC0415

        django.setup()
        payload = _bootstrap()
    except RuntimeBootstrapConflictError:
        _write_result({"status": "failed", "code": "fixture_conflict"})
        return 3
    except (DatabaseError, IntegrityError):
        _write_result({"status": "failed", "code": "database_unavailable"})
        return 4
    except Exception:  # noqa: BLE001 - never disclose private exception text
        _write_result({"status": "failed", "code": "internal_error"})
        return 5

    _write_result(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
