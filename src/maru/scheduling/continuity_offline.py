"""Preprovisioned offline verification; no Django setup, network or mutation relay."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from .continuity_known_state import (
    _MAX_KNOWN_STATE_BYTES,
    verify_continuity_with_known_state,
)
from .continuity_payload import decode_continuity_payload
from .continuity_presentation import render_offline_continuity_html
from .continuity_protocol import (
    MAX_CONTINUITY_PACKAGE_BYTES,
    MAX_CONTINUITY_TRUST_KEYS,
    ContinuityInvalidError,
    ContinuityScope,
    ContinuityTrustKey,
    _base64,
    _date,
    _json,
    _scope_document,
    _uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

TRUST_POLICY_CONTRACT = "scheduling.programme-continuity-trust@1"
MAX_TRUST_POLICY_BYTES = 32768
_PUBLIC_KEY_BYTES = 32
_FILE_MODE = 0o600
_DISTINCT_PATH_COUNT = 5


def _read(path: Path, maximum: int) -> bytes:
    if not path.is_file():
        raise ContinuityInvalidError
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ContinuityInvalidError
    return data


def decode_continuity_trust_policy(data: bytes) -> tuple[ContinuityTrustKey, ...]:
    """Read an independently provisioned public-key policy, never one inside the pack.

    Parameters
    ----------
    data : bytes
        Closed canonical JSON obtained through the authenticated pre-outage procedure.

    Returns
    -------
    tuple[ContinuityTrustKey, ...]
        Bounded public trust records; full validity and ambiguity checks run on verify.

    Raises
    ------
    ContinuityInvalidError
        If structure, identifiers, encoding or count is malformed or over-bound.

    Notes
    -----
    Reading this file proves no provenance. Protected operator provisioning is a
    prerequisite; the tool never downloads a key URL or trusts a key inside a pack.
    """
    document = _json(
        data, frozenset({"contract", "keys"}), maximum=MAX_TRUST_POLICY_BYTES
    )
    records = document["keys"]
    if (
        document["contract"] != TRUST_POLICY_CONTRACT
        or type(records) is not list
        or not 1 <= len(records) <= MAX_CONTINUITY_TRUST_KEYS
    ):
        raise ContinuityInvalidError
    keys = []
    for record in records:
        if type(record) is not dict or record.keys() != {
            "organization_id",
            "edition_id",
            "key_id",
            "public_key_b64",
            "not_before",
            "not_after",
        }:
            raise ContinuityInvalidError
        organization_id, edition_id = (
            _uuid(record["organization_id"]),
            _uuid(record["edition_id"]),
        )
        if (
            organization_id is None
            or edition_id is None
            or type(record["key_id"]) is not str
        ):
            raise ContinuityInvalidError
        keys.append(
            ContinuityTrustKey(
                organization_id,
                edition_id,
                record["key_id"],
                _base64(record["public_key_b64"], maximum=_PUBLIC_KEY_BYTES),
                _date(record["not_before"]),
                _date(record["not_after"]),
            )
        )
    return tuple(keys)


def _save(path: Path, data: bytes, *, replace_existing: bool) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".maru-continuity-", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            temporary.chmod(_FILE_MODE)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_existing:
            temporary.replace(path)
        else:
            # Publishing a complete file by hard link is atomic and never overwrites
            # an existing destination. Unsupported filesystems fail without output.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_continuity_files(
    *,
    package_path: Path,
    trust_path: Path,
    known_state_path: Path,
    output_path: Path,
    expected_scope: ContinuityScope,
    now: datetime,
    initialize: bool = False,
) -> None:
    """Verify, persist source history, then publish one complete historical HTML copy.

    Parameters
    ----------
    package_path : Path
        Untrusted bounded snapshot file, never executable or compressed content.
    trust_path : Path
        Independently provisioned protected public-key policy.
    known_state_path : Path
        Persistent protected state for this exact audience/person/purpose.
    output_path : Path
        New HTML filename in controlled storage; never overwrite another file.
    expected_scope : ContinuityScope
        Purpose from independent provisioning, not the snapshot's own asserted scope.
    now : datetime
        Actual aware verification clock; CLI users cannot override it with a flag.
    initialize : bool, default=False
        Connected initialization only; existing or corrupt history is not reset.

    Raises
    ------
    ContinuityInvalidError
        If paths collide, history is missing, output exists or initialization conflicts.

    Notes
    -----
    Signature, scope, age and parsing errors prevent normal content. Filesystem
    errors propagate; cleanup can fail after a complete output was published, so
    a failed invocation must not be treated as permission to use any output file.
    A purpose-specific exclusive lock prevents cooperating verifier races.
    Save verified metadata before decoding/rendering: even malformed newer signed
    payload cannot license an older fallback. A crash may leave a lock for accountable
    operator recovery; never automatically erase a stale lock or known-state record.
    Filesystem/clock custody, encrypted storage and paper disposal remain operational
    prerequisites. No remote change, copied-file erasure or filesystem rollback can
    be inferred from this local check. Existing HTML is not a live verification app.
    """
    _scope_document(expected_scope)
    package_path, trust_path, known_state_path, output_path = (
        path.resolve()
        for path in (package_path, trust_path, known_state_path, output_path)
    )
    lock_path = known_state_path.with_name(known_state_path.name + ".lock")
    if (
        len({package_path, trust_path, known_state_path, output_path, lock_path})
        != _DISTINCT_PATH_COUNT
        or output_path.exists()
        or type(initialize) is not bool
    ):
        raise ContinuityInvalidError
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
    try:
        os.close(descriptor)
        known_exists = known_state_path.exists()
        if initialize == known_exists:
            raise ContinuityInvalidError
        trust = decode_continuity_trust_policy(
            _read(trust_path, MAX_TRUST_POLICY_BYTES)
        )
        verified, known = verify_continuity_with_known_state(
            _read(package_path, MAX_CONTINUITY_PACKAGE_BYTES),
            expected_scope=expected_scope,
            trust=trust,
            now=now,
            known_state=_read(known_state_path, _MAX_KNOWN_STATE_BYTES)
            if known_exists
            else None,
            initialize=initialize,
        )
        _save(known_state_path, known, replace_existing=not initialize)
        projection = decode_continuity_payload(
            verified.payload, manifest=verified.manifest
        )
        output = render_offline_continuity_html(
            projection, at=now, expires_at=verified.manifest.expires_at
        )
        _save(output_path, output, replace_existing=False)
    finally:
        lock_path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded preprovisioned offline verifier without Django or network access.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Explicit command-line arguments for tests, or the real process arguments.

    Returns
    -------
    int
        Zero for a complete historical copy; two for failed verification or local I/O.

    Notes
    -----
    Argument-parser usage errors exit before file reads. Failure text never echoes
    file content, keys, private instructions or exception locals. No clock override,
    automatic key download, history reset or writable offline operation is offered.
    """
    parser = argparse.ArgumentParser(
        description="Verify a preprovisioned read-only Programme continuity pack."
    )
    for name in ("package", "trust", "known-state", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--organization", type=UUID, required=True)
    parser.add_argument("--edition", type=UUID, required=True)
    parser.add_argument(
        "--audience",
        choices=("public", "exact_person", "private_operator"),
        required=True,
    )
    parser.add_argument("--actor", type=UUID)
    parser.add_argument(
        "--kind",
        choices=("public", "personal", "room", "department", "edition"),
        required=True,
    )
    parser.add_argument("--target", type=UUID)
    parser.add_argument(
        "--layers",
        nargs="*",
        choices=("technical", "accessibility", "media", "staffing"),
        default=[],
    )
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Connected initialization only; never reset lost history this way.",
    )
    args = parser.parse_args(argv)
    try:
        scope = ContinuityScope(
            args.organization,
            args.edition,
            args.audience,
            args.actor,
            args.kind,
            args.target,
            tuple(sorted(args.layers)),
        )
        verify_continuity_files(
            package_path=args.package,
            trust_path=args.trust,
            known_state_path=args.known_state,
            output_path=args.output,
            expected_scope=scope,
            now=datetime.now(UTC),
            initialize=args.initialize,
        )
    except (ValueError, OSError):
        sys.stderr.write(
            "Continuity verification failed. Do not reuse an older copy. "
            "Preserve known state and obtain fresh authorized instructions or "
            "accountable trust/clock/storage recovery.\n",
        )
        return 2
    sys.stdout.write(
        "Verified historical HTML saved. This copy is not a live verifier. "
        "Keep its source/expiry warnings and dispose of replaced or expired copies.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
