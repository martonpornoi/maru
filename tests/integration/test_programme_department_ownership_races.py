"""Exercise real Programme ownership mutexes and retirement backstops."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from django.db import DatabaseError, connections, transaction
from django.db.models import F

from maru.applications.models import (
    ApplicationDefinition,
    ProgrammeCall,
    ProgrammeCommandReceipt,
    ProgrammeImportBatch,
    ProgrammeImportCommandReceipt,
    ProgrammeImportItem,
)
from maru.applications.programme_commands import retire_programme_call
from maru.applications.programme_department_dependencies import (
    ProgrammeDepartmentDependencyState,
    programme_department_retirement_dependency_state,
)
from maru.applications.programme_write_scope import lock_programme_edition_write_scope
from maru.workforce.models import Department
from maru.workforce.structure_commands import (
    StructureDependencyConflictError,
    retire_department,
)
from maru.workforce.writer_boundary import lock_edition_structure_mutex
from tests.factories import AccountFactory
from tests.integration.test_application_programme_import_services import (
    _call_item,
    _document,
    _stage,
)
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _active_call,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@pytest.fixture(autouse=True)
def _admit_dormant_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


@pytest.mark.parametrize(
    "model",
    [
        ApplicationDefinition,
        ProgrammeCall,
        ProgrammeCommandReceipt,
        ProgrammeImportBatch,
        ProgrammeImportItem,
        ProgrammeImportCommandReceipt,
    ],
)
def test_raw_programme_writes_fail_retryably_when_retirement_owns_mutex(model) -> None:
    """Every installed row barrier rejects inverted raw writes with SQLSTATE 40001."""
    world = _active_call()
    _stage(
        actor=world.manager,
        edition=world.edition,
        department_id=world.department_id,
        payload=_document([_call_item(world.now)]),
        now=world.now,
    )
    target_id = model.objects.filter(edition_id=world.edition.id).first().id
    locked = Event()
    release = Event()

    def hold_retirement_mutex() -> None:
        try:
            with transaction.atomic():
                lock_edition_structure_mutex(
                    organization_id=world.edition.organization_id,
                    edition_id=world.edition.id,
                )
                locked.set()
                assert release.wait(timeout=15)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_retirement_mutex)
        try:
            assert locked.wait(timeout=10)
            with pytest.raises(DatabaseError) as caught, transaction.atomic():
                model.objects.filter(id=target_id).update(id=F("id"))
            assert caught.value.__cause__.sqlstate == "40001"
        finally:
            release.set()
        holder.result(timeout=10)
    assert model.objects.filter(id=target_id).exists()


def test_programme_write_scope_waits_for_the_workforce_mutex() -> None:
    """The normal lock chain waits safely rather than using the raw-write fallback."""
    world = _active_call()
    started = Event()
    acquired = Event()

    def acquire_programme_scope() -> None:
        try:
            with transaction.atomic():
                started.set()
                lock_programme_edition_write_scope(
                    organization_id=world.edition.organization_id,
                    edition_id=world.edition.id,
                    department_ids=(world.department_id,),
                    actor_id=world.manager.id,
                )
                acquired.set()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            lock_edition_structure_mutex(
                organization_id=world.edition.organization_id,
                edition_id=world.edition.id,
            )
            writer = executor.submit(acquire_programme_scope)
            assert started.wait(timeout=10)
            assert not acquired.wait(timeout=0.2)
        writer.result(timeout=10)
    assert acquired.is_set()


@pytest.mark.parametrize("dependency", ["call", "import"])
def test_database_refuses_retirement_even_if_programme_preflight_misses_dependency(
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    """The SQL guard independently preserves ownership and rolls back structure."""
    world = _active_call()
    if dependency == "import":
        _stage(
            actor=world.manager,
            edition=world.edition,
            department_id=world.department_id,
            payload=_document([_call_item(world.now)]),
            now=world.now,
        )
        retire_programme_call(
            actor_id=world.manager.id,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            call_id=world.call_id,
            owner_department_id=world.department_id,
            expected_version=2,
            reason="Leave only unresolved staging as the retirement dependency.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=world.now,
            authorizer=_AUTHORIZER,
        )
    assert (
        programme_department_retirement_dependency_state(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            department_id=world.department_id,
        )
        is ProgrammeDepartmentDependencyState.BLOCKED
    )
    monkeypatch.setattr(
        "maru.workforce.structure_commands.programme_department_retirement_dependency_state",
        lambda **_kwargs: ProgrammeDepartmentDependencyState.CLEAR,
    )
    with pytest.raises(StructureDependencyConflictError):
        retire_department(
            actor=AccountFactory(is_staff=True, is_superuser=True),
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            department_id=world.department_id,
            expected_version=1,
            reason="Exercise the database ownership backstop independently.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert Department.objects.get(id=world.department_id).retired_at is None
