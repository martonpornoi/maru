"""Closed mandatory canonical release artifact, without ongoing serving authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

from .catalogs import MAX_OCCURRENCES

CANONICAL_RELEASE_ARTIFACT: Final = "programme.release.canonical@1"
MAX_CANONICAL_RELEASE_BYTES: Final = 2 * 1024 * 1024
_SHA256_HEX_LENGTH: Final = 64


class ReleaseArtifactInvalidError(ValidationError):
    """Reject incomplete or altered canonical artifact evidence."""

    def __init__(self) -> None:
        """Initialize one stable, content-free preparation failure."""
        super().__init__(
            "Exact canonical release artifact evidence is required.",
            code="scheduling_release_artifact_invalid",
        )


@dataclass(frozen=True, slots=True)
class ReleaseArtifactSelection:
    """Exact immutable placement and approved-copy selection for one occurrence.

    Attributes
    ----------
    occurrence_id
        Same-edition stable occurrence authenticated by Scheduling's composer.
    placement_id
        Exact immutable placement, including its time/day/room/presence references.
    public_rendition_id
        Exact approved Programme copy, never latest-copy discovery at render time.
    """

    occurrence_id: UUID
    placement_id: UUID
    public_rendition_id: UUID


@dataclass(frozen=True, slots=True)
class CanonicalReleaseArtifact:
    """Prepared internal bytes whose integrity does not grant disclosure authority.

    Attributes
    ----------
    contract
        Exactly the one code-owned mandatory artifact contract.
    payload
        Canonical UTF-8 JSON containing identifiers and exact source digest only.
    sha256
        Lowercase SHA-256 of those exact bytes.
    byte_length
        Exact byte count, independently bounded during verification.
    """

    contract: str
    payload: bytes
    sha256: str
    byte_length: int


def _selections(
    selections: tuple[ReleaseArtifactSelection, ...],
) -> list[dict[str, str]]:
    if type(selections) is not tuple or not 1 <= len(selections) <= MAX_OCCURRENCES:
        raise ReleaseArtifactInvalidError
    if any(
        type(row) is not ReleaseArtifactSelection
        or any(
            type(identifier) is not UUID or identifier.int == 0
            for identifier in (
                row.occurrence_id,
                row.placement_id,
                row.public_rendition_id,
            )
        )
        for row in selections
    ):
        raise ReleaseArtifactInvalidError
    if len({row.occurrence_id for row in selections}) != len(selections) or len(
        {row.placement_id for row in selections}
    ) != len(selections):
        raise ReleaseArtifactInvalidError
    return [
        {
            "occurrence_id": str(row.occurrence_id),
            "placement_id": str(row.placement_id),
            "public_rendition_id": str(row.public_rendition_id),
        }
        for row in sorted(selections, key=lambda row: str(row.occurrence_id))
    ]


def prepare_canonical_release_artifact(
    *,
    release_id: UUID,
    approval_id: UUID,
    candidate_revision_id: UUID,
    source_snapshot_digest: str,
    selections: tuple[ReleaseArtifactSelection, ...],
) -> CanonicalReleaseArtifact:
    """Prepare the mandatory artifact from owner-authenticated exact selections.

    Parameters
    ----------
    release_id : UUID
        Reserved new release identity in the publication transaction.
    approval_id : UUID
        Exact retained independent approval, authenticated by the command.
    candidate_revision_id : UUID
        Exact immutable candidate manifest, not a mutable candidate head.
    source_snapshot_digest : str
        Complete trusted source fingerprint repeated under publication locks.
    selections : tuple[ReleaseArtifactSelection, ...]
        Complete nonempty bounded occurrence/placement/copy selection.

    Returns
    -------
    CanonicalReleaseArtifact
        Deterministic minimized internal bytes and their checksum/length.

    Raises
    ------
    ReleaseArtifactInvalidError
        If identity, digest, complete selection shape or byte bounds are invalid.

    Notes
    -----
    This pure serializer authenticates no owner, tenant, approval or permission.
    Publication must obtain all inputs itself. The artifact has no host account,
    private source text, reason, calendar or user-supplied URL. Role-specific
    outputs must resolve these exact retained references through current owner
    disclosure and governing invalidation, never serve this internal manifest
    as an authorization token or rediscover a newer copy silently.
    """
    if (
        any(
            type(identifier) is not UUID or identifier.int == 0
            for identifier in (release_id, approval_id, candidate_revision_id)
        )
        or type(source_snapshot_digest) is not str
        or len(source_snapshot_digest) != _SHA256_HEX_LENGTH
        or any(
            character not in "0123456789abcdef" for character in source_snapshot_digest
        )
    ):
        raise ReleaseArtifactInvalidError
    payload = json.dumps(
        {
            "contract": CANONICAL_RELEASE_ARTIFACT,
            "release_id": str(release_id),
            "approval_id": str(approval_id),
            "candidate_revision_id": str(candidate_revision_id),
            "source_snapshot_digest": source_snapshot_digest,
            "selections": _selections(selections),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_CANONICAL_RELEASE_BYTES:
        raise ReleaseArtifactInvalidError
    return CanonicalReleaseArtifact(
        CANONICAL_RELEASE_ARTIFACT,
        payload,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )


def verify_canonical_release_artifact(
    artifact: CanonicalReleaseArtifact,
    *,
    release_id: UUID,
    approval_id: UUID,
    candidate_revision_id: UUID,
    source_snapshot_digest: str,
    selections: tuple[ReleaseArtifactSelection, ...],
) -> None:
    """Require exact semantic bytes, not merely an internally consistent checksum.

    Parameters
    ----------
    artifact : CanonicalReleaseArtifact
        Prepared or retained mandatory artifact to verify before use.
    release_id : UUID
        Independently obtained exact release identity.
    approval_id : UUID
        Independently obtained retained approval identity.
    candidate_revision_id : UUID
        Independently obtained exact immutable candidate identity.
    source_snapshot_digest : str
        Complete expected owner-authenticated source fingerprint.
    selections : tuple[ReleaseArtifactSelection, ...]
        Complete independently resolved exact immutable membership.

    Raises
    ------
    ReleaseArtifactInvalidError
        If shape, length, checksum or exact semantic membership differs.

    Notes
    -----
    Preparation validation propagates unchanged. A matching checksum alone is
    insufficient: altered bytes with a recomputed checksum still fail comparison
    with the command's independently authenticated release selection.
    """
    if (
        type(artifact) is not CanonicalReleaseArtifact
        or type(artifact.payload) is not bytes
        or type(artifact.byte_length) is not int
        or not 0 < artifact.byte_length <= MAX_CANONICAL_RELEASE_BYTES
        or len(artifact.payload) != artifact.byte_length
    ):
        raise ReleaseArtifactInvalidError
    expected = prepare_canonical_release_artifact(
        release_id=release_id,
        approval_id=approval_id,
        candidate_revision_id=candidate_revision_id,
        source_snapshot_digest=source_snapshot_digest,
        selections=selections,
    )
    if artifact != expected:
        raise ReleaseArtifactInvalidError
