"""Historical-orphan continuity coverage for Programme import disposal."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.applications.models import (
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportCommandAction,
    ProgrammeImportCommandReceipt,
    ProgrammeImportItem,
    ProgrammeImportItemState,
)
from maru.applications.programme_import_commands import (
    ApplicationsProgrammeImportUnavailableError,
    discard_programme_import,
    reassign_programme_import_batch,
)
from maru.applications.programme_import_writer_boundary import (
    programme_import_database_writer,
)
from maru.authorization.policy import PolicyDecision
from maru.workforce.models import Department
from tests.factories import AccountFactory, EventEditionFactory
from tests.support.migrations import restore_current_migration_graph
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from django.apps.registry import Apps


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

APPLICATIONS_BEFORE_OWNERSHIP = (
    "applications",
    "0009_programme_import_populated_downgrade_fence",
)
WORKFORCE_BEFORE_OWNERSHIP = (
    "workforce",
    "0017_programme_import_department_fk_contract",
)


@dataclass(frozen=True, slots=True)
class _AllowImportDisposalAuthorizer:
    """Return complete isolated-test decisions for historical disposal."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del (
            principal_id,
            organization_id,
            edition_id,
            department_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_edition(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, capability_code
        return self._decision(requested_fields)

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        return self._decision(frozenset())

    @staticmethod
    def _decision(requested_fields: frozenset[str] | None) -> PolicyDecision:
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="historical_programme_import_disposal_test",
        )


_AUTHORIZER = _AllowImportDisposalAuthorizer()


@pytest.fixture(autouse=True)
def _admit_dormant_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit only otherwise-dormant event publication in this service test."""
    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _migrate_to_pre_coordination_state() -> Apps:
    executor = MigrationExecutor(connection)
    targets = [APPLICATIONS_BEFORE_OWNERSHIP, WORKFORCE_BEFORE_OWNERSHIP]
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def _create_historical_staged_batch(
    *,
    historical_apps: Apps,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> UUID:
    batch_model = historical_apps.get_model("applications", "ProgrammeImportBatch")
    item_model = historical_apps.get_model("applications", "ProgrammeImportItem")
    receipt_model = historical_apps.get_model(
        "applications",
        "ProgrammeImportCommandReceipt",
    )
    now = timezone.now()
    private_payload = b'{"synthetic":"historical private Programme staging"}'
    source_digest = hashlib.sha256(private_payload).hexdigest()
    batch_id = uuid4()
    with transaction.atomic(), programme_import_database_writer():
        batch = batch_model.objects.create(
            id=batch_id,
            organization_id=organization_id,
            edition_id=edition_id,
            owner_department_id=department_id,
            source_system="legacy.programme.history",
            schema_version=1,
            source_digest=source_digest,
            item_count=1,
            retention_policy_code="applications.programme-import-staging.test-v1",
            expires_at=now + timedelta(days=1),
            state="staged",
            aggregate_version=1,
            staged_by_id=actor_id,
        )
        item_model.objects.create(
            id=uuid4(),
            batch_id=batch.id,
            organization_id=organization_id,
            edition_id=edition_id,
            sequence=1,
            kind="call",
            source_key="historical-programme-call",
            source_digest=source_digest,
            canonical_payload=private_payload,
            payload_size_bytes=len(private_payload),
            dependency_source_system="",
            dependency_source_key="",
            state="staged",
            aggregate_version=1,
        )
        receipt_model.objects.create(
            id=uuid4(),
            organization_id=organization_id,
            edition_id=edition_id,
            actor_id=actor_id,
            aggregate_kind="batch",
            action="batch_staged",
            retry_key=uuid4(),
            request_digest="1" * 64,
            reason="Retain the synthetic historical staging creation evidence.",
            correlation_id=uuid4(),
            source_channel="test",
            batch_id=batch.id,
            adopted_preview_digest="",
            result_kind="batch",
            expected_version=0,
            resulting_version=1,
            applied_command_count=0,
        )
    return batch_id


def _retire_historical_owner_directly(
    *,
    actor_id: UUID,
    department_id: UUID,
) -> None:
    """Synthesize a retirement committed before the coordination contract."""
    retired_at = timezone.now()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(
            """
            UPDATE public.workforce_department
               SET created_in_structure_version = COALESCE(
                       created_in_structure_version, 1
                   ),
                   last_changed_in_structure_version = COALESCE(
                       last_changed_in_structure_version,
                       created_in_structure_version,
                       1
                   ),
                   retired_at = %s,
                   retired_by_id = %s,
                   retired_in_structure_version = COALESCE(
                       last_changed_in_structure_version,
                       created_in_structure_version,
                       1
                   ),
                   updated_at = %s
             WHERE id = %s
            """,
            [retired_at, actor_id, retired_at, department_id],
        )
        assert cursor.rowcount == 1


def test_historical_orphan_staging_remains_disposable_after_upgrade() -> None:
    """Upgrade an old orphan without fabrication, then scrub it explicitly."""
    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Historical Programme custodian")
    department = create_department_for_test(
        edition=edition,
        name="Historical Programme",
        expected_code="historical-programme",
    )
    historical_apps = _migrate_to_pre_coordination_state()
    batch_id = _create_historical_staged_batch(
        historical_apps=historical_apps,
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        department_id=department.id,
    )
    _retire_historical_owner_directly(
        actor_id=manager.id,
        department_id=department.id,
    )

    restore_current_migration_graph()
    retired = Department.objects.get(id=department.id)
    assert retired.retired_at is not None
    batch = ProgrammeImportBatch.objects.get(id=batch_id)
    assert batch.owner_department_id == retired.id
    assert batch.state == ProgrammeImportBatchState.STAGED
    assert not ProgrammeImportCommandReceipt.objects.filter(
        batch_id=batch_id,
        action=ProgrammeImportCommandAction.BATCH_REASSIGNED,
    ).exists()
    destination = create_department_for_test(
        edition=edition,
        name="Current Programme",
        expected_code="current-programme",
    )
    with pytest.raises(ApplicationsProgrammeImportUnavailableError):
        reassign_programme_import_batch(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            batch_id=batch_id,
            source_department_id=retired.id,
            destination_department_id=destination.id,
            expected_version=1,
            reason="A historical orphan must not regain an active owner.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=_AUTHORIZER,
        )
    batch.refresh_from_db()
    assert batch.owner_department_id == retired.id
    assert batch.aggregate_version == 1

    disposed = discard_programme_import(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        batch_id=batch_id,
        expected_version=1,
        reason="Dispose a staged orphan retained from before coordination.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )

    assert disposed.resulting_version == 2
    batch.refresh_from_db()
    item = ProgrammeImportItem.objects.get(batch_id=batch_id)
    assert batch.owner_department_id == retired.id
    assert batch.state == ProgrammeImportBatchState.DISCARDED
    assert item.state == ProgrammeImportItemState.DISCARDED
    assert item.aggregate_version == 2
    assert item.canonical_payload is None
