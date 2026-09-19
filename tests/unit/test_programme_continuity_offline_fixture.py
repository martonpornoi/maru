"""Actual offline CLI/files/crypto with synthetic sources, not native owner proof."""

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.scheduling.continuity_payload import ContinuityProjection
from maru.scheduling.continuity_protocol import ContinuityScope
from maru.scheduling.continuity_signing import (
    load_continuity_signing_policy,
    sign_continuity_projection,
)
from tests.rehearsals import programme_continuity_material as material
from tests.rehearsals import programme_continuity_offline as offline
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    request = Mock(return_value=SimpleNamespace(run_id="a" * 32, lease_seconds=3600))
    monkeypatch.setattr(offline, "require_programme_rehearsal_request", request)
    monkeypatch.setattr(material, "require_programme_rehearsal_request", request)
    monkeypatch.setattr(offline, "remaining_lease", Mock(return_value=1800.0))
    monkeypatch.setattr(material, "remaining_lease", Mock(return_value=1800.0))
    monkeypatch.setattr(offline, "ROOT", tmp_path)
    (tmp_path / ".tools").mkdir()
    setup = SimpleNamespace(organization_id=uuid4(), edition_id=uuid4())
    keys = material.generate_continuity_material(setup, deadline=1900.0)
    policy = load_continuity_signing_policy(
        environment={material.SIGNING_ENV: keys.signing_policy}
    )
    scope = ContinuityScope(setup.organization_id, setup.edition_id, "public")
    now = datetime.now(UTC)
    projection = ContinuityProjection(
        scope,
        "scheduling.public-timetable@1",
        "a" * 64,
        now,
        "Europe/Budapest",
        "available",
        2,
        uuid4(),
        now - timedelta(seconds=1),
        "not_applicable",
        "not_applicable",
        (),
    )
    fixture = SimpleNamespace(
        run_id="a" * 32, deadline=1900.0, continuity_trust_policy=keys.trust_policy
    )
    return fixture, scope, projection, policy


def _put(workspace, name, projection, policy):
    workspace.write(
        name,
        sign_continuity_projection(
            projection, policy=policy, issued_at=datetime.now(UTC)
        ),
    )


def test_actual_offline_cli_retains_history_refuses_loss_and_replaces_withdrawal(
    prepared,
):
    fixture, scope, projection, policy = prepared
    with offline.isolated_continuity_files(fixture) as workspace:
        _put(workspace, "initial.json", projection, policy)
        initial = workspace.verify(
            "initial.json",
            purpose="public",
            output_name="initial.html",
            scope=scope,
            initialize=True,
        )
        text = initial.read_text(encoding="utf-8")
        assert "Historical / degraded" in text
        assert "cannot know newer releases" in text
        assert "Replace/dispose" in text
        workspace.verify(
            "initial.json", purpose="public", output_name="repeat.html", scope=scope
        )
        retained = workspace.path("public-known.json").read_bytes()
        with workspace.missing_history("public"):
            workspace.verify(
                "initial.json",
                purpose="public",
                output_name="missing.html",
                scope=scope,
                success=False,
            )
        assert workspace.path("public-known.json").read_bytes() == retained
        workspace.verify(
            "initial.json",
            purpose="public",
            output_name="reset.html",
            scope=scope,
            initialize=True,
            success=False,
        )
        assert workspace.path("public-known.json").read_bytes() == retained
        observed = datetime.now(UTC)
        withdrawn = replace(
            projection,
            observed_at=observed,
            release_state="withdrawn",
            pointer_version=3,
            release_id=None,
            published_at=None,
            source_sha256="b" * 64,
        )
        _put(workspace, "withdrawn.json", withdrawn, policy)
        warning = workspace.verify(
            "withdrawn.json",
            purpose="public",
            output_name="withdrawn.html",
            scope=scope,
        )
        assert "Normal Programme geometry is withheld" in warning.read_text(
            encoding="utf-8"
        )
        workspace.verify(
            "initial.json",
            purpose="public",
            output_name="older.html",
            scope=scope,
            success=False,
        )
        recovered = replace(
            projection,
            observed_at=datetime.now(UTC),
            pointer_version=4,
            release_id=uuid4(),
            source_sha256="c" * 64,
        )
        _put(workspace, "replacement.json", recovered, policy)
        result = workspace.verify(
            "replacement.json",
            purpose="public",
            output_name="replacement.html",
            scope=scope,
        )
        assert str(recovered.release_id) in result.read_text(encoding="utf-8")
        directory = workspace.directory
    assert not directory.exists()


@pytest.mark.parametrize("fault", ["tamper", "foreign_scope", "missing_history"])
def test_actual_cli_refusal_publishes_no_html(prepared, fault):
    fixture, scope, projection, policy = prepared
    with offline.isolated_continuity_files(fixture) as workspace:
        _put(workspace, "initial.json", projection, policy)
        name, initialize = "initial.json", True
        if fault == "tamper":
            workspace.write(
                "tampered.json", workspace.path(name).read_bytes()[:-1] + b"!"
            )
            name = "tampered.json"
        elif fault == "foreign_scope":
            scope = replace(scope, edition_id=uuid4())
        else:
            initialize = False
        workspace.verify(
            name,
            purpose="public",
            output_name="refused.html",
            scope=scope,
            initialize=initialize,
            success=False,
        )
        assert not workspace.path("public-known.json").exists()


@pytest.mark.parametrize(
    "name",
    ["../foreign.json", "C:/foreign.json", "a/b.json", "a\\b.json", "unsafe.exe"],
)
def test_export_names_cannot_escape_owned_directory(prepared, name):
    with (
        offline.isolated_continuity_files(prepared[0]) as workspace,
        pytest.raises(offline.ProgrammeHttpsError, match="path_invalid"),
    ):
        workspace.write(name, b"synthetic")


def test_exclusive_writes_keep_original_and_cleanup_does_not_touch_siblings(prepared):
    sibling = offline.ROOT / ".tools" / "untouched.txt"
    sibling.write_text("synthetic other task", encoding="utf-8")
    with offline.isolated_continuity_files(prepared[0]) as workspace:
        workspace.write("original.json", b"original")
        with pytest.raises(FileExistsError):
            workspace.write("original.json", b"replacement")
        assert workspace.path("original.json").read_bytes() == b"original"
    assert sibling.read_text(encoding="utf-8") == "synthetic other task"


@pytest.mark.parametrize("attempt", ["import socket; socket.socket()", "import django"])
def test_actual_child_audit_guard_blocks_network_and_django(attempt):
    script = offline._OFFLINE.replace(
        "runpy.run_module('maru.scheduling.continuity_offline', run_name='__main__')",
        attempt,
    )
    result = subprocess.run(  # noqa: S603 - fixed local interpreter and test literals
        [sys.executable, "-I", "-B", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode != 0
    assert "offline_boundary" in result.stderr


def test_deferral_precedes_filesystem_or_fixture_access(monkeypatch):
    monkeypatch.setattr(
        offline,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with (
        pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"),
        offline.isolated_continuity_files(None),
    ):
        pytest.fail("Deferred fixture was admitted.")
