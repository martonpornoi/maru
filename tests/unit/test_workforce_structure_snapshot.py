from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from maru.workforce import structure_snapshot
from maru.workforce.structure_snapshot import (
    StructureSnapshotChangedError,
    StructureSnapshotRead,
    load_version_fenced_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def test_absent_to_present_probe_reloads_the_whole_snapshot_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    events: list[str] = []
    reads = iter(
        (
            StructureSnapshotRead(
                value=("organization-v0", "department-v0"),
                organization_id=organization_id,
                edition_id=edition_id,
                aggregate_version=0,
            ),
            StructureSnapshotRead(
                value=("organization-v1", "department-v1"),
                organization_id=organization_id,
                edition_id=edition_id,
                aggregate_version=1,
            ),
        )
    )
    current_versions = iter((1, 1))

    @contextmanager
    def snapshot(*, using: str = "default") -> Iterator[None]:
        events.append(f"enter:{using}")
        yield
        events.append("leave")

    def load() -> StructureSnapshotRead[tuple[str, str]]:
        events.append("load")
        return next(reads)

    def current_version(
        *, organization_id: UUID, edition_id: UUID, using: str = "default"
    ) -> int:
        del organization_id, edition_id, using
        events.append("probe")
        return next(current_versions)

    monkeypatch.setattr(
        structure_snapshot,
        "repeatable_read_only_snapshot",
        snapshot,
    )
    monkeypatch.setattr(
        structure_snapshot,
        "current_structure_version",
        current_version,
    )

    result = load_version_fenced_snapshot(load=load)

    assert result == ("organization-v1", "department-v1")
    assert events == [
        "enter:default",
        "load",
        "leave",
        "probe",
        "enter:default",
        "load",
        "leave",
        "probe",
    ]


def test_second_version_movement_fails_closed_after_exactly_two_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    loads = 0

    @contextmanager
    def snapshot(*, using: str = "default") -> Iterator[None]:
        del using
        yield

    def load() -> StructureSnapshotRead[str]:
        nonlocal loads
        loads += 1
        return StructureSnapshotRead(
            value=f"snapshot-{loads}",
            organization_id=organization_id,
            edition_id=edition_id,
            aggregate_version=loads,
        )

    versions = iter((2, 3))
    monkeypatch.setattr(
        structure_snapshot,
        "repeatable_read_only_snapshot",
        snapshot,
    )
    monkeypatch.setattr(
        structure_snapshot,
        "current_structure_version",
        lambda **_kwargs: next(versions),
    )

    with pytest.raises(StructureSnapshotChangedError):
        load_version_fenced_snapshot(load=load)

    assert loads == 2
