"""Maintained native receipt checks; unexecuted during ADR 0100 deferral.

The transaction-local schema candidate below admits one exact future profile pair
solely to exercise receipt integrity. It copies Workforce's existing manifest for
foundation commands; it is NOT the complete Programme manifest, an integrated
rehearsal, a runtime-role proof, or production activation. No policy is always-allow
and no native guard is disabled. Pytest rolls back the DDL and rows together.
"""

from dataclasses import replace
from datetime import date
from enum import StrEnum
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.core.relation_schema_readiness import collect_relation_schema_fingerprints
from maru.events import adoption
from maru.events import programme_setup as setup_command
from maru.events.models import (
    EditionCreationReceipt,
    EventEdition,
    ProgrammeAdoptionSetupReceipt,
)
from maru.events.programme_setup_inputs import ProgrammeSetupInput, ProgrammeSetupMode
from maru.events.programme_setup_readiness import (
    PROGRAMME_SETUP_RELATION,
    PROGRAMME_SETUP_SCHEMA_SHA256,
    programme_setup_database_integrity_is_ready,
)
from maru.events.services import EventEditionDetails, create_event_edition
from maru.organizations.programme_setup_references import (
    resolve_programme_setup_foundation,
)
from maru.organizations.representation import provision_maru_operators
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
)
from maru.workforce.structure_commands import create_department
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def command_request(monkeypatch):
    _admit_transaction_local_schema_candidate(monkeypatch)
    return {
        "actor": AccountFactory(is_staff=True, is_superuser=True),
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
        "details": ProgrammeSetupInput(
            mode=ProgrammeSetupMode.NEW_FOUNDATION,
            organization_name="Synthetic atomic organizers",
            series_name="Synthetic atomic series",
            edition_name="Synthetic atomic edition",
            department_name="Programme",
            starts_on=date(2030, 9, 6),
            ends_on=date(2030, 9, 8),
            time_zone="UTC",
            reason="Prepare one synthetic Programme foundation.",
        ),
    }


@pytest.mark.parametrize("mode", list(ProgrammeSetupMode))
def test_atomic_command_retains_one_complete_result_and_exact_retry(
    command_request, mode
):
    values = command_request
    if mode != ProgrammeSetupMode.NEW_FOUNDATION:
        context = {
            name: values[name] for name in ("actor", "correlation_id", "source_channel")
        }
        organization = create_draft_organization(
            details=OrganizationCreationDetails(name="Synthetic reused parent"),
            **context,
        )
        representation = provision_maru_operators(
            organization_id=organization.id,
            reason="Synthetic accountable foundation.",
            **context,
        )
        series = (
            create_convention_series(
                organization_id=organization.id,
                details=ConventionSeriesCreationDetails(name="Synthetic reused series"),
                **context,
            )
            if mode == ProgrammeSetupMode.EXISTING_SERIES
            else None
        )
        reference = resolve_programme_setup_foundation(
            organization_id=organization.id,
            series_id=series.id if series else None,
        )
        values["details"] = replace(
            values["details"],
            mode=mode,
            organization_name="",
            organization_id=organization.id,
            series_id=series.id if series else None,
            series_name="" if series else values["details"].series_name,
            foundation_fingerprint=reference.fingerprint,
        )
    result = setup_command.setup_programme_foundation(**values)
    replay = setup_command.setup_programme_foundation(
        **{**values, "correlation_id": uuid4()}
    )
    assert replay == replace(result, replayed=True)
    receipt = ProgrammeAdoptionSetupReceipt.objects.get(id=result.receipt_id)
    assert receipt.actor_id == values["actor"].id
    assert receipt.department_creation.resulting_version == 1
    assert receipt.edition_creation.idempotency_key == values["idempotency_key"]
    assert receipt.source_audit.operation == "events.programme_adoption.setup"
    assert receipt.edition.adoption_profile_code == "programme_operations"
    assert receipt.edition.lifecycle == "draft"
    if mode != ProgrammeSetupMode.NEW_FOUNDATION:
        assert receipt.representation_id == representation.id
    receipt.representation.refresh_from_db()
    assert receipt.representation.state == "provisioning"
    assert (
        ProgrammeAdoptionSetupReceipt.objects.filter(
            actor_id=values["actor"].id
        ).count()
        == 1
    )
    with pytest.raises(ValidationError, match="different details"):
        setup_command.setup_programme_foundation(
            **{
                **values,
                "details": replace(
                    values["details"], department_name="Other Department"
                ),
            }
        )


@pytest.mark.parametrize("failure", ["department", "audit", "receipt"])
def test_atomic_command_failure_leaves_no_partial_owner_state(
    command_request, monkeypatch, failure
):
    labels = (
        "organizations.Organization",
        "organizations.ConventionSeries",
        "organizations.OrganizationRepresentation",
        "events.EventEdition",
        "events.EditionCreationReceipt",
        "workforce.Department",
        "workforce.EditionStructureCommandReceipt",
        "events.ProgrammeAdoptionSetupReceipt",
        "audit.AuditEvent",
        "effects.DomainEvent",
        "effects.OutboxMessage",
    )
    counts = {label: apps.get_model(label).objects.count() for label in labels}

    def reject(*_args, **_kwargs):
        raise RuntimeError("Synthetic final-write failure")

    if failure == "department":
        monkeypatch.setattr(setup_command, "create_department", reject)
    elif failure == "audit":
        monkeypatch.setattr(setup_command, "append_audit", reject)
    else:
        monkeypatch.setattr(ProgrammeAdoptionSetupReceipt, "save", reject)
    with pytest.raises(RuntimeError, match="Synthetic final-write failure"):
        setup_command.setup_programme_foundation(**command_request)
    assert {label: apps.get_model(label).objects.count() for label in labels} == counts


def test_atomic_command_rechecks_real_revocation_on_retained_retry(command_request):
    result = setup_command.setup_programme_foundation(**command_request)
    actor = command_request["actor"]
    actor.__class__.objects.filter(id=actor.id).update(is_active=False)
    # Deliberately keep the original Python principal stale and apparently active.
    assert actor.is_active
    with pytest.raises(PermissionDenied):
        setup_command.setup_programme_foundation(**command_request)
    assert ProgrammeAdoptionSetupReceipt.objects.filter(id=result.receipt_id).exists()


def test_atomic_command_rejects_reused_foundation_changed_after_preview(
    command_request,
):
    context = {
        name: command_request[name]
        for name in ("actor", "correlation_id", "source_channel")
    }
    organization = create_draft_organization(
        details=OrganizationCreationDetails(name="Synthetic stale parent"),
        **context,
    )
    reference = resolve_programme_setup_foundation(organization_id=organization.id)
    provision_maru_operators(
        organization_id=organization.id, reason="New source state.", **context
    )
    submitted = replace(
        command_request["details"],
        mode=ProgrammeSetupMode.EXISTING_ORGANIZATION,
        organization_name="",
        organization_id=organization.id,
        foundation_fingerprint=reference.fingerprint,
    )
    with pytest.raises(ValidationError, match="original foundation"):
        setup_command.setup_programme_foundation(
            **{**command_request, "details": submitted}
        )
    assert not EventEdition.objects.filter(organization_id=organization.id).exists()


def test_atomic_command_default_profile_is_zero_query_denial(django_assert_num_queries):
    actor = AccountFactory(is_staff=True, is_superuser=True)
    with (
        django_assert_num_queries(0),
        pytest.raises(ValidationError, match="not available"),
    ):
        setup_command.setup_programme_foundation(
            actor=actor,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            details=ProgrammeSetupInput(
                mode=ProgrammeSetupMode.NEW_FOUNDATION,
                organization_name="Synthetic organizers",
                series_name="Synthetic series",
                edition_name="Synthetic edition",
                department_name="Programme",
                starts_on=date(2030, 9, 6),
                ends_on=date(2030, 9, 8),
                time_zone="UTC",
                reason="Synthetic setup.",
            ),
        )


class _SchemaCandidateCode(StrEnum):
    FULL_CONVENTION = "full_convention"
    WORKFORCE_ONLY = "workforce_only"
    PROGRAMME_OPERATIONS = "programme_operations"


def _admit_transaction_local_schema_candidate(monkeypatch):
    candidate = replace(
        adoption.ADOPTION_PROFILES[("workforce_only", 1)],
        code=_SchemaCandidateCode.PROGRAMME_OPERATIONS,
    )
    monkeypatch.setattr(adoption, "AdoptionProfileCode", _SchemaCandidateCode)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {
            **adoption.ADOPTION_PROFILES,
            ("programme_operations", 1): candidate,
        },
    )
    monkeypatch.setattr(
        adoption,
        "SELECTABLE_ADOPTION_PROFILE_KEYS",
        {
            **adoption.SELECTABLE_ADOPTION_PROFILE_KEYS,
            _SchemaCandidateCode.PROGRAMME_OPERATIONS: ("programme_operations", 1),
        },
    )
    field = EventEdition._meta.get_field("adoption_profile_code")
    monkeypatch.setattr(
        field,
        "choices",
        [*field.choices, ("programme_operations", "Schema candidate only")],
    )
    constraint = next(
        value
        for value in EventEdition._meta.constraints
        if value.name == "edition_adoption_profile_supported"
    )
    monkeypatch.setattr(
        constraint,
        "condition",
        constraint.condition
        | models.Q(
            adoption_profile_code="programme_operations",
            adoption_profile_version=1,
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE events_eventedition "
            "DROP CONSTRAINT edition_adoption_profile_supported"
        )
        cursor.execute("""
            ALTER TABLE events_eventedition
            ADD CONSTRAINT edition_adoption_profile_supported
            CHECK (adoption_profile_version = 1 AND adoption_profile_code IN
                   ('full_convention', 'workforce_only', 'programme_operations'))
        """)


@pytest.fixture
def receipt_world(monkeypatch, request):
    profile_code = getattr(request, "param", "programme_operations")
    if profile_code == "programme_operations":
        _admit_transaction_local_schema_candidate(monkeypatch)
    actor = AccountFactory(is_staff=True, is_superuser=True)
    key, correlation, receipt_id = uuid4(), uuid4(), uuid4()
    reason = "Prepare a synthetic first Programme Department."
    context = {"actor": actor, "correlation_id": correlation, "source_channel": "test"}
    organization = create_draft_organization(
        details=OrganizationCreationDetails(name="Synthetic setup schema"),
        **context,
    )
    series = create_convention_series(
        organization_id=organization.id,
        details=ConventionSeriesCreationDetails(name="Synthetic schema series"),
        **context,
    )
    representation = provision_maru_operators(
        organization_id=organization.id,
        reason=reason,
        **context,
    )
    edition = create_event_edition(
        organization_id=organization.id,
        series_id=series.id,
        details=EventEditionDetails(
            name="Synthetic Programme edition",
            time_zone="Europe/Budapest",
            language_codes=("en",),
            currency_codes=("XXX",),
            starts_on=date(2030, 9, 6),
            ends_on=date(2030, 9, 8),
        ),
        idempotency_key=key,
        adoption_profile_code=profile_code,
        **context,
    ).edition
    department = create_department(
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
        name="Programme",
        description="",
        parent_department_id=None,
        display_order=None,
        expected_version=0,
        reason=reason,
        retry_key=key,
        **context,
    )
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=edition.id,
            capability_code="events.create",
            operation="events.programme_adoption.setup",
            target_type="events.programme_setup_receipt",
            target_id=receipt_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_administration",
            correlation_id=correlation,
            source_channel="test",
            retention_class="security-standard",
        )
    )
    return {
        "id": receipt_id,
        "organization_id": organization.id,
        "series_id": series.id,
        "edition_id": edition.id,
        "department_id": department.department_id,
        "representation_id": representation.id,
        "representation_version": representation.aggregate_version,
        "actor_id": actor.id,
        "source_audit_id": audit.id,
        "edition_creation_id": EditionCreationReceipt.objects.get(
            edition_id=edition.id
        ).id,
        "department_creation_id": department.receipt_id,
        "idempotency_key": key,
        "request_digest": "a" * 64,
        "mode": "new_foundation",
        "foundation_fingerprint": "",
        "reason": reason,
    }


def _native_insert(values):
    # Deliberate native-boundary probe, not an ORM command or runtime acceptance.
    return ProgrammeAdoptionSetupReceipt.objects.bulk_create(
        [
            ProgrammeAdoptionSetupReceipt(**values),
        ]
    )[0]


def test_installed_setup_schema_and_native_catalog_match_reviewed_shapes():
    assert (
        collect_relation_schema_fingerprints((PROGRAMME_SETUP_RELATION,))
        == PROGRAMME_SETUP_SCHEMA_SHA256
    )
    assert programme_setup_database_integrity_is_ready()


def test_exact_native_receipt_preserves_both_owner_receipts(receipt_world):
    receipt = _native_insert(receipt_world)
    loaded = ProgrammeAdoptionSetupReceipt.objects.get(pk=receipt.pk)
    for field, value in receipt_world.items():
        assert getattr(loaded, field) == value


@pytest.mark.parametrize(
    "receipt_world", ["full_convention", "workforce_only"], indirect=True
)
def test_current_profiles_cannot_receive_a_programme_setup_receipt(receipt_world):
    with (
        pytest.raises(IntegrityError, match="exact new dormant-profile edition"),
        transaction.atomic(),
    ):
        _native_insert(receipt_world)


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "series_id",
        "edition_id",
        "department_id",
        "representation_id",
        "actor_id",
        "source_audit_id",
        "edition_creation_id",
        "department_creation_id",
    ],
)
def test_native_receipt_rejects_unrelated_owner_or_evidence(receipt_world, field):
    with pytest.raises(IntegrityError), transaction.atomic():
        _native_insert({**receipt_world, field: uuid4()})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "unknown"),
        ("mode", "existing_series"),
        ("foundation_fingerprint", "b" * 64),
        ("request_digest", "BAD"),
        ("representation_version", 0),
        ("representation_version", 999),
        ("reason", ""),
        ("reason", "   "),
        ("reason", "Another rationale"),
    ],
)
def test_native_receipt_rejects_changed_intent_and_unproven_state(
    receipt_world, field, value
):
    with pytest.raises(IntegrityError), transaction.atomic():
        _native_insert({**receipt_world, field: value})


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
def test_completed_setup_evidence_is_retained(receipt_world, operation):
    receipt = _native_insert(receipt_world)
    statement, parameters = {
        "update": (
            "UPDATE events_programmeadoptionsetupreceipt SET reason = %s WHERE id = %s",
            ["Changed", receipt.id],
        ),
        "delete": (
            "DELETE FROM events_programmeadoptionsetupreceipt WHERE id = %s",
            [receipt.id],
        ),
        "truncate": ("TRUNCATE events_programmeadoptionsetupreceipt", []),
    }[operation]
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, parameters)
    assert ProgrammeAdoptionSetupReceipt.objects.filter(pk=receipt.id).exists()


def test_completed_setup_fences_guard_and_schema_removal(receipt_world):
    _native_insert(receipt_world)
    for reference, function in (
        ("0012_programme_setup_receipt", "refuse_used_setup_receipt_downgrade"),
        ("0014_programme_setup_downgrade_fence", "refuse_used_setup_guard_downgrade"),
    ):
        module = import_module("maru.events.migrations." + reference)
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="retain it and fix forward"),
        ):
            getattr(module, function)(apps, editor)


@pytest.mark.django_db(transaction=True)
def test_unused_setup_boundary_reverses_and_reapplies():
    executor = MigrationExecutor(connection)
    original_leaves = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("events", "0011_release_dependency_mutations")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.events_programmeadoptionsetupreceipt')"
            )
            assert cursor.fetchone() == (None,)
    finally:
        MigrationExecutor(connection).migrate(original_leaves)
    assert programme_setup_database_integrity_is_ready()
