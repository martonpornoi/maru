"""Maintained native starter regressions; uncollected/unexecuted under ADR 0100.

The rolled-back schema candidate is not the complete Programme runtime fixture.
Real source authority and public commands remain in use; no policy success stub.
"""

from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.authorization.services import AuthorizationDenied
from maru.core.relation_schema_readiness import collect_relation_schema_fingerprints
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.services import EventEditionDetails, create_event_edition
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
)
from maru.workforce import programme_starter_commands as commands
from maru.workforce.models import (
    Position,
    PositionAssignment,
    PositionTemplate,
    ProgrammeStarterDecision,
    ProgrammeStarterRequest,
)
from maru.workforce.programme_starter_creation import prepare_programme_starter_creation
from maru.workforce.programme_starter_inputs import ProgrammeStarterAction as Action
from maru.workforce.programme_starter_inputs import (
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
)
from maru.workforce.programme_starter_queries import load_programme_starter_workspace
from maru.workforce.programme_starter_readiness import (
    PROGRAMME_STARTER_RELATIONS,
    PROGRAMME_STARTER_SCHEMA_SHA256,
    programme_starter_database_integrity_is_ready,
)
from maru.workforce.programme_starter_selection import ProgrammeStarterDraft
from tests.factories import AccountFactory
from tests.support.authority import activate_synthetic_board
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def world(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    context = {
        "actor": administrator,
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    organization = create_draft_organization(
        details=OrganizationCreationDetails(name="Synthetic starter organizers"),
        **context,
    )
    author, approver = activate_synthetic_board(organization)
    series = create_convention_series(
        organization_id=organization.id,
        details=ConventionSeriesCreationDetails(name="Synthetic starter series"),
        **context,
    )
    edition = create_event_edition(
        organization_id=organization.id,
        series_id=series.id,
        details=EventEditionDetails(
            name="Synthetic starter edition",
            time_zone="UTC",
            language_codes=("en",),
            currency_codes=("XXX",),
            starts_on=date(2030, 9, 6),
            ends_on=date(2030, 9, 8),
        ),
        idempotency_key=uuid4(),
        adoption_profile_code="programme_operations",
        **context,
    ).edition
    return SimpleNamespace(
        author=author,
        approver=approver,
        scope=ProgrammeStarterScope(organization.id, series.id, edition.id),
    )


def request(world, **changes):
    return commands.request_programme_starter(
        **(
            {
                "actor": world.author,
                "scope": world.scope,
                "details": ProgrammeStarterIntent(
                    world.approver.id, "Prepare synthetic volunteer staffing."
                ),
                "idempotency_key": uuid4(),
                "correlation_id": uuid4(),
                "source_channel": "test",
            }
            | changes
        )
    )


def decide(world, original, **changes):
    return commands.decide_programme_starter(
        **(
            {
                "actor": world.approver,
                "scope": world.scope,
                "request_id": original.request_id,
                "action": Action.APPROVE,
                "reason": "Reviewed exact shared meaning.",
                "idempotency_key": uuid4(),
                "correlation_id": uuid4(),
                "source_channel": "test",
            }
            | changes
        )
    )


def counts():
    return tuple(
        model.objects.count()
        for model in (
            PositionTemplate,
            RoleBundle,
            Position,
            PositionAssignment,
            RoleAssignment,
            ProgrammeStarterDecision,
            AuditEvent,
            DomainEvent,
            OutboxMessage,
        )
    )


def test_native_schema_exact_metadata_and_guard_readiness():
    assert (
        collect_relation_schema_fingerprints(PROGRAMME_STARTER_RELATIONS)
        == PROGRAMME_STARTER_SCHEMA_SHA256
    )
    assert programme_starter_database_integrity_is_ready()


def test_actual_selected_people_review_own_intent_and_terminal_history(world):
    draft = ProgrammeStarterDraft(
        world.approver.email, "Synthetic original selection.", uuid4()
    )
    preview = prepare_programme_starter_creation(
        actor=world.author, scope=world.scope, draft=draft, correlation_id=uuid4()
    )
    assert preview.selection is not None
    original = request(
        world, details=preview.selection.details, idempotency_key=draft.idempotency_key
    )
    for person in (world.author, world.approver):
        result = load_programme_starter_workspace(
            actor=person,
            scope=world.scope,
            correlation_id=uuid4(),
            request_id=original.request_id,
        )
        assert result.requests[0].author_id == world.author.id
        assert result.requests[0].approver_id == world.approver.id
    unrelated = AccountFactory()
    with pytest.raises(AuthorizationDenied):
        load_programme_starter_workspace(
            actor=unrelated,
            scope=world.scope,
            correlation_id=uuid4(),
            request_id=original.request_id,
        )
    decide(world, original)
    result = load_programme_starter_workspace(
        actor=world.approver,
        scope=world.scope,
        correlation_id=uuid4(),
        request_id=original.request_id,
    )
    assert result.requests[0].state == "approve"
    assert not result.requests[0].can_approve
    assert not load_programme_starter_workspace(
        actor=world.author, scope=world.scope, correlation_id=uuid4()
    ).requests


def test_actual_two_people_approve_only_fixed_shared_definition_and_retry(world):
    before = counts()
    key = uuid4()
    original = request(world, idempotency_key=key)
    assert counts()[:6] == before[:6]
    assert request(world, idempotency_key=key).replayed
    decision_key = uuid4()
    result = decide(world, original, idempotency_key=decision_key)
    template = PositionTemplate.objects.get(id=result.template_id)
    bundle = RoleBundle.objects.get(id=result.role_bundle_id)
    assert template.role_bundle_id == bundle.id
    assert bundle.created_by_id == world.author.id
    assert bundle.approved_by_id == world.approver.id
    assert tuple(bundle.capability_codes) == (
        "events.view_basic",
        "workforce.view_structure",
    )
    assert counts()[2:5] == before[2:5]
    retained = counts()
    assert decide(world, original, idempotency_key=decision_key).replayed
    assert counts() == retained
    assert AuditEvent.objects.filter(
        principal_id=world.approver.id,
        target_id=bundle.id,
        operation="authorization.role_bundle.version_create.approve",
        reason_code="independent_approval",
    ).exists()
    second = decide(world, request(world))
    assert second.template_id == result.template_id
    assert not second.created_output


@pytest.mark.parametrize("action", [Action.DECLINE, Action.CANCEL])
def test_actual_nonapproval_retains_evidence_without_output(world, action):
    original = request(world)
    before = counts()
    result = decide(
        world,
        original,
        action=action,
        actor=world.author if action is Action.CANCEL else world.approver,
    )
    assert result.template_id is None
    assert counts()[:5] == before[:5]
    assert ProgrammeStarterRequest.objects.filter(id=original.request_id).exists()


def test_actual_known_request_never_authorizes_wrong_person(world):
    original = request(world)
    before = counts()
    with pytest.raises(AuthorizationDenied):
        decide(world, original, actor=world.author)
    assert counts() == before


def test_actual_expired_request_cannot_create_output(world, monkeypatch):
    original = request(world)
    before = counts()
    future = timezone.now() + timedelta(days=8)
    monkeypatch.setattr(commands.timezone, "now", lambda: future)
    with pytest.raises(ValidationError, match="expired"):
        decide(world, original)
    assert counts() == before


def test_actual_late_failure_rolls_back_bundle_template_audit_and_effects(
    world, monkeypatch
):
    original = request(world)
    before = counts()

    def fail(_record):
        raise ValidationError("Synthetic terminal failure")

    monkeypatch.setattr(commands, "_append", fail)
    with pytest.raises(ValidationError, match="terminal failure"):
        decide(world, original)
    assert counts() == before


@pytest.mark.parametrize("mutation", ["update", "delete", "truncate"])
def test_native_retained_request_refuses_direct_mutation(world, mutation):
    original = request(world)
    statements = {
        "update": (
            "UPDATE workforce_programmestarterrequest "
            "SET reason = 'changed' WHERE id = %s"
        ),
        "delete": "DELETE FROM workforce_programmestarterrequest WHERE id = %s",
        "truncate": "TRUNCATE workforce_programmestarterrequest CASCADE",
    }
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            statements[mutation],
            [original.request_id] if mutation != "truncate" else None,
        )
    assert ProgrammeStarterRequest.objects.filter(id=original.request_id).exists()


def test_native_readiness_denies_weakened_guard():
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE workforce_programmestarterrequest "
            "DISABLE TRIGGER workforce_programme_starter_request_guard"
        )
    assert not programme_starter_database_integrity_is_ready()


def test_native_used_evidence_refuses_schema_contraction(world):
    request(world)
    fence = import_module(
        "maru.workforce.migrations.0027_programme_starter_downgrade_fence"
    )
    with (
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="fix forward"),
    ):
        fence.refuse_used_starter_downgrade(apps, editor)


def test_native_unused_guard_reverse_and_forward_preserve_empty_schema():
    fence = import_module(
        "maru.workforce.migrations.0027_programme_starter_downgrade_fence"
    )
    guards = import_module("maru.workforce.migrations.0026_programme_starter_integrity")
    with connection.schema_editor() as editor:
        fence.refuse_used_starter_downgrade(apps, editor)
        editor.execute(guards.REVERSE_SQL)
        assert not programme_starter_database_integrity_is_ready()
        editor.execute(guards.FORWARD_SQL)
    assert programme_starter_database_integrity_is_ready()
