"""Validate GitHub release state against exact local release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ReleaseState = Literal["draft", "immutable"]
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def asset_digests(asset_paths: Sequence[Path]) -> dict[str, str]:
    """Calculate exact GitHub-style digests for release assets.

    Parameters
    ----------
    asset_paths : Sequence[Path]
        Local files that must appear on the GitHub release.

    Returns
    -------
    dict[str, str]
        Asset basenames mapped to ``sha256:<hex>`` digests.

    Raises
    ------
    ValueError
        If no asset is supplied, a path is not a file, or names collide.
    """
    if not asset_paths:
        raise ValueError("at least one release asset is required")

    digests: dict[str, str] = {}
    for path in asset_paths:
        if not path.is_file():
            raise ValueError(f"release asset is not a file: {path}")
        if path.name in digests:
            raise ValueError(f"duplicate release asset name: {path.name}")
        digests[path.name] = f"sha256:{_sha256(path)}"
    return digests


def verify_release_payload(
    payload: object,
    *,
    expected_tag: str,
    expected_commit: str,
    expected_prerelease: bool,
    expected_state: ReleaseState,
    expected_assets: Mapping[str, str],
) -> None:
    """Require a GitHub release payload to match the intended evidence.

    Parameters
    ----------
    payload : object
        Parsed response from GitHub's release-by-tag endpoint.
    expected_tag : str
        Exact immutable release tag.
    expected_commit : str
        Exact 40-character commit SHA selected for the release.
    expected_prerelease : bool
        Whether GitHub must classify the release as a prerelease.
    expected_state : ReleaseState
        ``draft`` before publication or ``immutable`` afterward.
    expected_assets : Mapping[str, str]
        Exact asset-name to SHA-256 digest mapping.

    Raises
    ------
    TypeError
        If the release or asset collection has the wrong JSON shape.
    ValueError
        If release identity, state, assets, or digests differ.
    """
    if not isinstance(payload, dict):
        raise TypeError("release response must be a JSON object")
    _validate_expected_inputs(
        expected_tag=expected_tag,
        expected_commit=expected_commit,
        expected_assets=expected_assets,
    )

    _require_equal(payload, "tag_name", expected_tag)
    _require_equal(payload, "target_commitish", expected_commit)
    _require_equal(payload, "prerelease", expected_prerelease)
    _require_equal(payload, "draft", expected_state == "draft")
    _require_equal(payload, "immutable", expected_state == "immutable")

    observed = _observed_asset_digests(payload.get("assets"))

    if observed.keys() != expected_assets.keys():
        missing = sorted(expected_assets.keys() - observed.keys())
        unexpected = sorted(observed.keys() - expected_assets.keys())
        raise ValueError(
            f"release asset set differs: missing={missing!r}; unexpected={unexpected!r}"
        )
    for name, expected_digest in expected_assets.items():
        if observed[name] != expected_digest:
            raise ValueError(
                f"release asset digest differs: {name}: "
                f"expected={expected_digest}; observed={observed[name]}"
            )


def _validate_expected_inputs(
    *,
    expected_tag: str,
    expected_commit: str,
    expected_assets: Mapping[str, str],
) -> None:
    """Validate the caller-provided release expectations.

    Parameters
    ----------
    expected_tag : str
        Required Git tag.
    expected_commit : str
        Required lowercase commit SHA.
    expected_assets : Mapping[str, str]
        Required asset names and GitHub-style digests.

    Raises
    ------
    ValueError
        If an expected identity or digest is malformed.
    """
    if not expected_tag:
        raise ValueError("expected release tag must not be empty")
    if SHA_PATTERN.fullmatch(expected_commit) is None:
        raise ValueError("expected commit must be a lowercase 40-character Git SHA")
    if not expected_assets:
        raise ValueError("expected release assets must not be empty")
    if any(
        SHA256_PATTERN.fullmatch(digest) is None for digest in expected_assets.values()
    ):
        raise ValueError("expected asset digests must use sha256:<hex>")


def _observed_asset_digests(assets: object) -> dict[str, str]:
    """Validate and collect assets from a GitHub release response.

    Parameters
    ----------
    assets : object
        Parsed ``assets`` field from a release response.

    Returns
    -------
    dict[str, str]
        Uploaded non-empty asset names and SHA-256 digests.

    Raises
    ------
    TypeError
        If the asset collection has the wrong JSON shape.
    ValueError
        If an asset is malformed, duplicated, empty, or not uploaded.
    """
    if not isinstance(assets, list):
        raise TypeError("release assets must be a JSON array")

    observed: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise TypeError("release asset entries must be JSON objects")
        name = asset.get("name")
        digest = asset.get("digest")
        if not isinstance(name, str) or not name:
            raise ValueError("release asset name must be a non-empty string")
        if name in observed:
            raise ValueError(f"duplicate remote release asset: {name}")
        if asset.get("state") != "uploaded":
            raise ValueError(f"release asset is not uploaded: {name}")
        size = asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError(f"release asset is empty: {name}")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"release asset has no valid SHA-256 digest: {name}")
        observed[name] = digest
    return observed


def _sha256(path: Path) -> str:
    """Calculate a file's SHA-256 digest.

    Parameters
    ----------
    path : Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_equal(payload: Mapping[str, object], field: str, expected: object) -> None:
    """Require one release response field to equal its expected value.

    Parameters
    ----------
    payload : Mapping[str, object]
        Parsed GitHub release response.
    field : str
        Response field to inspect.
    expected : object
        Required value.

    Raises
    ------
    ValueError
        If the response field differs.
    """
    observed = payload.get(field)
    if observed != expected:
        raise ValueError(
            f"release {field} differs: expected={expected!r}; observed={observed!r}"
        )


def _argument_parser() -> argparse.ArgumentParser:
    """Build the release-evidence command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for local assets and a GitHub release response.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--expected-prerelease",
        choices=("true", "false"),
        required=True,
    )
    parser.add_argument(
        "--expected-state",
        choices=("draft", "immutable"),
        required=True,
    )
    parser.add_argument(
        "--asset",
        action="append",
        dest="assets",
        required=True,
        type=Path,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate exact draft or immutable release evidence.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments; process arguments are used when omitted.

    Returns
    -------
    int
        Zero after every release invariant passes.
    """
    namespace = _argument_parser().parse_args(list(argv) if argv is not None else None)
    payload = json.loads(namespace.release_json.read_text(encoding="utf-8"))
    digests = asset_digests(namespace.assets)
    verify_release_payload(
        payload,
        expected_tag=namespace.expected_tag,
        expected_commit=namespace.expected_commit,
        expected_prerelease=namespace.expected_prerelease == "true",
        expected_state=namespace.expected_state,
        expected_assets=digests,
    )
    print(
        f"Release evidence valid: state={namespace.expected_state}; "
        f"assets={len(digests)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
