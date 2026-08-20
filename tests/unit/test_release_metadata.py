from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.release_metadata import derive_release_metadata, write_release_files
from scripts.verify_release_evidence import (
    ReleaseState,
    asset_digests,
    verify_release_payload,
)

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


def _release_payload(
    *,
    assets: dict[str, str],
    draft: bool,
    immutable: bool,
) -> dict[str, object]:
    return {
        "tag_name": "v2026.08.2-rc.1",
        "target_commitish": COMMIT,
        "draft": draft,
        "prerelease": True,
        "immutable": immutable,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": 42,
                "digest": digest,
            }
            for name, digest in assets.items()
        ],
    }


@pytest.mark.parametrize(
    ("state", "draft", "immutable"),
    [("draft", True, False), ("immutable", False, True)],
)
def test_release_evidence_accepts_exact_draft_and_immutable_states(
    tmp_path: Path,
    state: ReleaseState,
    draft: bool,
    immutable: bool,
) -> None:
    asset = tmp_path / "release-manifest.json"
    asset.write_text('{"version": "2026.08.2"}\n', encoding="utf-8")
    digests = asset_digests([asset])

    verify_release_payload(
        _release_payload(assets=digests, draft=draft, immutable=immutable),
        expected_tag="v2026.08.2-rc.1",
        expected_commit=COMMIT,
        expected_prerelease=True,
        expected_state=state,
        expected_assets=digests,
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("target_commitish", "b" * 40, "target_commitish differs"),
        ("draft", False, "draft differs"),
        ("immutable", True, "immutable differs"),
        ("prerelease", False, "prerelease differs"),
    ],
)
def test_release_evidence_rejects_identity_and_state_drift(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    asset = tmp_path / "release-manifest.json"
    asset.write_text("evidence\n", encoding="utf-8")
    digests = asset_digests([asset])
    payload = _release_payload(assets=digests, draft=True, immutable=False)
    payload[field] = value

    with pytest.raises(ValueError, match=match):
        verify_release_payload(
            payload,
            expected_tag="v2026.08.2-rc.1",
            expected_commit=COMMIT,
            expected_prerelease=True,
            expected_state="draft",
            expected_assets=digests,
        )


def test_release_evidence_rejects_missing_unexpected_and_changed_assets(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "release-manifest.json"
    checksums = tmp_path / "SHA256SUMS"
    manifest.write_text("manifest\n", encoding="utf-8")
    checksums.write_text("checksums\n", encoding="utf-8")
    digests = asset_digests([manifest, checksums])
    payload = _release_payload(assets=digests, draft=True, immutable=False)
    assets = payload["assets"]
    assert isinstance(assets, list)
    assets.pop()
    assets.append(
        {
            "name": "unexpected.txt",
            "state": "uploaded",
            "size": 1,
            "digest": f"sha256:{'f' * 64}",
        }
    )

    with pytest.raises(ValueError, match=r"missing=.*SHA256SUMS.*unexpected"):
        verify_release_payload(
            payload,
            expected_tag="v2026.08.2-rc.1",
            expected_commit=COMMIT,
            expected_prerelease=True,
            expected_state="draft",
            expected_assets=digests,
        )

    changed_payload = _release_payload(assets=digests, draft=True, immutable=False)
    changed_assets = changed_payload["assets"]
    assert isinstance(changed_assets, list)
    changed_assets[0]["digest"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValueError, match="asset digest differs"):
        verify_release_payload(
            changed_payload,
            expected_tag="v2026.08.2-rc.1",
            expected_commit=COMMIT,
            expected_prerelease=True,
            expected_state="draft",
            expected_assets=digests,
        )
