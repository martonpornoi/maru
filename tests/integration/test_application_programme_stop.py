"""Native stopped Applications scope, genuine cleanup policy and retained intent."""

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from psycopg import sql

from maru.applications import programme_commands as commands
from maru.applications import programme_stop_audit
from maru.applications.models import (
    ApplicationDefinition,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeImportBatch,
    ProgrammeImportItem,
    ProgrammeProposal,
)
from maru.applications.programme_import_commands import (
    discard_programme_import,
    stage_programme_import,
)
from maru.applications.programme_inputs import ProgrammeProposalSelectionInput
from maru.events import adoption
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration import (
    test_application_programme_import_services as import_inputs,
)
from tests.integration import test_application_programme_services as inputs
from tests.integration.test_scheduling_programme_stop import _terminal
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.support.programme_schema import admit_transaction_local_schema_candidate
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
GUARDS = import_module("maru.applications.migrations.0023_programme_stop_boundary")


@pytest.fixture
def candidate(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {
            **adoption.ADOPTION_PROFILES,
            ("programme_operations", 1): PROGRAMME_REHEARSAL_PROFILE,
        },
    )
    return EventEditionFactory(adoption_profile_code="programme_operations")


@pytest.fixture
def call(candidate):
    manager = AccountFactory()
    department = create_department_for_test(
        edition=candidate,
        name="Synthetic Programme",
        expected_code="synthetic-programme",
    )
    CapabilityGrantFactory(
        organization=candidate.organization,
        edition=candidate,
        department=department,
        principal=manager,
        capability_code="applications.manage_programme_calls",
    )
    common = {
        "actor_id": manager.id,
        "organization_id": candidate.organization_id,
        "edition_id": candidate.id,
        "source_channel": "test",
    }
    now = timezone.now()
    created = commands.create_programme_call(
        **common,
        definition_input=inputs._definition(now, code="synthetic-stop"),
        configuration=inputs._configuration(department.id),
        expected_version=0,
        reason="Prepare a synthetic retained call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    active = commands.activate_programme_call(
        **common,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=created.resulting_version,
        reason="Open synthetic proposal intake.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    return SimpleNamespace(common=common, department=department, active=active)


def test_real_call_retirement_is_retained_after_stop(candidate, call):
    _terminal(candidate, "archived")
    key = uuid4()
    arguments = dict(
        call.common,
        call_id=call.active.target_id,
        owner_department_id=call.department.id,
        expected_version=call.active.resulting_version,
        reason="Close retained “jelentkezés” intake.",
        retry_key=key,
    )
    result = commands.retire_programme_call(**arguments, correlation_id=uuid4())
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        ApplicationDefinition.objects.get(id=result.definition_id).status == "retired"
    )
    assert commands.retire_programme_call(**arguments, correlation_id=uuid4()).replayed


@pytest.mark.parametrize("model", GUARDS.DIRECT_MODELS)
def test_all_direct_owner_tables_refuse_new_stopped_work(candidate, model):
    _terminal(candidate, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, organization_id, edition_id) VALUES (%s, %s, %s)"
            ).format(sql.Identifier("public", f"applications_{model}")),
            [uuid4(), candidate.organization_id, candidate.id],
        )


def test_exact_applications_stop_preparation_is_ready():
    assert programme_stop_preparation_is_ready()


def test_actual_lead_can_withdraw_but_not_reopen_proposal_after_stop(candidate, call):
    lead = AccountFactory()
    common = {**call.common, "actor_id": lead.id}
    proposal = commands.start_programme_proposal(
        **common,
        call_id=call.active.target_id,
        selection=ProgrammeProposalSelectionInput(
            track_id=ProgrammeCallTrack.objects.get(call_id=call.active.target_id).id,
            format_id=ProgrammeCallFormat.objects.get(call_id=call.active.target_id).id,
            requested_duration_minutes=60,
        ),
        lead_profile=inputs._profile("Synthetic proposal lead"),
        expected_version=0,
        reason="Start a synthetic private proposal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    arguments = dict(
        common,
        proposal_id=proposal.target_id,
        expected_version=proposal.resulting_version,
        reason="Withdraw retained “előadás” proposal.",
        retry_key=uuid4(),
    )
    result = commands.withdraw_programme_proposal(**arguments, correlation_id=uuid4())
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert ProgrammeProposal.objects.get(id=proposal.target_id).state == "withdrawn"
    assert commands.withdraw_programme_proposal(
        **arguments, correlation_id=uuid4()
    ).replayed
    with pytest.raises(commands.ApplicationsProgrammeStateConflictError):
        commands.reopen_programme_proposal(
            **common,
            proposal_id=proposal.target_id,
            expected_version=result.resulting_version,
            reason="An old relationship cannot reopen stopped planning.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )


def test_actual_staged_payload_disposal_remains_available(candidate, call, settings):
    now = timezone.now()
    settings.MARU_APPLICATIONS_PROGRAMME_IMPORT_RETENTION_POLICY_JSON = json.dumps(
        {
            "policy_code": "synthetic.stop-retention.v1",
            "period_seconds": 86400,
            "approved_by_reference": "isolated-fixture-only",
            "approved_at": (now - timedelta(days=1)).isoformat(),
        }
    )
    for capability in (
        "applications.import_programme",
        "applications.dispose_programme_import",
    ):
        CapabilityGrantFactory(
            organization=candidate.organization,
            edition=candidate,
            department=call.department
            if capability == "applications.import_programme"
            else None,
            principal_id=call.common["actor_id"],
            capability_code=capability,
        )
    staged = stage_programme_import(
        **call.common,
        owner_department_id=call.department.id,
        source_system="synthetic.programme",
        raw_payload=import_inputs._document([import_inputs._call_item(now)]),
        expected_version=0,
        reason="Stage synthetic retained intake.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    arguments = dict(
        call.common,
        batch_id=staged.batch_id,
        expected_version=staged.resulting_version,
        reason="Erase retained synthetic import payload.",
        retry_key=uuid4(),
    )
    result = discard_programme_import(**arguments, correlation_id=uuid4())
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert ProgrammeImportBatch.objects.get(id=result.batch_id).state == "discarded"
    assert not ProgrammeImportItem.objects.filter(
        batch_id=result.batch_id, canonical_payload__isnull=False
    ).exists()
    assert discard_programme_import(**arguments, correlation_id=uuid4()).replayed


@pytest.mark.parametrize("model", GUARDS.DEFINITION_CHILDREN)
def test_definition_children_cannot_hide_their_stopped_owner(candidate, call, model):
    _terminal(candidate, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL("INSERT INTO {} (id, definition_id) VALUES (%s, %s)").format(
                sql.Identifier("public", f"applications_{model}"),
            ),
            [uuid4(), call.active.definition_id],
        )


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
def test_missing_applications_guard_closes_preparation_readiness(model):
    index = GUARDS.GUARDED_MODELS.index(model)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier("public", f"applications_{model}"),
                sql.Identifier(f"a00_applications_programme_stop_{index}"),
            )
        )
    assert not programme_stop_preparation_is_ready()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("changed_fields", ("status",)),
        ("idempotency_key_hash", "0" * 64),
    ],
)
def test_native_cleanup_rejects_audit_for_different_intent(
    candidate, call, monkeypatch, field, value
):
    _terminal(candidate, "archived")
    original = programme_stop_audit.audited_mutation

    @contextmanager
    def mismatched(record, **kwargs):
        with original(replace(record, **{field: value}), **kwargs) as evidence:
            yield evidence

    monkeypatch.setattr(programme_stop_audit, "audited_mutation", mismatched)
    with (  # noqa: PT012 -- mutate then enforce the same transaction's deferred proof.
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        commands.retire_programme_call(
            **call.common,
            call_id=call.active.target_id,
            owner_department_id=call.department.id,
            expected_version=call.active.resulting_version,
            reason="Retire synthetic intake.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        ApplicationDefinition.objects.get(id=call.active.definition_id).status
        == "active"
    )


def test_raw_retirement_cannot_smuggle_definition_content(candidate, call):
    _terminal(candidate, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            "UPDATE public.applications_applicationdefinition SET status = 'retired', "
            "retired_at = clock_timestamp(), retired_by_id = %s, "
            "aggregate_version = aggregate_version + 1, name = 'Changed scope' "
            "WHERE id = %s",
            [call.common["actor_id"], call.active.definition_id],
        )


@pytest.mark.parametrize(
    ("model", "parent"),
    [
        *((model, "submission_id") for model in GUARDS.SUBMISSION_CHILDREN),
        ("programmereviewpolicy", "call_id"),
        ("programmereviewcase", "proposal_id"),
        ("programmereviewassignment", "case_id"),
        ("programmereviewentry", "case_id"),
        ("programmereviewdecision", "entry_id"),
        ("programmedecisionacknowledgement", "decision_id"),
        ("programmefilecontent", "intake_id"),
    ],
)
def test_derived_scope_cannot_use_missing_parent_as_stop_bypass(model, parent):
    with (
        connection.cursor() as cursor,
        pytest.raises(
            IntegrityError, match="Applications stop requires an exact owner scope"
        ),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL("INSERT INTO {} (id, {}) VALUES (%s, %s)").format(
                sql.Identifier("public", f"applications_{model}"),
                sql.Identifier(parent),
            ),
            [uuid4(), uuid4()],
        )
