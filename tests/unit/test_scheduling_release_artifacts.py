import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from maru.scheduling import release_artifacts
from maru.scheduling.catalogs import MAX_OCCURRENCES
from maru.scheduling.release_artifacts import (
    CANONICAL_RELEASE_ARTIFACT,
    MAX_CANONICAL_RELEASE_BYTES,
    CanonicalReleaseArtifact,
    ReleaseArtifactInvalidError,
    ReleaseArtifactSelection,
    prepare_canonical_release_artifact,
    verify_canonical_release_artifact,
)


def _selection(number: int = 1) -> ReleaseArtifactSelection:
    return ReleaseArtifactSelection(
        UUID(int=number), UUID(int=10_000 + number), UUID(int=20_000 + number)
    )


def _inputs(**changes: object) -> dict[str, object]:
    return {
        "release_id": UUID(int=30_001),
        "approval_id": UUID(int=30_002),
        "candidate_revision_id": UUID(int=30_003),
        "source_snapshot_digest": "a" * 64,
        "selections": (_selection(),),
        **changes,
    }


def test_prepare_retains_only_exact_minimized_semantic_membership() -> None:
    artifact = prepare_canonical_release_artifact(**_inputs())
    document = json.loads(artifact.payload)
    assert document == {
        "contract": CANONICAL_RELEASE_ARTIFACT,
        "release_id": str(UUID(int=30_001)),
        "approval_id": str(UUID(int=30_002)),
        "candidate_revision_id": str(UUID(int=30_003)),
        "source_snapshot_digest": "a" * 64,
        "selections": [
            {
                "occurrence_id": str(UUID(int=1)),
                "placement_id": str(UUID(int=10_001)),
                "public_rendition_id": str(UUID(int=20_001)),
            }
        ],
    }
    assert artifact.byte_length == len(artifact.payload)
    assert artifact.sha256 == hashlib.sha256(artifact.payload).hexdigest()
    assert artifact.contract == CANONICAL_RELEASE_ARTIFACT
    verify_canonical_release_artifact(artifact, **_inputs())


def test_canonical_order_does_not_depend_on_query_input_order() -> None:
    rows = (_selection(1), _selection(2))
    first = prepare_canonical_release_artifact(**_inputs(selections=rows))
    reverse = prepare_canonical_release_artifact(**_inputs(selections=rows[::-1]))
    assert first == reverse
    verify_canonical_release_artifact(first, **_inputs(selections=rows[::-1]))


def test_same_public_copy_can_back_distinct_occurrences() -> None:
    first = _selection()
    second = replace(_selection(2), public_rendition_id=first.public_rendition_id)
    artifact = prepare_canonical_release_artifact(**_inputs(selections=(first, second)))
    assert len(json.loads(artifact.payload)["selections"]) == 2


def test_complete_maximum_selection_fits_mandatory_byte_bound() -> None:
    rows = tuple(_selection(number) for number in range(1, MAX_OCCURRENCES + 1))
    artifact = prepare_canonical_release_artifact(**_inputs(selections=rows))
    assert len(json.loads(artifact.payload)["selections"]) == MAX_OCCURRENCES
    assert artifact.byte_length < MAX_CANONICAL_RELEASE_BYTES
    verify_canonical_release_artifact(artifact, **_inputs(selections=rows))


@pytest.mark.parametrize(
    "field", ["release_id", "approval_id", "candidate_revision_id"]
)
@pytest.mark.parametrize("value", [None, False, "not-a-uuid", UUID(int=0)])
def test_invalid_envelope_identity_is_rejected(field, value) -> None:
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs(**{field: value}))


@pytest.mark.parametrize("digest", [None, False, "", "a" * 63, "a" * 65, "A" * 64])
def test_invalid_or_noncanonical_source_digest_is_rejected(digest) -> None:
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs(source_snapshot_digest=digest))


@pytest.mark.parametrize(
    "rows",
    [
        None,
        (),
        [_selection()],
        (None,),
        (_selection(), _selection()),
        tuple(_selection(number) for number in range(1, MAX_OCCURRENCES + 2)),
    ],
)
def test_absent_unbounded_or_duplicate_membership_is_rejected(rows) -> None:
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs(selections=rows))


@pytest.mark.parametrize(
    "field", ["occurrence_id", "placement_id", "public_rendition_id"]
)
@pytest.mark.parametrize("value", [None, False, "not-a-uuid", UUID(int=0)])
def test_invalid_selection_identity_is_rejected(field, value) -> None:
    selection = replace(_selection(), **{field: value})
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs(selections=(selection,)))


@pytest.mark.parametrize("field", ["occurrence_id", "placement_id"])
def test_duplicate_occurrence_or_placement_cannot_hide_behind_other_distinct_ids(
    field,
) -> None:
    rows = (
        _selection(),
        replace(_selection(2), **{field: getattr(_selection(), field)}),
    )
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs(selections=rows))


@pytest.mark.parametrize(
    "changes",
    [
        {"contract": "some-other-output@1"},
        {"payload": b"{}"},
        {"payload": "not bytes"},
        {"sha256": "f" * 64},
        {"sha256": None},
        {"byte_length": True},
        {"byte_length": 0},
        {"byte_length": MAX_CANONICAL_RELEASE_BYTES + 1},
    ],
)
def test_altered_envelope_or_bytes_fail_verification(changes) -> None:
    artifact = prepare_canonical_release_artifact(**_inputs())
    with pytest.raises(ReleaseArtifactInvalidError):
        verify_canonical_release_artifact(replace(artifact, **changes), **_inputs())


@pytest.mark.parametrize("artifact", [None, {}, b"{}"])
def test_missing_or_caller_shaped_artifact_is_not_a_verified_registry(artifact) -> None:
    with pytest.raises(ReleaseArtifactInvalidError):
        verify_canonical_release_artifact(artifact, **_inputs())


@pytest.mark.parametrize(
    "field",
    ["release_id", "approval_id", "candidate_revision_id", "source_snapshot_digest"],
)
def test_recomputed_checksum_does_not_authenticate_changed_semantics(field) -> None:
    artifact = prepare_canonical_release_artifact(**_inputs())
    document = json.loads(artifact.payload)
    document[field] = (
        "b" * 64 if field == "source_snapshot_digest" else str(UUID(int=99))
    )
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    tampered = CanonicalReleaseArtifact(
        artifact.contract, payload, hashlib.sha256(payload).hexdigest(), len(payload)
    )
    with pytest.raises(ReleaseArtifactInvalidError):
        verify_canonical_release_artifact(tampered, **_inputs())


def test_valid_artifact_for_another_membership_is_rejected() -> None:
    artifact = prepare_canonical_release_artifact(
        **_inputs(selections=(_selection(2),))
    )
    with pytest.raises(ReleaseArtifactInvalidError):
        verify_canonical_release_artifact(artifact, **_inputs())


def test_extra_payload_fields_cannot_be_smuggled_with_a_valid_checksum() -> None:
    artifact = prepare_canonical_release_artifact(**_inputs())
    document = json.loads(artifact.payload)
    document["private_reason"] = "synthetic forbidden field"
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    tampered = replace(
        artifact,
        payload=payload,
        byte_length=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    with pytest.raises(ReleaseArtifactInvalidError):
        verify_canonical_release_artifact(tampered, **_inputs())


def test_serializer_still_enforces_byte_bound_if_contract_grows(monkeypatch) -> None:
    monkeypatch.setattr(release_artifacts, "MAX_CANONICAL_RELEASE_BYTES", 1)
    with pytest.raises(ReleaseArtifactInvalidError):
        prepare_canonical_release_artifact(**_inputs())
