"""Fail-closed application construction for the isolated Programme rehearsal.

This is not a fixture launcher: foundation/provenance setup and credentials must
already exist through genuine owners. No server/socket is opened here. The
eventual owned runner consumes this application only after preparation succeeds.
"""

import os

from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)

# Declared exact SQL expectation, not an observed native fingerprint. Native
# acceptance must confirm it on supported PG17; any formatting/schema mismatch
# refuses startup rather than being normalized away.
_PROFILE_CHECK = (
    "CHECK (("
    + " OR ".join(
        "(((adoption_profile_code)::text = '"
        + code
        + "'::text) AND (adoption_profile_version = 1))"
        for code in ("full_convention", "workforce_only", "programme_operations")
    )
    + "))"
)


class ProgrammeStartupError(RuntimeError):
    """Report a stable startup failure without connection or checker contents."""


def _runtime_configuration_is_strict(settings):
    return (
        settings.SETTINGS_MODULE == "tests.rehearsals.programme_runtime_settings"
        and settings.DEBUG is False
        and settings.ALLOWED_HOSTS == ["127.0.0.1"]
        and settings.ROOT_URLCONF == "tests.rehearsals.programme_urls"
        and settings.MIGRATION_MODULES
        == {"events": "tests.rehearsals.programme_event_migrations"}
        and settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is True
        and settings.REQUIRE_PRIVILEGED_STEP_UP is True
        and settings.ENFORCE_EDITION_CLOSURE_GATES is True
        and settings.IDENTITY_INVITATION_ENCRYPTION_REQUIRED is True
        and settings.IDENTITY_EXPOSE_TEST_TOKENS is False
        and settings.MARU_EXPOSE_TEST_CREDENTIAL_TOKENS is False
        and settings.DEMO_PAYMENT_ADAPTER_ENABLED is False
        and not settings.SILENCED_SYSTEM_CHECKS
        and settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    )


def _require_native_readiness(environment):
    from django.db import connection  # noqa: PLC0415
    from django.test import RequestFactory  # noqa: PLC0415

    from maru.authorization.programme_role_readiness import (  # noqa: PLC0415
        programme_role_database_integrity_is_ready,
    )
    from maru.core.views import readiness  # noqa: PLC0415
    from maru.events.programme_setup_readiness import (  # noqa: PLC0415
        programme_setup_database_integrity_is_ready,
    )
    from tests.rehearsals.programme_runtime_privileges import (  # noqa: PLC0415
        require_candidate_reference_boundary,
    )

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), session_user, current_user")
        if cursor.fetchone() != (
            environment.database_name,
            "maru_runtime",
            "maru_runtime",
        ):
            raise ProgrammeStartupError("candidate_runtime_identity_mismatch")
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM public.django_migrations "
            "WHERE app = 'events' AND name = '0015_isolated_programme_candidate')"
        )
        if cursor.fetchone() != (True,):
            raise ProgrammeStartupError("candidate_schema_not_installed")
        cursor.execute(
            "SELECT pg_catalog.pg_get_constraintdef(oid, false), convalidated, "
            "conislocal, coninhcount, connoinherit "
            "FROM pg_catalog.pg_constraint "
            "WHERE conrelid = 'public.events_eventedition'::regclass "
            "AND conname = 'edition_adoption_profile_supported' AND contype = 'c'"
        )
        if cursor.fetchall() != [(_PROFILE_CHECK, True, True, 0, False)]:
            raise ProgrammeStartupError("candidate_profile_constraint_changed")
        require_candidate_reference_boundary(cursor)
    response = readiness(RequestFactory().get("/health/ready", HTTP_HOST="127.0.0.1"))
    if (
        response.status_code != 200
        or response.data.get("status") != "ok"
        or not response.data.get("dependencies")
        or any(value != "ok" for value in response.data["dependencies"].values())
        or not programme_setup_database_integrity_is_ready()
        or not programme_role_database_integrity_is_ready()
    ):
        raise ProgrammeStartupError("candidate_native_readiness_unavailable")


def build_candidate_application():
    """Construct WSGI only after real owner compatibility and native readiness.

    Returns
    -------
    tuple
        WSGI application and explicitly accounted-for dormant owner check IDs.
        The caller still owns the loopback server, resource lease and cleanup.

    Notes
    -----
    No account, role, grant, activation latch or approval is manufactured here.
    Normal deployment checks still reject the isolated profile. This component
    does not certify production transport or replace the P01-P12 journey.
    """
    environment = require_programme_runtime_environment()
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE")
        != "tests.rehearsals.programme_runtime_settings"
    ):
        raise ProgrammeStartupError("candidate_settings_required")
    if any(
        name in os.environ
        for name in (
            "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON",
            "MARU_PROGRAMME_REHEARSAL_ADMIN_PASSWORD",
            "MARU_PROGRAMME_REHEARSAL_BOOTSTRAP",
        )
    ):
        raise ProgrammeStartupError("candidate_web_secret_contamination")
    import django  # noqa: PLC0415
    from django.conf import settings  # noqa: PLC0415

    django.setup()
    if not _runtime_configuration_is_strict(settings):
        raise ProgrammeStartupError("candidate_settings_weakened")
    from tests.rehearsals.programme_compatibility import (  # noqa: PLC0415
        check_isolated_candidate,
    )
    from tests.rehearsals.programme_effects import (  # noqa: PLC0415
        install_isolated_candidate_handlers,
    )
    from tests.rehearsals.programme_runtime_privileges import (  # noqa: PLC0415
        install_isolated_candidate_privilege_contract,
    )

    install_isolated_candidate_privilege_contract()
    install_isolated_candidate_handlers()
    accounted = check_isolated_candidate()
    _require_native_readiness(environment)
    from django.core.wsgi import get_wsgi_application  # noqa: PLC0415

    return get_wsgi_application(), accounted
