"""One-way ADR 0044 activation and exact-policy integration evidence."""

from __future__ import annotations

import json
import logging
import re
from io import StringIO
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization import activation, policy
from maru.authorization.activation import (
    AuthorityProvenanceActivationBlockedError,
    AuthorityProvenanceActivationError,
    AuthorityProvenanceActivationResult,
    ProcessesStoppedAcknowledgementRequiredError,
    activate_authority_provenance,
)
from maru.authorization.commands import (
    assign_role,
    grant_capability_direct,
    revoke_capability_grant,
)
from maru.authorization.management.commands import (
    activate_authority_provenance as activation_command,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityProvenanceActivation,
)
from maru.authorization.policy import decide, resolve_organization_target
from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)
from maru.identity.models import Account
from maru.organizations.models import Organization
from tests.factories import AccountFactory, CapabilityGrantFactory, OrganizationFactory
from tests.support.authority import (
    activate_synthetic_board,
    create_provenance_backed_role_bundle,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("proves_safe_runtime_database_role"),
]


@pytest.fixture(autouse=True)
def _require_exact_authority_provenance(settings: object) -> None:
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True  # type: ignore[attr-defined]


def _administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _activate(actor: Account) -> AuthorityProvenanceActivationResult:
    return activate_authority_provenance(
        actor=actor,
        reason="Select the rehearsed exact-lineage production contract.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )


def _governed_organization() -> tuple[Organization, tuple[Account, Account]]:
    organization = OrganizationFactory()
    controllers = activate_synthetic_board(organization)
    return organization, controllers


def test_activation_requires_acknowledgement_and_platform_actor() -> None:
    administrator = _administrator()

    with pytest.raises(ProcessesStoppedAcknowledgementRequiredError):
        activate_authority_provenance(
            actor=administrator,
            reason="Maintenance cutover.",
            correlation_id=uuid4(),
            acknowledge_processes_stopped=False,
        )
    with pytest.raises(AuthorityProvenanceActivationError):
        activate_authority_provenance(
            actor=AccountFactory(),
            reason="Maintenance cutover.",
            correlation_id=uuid4(),
            acknowledge_processes_stopped=True,
        )
    with (
        transaction.atomic(),
        pytest.raises(
            AuthorityProvenanceActivationError,
            match="top-level maintenance transaction",
        ),
    ):
        activate_authority_provenance(
            actor=administrator,
            reason="Nested cutover must be rejected.",
            correlation_id=uuid4(),
            acknowledge_processes_stopped=True,
        )

    assert not AuthorityProvenanceActivation.objects.exists()


def test_activation_service_rejects_non_read_committed_isolation() -> None:
    administrator = _administrator()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL "
                "REPEATABLE READ"
            )
        with pytest.raises(
            AuthorityProvenanceActivationError,
            match="READ COMMITTED",
        ):
            _activate(administrator)
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL "
                "READ COMMITTED"
            )

    assert not AuthorityProvenanceActivation.objects.exists()


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=False)
def test_activation_requires_the_external_recovery_fence() -> None:
    with pytest.raises(
        AuthorityProvenanceActivationError,
        match="exact-provenance recovery fence",
    ):
        _activate(_administrator())

    assert not AuthorityProvenanceActivation.objects.exists()


def test_activation_rejects_manual_autocommit_off_transaction_ownership() -> None:
    administrator = _administrator()
    connection.set_autocommit(False)
    try:
        with pytest.raises(
            AuthorityProvenanceActivationError,
            match="top-level maintenance transaction",
        ):
            _activate(administrator)
    finally:
        connection.rollback()
        connection.set_autocommit(True)

    assert not AuthorityProvenanceActivation.objects.exists()


def test_activation_boundary_restores_the_callers_lock_timeout() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")

        activation._lock_activation_boundary()

        cursor.execute("SHOW lock_timeout")
        assert cursor.fetchone() == ("3s",)


def test_activation_pins_public_schema_against_temporary_marker_shadows() -> None:
    _organization, _controllers = _governed_organization()
    administrator = _administrator()
    shadow_correlation_id = uuid4()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE authorization_authorityprovenanceactivation "
                "(LIKE public.authorization_authorityprovenanceactivation "
                "INCLUDING ALL)"
            )
            cursor.execute(
                "CREATE TEMP TABLE authorization_provenanceactivationlatch "
                "(LIKE public.authorization_provenanceactivationlatch INCLUDING ALL)"
            )
            cursor.execute(
                """
                INSERT INTO pg_temp.authorization_authorityprovenanceactivation (
                    singleton,
                    contract_version,
                    policy_version,
                    reason,
                    correlation_id,
                    activated_at,
                    activated_by_id
                ) VALUES (TRUE, %s, %s, %s, %s, %s, %s)
                """,
                [
                    "temporary-shadow",
                    "temporary-shadow",
                    "This row must never control durable activation.",
                    shadow_correlation_id,
                    timezone.now(),
                    administrator.id,
                ],
            )
            cursor.execute(
                """
                INSERT INTO pg_temp.authorization_provenanceactivationlatch (
                    singleton,
                    generation
                ) VALUES (TRUE, 1)
                """
            )
            cursor.execute("SET search_path = pg_temp, public")

        result = _activate(administrator)

        assert result.activated
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) "
                "FROM public.authorization_authorityprovenanceactivation"
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT generation "
                "FROM public.authorization_provenanceactivationlatch "
                "WHERE singleton IS TRUE"
            )
            assert cursor.fetchone() == (1,)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET search_path = public")
            cursor.execute(
                "DROP TABLE IF EXISTS "
                "pg_temp.authorization_authorityprovenanceactivation"
            )
            cursor.execute(
                "DROP TABLE IF EXISTS pg_temp.authorization_provenanceactivationlatch"
            )


def test_data_blocker_rolls_back_without_marker_or_success_audit() -> None:
    organization = OrganizationFactory()
    CapabilityGrantFactory(organization=organization)
    correlation_id = uuid4()

    with pytest.raises(AuthorityProvenanceActivationBlockedError):
        activate_authority_provenance(
            actor=_administrator(),
            reason="Blocked maintenance cutover.",
            correlation_id=correlation_id,
            acknowledge_processes_stopped=True,
            source_channel="test",
        )

    assert not AuthorityProvenanceActivation.objects.exists()
    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_clean_graph_activates_once_with_exact_audit_and_ready_postflight() -> None:
    _organization, _controllers = _governed_organization()
    administrator = _administrator()
    correlation_id = uuid4()

    result = activate_authority_provenance(
        actor=administrator,
        reason="  Select the rehearsed exact-lineage production contract.  ",
        correlation_id=correlation_id,
        acknowledge_processes_stopped=True,
        source_channel="test",
    )

    assert result.activated
    assert result.blocker_total == 0
    assert result.production_status == "ready"
    marker = AuthorityProvenanceActivation.objects.get()
    assert marker.reason == "Select the rehearsed exact-lineage production contract."
    assert marker.activated_by == administrator
    audit = AuditEvent.objects.get(
        operation="authorization.authority_provenance.activate"
    )
    assert audit.correlation_id == correlation_id
    assert audit.principal_id == administrator.id
    assert audit.organization_id is None
    assert audit.event_edition_id is None
    assert audit.target_id is None
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.occurred_at == marker.activated_at
    assert audit.obligations == ["reason", "audit", "stopped_processes"]
    assert audit.changed_fields == ["authority_provenance_activation"]
    assert audit.delegated is False
    assert audit.elevated is True
    assert audit.break_glass is False
    assert audit.retention_class == "security-extended"
    assert audit.safe_metadata == {
        "contract_version": marker.contract_version,
        "policy_version": marker.policy_version,
    }
    report = build_authority_provenance_readiness_report()
    assert report["activation_status"] == "blocked"
    assert report["production_status"] == "ready"


def test_repeat_activation_is_idempotent_and_does_not_append_audit() -> None:
    _organization, _controllers = _governed_organization()
    administrator = _administrator()
    first = _activate(administrator)
    audit_count = AuditEvent.objects.filter(
        operation="authorization.authority_provenance.activate"
    ).count()

    repeated = activate_authority_provenance(
        actor=administrator,
        reason="A repeat must not rewrite the historical reason.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )

    assert not repeated.activated
    assert repeated.correlation_id == first.correlation_id
    assert AuthorityProvenanceActivation.objects.count() == 1
    assert (
        AuditEvent.objects.filter(
            operation="authorization.authority_provenance.activate"
        ).count()
        == audit_count
    )


def test_existing_marker_cannot_bypass_a_disabled_recovery_fence() -> None:
    _organization, _controllers = _governed_organization()
    administrator = _administrator()
    _activate(administrator)

    with (
        override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=False),
        pytest.raises(
            AuthorityProvenanceActivationError,
            match="exact-provenance recovery fence",
        ),
    ):
        _activate(administrator)

    assert AuthorityProvenanceActivation.objects.count() == 1
    assert (
        AuditEvent.objects.filter(
            operation="authorization.authority_provenance.activate"
        ).count()
        == 1
    )


def test_failed_postflight_rolls_marker_and_audit_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _organization, _controllers = _governed_organization()
    actual_report = build_authority_provenance_readiness_report()
    blocked_postflight = dict(actual_report)
    blocked_postflight["activation_status"] = "blocked"
    blocked_postflight["production_status"] = "blocked"
    reports = iter((actual_report, blocked_postflight))
    monkeypatch.setattr(
        activation,
        "build_authority_provenance_readiness_report",
        lambda: next(reports),
    )
    correlation_id = uuid4()

    with pytest.raises(AuthorityProvenanceActivationError):
        activate_authority_provenance(
            actor=_administrator(),
            reason="Prove transaction rollback.",
            correlation_id=correlation_id,
            acknowledge_processes_stopped=True,
            source_channel="test",
        )

    assert not AuthorityProvenanceActivation.objects.exists()
    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_command_output_is_count_only_idempotent_and_errors_are_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _organization, _controllers = _governed_organization()
    administrator = _administrator()
    secret_reason = "Private operator reason retained only in restricted storage."
    output = StringIO()

    call_command(
        "activate_authority_provenance",
        actor=administrator.email,
        reason=secret_reason,
        acknowledge_processes_stopped=True,
        stdout=output,
    )

    rendered = output.getvalue()
    payload = json.loads(rendered)
    assert payload["status"] == "activated"
    assert payload["production_status"] == "ready"
    assert payload["blocker_total"] == 0
    assert administrator.email not in rendered
    assert administrator.display_name not in rendered
    assert secret_reason not in rendered

    repeat_output = StringIO()
    call_command(
        "activate_authority_provenance",
        actor=administrator.email,
        reason="Repeat without mutation.",
        acknowledge_processes_stopped=True,
        stdout=repeat_output,
    )
    assert json.loads(repeat_output.getvalue())["status"] == "already_active"

    private_unknown = "private-unknown-operator@example.invalid"
    with (
        caplog.at_level(
            logging.ERROR,
            logger=activation_command.__name__,
        ),
        pytest.raises(CommandError) as error,
    ):
        call_command(
            "activate_authority_provenance",
            actor=private_unknown,
            reason="Never disclose the supplied values.",
            acknowledge_processes_stopped=True,
        )
    rendered_error = str(error.value)
    assert "code=actor_unavailable" in rendered_error
    correlation_match = re.search(
        r"correlation_id=([0-9a-f-]{36})",
        rendered_error,
    )
    assert correlation_match is not None
    UUID(correlation_match.group(1))
    assert "code=actor_unavailable" in caplog.text
    assert f"correlation_id={correlation_match.group(1)}" in caplog.text
    assert "exception_type=DoesNotExist" in caplog.text
    assert private_unknown not in rendered_error
    assert private_unknown not in caplog.text
    assert "Never disclose" not in rendered_error
    assert "Never disclose" not in caplog.text


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("55P03", "writer_drain_timeout"),
        ("40001", "concurrent_writer_conflict"),
        ("08006", "database_unavailable"),
    ],
)
def test_command_maps_database_sqlstate_to_safe_failure_code(
    sqlstate: str,
    expected: str,
) -> None:
    private_cause = RuntimeError("private database detail")
    private_cause.sqlstate = sqlstate  # type: ignore[attr-defined]
    database_error = OperationalError("private wrapper detail")
    database_error.__cause__ = private_cause

    assert activation_command._failure_code(database_error) == expected


def test_policy_switch_is_request_local_and_invalid_contract_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Prepare the compatibility-era graph before the external recovery fence is
    # raised. Once REQUIRE_EXACT is true with no marker, ordinary organizer
    # reads and writes correctly fail closed while processes are stopped.
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=False):
        organization, (actor, approver) = _governed_organization()
        target = resolve_organization_target(organization_id=organization.id)
        assert target is not None
        recipient = AccountFactory()
        grant = grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            target=target,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Create exact policy-switch evidence.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        assert grant.authority_issuance.ordinal > 0
        monkeypatch.setattr(policy, "_exact_issuance_allows", lambda **_kwargs: False)

        before = decide(
            principal=recipient,
            capability_code="events.view_basic",
            resource=target,
        )
        assert before.allowed

    _activate(_administrator())
    after = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=target,
    )
    assert not after.allowed
    assert after.reason_code == "permission_absent"

    monkeypatch.setattr(policy, "_exact_lineage_policy_state", lambda: (True, False))
    malformed = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=target,
    )
    assert not malformed.allowed
    assert malformed.reason_code == "authority_provenance_contract_invalid"


def test_revoked_pinned_source_is_not_rebound_to_equivalent_board_role() -> None:
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=False):
        organization, (actor, approver) = _governed_organization()
        target = resolve_organization_target(organization_id=organization.id)
        assert target is not None
        now = timezone.now()
        preferred_source = grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=actor,
            capability_code="authorization.grant_direct",
            target=target,
            effective_from=now,
            expires_at=None,
            reason="Create a narrower deterministic actor source.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        recipient = AccountFactory()
        child = grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            target=target,
            effective_from=now,
            expires_at=None,
            reason="Pin the deterministic direct actor source.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        actor_control = AuthorityControl.objects.get(
            issuance=child.authority_issuance,
            role=AuthorityControl.Role.ACTOR,
        )
        assert actor_control.source_issuance_id == (
            preferred_source.authority_issuance.ordinal
        )

    _activate(_administrator())
    assert decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=target,
    ).allowed

    revoke_capability_grant(
        actor=actor,
        target=target,
        grant_id=preferred_source.id,
        reason="End the exact pinned source.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert decide(
        principal=actor,
        capability_code="authorization.grant_direct",
        resource=target,
    ).allowed
    denied = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=target,
    )
    assert not denied.allowed
    assert denied.reason_code == "permission_absent"


def test_exact_policy_accepts_provenance_backed_role_assignment() -> None:
    with override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=False):
        organization = OrganizationFactory()
        actor, approver, role = create_provenance_backed_role_bundle(
            organization,
            code="exact-event-reader",
            name="Exact event reader",
            capability_codes=("events.view_basic",),
        )
        target = resolve_organization_target(organization_id=organization.id)
        assert target is not None
        recipient = AccountFactory()
        assignment = assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            target=target,
            role_bundle_id=role.id,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Assign exact synthetic reader authority.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        assert assignment.authority_issuance.ordinal > role.authority_issuance.ordinal

    _activate(_administrator())
    decision = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=target,
    )

    assert decision.allowed
    assert decision.reason_code == "role_assignment"
