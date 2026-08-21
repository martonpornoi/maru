"""Derive collision-resistant CalVer metadata for a Maru release PR."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

Channel = Literal["candidate", "gold"]
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
APPLICATION_LICENSE_EXPRESSION = "Apache-2.0 AND MIT"
APPLICATION_LICENSE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")


@dataclass(frozen=True, slots=True)
class ReleaseMetadata:
    """Names and provenance derived for one immutable release attempt.

    Parameters
    ----------
    version : str
        Display CalVer in ``YYYY.MM.PR`` form.
    python_version : str
        PEP 440-compatible version without month padding.
    tag : str
        Git tag, including a candidate suffix when applicable.
    image_tag : str
        OCI tag corresponding exactly to the GitHub release.
    title : str
        Human-readable GitHub release title.
    channel : Channel
        Promotion channel selected by the maintainer.
    pull_request : int
        Merged release pull request number.
    commit : str
        Exact merge commit being certified.
    merged_at : str
        GitHub merge timestamp used as the calendar source.
    candidate_number : int | None
        Positive candidate sequence, or ``None`` for gold.

    Attributes
    ----------
    version : str
        Display CalVer in ``YYYY.MM.PR`` form.
    python_version : str
        PEP 440-compatible version without month padding.
    tag : str
        Git tag, including a candidate suffix when applicable.
    image_tag : str
        OCI tag corresponding exactly to the GitHub release.
    title : str
        Human-readable GitHub release title.
    channel : Channel
        Promotion channel selected by the maintainer.
    pull_request : int
        Merged release pull request number.
    commit : str
        Exact merge commit being certified.
    merged_at : str
        GitHub merge timestamp used as the calendar source.
    candidate_number : int | None
        Positive candidate sequence, or ``None`` for gold.
    """

    version: str
    python_version: str
    tag: str
    image_tag: str
    title: str
    channel: Channel
    pull_request: int
    commit: str
    merged_at: str
    candidate_number: int | None


def derive_release_metadata(
    *,
    pull_request: int,
    merged_at: str,
    commit: str,
    channel: Channel,
    candidate_number: int | None = None,
) -> ReleaseMetadata:
    """Derive release names from the merge month and pull request.

    Parameters
    ----------
    pull_request : int
        Positive GitHub pull request number.
    merged_at : str
        ISO 8601 merge time reported by GitHub.
    commit : str
        Forty-character lowercase Git commit hash.
    channel : Channel
        Candidate or immutable gold promotion.
    candidate_number : int | None, default=None
        Positive candidate sequence required for candidate releases.

    Returns
    -------
    ReleaseMetadata
        Validated CalVer, tag, image, and provenance fields.

    Raises
    ------
    ValueError
        If an identity, timestamp, hash, or channel invariant is invalid.
    """
    if pull_request < 1:
        raise ValueError("pull request number must be positive")
    if not SHA_PATTERN.fullmatch(commit):
        raise ValueError("commit must be a 40-character lowercase Git SHA")
    try:
        merged = datetime.fromisoformat(merged_at)
    except ValueError as error:
        raise ValueError("merged_at must be an ISO 8601 timestamp") from error
    if channel == "candidate":
        if candidate_number is None or candidate_number < 1:
            raise ValueError("candidate releases need a positive candidate number")
    elif channel == "gold":
        if candidate_number is not None:
            raise ValueError("gold releases cannot have a candidate number")
    else:
        raise ValueError(f"unsupported release channel: {channel}")

    version = f"{merged.year:04d}.{merged.month:02d}.{pull_request}"
    python_version = f"{merged.year}.{merged.month}.{pull_request}"
    suffix = f"-rc.{candidate_number}" if channel == "candidate" else ""
    tag = f"v{version}{suffix}"
    title_suffix = f" release candidate {candidate_number}" if suffix else ""
    return ReleaseMetadata(
        version=version,
        python_version=python_version,
        tag=tag,
        image_tag=f"{version}{suffix}",
        title=f"Maru {version}{title_suffix}",
        channel=channel,
        pull_request=pull_request,
        commit=commit,
        merged_at=merged_at,
        candidate_number=candidate_number,
    )


def write_release_files(metadata: ReleaseMetadata, output_directory: Path) -> None:
    """Write a deterministic release manifest and workflow outputs.

    Parameters
    ----------
    metadata : ReleaseMetadata
        Validated release identity and provenance.
    output_directory : Path
        Directory receiving ``release-manifest.json`` and ``github-output``.
    """
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / "release-manifest.json"
    manifest = asdict(metadata)
    manifest["application_license"] = {
        "expression": APPLICATION_LICENSE_EXPRESSION,
        "files": list(APPLICATION_LICENSE_FILES),
        "scope": "Maru source and bundled Staff Console runtime",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    output_lines = {
        "version": metadata.version,
        "python_version": metadata.python_version,
        "tag": metadata.tag,
        "image_tag": metadata.image_tag,
        "title": metadata.title,
        "prerelease": str(metadata.channel == "candidate").lower(),
    }
    (output_directory / "github-output").write_text(
        "".join(f"{name}={value}\n" for name, value in output_lines.items()),
        encoding="utf-8",
        newline="\n",
    )


def _argument_parser() -> argparse.ArgumentParser:
    """Build the release metadata command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for GitHub-provided release PR metadata.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--merged-at", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--channel", choices=("candidate", "gold"), required=True)
    parser.add_argument("--candidate-number", type=int)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Derive and persist release metadata for GitHub Actions.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Optional arguments; process arguments are used when omitted.

    Returns
    -------
    int
        Zero after validated artifacts have been written.
    """
    namespace = _argument_parser().parse_args(list(argv) if argv is not None else None)
    metadata = derive_release_metadata(
        pull_request=namespace.pull_request,
        merged_at=namespace.merged_at,
        commit=namespace.commit,
        channel=namespace.channel,
        candidate_number=namespace.candidate_number,
    )
    write_release_files(metadata, namespace.output_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
