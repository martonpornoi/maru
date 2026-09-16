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
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.core.relation_schema_readiness import collect_relation_schema_fingerprints
from maru.events import adoption
from maru.events.models import (
    EditionCreationReceipt,
    EventEdition,
    ProgrammeAdoptionSetupReceipt,
)
from maru.events.programme_setup_readiness import (
    PROGRAMME_SETUP_RELATION,
    PROGRAMME_SETUP_SCHEMA_SHA256,
    programme_setup_database_integrity_is_ready,
)
from maru.events.services import EventEditionDetails, create_event_edition
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
