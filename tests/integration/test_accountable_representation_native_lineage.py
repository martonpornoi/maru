"""Real active-provenance commits for the existing accountable representation roots."""

from dataclasses import asdict, replace
from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.commands import grant_capability_direct
from maru.authorization.models import AuthorityIssuance, CapabilityGrant
from maru.authorization.policy import resolve_organization_target
from maru.authorization.provenance import (
    AuthorityIssuanceCurrentCheck,
    authority_issuance_is_current,
    authority_issuances_are_current,
    role_bundle_provenance_is_historical,
)
from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)
from maru.authorization.services import AuthorizationDenied
from maru.organizations.representation import (
    emergency_remove_executive_board_controller,
)
from tests.factories import AccountFactory, OrganizationFactory
from tests.integration.test_authority_provenance_activation import _activate
from tests.integration.test_authorization_provenance_runtime import _activate_board
from tests.integration.test_workforce_only_adoption import (
    _activate_maru_operators,
    _set_up_new_foundation,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]
_MIGRATION = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)


@pytest.fixture(params=["maru_operators", "executive_board"])
def active_root(settings, request):
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
    _activate(AccountFactory(is_staff=True, is_superuser=True))
    if request.param == "maru_operators":
        administrator, _key, result = _set_up_new_foundation()
        representation = result.representation
        appointments = _activate_maru_operators(administrator, representation)
    else:
        _administrator, representation, appointments = _activate_board()
    return representation, appointments


def test_maru_operator_activation_commits_with_native_provenance_active(settings):
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
    administrator, _key, result = _set_up_new_foundation()
    report = build_authority_provenance_readiness_report()
    assert report["activation_status"] == "ready", report
    _activate(administrator)
    representation = result.representation
    appointments = _activate_maru_operators(administrator, representation)
    representation.refresh_from_db()
    assert representation.state == "active"
    assert len(appointments) == 2
    report = build_authority_provenance_readiness_report()
    assert report["production_status"] == "ready", report


def test_both_roots_keep_exact_native_and_python_current_lineage(active_root):
    representation, appointments = active_root
    appointment = appointments[0]
    issuance = AuthorityIssuance.objects.get(
        role_assignment_id=appointment.role_assignment_id
    )
    target = resolve_organization_target(organization_id=representation.organization_id)
    now = timezone.now()
    valid = AuthorityIssuanceCurrentCheck(
        issuance_ordinal=issuance.ordinal,
        principal_id=appointment.account_id,
        capability_code="authorization.manage_roles",
        target=target,
        requested_effective_from=now,
        requested_expires_at=None,
    )
    foreign = OrganizationFactory()
    checks = (
        valid,
        replace(valid, principal_id=uuid4()),
        replace(valid, capability_code="registration.manage_finance"),
        replace(valid, target=resolve_organization_target(organization_id=foreign.id)),
        replace(
            valid, requested_effective_from=issuance.evaluated_at - timedelta(seconds=1)
        ),
    )
    assert authority_issuances_are_current(checks=checks, evaluated_at=now) == (
        True,
        False,
        False,
        False,
        False,
    )
    assert tuple(
        authority_issuance_is_current(
            **{
                **asdict(check),
                "target": check.target,
                "evaluated_at": now,
            }
        )
        for check in checks
    ) == (True, False, False, False, False)
    report = build_authority_provenance_readiness_report()
    assert report["production_status"] == "ready", report


def test_roots_can_issue_ordinary_dual_control_without_self_approval(active_root):
    representation, appointments = active_root
    actor, approver = (appointment.account for appointment in appointments)
    recipient = AccountFactory()
    arguments = {
        "actor": actor,
        "approver": approver,
        "recipient": recipient,
        "capability_code": "organizations.view_basic",
        "target": resolve_organization_target(
            organization_id=representation.organization_id
        ),
        "effective_from": timezone.now(),
        "expires_at": None,
        "reason": "Synthetic native representation delegation.",
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    grant = grant_capability_direct(**arguments)
    assert AuthorityIssuance.objects.filter(capability_grant=grant).exists()
    before = CapabilityGrant.objects.count()
    with pytest.raises(AuthorizationDenied, match="independent approver"):
        grant_capability_direct(
            **{**arguments, "approver": actor, "correlation_id": uuid4()}
        )
    assert CapabilityGrant.objects.count() == before
    report = build_authority_provenance_readiness_report()
    assert report["production_status"] == "ready", report


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_unused_native_lineage_reversal_and_reapply_preserves_identity():
    current = ("authorization", "0039_accountable_representation_lineage")
    previous = ("authorization", "0038_programme_archive_recipe")
    with connection.cursor() as cursor:
        before = {
            key: _MIGRATION._state(cursor, key)
            for key in _MIGRATION._PREVIOUS_FINGERPRINTS
        }
    MigrationExecutor(connection).migrate([previous])
    with connection.cursor() as cursor:
        for key, fingerprint in _MIGRATION._PREVIOUS_FINGERPRINTS.items():
            state = _MIGRATION._state(cursor, key)
            assert state[:3] == before[key][:3]
            assert _MIGRATION._fingerprint(state[3:]) == fingerprint
    MigrationExecutor(connection).migrate([current])
    with connection.cursor() as cursor:
        assert {key: _MIGRATION._state(cursor, key) for key in before} == before


def test_downgrade_fence_distinguishes_existing_board_from_operator_use(active_root):
    representation, _appointments = active_root
    if representation.code == "maru_operators":
        with pytest.raises(RuntimeError, match="fix-forward"), transaction.atomic():
            _MIGRATION.restore_lineage(None, connection.schema_editor())
    else:
        with transaction.atomic():
            _MIGRATION.restore_lineage(None, connection.schema_editor())
            _MIGRATION.install_lineage(None, connection.schema_editor())
    report = build_authority_provenance_readiness_report()
    assert report["production_status"] == "ready", report


def test_containment_ends_current_authority_without_erasing_historical_ceremony(
    active_root,
):
    representation, appointments = active_root
    appointment = appointments[0]
    assignment = appointment.role_assignment
    issuance = AuthorityIssuance.objects.get(role_assignment=assignment)
    before = timezone.now()
    representation.refresh_from_db()
    emergency_remove_executive_board_controller(
        actor=AccountFactory(is_staff=True, is_superuser=True),
        representation_id=representation.id,
        appointment_id=appointment.id,
        expected_version=representation.aggregate_version,
        reason="Synthetic containment preserves historical lineage.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    check = AuthorityIssuanceCurrentCheck(
        issuance_ordinal=issuance.ordinal,
        principal_id=appointment.account_id,
        capability_code="authorization.manage_roles",
        target=resolve_organization_target(
            organization_id=representation.organization_id
        ),
        requested_effective_from=before,
        requested_expires_at=None,
    )
    assert authority_issuances_are_current(checks=(check,)) == (False,)
    assert not authority_issuance_is_current(
        **{**asdict(check), "target": check.target}
    )
    assert role_bundle_provenance_is_historical(bundle=assignment.role_bundle)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authority_bundle_historical_v1("
            "%s,%s,%s,ARRAY[]::bigint[],0)",
            [assignment.role_bundle_id, timezone.now(), representation.id],
        )
        assert cursor.fetchone() == (True,)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authority_issuance_valid_v1("
            "%s,%s,%s,%s,NULL,NULL,NULL,%s,NULL,%s,FALSE,TRUE,ARRAY[]::bigint[],0)",
            [
                issuance.ordinal,
                appointment.account_id,
                "authorization.manage_roles",
                representation.organization_id,
                before,
                before,
            ],
        )
        assert cursor.fetchone() == (True,)


@pytest.mark.parametrize("identity", tuple(_MIGRATION._PREVIOUS_FINGERPRINTS))
def test_migration_refuses_metadata_drift_before_replacing_any_validator(identity):
    with connection.cursor() as cursor:
        before = {
            key: _MIGRATION._state(cursor, key)
            for key in _MIGRATION._PREVIOUS_FINGERPRINTS
        }
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("ALTER FUNCTION public." + identity + " IMMUTABLE")
        with pytest.raises(RuntimeError, match="changed native"):
            _MIGRATION.restore_lineage(None, connection.schema_editor())
        transaction.set_rollback(True)
    with connection.cursor() as cursor:
        assert {key: _MIGRATION._state(cursor, key) for key in before} == before
