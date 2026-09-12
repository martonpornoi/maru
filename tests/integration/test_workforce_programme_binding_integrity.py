"""Raw source integrity, readiness and both retained-binding migration paths."""

import json
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.audit.models import AuditNativeMutationWitness
from maru.authorization.provenance_readiness import _inspect_cutover_state
from maru.programme.models import ProgrammeStaffingRequirement
from maru.workforce.models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.shift_commands import update_shift_demand
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import (
    apply,
    create,
    shift_attribution,
)
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def append_raw(revision_id, **changes):
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT binding_id, sequence FROM workforce_programmeshiftbindingrevision "
            "WHERE id = %s",
            [revision_id],
        )
        binding_id, sequence = cursor.fetchone()
        patch = {"id": str(uuid4()), "sequence": sequence + 1, **changes}
        cursor.execute(
            "UPDATE workforce_programmeshiftbinding SET version = %s WHERE id = %s",
            [sequence + 1, binding_id],
        )
        cursor.execute(
            "INSERT INTO workforce_programmeshiftbindingrevision "
            "SELECT (jsonb_populate_record("
            "NULL::workforce_programmeshiftbindingrevision, "
            "to_jsonb(r) || %s::jsonb)).* "
            "FROM workforce_programmeshiftbindingrevision r WHERE id = %s",
            [json.dumps(patch), revision_id],
        )


@pytest.mark.parametrize("field", ["candidate_id", "placement_id"])
def test_raw_revision_cannot_substitute_a_missing_private_source(binding_world, field):
    scope = binding_world
    original = create(scope)
    terms = scope.selection.terms
    updated = update_shift_demand(
        **shift_attribution(scope),
        demand_id=original.demand_id,
        expected_version=1,
        title=terms.title,
        location_label=terms.location_label,
        briefing=terms.briefing,
        supervision_note=terms.supervision_note,
        starts_at=terms.starts_at,
        ends_at=terms.ends_at,
        required_headcount=terms.required_headcount,
        break_minutes=terms.break_minutes,
        minimum_rest_minutes=terms.minimum_rest_minutes,
    )
    with pytest.raises(IntegrityError, match="binding source is stale"):
        append_raw(
            original.revision_id,
            operation="reconcile",
            demand_version=updated.resulting_version,
            shift_receipt_id=str(updated.receipt_id),
            **{field: str(uuid4())},
        )
    assert ProgrammeShiftBinding.objects.get(id=original.binding_id).version == 1


def test_raw_reconciliation_cannot_reuse_an_already_consumed_workforce_revision(
    binding_world,
):
    scope = binding_world
    original = create(scope)
    revised = apply(
        scope,
        ProgrammeStaffingBindingChange(
            Action.RECONCILE,
            scope.selection.source,
            original.binding_id,
            1,
            original.demand_id,
            original.demand_version,
        ),
    )
    with pytest.raises(IntegrityError, match="Reconciliation must retain"):
        append_raw(revised.revision_id)
    assert ProgrammeShiftBinding.objects.get(id=original.binding_id).version == 2
    assert ProgrammeShiftBindingRevision.objects.count() == 2


def test_disabled_binding_guard_is_detected_without_reading_private_rows(binding_world):
    create(binding_world)
    assert _inspect_cutover_state().guards_installed
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE workforce_programmeshiftbinding "
            "DISABLE TRIGGER workforce_programme_binding_guard"
        )
        assert not _inspect_cutover_state().guards_installed
        transaction.set_rollback(True)
    assert _inspect_cutover_state().guards_installed


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_retained_binding_fences_downgrade_before_removing_its_guards(binding_world):
    original = create(binding_world)
    before = MigrationRecorder(connection).applied_migrations()
    retained = ProgrammeShiftBinding.objects.values().get(id=original.binding_id)
    revision = ProgrammeShiftBindingRevision.objects.values().get(
        id=original.revision_id
    )
    fence = import_module(
        "maru.workforce.migrations.0021_programme_binding_downgrade_fence"
    )
    with (
        pytest.raises(RuntimeError, match="retained Programme Shift lineage"),
        connection.schema_editor() as editor,
    ):
        fence.refuse_used_programme_binding_downgrade(apps, editor)
    assert AuditNativeMutationWitness.objects.exists()
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        MigrationExecutor(connection).migrate(
            [("workforce", "0019_programme_shift_bindings")]
        )
    assert MigrationRecorder(connection).applied_migrations() == before
    assert ProgrammeShiftBinding.objects.get(id=original.binding_id).version == 1
    assert (
        ProgrammeShiftBinding.objects.values().get(id=original.binding_id) == retained
    )
    assert (
        ProgrammeShiftBindingRevision.objects.values().get(id=original.revision_id)
        == revision
    )
    assert _inspect_cutover_state().guards_installed


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_native_requirements_fence_binding_contraction_without_a_binding(
    binding_world,
):
    identifier = binding_world.selection.source.requirement_id
    before = MigrationRecorder(connection).applied_migrations()
    assert not ProgrammeShiftBinding.objects.exists()
    assert AuditNativeMutationWitness.objects.exists()
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        MigrationExecutor(connection).migrate(
            [("workforce", "0018_programme_department_ownership_contract")]
        )
    assert MigrationRecorder(connection).applied_migrations() == before
    assert ProgrammeStaffingRequirement.objects.get(id=identifier).version == 1
    assert not ProgrammeShiftBinding.objects.exists()
    assert _inspect_cutover_state().guards_installed
