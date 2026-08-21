from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from scripts.verify_package_artifacts import (
    ArtifactVerificationError,
    main,
    verify_distribution_directory,
)

ASSETS = (
    "maru/core/static/core/app.js",
    "maru/core/templates/core/page.html",
)
SDIST_ROOT = "maru-1.0.0"


def _metadata(*, expression: str = "Apache-2.0 AND MIT") -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        "Name: maru\n"
        "Version: 1.0.0\n"
        f"License-Expression: {expression}\n"
        "License-File: LICENSE\n"
        "License-File: THIRD_PARTY_NOTICES.md\n"
        "\n"
    ).encode()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        "[project]\n"
        'name = "maru"\n'
        'version = "1.0.0"\n'
        'license = "Apache-2.0 AND MIT"\n'
        'license-files = ["LICENSE", "THIRD_PARTY_NOTICES.md"]\n',
        encoding="utf-8",
    )
    (repository / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (repository / "THIRD_PARTY_NOTICES.md").write_text(
        "MIT notices\n",
        encoding="utf-8",
    )
    for asset in ASSETS:
        path = repository / "src" / Path(asset)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"asset: {asset}\n", encoding="utf-8")
    return repository


def _write_artifacts(
    tmp_path: Path,
    *,
    wheel_expression: str = "Apache-2.0 AND MIT",
    omitted_wheel_member: str | None = None,
    extra_sdist_member: str | None = None,
) -> tuple[Path, Path]:
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    wheel = distribution / "maru-1.0.0-py3-none-any.whl"
    wheel_members = {
        "maru-1.0.0.dist-info/METADATA": _metadata(expression=wheel_expression),
        "maru-1.0.0.dist-info/licenses/LICENSE": b"Apache-2.0\n",
        "maru-1.0.0.dist-info/licenses/THIRD_PARTY_NOTICES.md": b"MIT notices\n",
        **{asset: f"asset: {asset}\n".encode() for asset in ASSETS},
    }
    if omitted_wheel_member is not None:
        wheel_members.pop(omitted_wheel_member)
    with zipfile.ZipFile(wheel, mode="w") as archive:
        for name, payload in wheel_members.items():
            archive.writestr(name, payload)

    sdist = distribution / "maru-1.0.0.tar.gz"
    sdist_members = {
        f"{SDIST_ROOT}/PKG-INFO": _metadata(),
        f"{SDIST_ROOT}/LICENSE": b"Apache-2.0\n",
        f"{SDIST_ROOT}/THIRD_PARTY_NOTICES.md": b"MIT notices\n",
        **{
            f"{SDIST_ROOT}/src/{asset}": f"asset: {asset}\n".encode()
            for asset in ASSETS
        },
    }
    if extra_sdist_member is not None:
        sdist_members[extra_sdist_member] = b"leaked\n"
    with tarfile.open(sdist, mode="w:gz") as archive:
        for name, payload in sdist_members.items():
            information = tarfile.TarInfo(name)
            information.size = len(payload)
            archive.addfile(information, io.BytesIO(payload))
    return wheel, sdist


def test_verifies_complete_wheel_and_sdist(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, sdist = _write_artifacts(tmp_path)

    summary = verify_distribution_directory(
        wheel.parent,
        repository_root=repository,
    )

    assert summary.wheel_path == wheel
    assert summary.sdist_path == sdist
    assert summary.license_file_count == 2
    assert summary.package_asset_count == len(ASSETS)


def test_cli_reports_verified_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(tmp_path)

    assert (
        main(
            [
                "--distribution-directory",
                str(wheel.parent),
                "--repository-root",
                str(repository),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Package artifacts valid" in output
    assert "legal_files=2" in output
    assert f"package_assets={len(ASSETS)}" in output


def test_rejects_missing_wheel_package_asset(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(
        tmp_path,
        omitted_wheel_member=ASSETS[0],
    )

    with pytest.raises(ArtifactVerificationError, match="missing package asset"):
        verify_distribution_directory(wheel.parent, repository_root=repository)


def test_rejects_wrong_pep639_expression(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(tmp_path, wheel_expression="Apache-2.0")

    with pytest.raises(ArtifactVerificationError, match="License-Expression differs"):
        verify_distribution_directory(wheel.parent, repository_root=repository)


def test_rejects_sdist_doctree_cache_leak(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(
        tmp_path,
        extra_sdist_member=f"{SDIST_ROOT}/docs/.doctrees/environment.pickle",
    )

    with pytest.raises(ArtifactVerificationError, match="cache or doctree"):
        verify_distribution_directory(wheel.parent, repository_root=repository)


def test_rejects_sdist_uv_cache_leak(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(
        tmp_path,
        extra_sdist_member=f"{SDIST_ROOT}/.uv-cache/archive-v0/build-backend.whl",
    )

    with pytest.raises(ArtifactVerificationError, match="cache or doctree"):
        verify_distribution_directory(wheel.parent, repository_root=repository)


def test_rejects_ambiguous_distribution_directory(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    wheel, _sdist = _write_artifacts(tmp_path)
    (wheel.parent / "duplicate.whl").write_bytes(b"not inspected")

    with pytest.raises(ArtifactVerificationError, match=r"exactly one \.whl"):
        verify_distribution_directory(wheel.parent, repository_root=repository)
