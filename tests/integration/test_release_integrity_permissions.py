"""Catalog-level proof that explicit runtime helpers do not open other guards."""

from dataclasses import replace

import pytest
from django.db import connection
from django.test import override_settings
from psycopg import sql

from maru.catalog.readiness import CATALOG_INTEGRITY_CONTRACT
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.scheduling.readiness import SCHEDULING_INTEGRITY_CONTRACT
from tests.integration.test_database_role_safety import _create_role

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _helper_contract():
    identity = next(iter(CATALOG_INTEGRITY_CONTRACT.functions))
    return replace(
        CATALOG_INTEGRITY_CONTRACT,
        runtime_executable_functions=frozenset({identity}),
    ), identity


def _grant(identity, role, *, grant_option=False):
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}{}").format(
                sql.SQL("public." + identity),
                sql.SQL("PUBLIC") if role == "PUBLIC" else sql.Identifier(role),
                sql.SQL(" WITH GRANT OPTION" if grant_option else ""),
            )
        )


def test_existing_owner_only_contract_is_unchanged():
    with override_settings(RUNTIME_DATABASE_ROLE=""):
        catalog = inspect_database_integrity_catalog(CATALOG_INTEGRITY_CONTRACT)
        assert catalog.ready
        assert catalog.function_execute_owner_only
        assert catalog.function_execute_boundary_closed


def test_declared_helper_requires_the_exact_configured_login_without_grant_option():
    contract, identity = _helper_contract()
    role = _create_role()
    with override_settings(RUNTIME_DATABASE_ROLE=role):
        assert not inspect_database_integrity_catalog(contract).ready
        _grant(identity, role)
        catalog = inspect_database_integrity_catalog(contract)
        assert catalog.ready
        assert catalog.function_execute_boundary_closed
        assert not catalog.function_execute_owner_only
        # Declaring one helper does not change the default owner-only contract.
        assert not inspect_database_integrity_catalog(CATALOG_INTEGRITY_CONTRACT).ready


@pytest.mark.parametrize(
    "drift",
    [
        "public",
        "other_role",
        "grant_option",
        "undeclared_function",
        "missing_login",
        "nologin",
        "privileged_login",
        "unknown_function",
    ],
)
def test_explicit_helper_boundary_rejects_acl_and_contract_drift(drift):
    contract, identity = _helper_contract()
    role = _create_role()
    _grant(identity, role)
    configured_role = role
    if drift == "public":
        _grant(identity, "PUBLIC")
    elif drift == "other_role":
        _grant(identity, _create_role())
    elif drift == "grant_option":
        _grant(identity, role, grant_option=True)
    elif drift == "undeclared_function":
        other = next(name for name in contract.functions if name != identity)
        _grant(other, role)
    elif drift == "missing_login":
        configured_role = "maru_intentionally_nonexistent_integrity_role"
    elif drift in {"nologin", "privileged_login"}:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} {}").format(
                    sql.Identifier(role),
                    sql.SQL("NOLOGIN" if drift == "nologin" else "CREATEROLE"),
                )
            )
    else:
        contract = replace(
            contract,
            runtime_executable_functions=frozenset({identity, "missing(uuid)"}),
        )
    with override_settings(RUNTIME_DATABASE_ROLE=configured_role):
        catalog = inspect_database_integrity_catalog(contract)
        assert catalog.function_contract_current
        assert not catalog.function_execute_boundary_closed
        assert not catalog.ready


def test_unconfigured_login_does_not_accept_a_preexisting_grant():
    contract, identity = _helper_contract()
    with override_settings(RUNTIME_DATABASE_ROLE=""):
        assert inspect_database_integrity_catalog(contract).ready
        _grant(identity, _create_role())
        assert not inspect_database_integrity_catalog(contract).ready


@pytest.mark.parametrize(
    "trigger_name",
    [
        "audit_native_mutation_capture",
        "identity_release_source_evidence",
        "events_release_source_evidence",
        "programme_release_host_identity",
        "workforce_release_commitment_evidence",
        "venue_release_occupancy_evidence",
    ],
)
def test_native_supporting_attachment_is_checked_by_release_readiness(trigger_name):
    contract = SCHEDULING_INTEGRITY_CONTRACT
    trigger = contract.supporting_triggers[trigger_name]
    assert inspect_database_integrity_catalog(contract).ready
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(
                sql.Identifier(trigger.table),
                sql.Identifier(trigger.name),
            )
        )
    catalog = inspect_database_integrity_catalog(contract)
    assert catalog.function_contract_current
    assert not catalog.trigger_contract_current
    assert not catalog.ready


def test_literal_host_dependency_discriminator_is_not_interchangeable():
    contract = SCHEDULING_INTEGRITY_CONTRACT
    trigger = contract.supporting_triggers["programme_release_host_identity"]
    assert inspect_database_integrity_catalog(contract).ready
    with connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER programme_release_host_identity "
            "ON public.programme_programmehostrelationship"
        )
        cursor.execute(
            "CREATE TRIGGER programme_release_host_identity BEFORE UPDATE OR DELETE "
            "ON public.programme_programmehostrelationship "
            "FOR EACH ROW EXECUTE FUNCTION "
            "public.maru_scheduling_release_source_identity_guard('programme_host_operational')"
        )
    assert trigger.arguments == (
        "programme_host_operational",
        "programme_host_disclosure",
    )
    assert not inspect_database_integrity_catalog(contract).ready
