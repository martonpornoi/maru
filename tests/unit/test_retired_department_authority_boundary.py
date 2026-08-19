from __future__ import annotations

from typing import TYPE_CHECKING

from maru.authorization import retired_targets

if TYPE_CHECKING:
    import pytest


def test_combined_writer_boundary_uses_canonical_structure_authority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        retired_targets,
        "lock_page_9_structure_writer_boundary",
        lambda: calls.append("structure"),
    )
    monkeypatch.setattr(
        retired_targets,
        "lock_authority_provenance_writer_boundary",
        lambda: calls.append("provenance"),
    )
    monkeypatch.setattr(
        retired_targets,
        "lock_retired_department_authority_writer",
        lambda: calls.append("retirement"),
    )

    retired_targets.lock_retired_department_authority_boundaries()

    assert calls == ["structure", "provenance", "retirement"]
