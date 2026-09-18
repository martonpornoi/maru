"""Host-only #102 provisioning proof; no routine discovery or deferred execution."""

import secrets
from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals import programme_provisioning as provisioning
from tests.rehearsals.programme_database import isolated_programme_database
from tests.rehearsals.programme_fixture_material import generate_fixture_material
from tests.rehearsals.programme_provisioning import (
    ProgrammeProvisioningError,
    provision_programme_runtime,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("candidate_schema", "candidate_writes"),
    [(False, False), (True, False), (True, True)],
)
def test_native_migration_runtime_separation_and_reprovision_refusal(
    monkeypatch, candidate_schema, candidate_writes
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_database() as lease:
        runtime = provision_programme_runtime(
            lease, candidate_schema=candidate_schema, candidate_writes=candidate_writes
        )
        with psycopg.connect(
            runtime.database_url,
            connect_timeout=5,
            options="-c search_path=public,pg_temp",
        ) as connection:
            assert connection.execute(
                "SELECT current_database(), session_user, current_user"
            ).fetchone() == (lease.database_name, "maru_runtime", "maru_runtime")
            from tests.rehearsals.programme_runtime_privileges import (  # noqa: PLC0415
                PRIVILEGES,
            )

            for table, allowed in PRIVILEGES.items():
                actual = connection.execute(
                    "SELECT pg_catalog.has_table_privilege("
                    "current_user, %s, permission) "
                    "FROM unnest(%s::text[]) WITH ORDINALITY "
                    "AS requested(permission, position) ORDER BY position",
                    [
                        table,
                        [
                            "SELECT",
                            "INSERT",
                            "UPDATE",
                            "DELETE",
                            "REFERENCES",
                            "TRIGGER",
                            "TRUNCATE",
                            "MAINTAIN",
                        ],
                    ],
                ).fetchall()
                expected = [(True,)] + [
                    (candidate_writes and permission in allowed,)
                    for permission in (
                        "INSERT",
                        "UPDATE",
                        "DELETE",
                        "REFERENCES",
                        "TRIGGER",
                        "TRUNCATE",
                        "MAINTAIN",
                    )
                ]
                assert actual == expected
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
from tests.rehearsals.programme_runtime import (
    ProgrammeStartupError, _require_native_readiness,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
try:
    _require_native_readiness(require_programme_runtime_environment())
except ProgrammeStartupError as error:
    # Real identity, installed migration and physical profile constraint must
    # pass before the genuinely inactive authority boundary refuses readiness.
    assert str(error) == "candidate_native_readiness_unavailable"
else:
    raise AssertionError("Unactivated native authority unexpectedly ready")
print("programme-candidate-registration-verified")
""",
                ],
                environment,
                timeout=60,
                expected_output="programme-candidate-registration-verified",
            )


def test_native_stopped_foundation_has_real_activation_and_no_person_or_edition(
    monkeypatch,
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    material = generate_fixture_material(web_port=55443)  # Configuration, not a socket.
    with isolated_programme_database() as lease:
        runtime = provision_programme_runtime(
            lease,
            candidate_schema=True,
            candidate_writes=True,
            fixture_material=material,
        )
        environment = (
            provisioning._child_environment(
                lease,
                require_programme_rehearsal_request(),
                role="maru_runtime",
                password="",
                secret_key=material.secret_key,
            )
            | dict(material.runtime_configuration)
            | {"MARU_DATABASE_URL": runtime.database_url}
        )
        provisioning._child(
            [
                "-c",
                """
from tests.rehearsals.programme_registration import (
    register_isolated_programme_candidate,
)
register_isolated_programme_candidate()
import django
django.setup()
from tests.rehearsals.programme_runtime_privileges import (
    install_isolated_candidate_privilege_contract,
)
install_isolated_candidate_privilege_contract()
from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)
from maru.identity.invitation_retention import (
    invitation_retention_policy_control_is_ready,
)
from maru.identity.models import Account
from maru.events.models import EventEdition
from maru.organizations.models import Organization
from django.db import connection
assert build_authority_provenance_readiness_report()["production_status"] == "ready"
assert invitation_retention_policy_control_is_ready()
assert Account.objects.count() == 1
assert Account.objects.get().is_platform_administrator
assert not Organization.objects.exists()
assert not EventEdition.objects.exists()
with connection.cursor() as cursor:
    cursor.execute("SELECT session_user, current_user")
    assert cursor.fetchone() == ("maru_runtime", "maru_runtime")
print("programme-native-foundation-verified")
""",
            ],
            environment,
            timeout=180,
            expected_output="programme-native-foundation-verified",
        )
        candidate_environment = environment | {
            "DJANGO_SETTINGS_MODULE": "tests.rehearsals.programme_runtime_settings"
        }
        provisioning._child(
            [
                "-c",
                """
from tests.rehearsals.programme_invitation_worker import run_invitation_worker_cycle
assert len(run_invitation_worker_cycle()) == 3
print("programme-native-worker-verified")
""",
            ],
            candidate_environment | material.worker_environment(),
            timeout=180,
            expected_output="programme-native-worker-verified",
        )
        provisioning._child(
            [
                "-c",
                """
import os
assert "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON" not in os.environ
assert "MARU_PROGRAMME_REHEARSAL_ADMIN_PASSWORD" not in os.environ
from tests.rehearsals.programme_runtime import build_candidate_application
application, accounted = build_candidate_application()
assert callable(application)
assert len(accounted) == 3
print("programme-native-application-constructed")
""",
            ],
            candidate_environment,
            timeout=180,
            expected_output="programme-native-application-constructed",
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
