from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.release_metadata import derive_release_metadata, write_release_files

if TYPE_CHECKING:
    from pathlib import Path

COMMIT = "a" * 40


def test_gold_release_uses_full_year_month_and_pull_request() -> None:
    metadata = derive_release_metadata(
        pull_request=2,
        merged_at="2026-08-19T12:30:00Z",
        commit=COMMIT,
        channel="gold",
    )

    assert metadata.version == "2026.08.2"
    assert metadata.python_version == "2026.8.2"
    assert metadata.tag == "v2026.08.2"
    assert metadata.image_tag == "2026.08.2"
    assert metadata.title == "Maru 2026.08.2"


def test_candidate_release_has_one_explicit_sequence() -> None:
    metadata = derive_release_metadata(
        pull_request=42,
        merged_at="2027-01-02T00:00:00+00:00",
        commit=COMMIT,
        channel="candidate",
        candidate_number=3,
    )

    assert metadata.tag == "v2027.01.42-rc.3"
    assert metadata.image_tag == "2027.01.42-rc.3"
    assert metadata.candidate_number == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"pull_request": 0},
        {"commit": "short"},
        {"merged_at": "not-a-time"},
        {"channel": "candidate", "candidate_number": None},
        {"channel": "gold", "candidate_number": 1},
    ],
)
def test_invalid_release_identity_is_rejected(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "pull_request": 2,
        "merged_at": "2026-08-19T12:30:00Z",
        "commit": COMMIT,
        "channel": "gold",
        "candidate_number": None,
    }
    values.update(overrides)

    with pytest.raises(
        ValueError,
        match=r"pull request|commit|merged_at|candidate|gold",
    ):
        derive_release_metadata(**values)  # type: ignore[arg-type]


def test_release_files_are_deterministic_and_workflow_ready(tmp_path: Path) -> None:
    metadata = derive_release_metadata(
        pull_request=2,
        merged_at="2026-08-19T12:30:00Z",
        commit=COMMIT,
        channel="candidate",
        candidate_number=1,
    )

    write_release_files(metadata, tmp_path)

    manifest = json.loads(
        (tmp_path / "release-manifest.json").read_text(encoding="utf-8")
    )
    outputs = (tmp_path / "github-output").read_text(encoding="utf-8")
    assert manifest["tag"] == "v2026.08.2-rc.1"
    assert "prerelease=true\n" in outputs
    assert "python_version=2026.8.2\n" in outputs
