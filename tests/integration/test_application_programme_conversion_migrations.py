"""Real schema round trips, populated fences and conversion guard drift."""

from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.applications.models import ProgrammeAcceptedTransition
from maru.applications.programme_conversion_commands import (
    convert_accepted_programme_proposal,
)
from maru.applications.readiness import (
    APPLICATIONS_INTEGRITY_CONTRACT,
    applications_database_integrity_is_ready,
)
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.programme.host_commands import invite_programme_host
from maru.programme.host_inputs import ProgrammeHostInvitationInput
from maru.programme.models import (
    ProgrammeHostRelationship,
    ProgrammeItemSourceBinding,
    ProgrammeWorkingRevision,
)
from maru.programme.readiness import (
    _ACCEPTED_INTEGRITY_CONTRACT,
    _HOST_INTEGRITY_CONTRACT,
    PROGRAMME_INTEGRITY_CONTRACT,
    programme_database_integrity_is_ready,
)
from maru.scheduling.readiness import scheduling_database_integrity_is_ready
from maru.venues.readiness import venues_database_integrity_is_ready
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_application_programme_conversion import accepted
from tests.integration.test_application_programme_services import (
    _admit_future_programme_effects,
)
from tests.integration.test_programme_commands import (
    _create,
    _TrustedProgrammeAuthorizer,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures(
        "restores_current_migration_graph", _admit_future_programme_effects.__name__
    ),
]

UNUSED_PLANNING_SUCCESSORS = {
    ("programme", "0010_staffing_requirements"),
    ("programme", "0011_staffing_integrity"),
    ("programme", "0012_staffing_downgrade_fence"),
    ("programme", "0013_placement_decisions"),
    ("programme", "0014_placement_decision_integrity"),
    ("programme", "0015_placement_decision_downgrade_fence"),
    ("workforce", "0019_programme_shift_bindings"),
    ("workforce", "0020_programme_binding_integrity"),
    ("workforce", "0021_programme_binding_downgrade_fence"),
    ("scheduling", "0001_initial"),
    ("scheduling", "0002_service_day_retirement"),
    ("scheduling", "0003_scheduling_reservation_sources"),
    ("scheduling", "0004_conflict_vocabulary"),
    ("scheduling", "0005_integrity_guards"),
    ("scheduling", "0006_scheduling_downgrade_fence"),
    ("venues", "0003_scheduling_reservation_sources"),
    ("venues", "0004_scheduling_binding_integrity"),
    ("venues", "0005_scheduling_downgrade_fence"),
}


def test_empty_conversion_reversal_preserves_the_old_source_column_and_reinstalls():
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    executor.migrate([("applications", "0015_programme_review_downgrade_fence")])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.applications_programmeacceptedtransition')"
        )
        assert cursor.fetchone() == (None,)
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='public' "
            "AND table_name='programme_programmeitemsourcebinding' "
            "AND column_name='source_object_id'"
        )
        assert cursor.fetchone() == (1,)
    assert not applications_database_integrity_is_ready()
    assert not programme_database_integrity_is_ready()
    MigrationExecutor(connection).migrate(current)
    assert applications_database_integrity_is_ready()
    assert programme_database_integrity_is_ready()


def test_organizer_item_survives_unused_conversion_downgrade_and_upgrade():
    edition, actor = EventEditionFactory(), AccountFactory()
    result, _, _ = _create(
        actor=actor, edition=edition, authorizer=_TrustedProgrammeAuthorizer()
    )
    original = ProgrammeWorkingRevision.objects.get(item_id=result.item_id)
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    executor.migrate([("applications", "0015_programme_review_downgrade_fence")])
    assert (
        ProgrammeItemSourceBinding.objects.get(item_id=result.item_id).source_object_id
        is None
    )
    assert (
        ProgrammeWorkingRevision.objects.get(id=original.id).internal_title
        == original.internal_title
    )
    MigrationExecutor(connection).migrate(current)
    assert (
        ProgrammeItemSourceBinding.objects.get(item_id=result.item_id).source_object_id
        is None
    )
    assert (
        ProgrammeWorkingRevision.objects.get(id=original.id).internal_title
        == original.internal_title
    )
    assert applications_database_integrity_is_ready()
    assert programme_database_integrity_is_ready()


@pytest.mark.usefixtures(accepted.__name__)
@pytest.mark.parametrize("has_host", [False, True])
@pytest.mark.parametrize(
    "target",
    [
        ("applications", "0015_programme_review_downgrade_fence"),
        ("programme", "0003_downgrade_fence"),
        ("authorization", "0024_programme_review_capabilities"),
    ],
)
def test_completed_conversion_fences_contraction_before_any_guard_is_removed(
    accepted, target, has_host
):
    world, _, kwargs = accepted
    result = convert_accepted_programme_proposal(**kwargs)
    host_id = None
    if has_host:
        host_id = invite_programme_host(
            actor_id=kwargs["actor_id"],
            organization_id=kwargs["organization_id"],
            edition_id=kwargs["edition_id"],
            item_id=result.programme_item_id,
            invitation=ProgrammeHostInvitationInput(
                world.lead.id, "host", "Explicit hosting invitation", "", 1
            ),
            reason="Separate retained hosting purpose",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            authorizer=kwargs["programme_authorizer"],
        ).host_id
    current = MigrationExecutor(connection).loader.graph.leaf_nodes()
    applied_before = MigrationRecorder(connection).applied_migrations()
    binding_before = (
        ProgrammeItemSourceBinding.objects.filter(item_id=result.programme_item_id)
        .values()
        .get()
    )
    with pytest.raises(RuntimeError, match="Cannot remove"):
        MigrationExecutor(connection).migrate([target])
    assert ProgrammeAcceptedTransition.objects.filter(id=result.transition_id).exists()
    assert (
        ProgrammeItemSourceBinding.objects.filter(item_id=result.programme_item_id)
        .values()
        .get()
        == binding_before
    )
    assert applications_database_integrity_is_ready()
    if has_host:
        assert ProgrammeHostRelationship.objects.get(id=host_id).version == 1
        applied_after = MigrationRecorder(connection).applied_migrations()
        removed_unused = set(applied_before) - set(applied_after)
        # Only these exact unused successors may reverse before the populated
        # host fence. Every remaining owner recorder row must be identical.
        assert removed_unused <= UNUSED_PLANNING_SUCCESSORS
        assert applied_after == {
            key: value
            for key, value in applied_before.items()
            if key not in removed_unused
        }
        # The retained host contract remains exact, but the current staffing
        # schema was unused and reversed. It must not claim current readiness.
        guards = inspect_database_integrity_catalog(_HOST_INTEGRITY_CONTRACT)
        assert guards.source_contract_current
        assert guards.required_migrations_applied
        assert not guards.relations_installed
        assert guards.relation_ownership_consistent
        assert guards.trigger_contract_current
        assert guards.function_contract_current
        assert guards.function_execute_owner_only
        assert guards.function_ownership_current
        assert not programme_database_integrity_is_ready()
    else:
        # Django reverses unused successors before reaching the older populated
        # fence. Verify the retained conversion guards, not current host tables.
        guards = inspect_database_integrity_catalog(_ACCEPTED_INTEGRITY_CONTRACT)
        assert guards.source_contract_current
        assert guards.required_migrations_applied
        assert guards.relation_ownership_consistent
        assert guards.trigger_contract_current
        assert guards.function_contract_current
        assert guards.function_execute_owner_only
        assert guards.function_ownership_current
        assert not programme_database_integrity_is_ready()
    MigrationExecutor(connection).migrate(current)
    assert ProgrammeAcceptedTransition.objects.filter(id=result.transition_id).exists()
    assert (
        ProgrammeItemSourceBinding.objects.filter(item_id=result.programme_item_id)
        .values()
        .get()
        == binding_before
    )
    assert applications_database_integrity_is_ready()
    assert programme_database_integrity_is_ready()
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()


@pytest.mark.parametrize(
    ("identity", "contract"),
    [
        (
            "maru_applications_guard_programme_conversion()",
            APPLICATIONS_INTEGRITY_CONTRACT,
        ),
        (
            "maru_applications_validate_programme_conversion()",
            APPLICATIONS_INTEGRITY_CONTRACT,
        ),
        ("maru_guard_programme_source_binding()", PROGRAMME_INTEGRITY_CONTRACT),
    ],
)
def test_conversion_guard_execute_drift_fails_closed_and_rollback_recovers(
    identity, contract
):
    assert inspect_database_integrity_catalog(contract).ready
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"GRANT EXECUTE ON FUNCTION public.{identity} TO PUBLIC")
        assert not inspect_database_integrity_catalog(contract).ready
        transaction.set_rollback(True)
    assert inspect_database_integrity_catalog(contract).ready
