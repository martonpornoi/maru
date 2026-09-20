"""Native stopped issuance/refusal and real authorized security-only revocation."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from psycopg import sql

from maru.audit.models import AuditEvent, AuditNativeMutationWitness
from maru.authorization.commands import revoke_capability_grant, revoke_role_assignment
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.integration.test_authority_commands import _edition_target, _grant_management
from tests.integration.test_scheduling_programme_stop import _terminal
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def stopped_scope(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code="programme_operations")
    controller = AccountFactory()
    _grant_management(controller, edition.organization, "authorization.revoke")
    grant = CapabilityGrantFactory(organization=edition.organization, edition=edition)
    role = RoleAssignmentFactory(
        role_bundle=RoleBundleFactory(organization=edition.organization),
        edition=edition,
    )
    _terminal(edition, "archived")
    return edition, controller, grant, role


@pytest.mark.parametrize(
    "model",
    [
        "capabilitygrant",
        "roleassignment",
        "scopedresourcebinding",
        "programmerolerequest",
    ],
)
def test_native_terminal_scope_refuses_all_fresh_authority(stopped_scope, model):
    edition = stopped_scope[0]
    field = "programme_edition_id" if model == "programmerolerequest" else "edition_id"
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, organization_id, {}) VALUES (%s, %s, %s)"
            ).format(
                sql.Identifier("public", f"authorization_{model}"),
                sql.Identifier(field),
            ),
            [uuid4(), edition.organization_id, edition.id],
        )


@pytest.mark.parametrize("kind", ["grant", "role"])
def test_actual_owner_revocation_retains_same_transaction_native_evidence(
    stopped_scope, kind
):
    edition, controller, grant, role = stopped_scope
    trace = uuid4()
    target = _edition_target(edition)
    if kind == "grant":
        result = revoke_capability_grant(
            actor=controller,
            target=target,
            grant_id=grant.id,
            reason="End synthetic retained authority.",
            correlation_id=trace,
        )
    else:
        result = revoke_role_assignment(
            actor=controller,
            target=target,
            assignment_id=role.id,
            reason="End synthetic retained authority.",
            correlation_id=trace,
        )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert result.revoked_by_id == controller.id
    audit = AuditEvent.objects.get(correlation_id=trace, outcome="allow")
    assert AuditNativeMutationWitness.objects.filter(audit_event_id=audit.id).exists()
    assert audit.target_id == result.id
    assert audit.event_edition_id == edition.id


@pytest.mark.parametrize("kind", ["grant", "role"])
def test_raw_revocation_without_native_owner_audit_rolls_back(stopped_scope, kind):
    _edition, controller, grant, role = stopped_scope
    record = grant if kind == "grant" else role
    with (
        pytest.raises(IntegrityError, match="requires native audit"),
        transaction.atomic(),
    ):
        _raw_revoke_and_check(record, controller.id)
    record.refresh_from_db()
    assert record.revoked_at is None


def _raw_revoke_and_check(record, actor_id):
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET revoked_at = %s, revoked_by_id = %s, "
                "revocation_reason = %s WHERE id = %s"
            ).format(sql.Identifier("public", record._meta.db_table)),
            [timezone.now(), actor_id, "Synthetic raw negative.", record.id],
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_exact_authorization_stop_catalog_is_required():
    assert programme_stop_preparation_is_ready()
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.authorization_capabilitygrant "
            "DISABLE TRIGGER authorization_programme_stop_revoke_0"
        )
    assert not programme_stop_preparation_is_ready()


def test_valid_same_transaction_audit_cannot_authorize_another_revocation(
    stopped_scope,
):
    edition, controller, grant, role = stopped_scope
    revoke_capability_grant(
        actor=controller,
        target=_edition_target(edition),
        grant_id=grant.id,
        reason="End one exact retained grant.",
        correlation_id=uuid4(),
    )
    with (
        pytest.raises(IntegrityError, match="requires native audit"),
        transaction.atomic(),
    ):
        _raw_revoke_and_check(role, controller.id)
    role.refresh_from_db()
    grant.refresh_from_db()
    assert role.revoked_at is None
    assert grant.revoked_at is not None


@pytest.mark.parametrize(
    "changed", ["reason", "principal_id", "edition_id", "expires_at"]
)
def test_revocation_cannot_smuggle_issuance_changes_or_escape_to_shared_scope(
    stopped_scope, changed
):
    _edition, controller, grant, _role = stopped_scope
    value = {
        "reason": "Replacement original intent.",
        "principal_id": controller.id,
        "edition_id": None,
        "expires_at": timezone.now(),
    }[changed]
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "UPDATE public.authorization_capabilitygrant SET revoked_at = %s, "
                "revoked_by_id = %s, revocation_reason = %s, {} = %s WHERE id = %s"
            ).format(sql.Identifier(changed)),
            [
                timezone.now(),
                controller.id,
                "Synthetic wrong-field revocation.",
                value,
                grant.id,
            ],
        )


def test_shared_organization_and_other_edition_remain_usable(stopped_scope):
    edition = stopped_scope[0]
    recipient = AccountFactory()
    shared = _grant_management(recipient, edition.organization, "events.view_basic")
    other = EventEditionFactory(series=edition.series)
    separate = _grant_management(
        recipient, edition.organization, "events.view_basic", edition=other
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert shared.edition_id is None
    assert separate.edition_id == other.id


def test_decision_without_original_scope_is_unavailable():
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="exact parent scope"),
        transaction.atomic(),
    ):
        cursor.execute(
            "INSERT INTO public.authorization_programmeroledecisionrecord "
            "(id, request_id) VALUES (%s, %s)",
            [uuid4(), uuid4()],
        )
