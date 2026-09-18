"""Stopped, owned-fixture bootstrap through real Identity/Authorization owners.

This is not a generic seed command. It refuses populated databases, ordinary
runtime/admin logins, private worker keys, foreign policies and non-fixture scope.
Failure requires disposing the exact owned database, never clearing its evidence.
"""

import json
import os
import re
from uuid import uuid4

from tests.rehearsals.programme_fixture_material import (
    ADMIN_PASSWORD_ENV,
    BOOTSTRAP_VERSION,
    PRIVATE_KEYS_ENV,
    synthetic_retention_policy,
)
from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    require_provisioning_process_environment,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)


def _require_stopped_bootstrap_environment():
    request = require_programme_rehearsal_request()
    require_provisioning_process_environment()
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE")
        != "tests.rehearsals.programme_provisioning_settings"
        or os.environ.get("MARU_PROGRAMME_REHEARSAL_PROCESS") != "maru_migration"
        or os.environ.get("MARU_PROGRAMME_REHEARSAL_BOOTSTRAP") != BOOTSTRAP_VERSION
        or PRIVATE_KEYS_ENV in os.environ
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", os.environ.get(ADMIN_PASSWORD_ENV, ""))
        is None
    ):
        raise ProgrammeProvisioningError("foundation_bootstrap_environment_invalid")
    return request


def bootstrap_stopped_foundation():
    """Activate genuine provenance/retention in a fresh stopped owned fixture.

    Notes
    -----
    The provisioner calls this fixed child after canonical runtime verification
    and before candidate grants, workers, domain seeding or serving. Each owner
    controls its own transaction. Partial failure disposes the whole fixture;
    it never rewrites an activation, approval, policy or audit record.
    """
    request = _require_stopped_bootstrap_environment()
    import django  # noqa: PLC0415
    from django.conf import settings  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    django.setup()
    from maru.authorization.activation import (  # noqa: PLC0415
        activate_authority_provenance,
    )
    from maru.identity.invitation_key_config import (  # noqa: PLC0415
        active_invitation_encryption_key,
    )
    from maru.identity.invitation_retention import (  # noqa: PLC0415
        activate_configured_invitation_retention_policy,
        configured_invitation_retention_policy,
        invitation_retention_policy_control_is_ready,
    )
    from maru.identity.invitation_token_keys import (  # noqa: PLC0415
        invitation_token_keyring,
    )
    from maru.identity.models import Account  # noqa: PLC0415

    origin = re.fullmatch(
        r"https://127\.0\.0\.1:([1-9][0-9]{3,4})", settings.MARU_PUBLIC_BASE_URL
    )
    if (
        settings.SETTINGS_MODULE != "tests.rehearsals.programme_provisioning_settings"
        or settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is not True
        or settings.REQUIRE_PRIVILEGED_STEP_UP is not True
        or settings.DEBUG is not False
        or settings.EMAIL_BACKEND != "django.core.mail.backends.locmem.EmailBackend"
        or settings.IDENTITY_EXPOSE_TEST_TOKENS is not False
        or settings.MARU_EXPOSE_TEST_CREDENTIAL_TOKENS is not False
        or settings.SILENCED_SYSTEM_CHECKS
        or connection.in_atomic_block
        or not connection.get_autocommit()
        or origin is None
        or not 1024 <= int(origin[1]) <= 65535
    ):
        raise ProgrammeProvisioningError("foundation_bootstrap_settings_invalid")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), session_user, current_user, "
            "current_setting('server_version_num')::integer"
        )
        identity = cursor.fetchone()
        if (
            identity is None
            or identity[:3]
            != (f"maru_programme_{request.run_id}", "maru_migration", "maru_migration")
            or not 170000 <= identity[3] < 180000
        ):
            raise ProgrammeProvisioningError("foundation_bootstrap_identity_invalid")
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM public.django_migrations "
            "WHERE app = 'events' AND name = '0015_isolated_programme_candidate'), "
            "EXISTS (SELECT 1 FROM public.identity_account), "
            "EXISTS (SELECT 1 FROM public.organizations_organization), "
            "EXISTS (SELECT 1 FROM public.events_eventedition), "
            "EXISTS (SELECT 1 FROM "
            "public.authorization_authorityprovenanceactivation), "
            "EXISTS (SELECT 1 FROM "
            "public.identity_platforminvitationretentionpolicycontrol)"
        )
        if cursor.fetchone() != (True, False, False, False, False, False):
            raise ProgrammeProvisioningError("foundation_bootstrap_not_fresh")

    # Validate the real key/policy parsers before creating any identity. The
    # fixture-only jurisdiction/approval cannot be mistaken for legal acceptance.
    active_invitation_encryption_key()
    invitation_token_keyring()
    configured_invitation_retention_policy()
    try:
        policy = json.loads(settings.MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON)
    except (TypeError, ValueError):
        raise ProgrammeProvisioningError(
            "foundation_bootstrap_policy_invalid"
        ) from None
    expected = synthetic_retention_policy(request.run_id)
    if set(policy) != set(expected) | {"approved_at"} or any(
        policy[key] != value for key, value in expected.items()
    ):
        raise ProgrammeProvisioningError("foundation_bootstrap_policy_invalid")
    administrator = Account.objects.create_superuser(
        email=f"programme-platform-{request.run_id}@example.invalid",
        password=os.environ[ADMIN_PASSWORD_ENV],
        display_name="Synthetic Programme platform administrator",
    )
    activation = activate_authority_provenance(
        actor=administrator,
        reason="Fresh synthetic Programme fixture; no serving processes started.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="programme_fixture",
    )
    if (
        activation.activated is not True
        or activation.production_status != "ready"
        or activation.blocker_total != 0
    ):
        raise ProgrammeProvisioningError("foundation_bootstrap_activation_unavailable")
    activate_configured_invitation_retention_policy()
    if not invitation_retention_policy_control_is_ready():
        raise ProgrammeProvisioningError("foundation_bootstrap_retention_unavailable")
