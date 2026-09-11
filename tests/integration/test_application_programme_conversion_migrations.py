"""Real schema round trips, populated fences and conversion guard drift."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
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
from maru.audit.models import AuditNativeMutationWitness
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.programme.host_commands import invite_programme_host
from maru.programme.host_inputs import ProgrammeHostInvitationInput
from maru.programme.models import (
    ProgrammeHostRelationship,
    ProgrammeItemSourceBinding,
    ProgrammeWorkingRevision,
)
from maru.programme.readiness import (
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


def test_organizer_item_native_evidence_fences_conversion_downgrade():
    edition, actor = EventEditionFactory(), AccountFactory()
    result, _, _ = _create(
        actor=actor, edition=edition, authorizer=_TrustedProgrammeAuthorizer()
    )
    original = ProgrammeWorkingRevision.objects.get(item_id=result.item_id)
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    applied_before = MigrationRecorder(connection).applied_migrations()
    assert AuditNativeMutationWitness.objects.exists()
    # Creating an organizer item now uses the native owner boundary even when
    # no accepted conversion or timetable has been created. Its evidence makes
    # the release extension used; no successor guard may partially reverse.
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        executor.migrate([("applications", "0015_programme_review_downgrade_fence")])
    assert MigrationRecorder(connection).applied_migrations() == applied_before
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
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()


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
    # Retain direct proof of the older conversion-specific safeguard. Current
    # whole-graph reversal must now stop at the newer top-level release fence,
    # before Django can reach this populated predecessor or remove successors.
    conversion_fence = import_module(
        "maru.applications.migrations.0018_programme_conversion_downgrade_fence"
    )
    with (
        pytest.raises(RuntimeError, match="Cannot remove Programme conversion"),
        connection.schema_editor() as schema_editor,
    ):
        conversion_fence.refuse_populated_programme_conversion_downgrade(
            apps, schema_editor
        )
    assert AuditNativeMutationWitness.objects.exists()
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
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
    assert MigrationRecorder(connection).applied_migrations() == applied_before
    assert programme_database_integrity_is_ready()
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()
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
