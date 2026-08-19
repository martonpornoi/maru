"""Regression tests for the cross-platform production-settings verifier."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import pytest

from maru.settings.environment import (
    invitation_public_key_configuration_is_valid,
    invitation_token_key_configuration_is_valid,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_production_settings.py"
WRAPPER_PATH = REPOSITORY_ROOT / "scripts" / "verify-production-settings.ps1"


class _VerifierModule(Protocol):
    REPOSITORY_ROOT: Path
    MANAGE_PY: Path
    EXACT_PROVENANCE_ENVIRONMENT: str
    WORKER_PRIVATE_KEY_ENVIRONMENT: str
    VERIFICATION_ENVIRONMENT: Mapping[str, str]

    def verification_environment(
        self,
        parent_environment: Mapping[str, str],
        *,
        exact_provenance_required: str,
    ) -> dict[str, str]: ...

    def verify_production_settings(
        self,
        parent_environment: Mapping[str, str] | None = None,
    ) -> int: ...


def _load_verifier() -> _VerifierModule:
    spec = importlib.util.spec_from_file_location(
        "maru_verify_production_settings",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_VerifierModule, module)


VERIFIER = _load_verifier()


def test_fixture_has_valid_public_invitation_and_digest_keys() -> None:
    environment = VERIFIER.VERIFICATION_ENVIRONMENT
    encryption_key_id = environment["MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID"]
    public_key_b64 = environment["MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64"]
    digest_key_id = environment["MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID"]
    digest_keys_json = environment["MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON"]

    assert invitation_public_key_configuration_is_valid(
        encryption_key_id,
        public_key_b64,
    )
    assert invitation_token_key_configuration_is_valid(
        digest_key_id,
        digest_keys_json,
    )
    assert json.loads(digest_keys_json) == {
        "verification-digest-2026-08": base64.b64encode(bytes(range(1, 33))).decode()
    }
    assert b"PRIVATE KEY" not in base64.b64decode(public_key_b64, validate=True)


def test_child_environment_is_deterministic_and_excludes_worker_private_keys() -> None:
    inherited = {
        "PATH": "inherited-path",
        "DJANGO_SETTINGS_MODULE": "maru.settings.test",
        "MARU_DEBUG": "true",
        "MARU_SECRET_KEY": "inherited-secret",
        VERIFIER.WORKER_PRIVATE_KEY_ENVIRONMENT: "private-worker-material",
    }

    environment = VERIFIER.verification_environment(
        inherited,
        exact_provenance_required="true",
    )

    assert environment["PATH"] == "inherited-path"
    assert environment["DJANGO_SETTINGS_MODULE"] == "maru.settings.production"
    assert environment["MARU_SETTINGS_MODULE"] == "maru.settings.production"
    assert environment[VERIFIER.EXACT_PROVENANCE_ENVIRONMENT] == "true"
    assert environment["MARU_SECRET_KEY"].startswith("verification-only-")
    assert "MARU_DEBUG" not in environment
    assert VERIFIER.WORKER_PRIVATE_KEY_ENVIRONMENT not in environment
    assert inherited[VERIFIER.WORKER_PRIVATE_KEY_ENVIRONMENT] == (
        "private-worker-material"
    )


def test_verifier_runs_both_provenance_modes_in_isolated_subprocesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Sequence[str], Path, Mapping[str, str], bool]] = []

    def record_run(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, cwd, env, check))
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", record_run)

    assert VERIFIER.verify_production_settings({"PATH": "test-path"}) == 0
    assert len(calls) == 2
    assert [
        environment[VERIFIER.EXACT_PROVENANCE_ENVIRONMENT]
        for _, _, environment, _ in calls
    ] == ["false", "true"]
    assert calls[0][2] is not calls[1][2]
    for command, cwd, environment, check in calls:
        assert tuple(command) == (
            sys.executable,
            str(VERIFIER.MANAGE_PY),
            "check",
            "--deploy",
        )
        assert cwd == VERIFIER.REPOSITORY_ROOT == REPOSITORY_ROOT
        assert check is False
        assert VERIFIER.WORKER_PRIVATE_KEY_ENVIRONMENT not in environment


def test_verifier_reports_the_first_failure_after_checking_both_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    return_codes = iter((7, 9))
    calls = 0

    def fail_run(
        command: Sequence[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, returncode=next(return_codes))

    monkeypatch.setattr(subprocess, "run", fail_run)

    assert VERIFIER.verify_production_settings({}) == 7
    assert calls == 2


def test_powershell_entrypoint_only_delegates_to_the_python_verifier() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")

    assert "verify_production_settings.py" in wrapper
    assert "src/manage.py check --deploy" not in wrapper
    assert "MARU_IDENTITY_INVITATION_" not in wrapper
