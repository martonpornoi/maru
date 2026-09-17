"""Maintained native approval-record regressions, deferred under ADR 0100.

The shared transaction-local candidate is not the complete Programme manifest.
Foundation and grant fixtures use real controller ceremonies and public commands.
Deliberate bulk inserts probe native evidence guards, not runtime write permission
or the future owning approval workflow. Never treat these tests as collected or
executed until the final #102 gate restores PostgreSQL testing.
"""

from datetime import date, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from psycopg import sql

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.commands import assign_role, create_role_bundle_version
from maru.authorization.models import (
    ProgrammeRoleDecisionRecord,
    ProgrammeRoleRequest,
    RoleAssignment,
)
from maru.authorization.policy import (
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.programme_role_readiness import (
    PROGRAMME_ROLE_RELATIONS,
    PROGRAMME_ROLE_SCHEMA_SHA256,
    programme_role_database_integrity_is_ready,
)
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.core.relation_schema_readiness import collect_relation_schema_fingerprints
from maru.events.services import EventEditionDetails, create_event_edition
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
)
from tests.factories import AccountFactory
from tests.support.authority import activate_synthetic_board
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def world(monkeypatch, request):
    profile = getattr(request, "param", "programme_operations")
    if profile == "programme_operations":
        admit_transaction_local_schema_candidate(monkeypatch)
    return _foundation(profile)


def _foundation(profile):
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    context = {
        "actor": administrator,
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    organization = create_draft_organization(
        details=OrganizationCreationDetails(name="Synthetic approval organizers"),
        **context,
    )
    author, approver = activate_synthetic_board(organization)
    series = create_convention_series(
        organization_id=organization.id,
        details=ConventionSeriesCreationDetails(name="Synthetic approval series"),
        **context,
    )
    edition = create_event_edition(
        organization_id=organization.id,
        series_id=series.id,
        details=EventEditionDetails(
            name="Synthetic approval edition",
            time_zone="UTC",
            language_codes=("en",),
            currency_codes=("XXX",),
            starts_on=date(2030, 9, 6),
            ends_on=date(2030, 9, 8),
        ),
        idempotency_key=uuid4(),
        adoption_profile_code=profile,
        **context,
    ).edition
    return organization, edition, author, approver, AccountFactory()


def _audit(world, *, record_id, actor_id, operation, target_type, correlation):
    organization, edition, *_people = world
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=edition.id,
            capability_code="authorization.manage_roles",
            operation=operation,
            target_type=target_type,
            target_id=record_id,
            outcome="allow",
            reason_code="independent_approval",
            correlation_id=correlation,
            source_channel="test",
            retention_class="security-extended",
        )
    )


def _request_values(world):
    organization, edition, author, approver, recipient = world
    recipe = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]
    record_id, correlation, now = uuid4(), uuid4(), timezone.now()
    audit = _audit(
        world,
        record_id=record_id,
        actor_id=author.id,
        operation="authorization.programme_role.request",
        target_type="authorization.programme_role_request",
        correlation=correlation,
    )
    return {
        "id": record_id,
        "idempotency_key": uuid4(),
        "request_digest": "a" * 64,
        "reason": "Synthetic independent coverage access.",
        "correlation_id": correlation,
        "source_channel": "test",
        "source_audit_id": audit.id,
        "organization_id": organization.id,
        "programme_edition_id": edition.id,
        "edition_id": edition.id,
        "scope_level": "edition",
        "author_id": author.id,
        "approver_id": approver.id,
        "recipient_id": recipient.id,
        "recipe_code": recipe.code,
        "recipe_version": recipe.version,
        "recipe_digest": recipe.digest,
        "requested_at": now,
        "approval_deadline": now + timedelta(days=7),
    }


def _insert_request(values):
    return ProgrammeRoleRequest.objects.bulk_create([ProgrammeRoleRequest(**values)])[0]


def _decision_values(world, original, action="decline"):
    record_id, correlation = uuid4(), uuid4()
    actor = world[2] if action == "cancel" else world[3]
    audit = _audit(
        world,
        record_id=record_id,
        actor_id=actor.id,
        operation="authorization.programme_role." + action,
        target_type="authorization.programme_role_decision",
        correlation=correlation,
    )
    return {
        "id": record_id,
        "idempotency_key": uuid4(),
        "request_digest": "b" * 64,
        "reason": "Synthetic own decision.",
        "correlation_id": correlation,
        "source_channel": "test",
        "source_audit_id": audit.id,
        "request_id": original.id,
        "actor_id": actor.id,
        "action": action,
        "decided_at": timezone.now(),
    }


def _insert_decision(values):
    return ProgrammeRoleDecisionRecord.objects.bulk_create(
        [
            ProgrammeRoleDecisionRecord(**values),
        ]
    )[0]


def test_installed_approval_relations_and_native_boundary_are_exact():
    assert collect_relation_schema_fingerprints(PROGRAMME_ROLE_RELATIONS) == (
        PROGRAMME_ROLE_SCHEMA_SHA256
    )
    assert programme_role_database_integrity_is_ready()


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_request_and_own_nonapproval_retain_intent_without_grant(world, action):
    before = RoleAssignment.objects.count()
    values = _request_values(world)
    original = _insert_request(values)
    decision = _insert_decision(_decision_values(world, original, action))
    assert RoleAssignment.objects.count() == before
    assert decision.role_assignment_id is None
    original.refresh_from_db()
    for field, value in values.items():
        assert getattr(original, field) == value


@pytest.mark.parametrize("fault", [None, "recipient", "reason", "start", "old_output"])
def test_approval_requires_exact_new_provenance_backed_assignment(world, fault):
    organization, edition, author, approver, recipient = world
    recipe = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]
    role = create_role_bundle_version(
        actor=author,
        approver=approver,
        target=resolve_organization_target(organization_id=organization.id),
        code=recipe.role_code,
        name=recipe.name,
        capability_codes=recipe.capability_codes,
        reason="Synthetic role definition.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    original = _insert_request(_request_values(world))
    values = _decision_values(world, original, "approve")
    assignment = assign_role(
        actor=author,
        approver=approver,
        recipient=AccountFactory() if fault == "recipient" else recipient,
        target=resolve_edition_target(
            organization_id=organization.id,
            edition_id=edition.id,
        ),
        role_bundle_id=role.id,
        effective_from=values["decided_at"] + timedelta(days=1)
        if fault == "start"
        else values["decided_at"],
        expires_at=None,
        reason="Different rationale" if fault == "reason" else original.reason,
        correlation_id=values["correlation_id"],
        source_channel="test",
    )
    values.update(role_bundle_id=role.id, role_assignment_id=assignment.id)
    if fault == "old_output":
        values["decided_at"] = timezone.now()
    if fault:
        with pytest.raises(IntegrityError), transaction.atomic():
            _insert_decision(values)
        assert not ProgrammeRoleDecisionRecord.objects.filter(request=original).exists()
        return
    decision = _insert_decision(values)
    assert decision.role_assignment_id == assignment.id
    assert decision.actor_id == approver.id


@pytest.mark.parametrize("world", ["full_convention", "workforce_only"], indirect=True)
def test_current_profiles_cannot_receive_operational_approval_requests(world):
    values = _request_values(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request(values)


@pytest.mark.parametrize(
    "field", ["organization_id", "programme_edition_id", "edition_id"]
)
def test_existing_foreign_organization_and_edition_cannot_substitute(world, field):
    other = _foundation("programme_operations")
    values = _request_values(world)
    foreign = other[0].id if field == "organization_id" else other[1].id
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**values, field: foreign})


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "programme_edition_id",
        "edition_id",
        "department_id",
        "resource_binding_id",
        "author_id",
        "approver_id",
        "recipient_id",
        "source_audit_id",
    ],
)
def test_native_request_rejects_unrelated_scope_person_or_evidence(world, field):
    values = _request_values(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**values, field: uuid4()})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipe_code", "unknown"),
        ("recipe_version", 2),
        ("recipe_digest", "b" * 64),
        ("scope_level", "organization"),
        ("request_digest", "invalid"),
        ("reason", " "),
        ("reason", "line\nbreak"),
        ("source_channel", "bad channel"),
        ("idempotency_key", UUID(int=0)),
    ],
)
def test_native_request_rejects_invalid_closed_intent(world, field, value):
    values = _request_values(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**values, field: value})


@pytest.mark.parametrize("same_as", ["author_id", "recipient_id"])
def test_native_request_requires_independent_named_approver(world, same_as):
    values = _request_values(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**values, "approver_id": values[same_as]})


@pytest.mark.parametrize("fault", ["deadline", "expired", "inverted"])
def test_native_request_rejects_invalid_time_window(world, fault):
    values = _request_values(world)
    now = values["requested_at"]
    changes = {
        "deadline": {"approval_deadline": now + timedelta(days=8)},
        "expired": {"expires_at": now - timedelta(seconds=1)},
        "inverted": {
            "not_before": now + timedelta(days=2),
            "expires_at": now + timedelta(days=1),
        },
    }[fault]
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**values, **changes})


@pytest.mark.parametrize("action", ["approve", "decline", "cancel"])
def test_decision_rejects_impersonation_and_approval_without_output(world, action):
    original = _insert_request(_request_values(world))
    values = _decision_values(world, original, action)
    changes = {} if action == "approve" else {"actor_id": world[4].id}
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_decision({**values, **changes})


def test_request_key_and_terminal_outcome_cannot_be_reused(world):
    values = _request_values(world)
    original = _insert_request(values)
    repeated = _request_values(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_request({**repeated, "idempotency_key": values["idempotency_key"]})
    _insert_decision(_decision_values(world, original))
    repeated_decision = _decision_values(world, original, "cancel")
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_decision(repeated_decision)


@pytest.mark.parametrize("model", [ProgrammeRoleRequest, ProgrammeRoleDecisionRecord])
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
def test_native_evidence_is_retained(world, model, operation):
    original = _insert_request(_request_values(world))
    decision = _insert_decision(_decision_values(world, original))
    record = original if model is ProgrammeRoleRequest else decision
    table = sql.Identifier(model._meta.db_table)
    statement, params = {
        "update": (
            sql.SQL("UPDATE {} SET reason = %s WHERE id = %s").format(table),
            ["Changed", record.id],
        ),
        "delete": (sql.SQL("DELETE FROM {} WHERE id = %s").format(table), [record.id]),
        "truncate": (sql.SQL("TRUNCATE {} CASCADE").format(table), []),
    }[operation]
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, params)
    assert model.objects.filter(pk=record.id).exists()


def test_retained_request_fences_guard_and_schema_downgrade(world):
    _insert_request(_request_values(world))
    for name, operation in (
        (
            "0032_programme_role_approval_records",
            "refuse_used_programme_role_downgrade",
        ),
        (
            "0034_programme_role_approval_downgrade_fence",
            "refuse_used_approval_guard_downgrade",
        ),
    ):
        migration = import_module("maru.authorization.migrations." + name)
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="fix forward"),
        ):
            getattr(migration, operation)(apps, editor)


def test_retained_approval_audit_repair_refuses_reverse(world):
    original = _insert_request(_request_values(world))
    decision = _insert_decision(_decision_values(world, original))
    repair = import_module(
        "maru.authorization.migrations.0035_programme_role_approval_audit"
    )
    with connection.cursor() as cursor:
        cursor.execute(repair.FORWARD_SQL)
    assert programme_role_database_integrity_is_ready()
    with (
        pytest.raises(IntegrityError, match="fix forward"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(repair.REVERSE_SQL)
    assert ProgrammeRoleRequest.objects.filter(pk=original.id).exists()
    assert ProgrammeRoleDecisionRecord.objects.filter(pk=decision.id).exists()
    assert programme_role_database_integrity_is_ready()


@pytest.mark.parametrize("weakening", ["check", "function_acl", "trigger"])
def test_metadata_readiness_rejects_weakened_database_contract(weakening):
    assert programme_role_database_integrity_is_ready()
    sql = {
        "check": "ALTER TABLE authorization_programmeroledecisionrecord "
        "DROP CONSTRAINT programme_role_decision_output",
        "function_acl": "GRANT EXECUTE ON FUNCTION "
        "public.maru_programme_role_decision_guard() TO PUBLIC",
        "trigger": "ALTER TABLE authorization_programmerolerequest "
        "DISABLE TRIGGER authorization_programme_role_request_guard",
    }[weakening]
    with connection.cursor() as cursor:
        cursor.execute(sql)
    assert not programme_role_database_integrity_is_ready()


@pytest.mark.django_db(transaction=True)
def test_unused_approval_schema_reverses_and_reapplies():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(
            [("authorization", "0031_programme_change_communication_capabilities")]
        )
        with connection.cursor() as cursor:
            for table in PROGRAMME_ROLE_RELATIONS:
                cursor.execute("SELECT to_regclass(%s)", ["public." + table])
                assert cursor.fetchone() == (None,)
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert programme_role_database_integrity_is_ready()
