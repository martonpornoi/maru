"""Focused application-service coverage for unmounted Page 9a.1 commands."""

from __future__ import annotations

from datetime import timedelta
from typing import Never
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.structure_commands import (
    StructureAuthorizationDeniedError,
    StructureDepartmentUnavailableError,
    StructureDependencyConflictError,
    StructureLifecycleConflictError,
    StructureRetryConflictError,
    StructureVersionConflictError,
    apply_builtin_structure_template,
    create_department,
    delete_unused_department,
    retire_department,
    update_department,
)
from maru.workforce.structure_templates import AWOOSTRIA_REFERENCE_V1
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _create(
    *,
    actor: Account,
    edition: EventEdition,
    name: str = "Operations",
    parent_department_id=None,  # type: ignore[no-untyped-def]
    expected_version: int = 0,
    retry_key=None,  # type: ignore[no-untyped-def]
):
    return create_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        name=name,
        description="  Coordinates synthetic operations.  ",
        parent_department_id=parent_department_id,
        display_order=10,
        expected_version=expected_version,
        reason="  Establish the synthetic structure.  ",
        retry_key=retry_key or uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_template_application_is_exact_atomic_minimized_and_nonparticipating() -> None:
    actor = _administrator()
    edition = EventEditionFactory(
        organization__lifecycle=Organization.Lifecycle.DRAFT,
        lifecycle=EventEdition.Lifecycle.DRAFT,
        name="Synthetic Reference Edition",
    )
    before = {
        "accounts": Account.objects.count(),
        "positions": Position.objects.count(),
        "assignments": PositionAssignment.objects.count(),
        "grants": CapabilityGrant.objects.count(),
        "roles": RoleAssignment.objects.count(),
    }

    result = apply_builtin_structure_template(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_identifier=AWOOSTRIA_REFERENCE_V1.identifier,
        expected_version=0,
        confirmation_name=edition.name,
        reason="Use the reviewed synthetic taxonomy.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    departments = tuple(
        Department.objects.filter(edition=edition).order_by("display_order")
    )
    assert result.replayed is False
    assert result.resulting_version == 1
    assert len(result.department_ids) == 22
    assert [item.code for item in departments] == [
        item.code for item in AWOOSTRIA_REFERENCE_V1.departments
    ]
    assert departments[0].name == "Helper Board"
    assert departments[0].parent_id is None
    assert {item.parent_id for item in departments[1:]} == {departments[0].id}
    assert EditionStructureControl.objects.get(edition=edition).origin == (
        EditionStructureControl.Origin.BUILTIN_TEMPLATE
    )
    receipt = EditionStructureCommandReceipt.objects.get(pk=result.receipt_id)
    assert receipt.template_digest == AWOOSTRIA_REFERENCE_V1.sha256_digest
    assert receipt.reason == "Use the reviewed synthetic taxonomy."
    audit = AuditEvent.objects.get(operation="workforce.structure.change")
    event = DomainEvent.objects.get(event_name="workforce.structure.changed.v1")
    assert audit.safe_metadata == {
        "policy_version": POLICY_VERSION,
        "target_count": 22,
    }
    assert "reason" not in event.payload
    assert event.causation_id == audit.id
    assert event.payload == {
        "action": "template_applied",
        "aggregate_version": "1",
        "changed_fields": "departments",
        "template_code": "awoostria-reference",
        "template_version": "1",
    }
    assert OutboxMessage.objects.filter(event=event).count() == 1
    assert {
        "accounts": Account.objects.count(),
        "positions": Position.objects.count(),
        "assignments": PositionAssignment.objects.count(),
        "grants": CapabilityGrant.objects.count(),
        "roles": RoleAssignment.objects.count(),
    } == before


def test_create_replay_precedes_stale_and_lifecycle_but_changed_reuse_conflicts() -> (
    None
):
    actor = _administrator()
    edition = EventEditionFactory()
    retry_key = uuid4()
    first = _create(actor=actor, edition=edition, retry_key=retry_key)
    EventEdition.objects.filter(pk=edition.pk).update(
        lifecycle=EventEdition.Lifecycle.CANCELLED,
        lifecycle_version=1,
        aggregate_version=2,
    )

    replay = _create(actor=actor, edition=edition, retry_key=retry_key)

    assert replay.replayed is True
    assert replay.department_id == first.department_id
    assert replay.receipt_id == first.receipt_id
    assert Department.objects.filter(edition=edition).count() == 1
    assert EditionStructureCommandReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    with pytest.raises(StructureRetryConflictError) as caught:
        _create(
            actor=actor,
            edition=edition,
            name="Changed operations",
            retry_key=retry_key,
        )
    assert caught.value.reason_code == "structure_retry_conflict"


def test_update_is_complete_versioned_and_normalized_noop_emits_nothing() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    created = _create(actor=actor, edition=edition)

    changed = update_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        department_id=created.department_id,
        name="  Event   Operations ",
        description="Coordinates the changed synthetic operation.",
        parent_department_id=None,
        display_order=20,
        expected_version=1,
        reason="Replace every editable property.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert changed.resulting_version == 2
    assert changed.changed_fields == ("description", "display_order", "name")
    department = Department.objects.get(pk=created.department_id)
    assert department.name == "Event Operations"
    assert department.display_order == 20
    evidence_counts = (
        EditionStructureCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    noop = update_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        department_id=created.department_id,
        name=" Event Operations ",
        description="Coordinates the changed synthetic operation.",
        parent_department_id=None,
        display_order=20,
        expected_version=2,
        reason="Confirm there is no normalized change.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert noop.resulting_version == 2
    assert noop.changed_fields == ()
    assert noop.receipt_id is None
    assert evidence_counts == (
        EditionStructureCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    with pytest.raises(StructureVersionConflictError):
        update_department(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=created.department_id,
            name=department.name,
            description=department.description,
            parent_department_id=None,
            display_order=department.display_order,
            expected_version=1,
            reason="Use a stale version.",
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_exact_route_scope_and_both_capabilities_are_required_without_writes() -> None:
    edition = EventEditionFactory()
    foreign = EventEditionFactory()
    person = AccountFactory(is_staff=False, is_superuser=False)

    with pytest.raises(StructureAuthorizationDeniedError) as denied:
        _create(actor=person, edition=edition)
    assert denied.value.reason_code == "structure_authorization_denied"
    with pytest.raises(StructureAuthorizationDeniedError) as unavailable:
        create_department(
            actor=_administrator(),
            organization_id=edition.organization_id,
            series_id=foreign.series_id,
            edition_id=edition.id,
            name="Foreign route",
            description="",
            parent_department_id=None,
            display_order=0,
            expected_version=0,
            reason="Prove exact route scope.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert unavailable.value.reason_code == "structure_authorization_denied"
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()
    assert not AuditEvent.objects.exists()


def test_noneditable_lifecycle_and_retired_rows_are_immutable() -> None:
    actor = _administrator()
    ready = EventEditionFactory()
    EventEdition.objects.filter(pk=ready.pk).update(
        lifecycle=EventEdition.Lifecycle.CANCELLED,
        lifecycle_version=1,
        aggregate_version=2,
    )
    ready.refresh_from_db()
    with pytest.raises(StructureLifecycleConflictError):
        _create(actor=actor, edition=ready)

    edition = EventEditionFactory()
    created = _create(actor=actor, edition=edition)
    retired = retire_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        department_id=created.department_id,
        expected_version=1,
        reason="Retain this Department as history.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert retired.resulting_version == 2
    with pytest.raises(StructureDepartmentUnavailableError):
        update_department(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=created.department_id,
            name="Changed retired row",
            description="",
            parent_department_id=None,
            display_order=0,
            expected_version=2,
            reason="This must not work.",
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_retirement_rejects_child_and_current_or_future_authority() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    parent = _create(actor=actor, edition=edition, name="Parent")
    child = _create(
        actor=actor,
        edition=edition,
        name="Child",
        parent_department_id=parent.department_id,
        expected_version=1,
    )
    with pytest.raises(StructureDependencyConflictError):
        retire_department(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=parent.department_id,
            expected_version=2,
            reason="A current child must block this.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department_id=child.department_id,
        effective_from=timezone.now() + timedelta(days=1),
    )
    with pytest.raises(StructureDependencyConflictError) as caught:
        retire_department(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=child.department_id,
            expected_version=2,
            reason="Future authority must also block retirement.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert caught.value.reason_code == "structure_department_has_dependencies"


def test_retirement_preserves_a_retained_binding_for_a_closed_position() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    created = _create(actor=actor, edition=edition)
    department = Department.objects.get(pk=created.department_id)
    role = RoleBundleFactory(organization=edition.organization)
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="closed-position",
        name="Closed position",
        description="Synthetic closed Position template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role,
        created_by=actor,
    )
    position = Position.objects.create(
        organization=edition.organization,
        edition=edition,
        template=template,
        department=department,
        role_bundle=role,
        code="closed-position",
        title="Closed position",
        description="Synthetic closed Position.",
        capacity_codes=["volunteer"],
        status=Position.Status.CLOSED,
        created_by=actor,
    )
    binding = ensure_workforce_position_binding(position=position)

    result = retire_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        department_id=department.id,
        expected_version=1,
        reason="Retain the immutable binding as closed history.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    department.refresh_from_db()
    assert result.resulting_version == 2
    assert department.retired_at is not None
    assert ScopedResourceBinding.objects.filter(pk=binding.pk).exists()


def test_unauthorized_unknown_template_is_not_a_catalog_oracle() -> None:
    actor = AccountFactory(is_staff=False, is_superuser=False)
    edition = EventEditionFactory()

    with pytest.raises(StructureAuthorizationDeniedError):
        apply_builtin_structure_template(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            template_identifier="unknown-template@999",
            expected_version=0,
            confirmation_name=edition.name,
            reason="Do not disclose the template catalog.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_unused_command_created_leaf_can_be_deleted_with_a_tombstone() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    created = _create(actor=actor, edition=edition)

    deleted = delete_unused_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        department_id=created.department_id,
        expected_version=1,
        confirmation_name="Operations",
        reason="Remove an unused mistaken Department.",
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert deleted.resulting_version == 2
    assert not Department.objects.filter(pk=created.department_id).exists()
    receipt = EditionStructureCommandReceipt.objects.get(pk=deleted.receipt_id)
    assert receipt.deleted_name_snapshot == "Operations"


def test_unknown_database_reference_is_a_recoverable_protected_delete_conflict() -> (
    None
):
    actor = _administrator()
    edition = EventEditionFactory()
    created = _create(actor=actor, edition=edition)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE workforce_test_unknown_department_reference (
                department_id uuid NOT NULL REFERENCES workforce_department(id)
            )
            """
        )
        cursor.execute(
            "INSERT INTO workforce_test_unknown_department_reference "
            "(department_id) VALUES (%s)",
            [created.department_id],
        )

    try:
        with pytest.raises(StructureDependencyConflictError):
            delete_unused_department(
                actor=actor,
                organization_id=edition.organization_id,
                series_id=edition.series_id,
                edition_id=edition.id,
                department_id=created.department_id,
                expected_version=1,
                confirmation_name="Operations",
                reason="The unknown reference must protect this row.",
                correlation_id=uuid4(),
                source_channel="test",
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE workforce_test_unknown_department_reference")

    assert Department.objects.filter(pk=created.department_id).exists()
    assert EditionStructureControl.objects.get(edition=edition).aggregate_version == 1
    assert EditionStructureCommandReceipt.objects.filter(edition=edition).count() == 1


def test_outbox_failure_rolls_back_department_control_receipt_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _administrator()
    edition = EventEditionFactory()

    def fail_publish(*_args, **_kwargs) -> Never:  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic structure outbox failure")

    monkeypatch.setattr(
        "maru.workforce.structure_commands.publish_domain_event",
        fail_publish,
    )
    with pytest.raises(RuntimeError, match="synthetic structure outbox"):
        _create(actor=actor, edition=edition)

    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()
    assert not EditionStructureCommandReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_confirmation_and_reserved_governance_name_are_strict_inputs() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    with pytest.raises(ValidationError) as reserved:
        _create(actor=actor, edition=edition, name="Executive Board")
    assert reserved.value.error_dict["name"][0].code == (
        "structure_executive_board_reserved"
    )
    with pytest.raises(ValidationError) as confirmation:
        apply_builtin_structure_template(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            template_identifier=AWOOSTRIA_REFERENCE_V1.identifier,
            expected_version=0,
            confirmation_name=edition.name.lower(),
            reason="Require exact edition confirmation.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert confirmation.value.error_dict["confirmation_name"][0].code == (
        "structure_confirmation_mismatch"
    )
