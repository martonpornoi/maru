from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from scripts import verify_release_consumer as verifier

if TYPE_CHECKING:
    from collections.abc import Sequence


REPOSITORY = "martonpornoi/maru"
TAG = "v2026.08.27-rc.1"
SOURCE_COMMIT = "a" * 40
IMAGE = "ghcr.io/martonpornoi/maru:2026.08.27-rc.1"
IMAGE_DIGEST = f"sha256:{'b' * 64}"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _expectations(download_directory: Path) -> verifier.ConsumerExpectations:
    return verifier.ConsumerExpectations.from_inputs(
        repository=REPOSITORY,
        tag=TAG,
        source_commit=SOURCE_COMMIT,
        image=IMAGE,
        image_digest=IMAGE_DIGEST,
        download_directory=download_directory,
    )


def _manifest_payload(
    expectations: verifier.ConsumerExpectations,
) -> dict[str, object]:
    identity = expectations.identity
    return {
        "application_license": {
            "expression": "Apache-2.0 AND MIT",
            "files": ["LICENSE", "THIRD_PARTY_NOTICES.md"],
            "scope": "Maru source and bundled Staff Console runtime",
        },
        "candidate_number": identity.candidate_number,
        "channel": identity.channel,
        "commit": expectations.source_commit,
        "image": expectations.image,
        "image_digest": expectations.image_digest,
        "image_tag": identity.image_tag,
        "merged_at": "2026-08-27T12:30:00+00:00",
        "pull_request": identity.pull_request,
        "python_version": identity.python_version,
        "tag": expectations.tag,
        "title": identity.title,
        "version": identity.version,
    }


def _release_files(
    expectations: verifier.ConsumerExpectations,
) -> dict[str, bytes]:
    payloads = {
        "LICENSE": b"license\n",
        "THIRD_PARTY_NOTICES.md": b"notices\n",
        f"maru-docs-{expectations.identity.version}.tar.gz": b"docs archive\n",
        "openapi.yaml": b"openapi: 3.1.0\n",
        "pnpm-lock.yaml": b"lockfileVersion: 9\n",
        "release-manifest.json": (
            json.dumps(_manifest_payload(expectations), sort_keys=True) + "\n"
        ).encode(),
        "uv.lock": b"version = 1\n",
    }
    checksums = "".join(
        f"{hashlib.sha256(content).hexdigest()}  release-assets/{name}\n"
        for name, content in sorted(payloads.items())
    )
    payloads[verifier.CHECKSUMS_NAME] = checksums.encode()
    return payloads


def _release_payload(
    expectations: verifier.ConsumerExpectations,
    files: dict[str, bytes],
) -> dict[str, object]:
    return {
        "tag_name": expectations.tag,
        "target_commitish": expectations.source_commit,
        "draft": False,
        "immutable": True,
        "prerelease": expectations.identity.prerelease,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(content),
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
            for name, content in sorted(files.items())
        ],
    }


def _pull_request_payload(
    expectations: verifier.ConsumerExpectations,
) -> dict[str, object]:
    return {
        "baseRefName": "main",
        "mergeCommit": {"oid": expectations.source_commit},
        "mergedAt": "2026-08-27T12:30:00Z",
        "number": expectations.identity.pull_request,
        "state": "MERGED",
        "url": (
            f"https://github.com/{expectations.repository}/pull/"
            f"{expectations.identity.pull_request}"
        ),
    }


def _provenance_payload(
    expectations: verifier.ConsumerExpectations,
) -> list[dict[str, object]]:
    return [
        {
            "verificationResult": {
                "signature": {
                    "certificate": {
                        "subjectAlternativeName": (
                            "https://github.com/"
                            f"{expectations.repository}/{verifier.RELEASE_WORKFLOW}"
                            f"@{verifier.MAIN_REF}"
                        ),
                        "githubWorkflowRepository": expectations.repository,
                        "githubWorkflowRef": verifier.MAIN_REF,
                        "githubWorkflowSHA": expectations.source_commit,
                        "runnerEnvironment": "github-hosted",
                        "sourceRepositoryURI": (
                            f"https://github.com/{expectations.repository}"
                        ),
                        "sourceRepositoryDigest": expectations.source_commit,
                        "sourceRepositoryRef": verifier.MAIN_REF,
                    }
                },
                "verifiedIdentity": {"runnerEnvironment": "github-hosted"},
                "verifiedTimestamps": [{"type": "rekor"}],
                "statement": {
                    "predicateType": verifier.SLSA_PREDICATE,
                    "subject": [
                        {
                            "name": expectations.image_name,
                            "digest": {
                                "sha256": expectations.image_digest.removeprefix(
                                    "sha256:"
                                )
                            },
                        }
                    ],
                },
            }
        }
    ]


class _QueuedRunner(verifier.CommandRunner):
    def __init__(self, outputs: Sequence[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int = verifier.COMMAND_TIMEOUT_SECONDS,
    ) -> verifier.CommandResult:
        self.calls.append((tuple(arguments), stage, timeout_seconds))
        if not self.outputs:
            raise AssertionError(f"unexpected command: {arguments!r}")
        return verifier.CommandResult(0, self.outputs.pop(0), "")


class _EndToEndRunner(verifier.CommandRunner):
    def __init__(self, expectations: verifier.ConsumerExpectations) -> None:
        self.expectations = expectations
        self.files = _release_files(expectations)
        self.release = _release_payload(expectations, self.files)
        self.pull_request = _pull_request_payload(expectations)
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    def run(  # noqa: PLR0911 - explicit fake command dispatcher
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int = verifier.COMMAND_TIMEOUT_SECONDS,
    ) -> verifier.CommandResult:
        argv = tuple(arguments)
        self.calls.append((argv, stage, timeout_seconds))
        if argv == ("gh", "--version"):
            return verifier.CommandResult(0, "gh version 2.96.0\n", "")
        if argv in {
            ("gh", "auth", "status", "--active", "--hostname", "github.com"),
            ("git", "--version"),
            ("docker", "buildx", "imagetools", "inspect", "--help"),
        }:
            return verifier.CommandResult(0, "available\n", "")
        release_endpoint = (
            f"repos/{self.expectations.repository}/releases/tags/"
            f"{self.expectations.tag}"
        )
        release_api_command = (
            "gh",
            "api",
            "--hostname",
            verifier.GITHUB_HOST,
            "--method",
            "GET",
            release_endpoint,
            "--header",
            f"X-GitHub-Api-Version: {verifier.RELEASE_API_VERSION}",
        )
        if argv == release_api_command:
            return verifier.CommandResult(0, json.dumps(self.release), "")
        pull_request_command = (
            "gh",
            "pr",
            "view",
            str(self.expectations.identity.pull_request),
            "--repo",
            self.expectations.github_repository,
            "--json",
            "number,state,mergedAt,mergeCommit,baseRefName,url",
        )
        if argv == pull_request_command:
            return verifier.CommandResult(0, json.dumps(self.pull_request), "")
        if argv == (
            "gh",
            "release",
            "verify",
            self.expectations.tag,
            "--repo",
            self.expectations.github_repository,
            "--format",
            "json",
        ):
            return verifier.CommandResult(0, '{"verified": true}\n', "")
        if argv == (
            "gh",
            "release",
            "download",
            self.expectations.tag,
            "--repo",
            self.expectations.github_repository,
            "--dir",
            str(self.expectations.download_directory),
        ):
            self.expectations.download_directory.mkdir(exist_ok=True)
            for name, content in self.files.items():
                (self.expectations.download_directory / name).write_bytes(content)
            return verifier.CommandResult(0, "", "")
        if (
            argv[:4]
            == (
                "gh",
                "release",
                "verify-asset",
                self.expectations.tag,
            )
            and len(argv) == 9
            and argv[5:]
            == (
                "--repo",
                self.expectations.github_repository,
                "--format",
                "json",
            )
            and Path(argv[4]).parent == self.expectations.download_directory
            and Path(argv[4]).name in self.expectations.expected_assets
        ):
            return verifier.CommandResult(0, '{"verified": true}\n', "")
        if argv[:2] == ("git", "ls-remote"):
            ref = f"refs/tags/{self.expectations.tag}"
            return verifier.CommandResult(
                0,
                f"{self.expectations.source_commit}\t{ref}\n",
                "",
            )
        if "{{json .Manifest}}" in argv:
            return verifier.CommandResult(
                0,
                json.dumps({"digest": self.expectations.image_digest}),
                "",
            )
        if "{{json .SBOM.SPDX}}" in argv:
            return verifier.CommandResult(
                0,
                json.dumps(
                    {
                        "spdxVersion": "SPDX-2.3",
                        "SPDXID": "SPDXRef-DOCUMENT",
                        "packages": [
                            {"name": "maru", "SPDXID": "SPDXRef-Package-maru"},
                            {
                                "name": "django",
                                "SPDXID": "SPDXRef-Package-django",
                            },
                        ],
                        "creationInfo": {
                            "creators": [
                                "Organization: Anchore, Inc",
                                "Tool: syft-1.51.0",
                                "Tool: buildkit-0.32.2",
                            ]
                        },
                    }
                ),
                "",
            )
        if argv[:3] == ("gh", "attestation", "verify"):
            return verifier.CommandResult(
                0,
                json.dumps(_provenance_payload(self.expectations)),
                "",
            )
        raise AssertionError(f"unexpected command: {argv!r}")


class _MutableTagDriftRunner(_EndToEndRunner):
    def __init__(self, expectations: verifier.ConsumerExpectations) -> None:
        super().__init__(expectations)
        self.provenance_seen = False

    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int = verifier.COMMAND_TIMEOUT_SECONDS,
    ) -> verifier.CommandResult:
        argv = tuple(arguments)
        if (
            self.provenance_seen
            and "{{json .Manifest}}" in argv
            and self.expectations.image in argv
        ):
            self.calls.append((argv, stage, timeout_seconds))
            return verifier.CommandResult(
                0,
                json.dumps({"digest": f"sha256:{'c' * 64}"}),
                "",
            )
        result = super().run(
            arguments,
            stage=stage,
            timeout_seconds=timeout_seconds,
        )
        if argv[:3] == ("gh", "attestation", "verify"):
            self.provenance_seen = True
        return result


class _LocalAssetDriftRunner(_EndToEndRunner):
    def run(
        self,
        arguments: Sequence[str],
        *,
        stage: str,
        timeout_seconds: int = verifier.COMMAND_TIMEOUT_SECONDS,
    ) -> verifier.CommandResult:
        argv = tuple(arguments)
        result = super().run(
            arguments,
            stage=stage,
            timeout_seconds=timeout_seconds,
        )
        if argv[:3] == ("gh", "attestation", "verify"):
            (self.expectations.download_directory / "LICENSE").write_text(
                "changed during verification\n",
                encoding="utf-8",
            )
        return result


def test_complete_consumer_verification_uses_every_fail_closed_stage(
    tmp_path: Path,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    runner = _EndToEndRunner(expectations)

    summary = verifier.verify_release_consumer(expectations, runner=runner)

    assert summary.assets == 8
    assert summary.checksum_payloads == 7
    assert summary.sbom_packages == 2
    assert summary.sbom_generators == (
        "Tool: syft-1.51.0",
        "Tool: buildkit-0.32.2",
    )
    assert summary.provenance_attestations == 1
    commands = [call[0] for call in runner.calls]
    release_api_command = (
        "gh",
        "api",
        "--hostname",
        verifier.GITHUB_HOST,
        "--method",
        "GET",
        f"repos/{expectations.repository}/releases/tags/{expectations.tag}",
        "--header",
        f"X-GitHub-Api-Version: {verifier.RELEASE_API_VERSION}",
    )
    assert commands.count(release_api_command) == 2
    assert (
        "gh",
        "pr",
        "view",
        str(expectations.identity.pull_request),
        "--repo",
        expectations.github_repository,
        "--json",
        "number,state,mergedAt,mergeCommit,baseRefName,url",
    ) in commands
    assert (
        "gh",
        "release",
        "download",
        expectations.tag,
        "--repo",
        expectations.github_repository,
        "--dir",
        str(expectations.download_directory),
    ) in commands
    asset_commands = [
        command
        for command in commands
        if command[:3] == ("gh", "release", "verify-asset")
    ]
    assert len(asset_commands) == 8
    assert Path(asset_commands[0][4]).name == verifier.CHECKSUMS_NAME
    assert {Path(command[4]).name for command in asset_commands} == (
        expectations.expected_assets
    )

    provenance = next(
        command
        for command in commands
        if command[:3] == ("gh", "attestation", "verify")
    )
    assert provenance[3] == f"oci://{expectations.immutable_image}"
    assert (
        provenance[provenance.index("--hostname")],
        provenance[provenance.index("--hostname") + 1],
    ) == ("--hostname", verifier.GITHUB_HOST)
    assert (
        provenance[provenance.index("--source-ref")],
        provenance[provenance.index("--source-ref") + 1],
    ) == ("--source-ref", verifier.MAIN_REF)
    assert (
        provenance[provenance.index("--source-digest")],
        provenance[provenance.index("--source-digest") + 1],
    ) == ("--source-digest", SOURCE_COMMIT)
    assert "--deny-self-hosted-runners" in provenance
    assert provenance[provenance.index("--signer-workflow") + 1] == (
        f"{expectations.github_repository}/{verifier.RELEASE_WORKFLOW}"
    )
    assert not any("--show-token" in command for command in commands)
    assert all(
        isinstance(argument, str) for command in commands for argument in command
    )


def test_complete_verification_rechecks_mutable_image_after_long_stages(
    tmp_path: Path,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")

    with pytest.raises(verifier.ConsumerVerificationError, match="another digest"):
        verifier.verify_release_consumer(
            expectations,
            runner=_MutableTagDriftRunner(expectations),
        )


def test_complete_verification_rechecks_local_assets_before_success(
    tmp_path: Path,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="downloaded assets changed",
    ):
        verifier.verify_release_consumer(
            expectations,
            runner=_LocalAssetDriftRunner(expectations),
        )


def test_release_runbook_exposes_the_complete_consumer_contract() -> None:
    runbook = (REPOSITORY_ROOT / "docs/operations/release-process.md").read_text(
        encoding="utf-8"
    )
    section = runbook.split("## Consumer verification", maxsplit=1)[1]
    normalized = " ".join(section.split())

    for literal in (
        "GitHub CLI `2.96.0` or later",
        "Python 3.12 through 3.14",
        "python --version",
        "python3 --version",
        "gh auth status --active --hostname github.com",
        "python scripts/verify_release_consumer.py",
        "python3 scripts/verify_release_consumer.py",
        "--repository $Repository",
        "--tag $Tag",
        "--source-commit $SourceCommit",
        "--image $Image",
        "--image-digest $ImageDigest",
        "--download-directory $DownloadDirectory",
        ".local-ci/release-consumer",
        "SHA256SUMS",
        "release-manifest.json",
        "SPDX 2.3",
        "SLSA v1",
        "refs/heads/main",
        "self-hosted runners",
        "https://github.com/martonpornoi/maru/issues/29",
        "https://github.com/martonpornoi/maru/issues/40",
        "../checkpoints/2026-08-30-release-consumer-supply-chain-verification.md",
        "public Release page",
        "preauthenticated GitHub CLI session",
        "Every networked GitHub CLI operation is pinned to `github.com`",
        "actual tag-derived release pull request",
        "rechecks the mutable image identity",
        "does not create, edit, retag, publish, run, or extract an artifact",
        "not a gold-release, deployment, recovery, accessibility, "
        "owner-acceptance, or production-readiness decision",
    ):
        assert literal in normalized
    for unsafe_auth_literal in ("gh auth token", "--show-token", "--with-token"):
        assert unsafe_auth_literal not in section


def test_prerequisites_accept_official_gh_version_with_release_date() -> None:
    runner = _QueuedRunner(
        [
            "gh version 2.96.0 (2026-07-02)\n"
            "https://github.com/cli/cli/releases/tag/v2.96.0\n",
            "authenticated\n",
            "git version 2.51.0.windows.1\n",
            "Buildx imagetools help\n",
        ]
    )

    verifier._verify_prerequisites(runner)

    assert runner.calls[1][0] == (
        "gh",
        "auth",
        "status",
        "--active",
        "--hostname",
        "github.com",
    )


@pytest.mark.parametrize(
    ("version_output", "match"),
    [
        ("gh version 2.95.9 (2026-06-01)\n", "2.96.0 or later"),
        ("unexpected version output\n", "could not be parsed"),
    ],
)
def test_prerequisites_reject_unsupported_or_malformed_gh_versions(
    version_output: str,
    match: str,
) -> None:
    runner = _QueuedRunner([version_output])

    with pytest.raises(verifier.ConsumerVerificationError, match=match):
        verifier._verify_prerequisites(runner)


def test_gold_tag_derives_the_exact_release_contract(tmp_path: Path) -> None:
    expectations = verifier.ConsumerExpectations.from_inputs(
        repository=REPOSITORY,
        tag="v2026.08.27",
        source_commit=SOURCE_COMMIT,
        image="ghcr.io/martonpornoi/maru:2026.08.27",
        image_digest=IMAGE_DIGEST,
        download_directory=tmp_path / "gold-release",
    )

    assert expectations.identity.channel == "gold"
    assert expectations.identity.candidate_number is None
    assert expectations.identity.prerelease is False
    assert expectations.identity.pull_request == 27
    assert expectations.identity.title == "Maru 2026.08.27"
    assert expectations.identity.image_tag == "2026.08.27"
    assert "maru-docs-2026.08.27.tar.gz" in expectations.expected_assets
    verifier._verify_manifest(
        json.dumps(_manifest_payload(expectations)),
        expectations,
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("repository", "MartonPornoi/maru", "lowercase owner/repository"),
        ("tag", "v2026.8.27-rc.1", "vYYYY.MM.PR"),
        ("source_commit", "short", "40-character Git SHA"),
        ("image_digest", "sha256:short", "sha256:<64-hex>"),
        ("image", "ghcr.io/martonpornoi/maru:latest", "tag-derived reference"),
    ],
)
def test_independent_inputs_reject_malformed_or_inconsistent_identity(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    inputs: dict[str, object] = {
        "repository": REPOSITORY,
        "tag": TAG,
        "source_commit": SOURCE_COMMIT,
        "image": IMAGE,
        "image_digest": IMAGE_DIGEST,
        "download_directory": tmp_path / "release-evidence",
    }
    inputs[field] = value

    with pytest.raises(verifier.ConsumerVerificationError, match=match):
        verifier.ConsumerExpectations.from_inputs(**inputs)  # type: ignore[arg-type]


def test_independent_inputs_reject_existing_download_directory(tmp_path: Path) -> None:
    directory = tmp_path / "release-evidence"
    directory.mkdir()

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="must not already exist",
    ):
        _expectations(directory)


def test_relative_download_directory_is_normalized_before_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_directory = tmp_path / "caller directory"
    caller_directory.mkdir()
    monkeypatch.chdir(caller_directory)

    expectations = _expectations(Path("evidence with spaces") / "candidate")

    assert expectations.download_directory == (
        caller_directory / "evidence with spaces" / "candidate"
    )
    assert expectations.download_directory.is_absolute()
    runner = _EndToEndRunner(expectations)
    verifier.verify_release_consumer(expectations, runner=runner)
    download_command = next(
        call[0] for call in runner.calls if call[0][:3] == ("gh", "release", "download")
    )
    assert download_command[-1] == str(expectations.download_directory)


def test_strict_json_rejects_duplicate_nested_keys() -> None:
    malicious_key = "\x1b[31msecret"
    document = json.dumps({"outer": {malicious_key: 1}})
    document = document.replace(": 1}", ': 1, "\\u001b[31msecret": 2}')

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="duplicate key",
    ) as error:
        verifier._strict_json_loads(
            document,
            stage="test document",
        )

    assert malicious_key not in str(error.value)


def test_download_directory_rejects_junction_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "redirecting-ancestor"
    ancestor.mkdir()
    original_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_junction(path: Path) -> bool:
        return path == ancestor or original_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", is_junction, raising=False)

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="link or reparse point",
    ):
        verifier._create_download_directory(ancestor / "release-evidence")


@pytest.mark.parametrize(
    "name",
    ["../LICENSE", "nested/LICENSE", "nested\\LICENSE", ".", "bad\x1bname"],
)
def test_release_asset_names_reject_traversal_and_control_characters(
    name: str,
) -> None:
    with pytest.raises(verifier.ConsumerVerificationError, match="asset name"):
        verifier._safe_asset_name(name)


def test_remote_asset_inventory_rejects_boolean_size() -> None:
    with pytest.raises(verifier.ConsumerVerificationError, match="asset is empty"):
        verifier._remote_asset_inventory(
            [
                {
                    "name": "LICENSE",
                    "state": "uploaded",
                    "size": True,
                    "digest": f"sha256:{'a' * 64}",
                }
            ]
        )


@pytest.mark.parametrize(
    ("field", "value"), [("draft", 0), ("immutable", 1), ("prerelease", 1)]
)
def test_release_payload_rejects_integer_boolean_substitutes(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    files = _release_files(expectations)
    payload = _release_payload(expectations, files)
    payload[field] = value

    with pytest.raises(verifier.ConsumerVerificationError, match="field differs"):
        verifier._verify_release_payload(payload, expectations)


def test_downloaded_inventory_rejects_missing_and_nested_entries(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "download"
    directory.mkdir()
    (directory / "LICENSE").write_text("license\n", encoding="utf-8")
    (directory / "nested").mkdir()

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="not a direct regular file",
    ):
        verifier._downloaded_asset_inventory(
            directory,
            frozenset({"LICENSE", "uv.lock"}),
        )


def test_downloaded_inventory_rejects_symlink_like_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "download"
    directory.mkdir()
    asset = directory / "LICENSE"
    asset.write_text("license\n", encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def is_symlink(path: Path) -> bool:
        return path == asset or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match="not a direct regular file",
    ):
        verifier._downloaded_asset_inventory(directory, frozenset({"LICENSE"}))


def test_checksum_inventory_accepts_only_publisher_relative_paths() -> None:
    digest = "a" * 64

    assert verifier._parse_checksum_inventory(
        f"{digest}  release-assets/LICENSE\n"
    ) == {"LICENSE": digest}


@pytest.mark.parametrize(
    "text",
    [
        f"{'a' * 64} release-assets/LICENSE\n",
        f"{'a' * 64} *release-assets/LICENSE\n",
        f"{'A' * 64}  release-assets/LICENSE\n",
        f"{'a' * 64}  release-assets/../LICENSE\n",
        f"{'a' * 64}  release-assets/SHA256SUMS\n",
        (f"{'a' * 64}  release-assets/LICENSE\n{'b' * 64}  release-assets/LICENSE\n"),
    ],
)
def test_checksum_inventory_rejects_ambiguous_or_unsafe_lines(text: str) -> None:
    with pytest.raises(verifier.ConsumerVerificationError, match="SHA256SUMS"):
        verifier._parse_checksum_inventory(text)


def test_checksum_verification_rejects_tampered_payload(tmp_path: Path) -> None:
    directory = tmp_path / "download"
    directory.mkdir()
    (directory / "LICENSE").write_text("tampered\n", encoding="utf-8")
    (directory / verifier.CHECKSUMS_NAME).write_text(
        f"{'a' * 64}  release-assets/LICENSE\n",
        encoding="utf-8",
    )

    with pytest.raises(verifier.ConsumerVerificationError, match="checksum differs"):
        verifier._verify_checksums(
            directory,
            frozenset({"LICENSE", verifier.CHECKSUMS_NAME}),
        )


def test_manifest_accepts_exact_independent_identity(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")

    verifier._verify_manifest(json.dumps(_manifest_payload(expectations)), expectations)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("pull_request", True, "field differs"),
        ("commit", "c" * 40, "field differs"),
        ("image_digest", f"sha256:{'d' * 64}", "field differs"),
        ("merged_at", "2026-08-27T12:30:00", "timezone is missing"),
        ("merged_at", "2026-08-31T23:30:00-01:00", "CalVer month"),
    ],
)
def test_manifest_rejects_type_identity_and_timezone_drift(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    manifest = _manifest_payload(expectations)
    manifest[field] = value

    with pytest.raises(verifier.ConsumerVerificationError, match=match):
        verifier._verify_manifest(json.dumps(manifest), expectations)


def test_manifest_rejects_unknown_schema_field(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    manifest = _manifest_payload(expectations)
    manifest["unexpected"] = "field"

    with pytest.raises(verifier.ConsumerVerificationError, match="schema differs"):
        verifier._verify_manifest(json.dumps(manifest), expectations)


def test_release_pull_request_matches_manifest_source_and_main(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    manifest_merged_at = verifier._verify_manifest(
        json.dumps(_manifest_payload(expectations)),
        expectations,
    )
    payload = _pull_request_payload(expectations)

    verifier._verify_pull_request(payload, expectations, manifest_merged_at)


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("number",), True, "field differs"),
        (("state",), "CLOSED", "field differs"),
        (("baseRefName",), "develop", "field differs"),
        (("url",), "https://example.invalid/pull/27", "field differs"),
        (("mergeCommit", "oid"), "c" * 40, "field differs"),
        (("mergedAt",), "2026-08-27T12:31:00Z", "merge instant differs"),
        (("mergedAt",), "2026-08-27T12:30:00", "timezone is missing"),
        (("mergedAt",), "2026-08-31T23:30:00-01:00", "CalVer month"),
    ],
)
def test_release_pull_request_rejects_identity_or_merge_drift(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
    match: str,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    manifest_merged_at = verifier._verify_manifest(
        json.dumps(_manifest_payload(expectations)),
        expectations,
    )
    payload = _pull_request_payload(expectations)
    target: dict[str, object] = payload
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(verifier.ConsumerVerificationError, match=match):
        verifier._verify_pull_request(payload, expectations, manifest_merged_at)


def test_tag_source_accepts_annotated_tag_only_at_exact_peeled_source(
    tmp_path: Path,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    direct_ref = f"refs/tags/{expectations.tag}"
    runner = _QueuedRunner(
        [f"{'c' * 40}\t{direct_ref}\n{expectations.source_commit}\t{direct_ref}^{{}}\n"]
    )

    verifier._verify_tag_source(expectations, runner)

    command = runner.calls[0][0]
    assert command == (
        "git",
        "ls-remote",
        "--exit-code",
        f"https://github.com/{expectations.repository}.git",
        direct_ref,
        f"{direct_ref}^{{}}",
    )


@pytest.mark.parametrize(
    "output",
    [
        "malformed output\n",
        f"{'c' * 40}\trefs/tags/{TAG}\n",
        "",
    ],
)
def test_tag_source_rejects_malformed_mismatched_or_missing_ref(
    tmp_path: Path,
    output: str,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")

    with pytest.raises(verifier.ConsumerVerificationError, match="Git tag"):
        verifier._verify_tag_source(expectations, _QueuedRunner([output]))


def test_image_identity_checks_mutable_and_digest_bound_references(
    tmp_path: Path,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    manifest = json.dumps({"digest": expectations.image_digest})
    runner = _QueuedRunner([manifest, manifest])

    verifier._verify_image_identity(expectations, runner)

    commands = [call[0] for call in runner.calls]
    assert commands[0][4] == expectations.image
    assert commands[1][4] == expectations.immutable_image
    assert all(command[-1] == "{{json .Manifest}}" for command in commands)


def test_image_identity_rejects_mutable_tag_drift(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    runner = _QueuedRunner([json.dumps({"digest": f"sha256:{'c' * 64}"})])

    with pytest.raises(verifier.ConsumerVerificationError, match="another digest"):
        verifier._verify_image_identity(expectations, runner)


def test_spdx_is_digest_bound_and_reports_expected_generators(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    runner = _QueuedRunner(
        [
            json.dumps(
                {
                    "spdxVersion": "SPDX-2.3",
                    "SPDXID": "SPDXRef-DOCUMENT",
                    "packages": [{"name": "maru", "SPDXID": "SPDXRef-Package-maru"}],
                    "creationInfo": {
                        "creators": [
                            "Tool: syft-1.51.0",
                            "Tool: buildkit-0.32.2",
                        ]
                    },
                }
            )
        ]
    )

    package_count, generators = verifier._inspect_spdx(expectations, runner)

    assert package_count == 1
    assert generators == ("Tool: syft-1.51.0", "Tool: buildkit-0.32.2")
    assert runner.calls[0][0][4] == expectations.immutable_image
    assert runner.calls[0][0][-1] == "{{json .SBOM.SPDX}}"
    assert runner.calls[0][2] == verifier.SBOM_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "overrides",
    [
        {"spdxVersion": "SPDX-2.2"},
        {"packages": []},
        {"creationInfo": {"creators": ["Tool: syft-1.51.0", "Tool: another-1.0"]}},
    ],
)
def test_spdx_rejects_wrong_version_empty_packages_or_missing_generator(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    spdx: dict[str, object] = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "packages": [{"name": "maru", "SPDXID": "SPDXRef-Package-maru"}],
        "creationInfo": {"creators": ["Tool: syft-1.51.0", "Tool: buildkit-0.32.2"]},
    }
    spdx.update(overrides)

    with pytest.raises(verifier.ConsumerVerificationError, match="SPDX"):
        verifier._inspect_spdx(expectations, _QueuedRunner([json.dumps(spdx)]))


@pytest.mark.parametrize(
    "packages",
    [
        [{}],
        [{"name": "maru"}],
        [{"name": "maru", "SPDXID": "not-an-spdx-id"}],
        [
            {"name": "maru", "SPDXID": "SPDXRef-Package-same"},
            {"name": "django", "SPDXID": "SPDXRef-Package-same"},
        ],
    ],
)
def test_spdx_rejects_content_free_or_ambiguous_packages(
    tmp_path: Path,
    packages: list[dict[str, object]],
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    spdx = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "packages": packages,
        "creationInfo": {"creators": ["Tool: syft-1.51.0", "Tool: buildkit-0.32.2"]},
    }

    with pytest.raises(verifier.ConsumerVerificationError, match="SPDX"):
        verifier._inspect_spdx(expectations, _QueuedRunner([json.dumps(spdx)]))


def test_provenance_command_and_result_are_exactly_constrained(tmp_path: Path) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    runner = _QueuedRunner([json.dumps(_provenance_payload(expectations))])

    assert verifier._verify_provenance(expectations, runner) == 1

    command = runner.calls[0][0]
    assert command == (
        "gh",
        "attestation",
        "verify",
        f"oci://{expectations.immutable_image}",
        "--repo",
        expectations.repository,
        "--hostname",
        verifier.GITHUB_HOST,
        "--signer-workflow",
        f"{expectations.github_repository}/{verifier.RELEASE_WORKFLOW}",
        "--source-ref",
        verifier.MAIN_REF,
        "--source-digest",
        expectations.source_commit,
        "--predicate-type",
        verifier.SLSA_PREDICATE,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    )


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (
            ("verificationResult", "signature", "certificate", "runnerEnvironment"),
            "self-hosted",
            "field differs",
        ),
        (
            ("verificationResult", "verifiedTimestamps"),
            [],
            "timestamp is missing",
        ),
        (
            (
                "verificationResult",
                "statement",
                "subject",
                0,
                "digest",
                "sha256",
            ),
            "c" * 64,
            "field differs",
        ),
    ],
)
def test_provenance_rejects_runner_timestamp_and_subject_drift(
    tmp_path: Path,
    path: tuple[str | int, ...],
    value: object,
    match: str,
) -> None:
    expectations = _expectations(tmp_path / "release-evidence")
    payload: object = copy.deepcopy(_provenance_payload(expectations)[0])
    target = payload
    for key in path[:-1]:
        if isinstance(key, int):
            assert isinstance(target, list)
            target = target[key]
        else:
            assert isinstance(target, dict)
            target = target[key]
    final_key = path[-1]
    if isinstance(final_key, int):
        assert isinstance(target, list)
        target[final_key] = value
    else:
        assert isinstance(target, dict)
        target[final_key] = value

    with pytest.raises(verifier.ConsumerVerificationError, match=match):
        verifier._verify_one_provenance(payload, expectations)


def test_command_runner_uses_explicit_argv_and_never_surfaces_stderr_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fail_command(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            arguments,
            returncode=7,
            stdout="private-output",
            stderr="ghp_super_secret_token",
        )

    monkeypatch.setattr(verifier.subprocess, "run", fail_command)

    with pytest.raises(
        verifier.ConsumerVerificationError,
        match=r"command failed: safe authentication check; exit=7",
    ) as error:
        verifier.CommandRunner().run(
            ("gh", "auth", "status"),
            stage="safe authentication check",
        )

    assert "ghp_super_secret_token" not in str(error.value)
    assert "private-output" not in str(error.value)
    assert captured["arguments"] == ["gh", "auth", "status"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("shell", False) is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "strict"


@pytest.mark.parametrize("arguments", [(), ("gh", ""), "gh"])
def test_command_runner_rejects_empty_or_incomplete_argv(
    arguments: Sequence[str],
) -> None:
    with pytest.raises(verifier.ConsumerVerificationError, match="invalid command"):
        verifier.CommandRunner().run(arguments, stage="unsafe input")
