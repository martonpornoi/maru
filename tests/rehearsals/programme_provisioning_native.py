"""Host-only #102 provisioning proof; no routine discovery or deferred execution."""

import secrets
from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals import programme_provisioning as provisioning
from tests.rehearsals.programme_database import isolated_programme_database
from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    provision_programme_runtime,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("candidate_schema", [False, True])
def test_native_migration_runtime_separation_and_reprovision_refusal(
    monkeypatch, candidate_schema
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_database() as lease:
        runtime = provision_programme_runtime(lease, candidate_schema=candidate_schema)
        with psycopg.connect(
            runtime.database_url,
            connect_timeout=5,
            options="-c search_path=public,pg_temp",
        ) as connection:
            assert connection.execute(
                "SELECT current_database(), session_user, current_user"
            ).fetchone() == (lease.database_name, "maru_runtime", "maru_runtime")
            assert connection.execute(
                "SELECT pg_catalog.pg_get_userbyid(datdba) "
                "FROM pg_catalog.pg_database WHERE datname = current_database()"
            ).fetchone() == ("maru_migration",)
            definition, validated = connection.execute(
                "SELECT pg_catalog.pg_get_constraintdef(oid), convalidated "
                "FROM pg_catalog.pg_constraint "
                "WHERE conrelid = 'public.events_eventedition'::regclass "
                "AND conname = 'edition_adoption_profile_supported'"
            ).fetchone()
            assert validated is True
            assert ("programme_operations" in definition) is candidate_schema
            assert "full_convention" in definition
            assert "workforce_only" in definition
            assert connection.execute(
                "SELECT EXISTS (SELECT 1 FROM public.django_migrations "
                "WHERE app = 'events' AND name = '0015_isolated_programme_candidate')"
            ).fetchone() == (candidate_schema,)
            with (
                pytest.raises(psycopg.errors.InsufficientPrivilege),
                connection.transaction(),
            ):
                connection.execute(
                    "CREATE TABLE public.forbidden_runtime_ddl (id integer)"
                )
        with pytest.raises(
            ProgrammeProvisioningError, match="existing_provisioning_roles"
        ):
            provision_programme_runtime(lease)
        if candidate_schema:
            environment = provisioning._child_environment(
                lease,
                require_programme_rehearsal_request(),
                role="maru_runtime",
                password="",  # Replaced by the already verified endpoint below.
                secret_key=secrets.token_urlsafe(64),
            ) | {"MARU_DATABASE_URL": runtime.database_url}
            provisioning._child(
                [
                    "-c",
                    """
from tests.rehearsals.programme_registration import (
    register_isolated_programme_candidate,
)
from maru.events import adoption
before = dict(adoption.ADOPTION_PROFILES)
register_isolated_programme_candidate()
import django
django.setup()
from maru.events.models import EventEdition
from maru.events.checks import (
    adoption_manifest_catalog_problem_codes, current_adoption_catalog_snapshot,
)
from maru.programme.checks import programme_dormancy_problem_codes
for key, profile in before.items():
    assert adoption.ADOPTION_PROFILES[key] is profile
assert adoption.adoption_profile("programme_operations", 1) is not None
assert adoption.adoption_profile("programme_operations", 2) is None
choices = dict(EventEdition._meta.get_field("adoption_profile_code").choices)
assert "programme_operations" in choices
assert not adoption_manifest_catalog_problem_codes(
    profiles=adoption.ADOPTION_PROFILES,
    selectable_profile_keys=adoption.SELECTABLE_ADOPTION_PROFILE_KEYS,
    catalog=current_adoption_catalog_snapshot(),
)
# Registration is deliberately not startup acceptance.
assert programme_dormancy_problem_codes()
print("programme-candidate-registration-verified")
""",
                ],
                environment,
                timeout=60,
                expected_output="programme-candidate-registration-verified",
            )


@pytest.mark.parametrize("drift", [False, True])
def test_native_candidate_empty_roundtrip_or_drift_refusal(monkeypatch, drift):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    original_child = provisioning._child

    def inspect_overlay(arguments, environment, **kwargs):
        if environment.get("MARU_PROGRAMME_REHEARSAL_SCHEMA") != "candidate-v1":
            return original_child(arguments, environment, **kwargs)
        if drift:
            original_child(
                [
                    "-c",
                    """
import django
django.setup()
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("ALTER TABLE public.events_eventedition "
                   "DROP CONSTRAINT edition_adoption_profile_supported")
    cursor.execute("ALTER TABLE public.events_eventedition ADD CONSTRAINT "
                   "edition_adoption_profile_supported CHECK (true)")
""",
                ],
                environment,
                timeout=60,
            )
            return original_child(arguments, environment, **kwargs)
        original_child(arguments, environment, **kwargs)
        original_child(
            [
                "-m",
                "django",
                "migrate",
                "events",
                "0014_programme_setup_downgrade_fence",
                "--noinput",
            ],
            environment,
            **kwargs,
        )
        return original_child(arguments, environment, **kwargs)

    monkeypatch.setattr(provisioning, "_child", inspect_overlay)
    with isolated_programme_database() as lease:
        if drift:
            with pytest.raises(ProgrammeProvisioningError, match="process_failed"):
                provision_programme_runtime(lease, candidate_schema=True)
        else:
            provision_programme_runtime(lease, candidate_schema=True)
