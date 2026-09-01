"""PostgreSQL regressions for V2 runtime-executable helper hardening."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

from maru.authorization import provenance_readiness
from maru.authorization.activation import activate_authority_provenance
from maru.authorization.models import AuthorityProvenanceActivation
from maru.organizations.models import OrganizationRepresentation
from maru.workforce.models import (
    Position,
    PositionAssignment,
    PositionTemplate,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleBundleFactory,
)
from tests.support.authority import activate_synthetic_board
from tests.support.migrations import workforce_migration_targets
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_assignment_for_test,
    save_position_for_test,
)

if TYPE_CHECKING:
    from maru.events.models import EventEdition

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(
        "proves_safe_runtime_database_role",
        "restores_current_migration_graph",
    ),
]

ORGANIZATIONS_BEFORE = (
    "organizations",
    "0012_idn011_convention_subject_guards",
)
ORGANIZATIONS_AFTER = (
    "organizations",
    "0013_runtime_executable_function_hardening",
)
WORKFORCE_BEFORE = ("workforce", "0004_scope_v2_integrity")
WORKFORCE_AFTER = (
    "workforce",
    "0005_runtime_executable_function_hardening",
)
SAFE_SEARCH_PATH = ["search_path=pg_catalog, public, pg_temp"]
FUNCTION_IDENTIFIERS = {
    "public.maru_assert_active_board_membership_provenance(uuid)": (
        "organizations_organizationmembership",
        "organizations_organizationrepresentation",
        "organizations_representationappointment",
    ),
    "public.maru_assert_active_executive_board(uuid)": (
        "organizations_organizationmembership",
        "organizations_organizationrepresentation",
        "organizations_representationappointment",
        "organizations_organization",
        "authorization_roleassignment",
        "authorization_rolebundle",
        "identity_account",
        "audit_auditevent",
        "effects_domainevent",
        "effects_outboxmessage",
        "maru_assert_active_executive_board_v0009",
    ),
    "public.maru_assert_active_executive_board_v0009(uuid)": (
        "organizations_organizationmembership",
        "organizations_organizationrepresentation",
        "organizations_representationappointment",
        "organizations_organization",
        "authorization_roleassignment",
        "authorization_rolebundle",
        "identity_account",
        "audit_auditevent",
        "effects_domainevent",
        "effects_outboxmessage",
    ),
    (
        "public.maru_workforce_role_evidence_matches_position"
        "(uuid,uuid,uuid,uuid,uuid,uuid)"
    ): (
        "authorization_roleassignment",
        "authorization_scopedresourcebinding",
    ),
}
CALLER_FUNCTION_TARGETS = {
    "public.maru_deferred_validate_board_membership_from_representation()": (
        "maru_assert_active_board_membership_provenance"
    ),
    "public.maru_deferred_validate_board_membership_from_appointment()": (
        "maru_assert_active_board_membership_provenance"
    ),
    "public.maru_deferred_validate_board_membership()": (
        "maru_assert_active_board_membership_provenance"
    ),
    "public.maru_deferred_validate_representation()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_appointment()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_role_assignment()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_role_bundle()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_membership()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_board_account()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_deferred_validate_board_organization()": (
        "maru_assert_active_executive_board"
    ),
    "public.maru_guard_workforce_position()": (
        "maru_workforce_role_evidence_matches_position"
    ),
    "public.maru_guard_workforce_assignment()": (
        "maru_workforce_role_evidence_matches_position"
    ),
}
CALLER_RELATIONS = {
    "authorization_rolebundle",
    "authorization_scopedresourcebinding",
    "events_eventedition",
    "identity_account",
    "organizations_organizationrepresentation",
    "organizations_representationappointment",
    "participation_participation",
    "participation_participationcapacity",
    "workforce_department",
    "workforce_position",
    "workforce_positionassignment",
    "workforce_positiontemplate",
}


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(workforce_migration_targets(executor, *targets))
    return executor


def _function_contract() -> dict[str, tuple[object, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT signature,
                   procedure.oid,
                   pg_get_functiondef(procedure.oid),
                   procedure.prosrc,
                   procedure.proconfig,
                   procedure.proowner,
                   procedure.proacl
              FROM unnest(%s::text[]) AS required(signature)
              JOIN pg_proc AS procedure
                ON procedure.oid = to_regprocedure(required.signature)
             ORDER BY signature
            """,
            [list(FUNCTION_IDENTIFIERS)],
        )
        return {str(row[0]): tuple(row[1:]) for row in cursor.fetchall()}


def _caller_contract() -> dict[str, tuple[str, list[str] | None]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT signature, procedure.prosrc, procedure.proconfig
              FROM unnest(%s::text[]) AS required(signature)
              JOIN pg_proc AS procedure
                ON procedure.oid = to_regprocedure(required.signature)
             ORDER BY signature
            """,
            [list(CALLER_FUNCTION_TARGETS)],
        )
        return {str(row[0]): (str(row[1]), row[2]) for row in cursor.fetchall()}


def _assert_hardened(contract: dict[str, tuple[object, ...]]) -> None:
    assert contract.keys() == FUNCTION_IDENTIFIERS.keys()
    for signature, identifiers in FUNCTION_IDENTIFIERS.items():
        source = str(contract[signature][2])
        assert contract[signature][3] == SAFE_SEARCH_PATH
        for identifier in identifiers:
            assert f"public.{identifier}" in source
            assert not re.search(
                rf"(?<![A-Za-z0-9_.]){re.escape(identifier)}(?![A-Za-z0-9_])",
                source,
            )


def _activate() -> AuthorityProvenanceActivation:
    actor = AccountFactory(is_staff=True, is_superuser=True)
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True):
        activate_authority_provenance(
            actor=actor,
            reason="Activate exact lineage for a runtime helper regression.",
            correlation_id=uuid4(),
            acknowledge_processes_stopped=True,
            source_channel="test",
        )
    return AuthorityProvenanceActivation.objects.get(singleton=True)


def _workforce_graph() -> tuple[EventEdition, Position, PositionAssignment]:
    actor = AccountFactory()
    assignee = AccountFactory()
    edition = EventEditionFactory()
    role_bundle = RoleBundleFactory(
        organization=edition.organization,
        capability_codes=["organizations.view_basic"],
    )
    department = create_department_for_test(
        edition=edition,
        name="Runtime shadow department",
        expected_code="runtime-shadow-department",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"runtime-shadow-{uuid4().hex[:8]}",
        name="Runtime shadow template",
        description="Synthetic trigger resolution template.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=actor,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code=f"runtime-shadow-{uuid4().hex[:8]}",
            title="Runtime shadow position",
            description="Synthetic trigger resolution position.",
            capacity_codes=["staff"],
            created_by=actor,
        )
    )
    assignment = save_position_assignment_for_test(
        assignment=PositionAssignment(
            position=position,
            organization=edition.organization,
            edition=edition,
            account=assignee,
            effective_from=timezone.now(),
            proposed_by=actor,
            reason="Exercise hardened trigger resolution.",
        )
    )
    return edition, position, assignment


def test_fresh_and_populated_forward_reverse_preserve_definition_identity_and_acl() -> (
    None
):
    organization = OrganizationFactory()
    organization_id = organization.id

    with transaction.atomic():
        _migrate(ORGANIZATIONS_BEFORE, WORKFORCE_BEFORE)
        with connection.cursor() as cursor:
            for signature in FUNCTION_IDENTIFIERS:
                cursor.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC")
        baseline = _function_contract()
        assert baseline.keys() == FUNCTION_IDENTIFIERS.keys()
        assert all(row[3] is None for row in baseline.values())

        _migrate(ORGANIZATIONS_AFTER, WORKFORCE_AFTER)
        hardened = _function_contract()
        _assert_hardened(hardened)
        for signature in FUNCTION_IDENTIFIERS:
            assert hardened[signature][0] == baseline[signature][0]
            assert hardened[signature][4:] == baseline[signature][4:]

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM public.organizations_organization WHERE id = %s",
                [organization_id],
            )
            assert cursor.fetchone() == (1,)

        _migrate(ORGANIZATIONS_BEFORE, WORKFORCE_BEFORE)
        assert _function_contract() == baseline
        transaction.set_rollback(True)


def test_hostile_search_path_and_shadow_objects_cannot_redirect_runtime_helpers() -> (
    None
):
    organization = OrganizationFactory()
    activate_synthetic_board(organization)
    representation = OrganizationRepresentation.objects.get(
        organization=organization,
        code=OrganizationRepresentation.EXECUTIVE_BOARD_CODE,
    )
    _edition, position, _assignment = _workforce_graph()
    hostile_schema = f"runtime_shadow_{uuid4().hex}"
    shadow_relations = {
        identifier
        for identifiers in FUNCTION_IDENTIFIERS.values()
        for identifier in identifiers
        if not identifier.startswith("maru_")
    } | CALLER_RELATIONS

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('search_path')")
        original_search_path = str(cursor.fetchone()[0])
        cursor.execute(f'CREATE SCHEMA "{hostile_schema}"')
        try:
            for relation in sorted(shadow_relations):
                cursor.execute(
                    f'CREATE TABLE "{hostile_schema}"."{relation}" (trap integer)'
                )
            cursor.execute(
                f"""
                CREATE FUNCTION
                    "{hostile_schema}".maru_assert_active_executive_board_v0009(
                        uuid
                    )
                RETURNS void
                LANGUAGE plpgsql
                AS $shadow$
                BEGIN
                    RAISE EXCEPTION 'hostile helper selected';
                END;
                $shadow$
                """
            )
            cursor.execute(
                "SELECT set_config('search_path', %s, false)",
                [f'"{hostile_schema}", public, pg_catalog'],
            )
            cursor.execute("SELECT current_schema(), current_schemas(false)")
            current_schema, current_schemas = cursor.fetchone()
            assert current_schema == hostile_schema
            assert current_schemas[0] == hostile_schema
            cursor.execute(
                "SELECT public.maru_assert_active_board_membership_provenance(%s)",
                [representation.id],
            )
            cursor.execute(
                "SELECT public.maru_assert_active_executive_board_v0009(%s)",
                [representation.id],
            )
            cursor.execute(
                "SELECT public.maru_assert_active_executive_board(%s)",
                [representation.id],
            )
            cursor.execute(
                """
                SELECT public.maru_workforce_role_evidence_matches_position(
                    %s, %s, %s, %s, %s, %s
                )
                """,
                [uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()],
            )
            assert cursor.fetchone() == (False,)
            cursor.execute(
                """
                UPDATE public.workforce_position
                   SET title = title
                 WHERE id = %s
                """,
                [position.id],
            )
        finally:
            cursor.execute(
                "SELECT set_config('search_path', %s, false)",
                [original_search_path],
            )
            cursor.execute(f'DROP SCHEMA "{hostile_schema}" CASCADE')


def test_persistent_trigger_callers_pin_their_runtime_helper_resolution() -> None:
    callers = _caller_contract()

    assert callers.keys() == CALLER_FUNCTION_TARGETS.keys()
    for identity, target in CALLER_FUNCTION_TARGETS.items():
        source, configuration = callers[identity]
        source_without_literals = re.sub(r"'(?:''|[^'])*'", "''", source)
        assert configuration == SAFE_SEARCH_PATH
        assert f"public.{target}" in source
        assert not re.search(
            rf"(?<![A-Za-z0-9_.]){re.escape(target)}(?![A-Za-z0-9_])",
            source_without_literals,
        )
        assert not re.search(
            r"(?<![A-Za-z0-9_.])"
            r"(?:organizations|authorization|identity|audit|effects|events|"
            r"workforce|participation)_[a-z0-9_]+(?![A-Za-z0-9_])",
            source_without_literals,
        )

    combined_sources = "\n".join(source for source, _config in callers.values())
    for relation in CALLER_RELATIONS:
        assert f"public.{relation}" in combined_sources


def test_readiness_fails_closed_for_each_runtime_helper_configuration_tamper() -> None:
    _activate()
    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()

    for signature in FUNCTION_IDENTIFIERS:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER FUNCTION {signature} RESET search_path")
            assert not (
                provenance_readiness.authority_provenance_runtime_contract_is_ready()
            )
            transaction.set_rollback(True)
        assert provenance_readiness.authority_provenance_runtime_contract_is_ready()


def test_readiness_fails_closed_for_persistent_caller_definition_tamper() -> None:
    _activate()
    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER FUNCTION public.maru_guard_workforce_position()
                RESET search_path
                """
            )
        assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()
        transaction.set_rollback(True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION
                    public.maru_deferred_validate_representation()
                RETURNS trigger
                LANGUAGE plpgsql
                VOLATILE
                CALLED ON NULL INPUT
                SECURITY INVOKER
                PARALLEL UNSAFE
                SET search_path = pg_catalog, public, pg_temp
                AS $tampered$
                BEGIN
                    RETURN NULL;
                END;
                $tampered$
                """
            )
        assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()
        transaction.set_rollback(True)

    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()


def test_readiness_rejects_persistent_caller_trigger_detachment_and_shape() -> None:
    _activate()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.workforce_position
                DISABLE TRIGGER workforce_position_guard
                """
            )
        assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()
        transaction.set_rollback(True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DROP TRIGGER identity_account_deferred_board_integrity
                ON public.identity_account
                """
            )
            cursor.execute(
                """
                CREATE CONSTRAINT TRIGGER
                    identity_account_deferred_board_integrity
                AFTER UPDATE OF is_active
                ON public.identity_account
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION
                    public.maru_deferred_validate_board_account()
                """
            )
        assert not provenance_readiness.authority_provenance_runtime_contract_is_ready()
        transaction.set_rollback(True)

    assert provenance_readiness.authority_provenance_runtime_contract_is_ready()


@pytest.mark.parametrize("target", [ORGANIZATIONS_BEFORE, WORKFORCE_BEFORE])
def test_activated_database_refuses_runtime_helper_downgrade(
    target: tuple[str, str],
) -> None:
    _activate()

    with pytest.raises(RuntimeError, match="runtime-executable"):
        _migrate(target)

    assert AuthorityProvenanceActivation.objects.filter(singleton=True).exists()
    _assert_hardened(_function_contract())


def test_owning_fence_survives_a_missing_convergence_migration_record() -> None:
    _activate()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'authorization'
               AND name = '0009_runtime_executable_function_contract'
            """
        )

    with pytest.raises(RuntimeError, match="runtime-executable"):
        _migrate(ORGANIZATIONS_BEFORE)

    assert AuthorityProvenanceActivation.objects.filter(singleton=True).exists()
    _assert_hardened(_function_contract())
