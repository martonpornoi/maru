"""Owned temporary exports and the actual offline CLI with networking denied."""

import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

ROOT = Path(__file__).resolve().parents[2]
_OFFLINE = """
import runpy, sys
def guard(event, args):
    if event.startswith('socket.') or (event == 'import' and
        (args[0] == 'django' or args[0].startswith('django.'))):
        raise RuntimeError('offline_boundary')
sys.addaudithook(guard)
runpy.run_module('maru.scheduling.continuity_offline', run_name='__main__')
"""


def _require(condition, code):
    if not condition:
        raise ProgrammeHttpsError(code)


@dataclass(frozen=True, slots=True)
class ProgrammeOfflineWorkspace:
    """One owned synthetic export directory; never an event device custody approval."""

    directory: Path = field(repr=False)
    run_id: str
    deadline: float

    def path(self, name):
        """Resolve only a fixed safe basename inside the still-owned run directory."""
        request = require_programme_rehearsal_request()
        remaining_lease(self.deadline)
        _require(
            request.run_id == self.run_id
            and not self.directory.is_symlink()
            and self.directory.is_dir()
            and self.directory.resolve().parent == (ROOT / ".tools").resolve()
            and self.directory.name.startswith(f"programme-continuity-{self.run_id}-")
            and re.fullmatch(r"[a-z][a-z0-9-]{0,48}\.(?:json|html)", name) is not None,
            "fixture_offline_path_invalid",
        )
        result = self.directory / name
        _require(not result.is_symlink(), "fixture_offline_path_invalid")
        return result

    def write(self, name, data):
        """Create a new bounded synthetic file, never overwrite a retained artifact."""
        path = self.path(name)
        _require(
            type(data) is bytes and len(data) <= 2_097_152,
            "fixture_offline_input_invalid",
        )
        with path.open("xb") as stream:
            stream.write(data)
        return path

    def verify(
        self,
        package_name,
        *,
        purpose,
        output_name,
        scope,
        initialize=False,
        success=True,
    ):
        """Run the actual CLI without database settings, Django imports or sockets."""
        package = self.path(package_name)
        trust = self.path("trust.json")
        history = self.path(purpose + "-known.json")
        output = self.path(output_name)
        _require(not output.exists(), "fixture_offline_output_exists")
        arguments = [
            "--package",
            str(package),
            "--trust",
            str(trust),
            "--known-state",
            str(history),
            "--output",
            str(output),
            "--organization",
            str(scope.organization_id),
            "--edition",
            str(scope.edition_id),
            "--audience",
            scope.audience,
            "--kind",
            scope.kind,
        ]
        if scope.actor_id is not None:
            arguments.extend(("--actor", str(scope.actor_id)))
        if scope.target_id is not None:
            arguments.extend(("--target", str(scope.target_id)))
        if scope.layers:
            arguments.extend(("--layers", *scope.layers))
        if initialize:
            arguments.append("--initialize")
        environment = {
            key: os.environ[key]
            for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
            if key in os.environ
        }
        try:
            result = subprocess.run(  # noqa: S603 - fixed interpreter/module, owned paths
                [sys.executable, "-I", "-B", "-c", _OFFLINE, *arguments],
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=min(30, remaining_lease(self.deadline)),
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ProgrammeHttpsError("fixture_offline_process_failed") from None
        remaining_lease(self.deadline)
        _require(
            len(result.stdout) + len(result.stderr) <= 4096,
            "fixture_offline_process_failed",
        )
        if success:
            _require(
                result.returncode == 0
                and not result.stderr
                and result.stdout.startswith("Verified historical HTML saved.")
                and history.is_file()
                and output.is_file(),
                "fixture_offline_verification_failed",
            )
            return output
        _require(
            result.returncode == 2
            and not result.stdout
            and result.stderr.startswith("Continuity verification failed.")
            and not output.exists(),
            "fixture_offline_refusal_missing",
        )
        return None

    @contextmanager
    def missing_history(self, purpose):
        """Retain history under another owned name without resetting its bytes."""
        path = self.path(purpose + "-known.json")
        retained = self.path(purpose + "-retained.json")
        _require(
            path.is_file() and not retained.exists(), "fixture_offline_history_invalid"
        )
        path.rename(retained)
        try:
            yield
        finally:
            _require(not path.exists(), "fixture_offline_history_recreated")
            retained.rename(path)


@contextmanager
def isolated_continuity_files(fixture):
    """Remove only this newly created synthetic directory at normal exit/failure."""
    request = require_programme_rehearsal_request()
    remaining_lease(fixture.deadline)
    _require(
        request.run_id == fixture.run_id
        and type(fixture.continuity_trust_policy) is bytes,
        "fixture_offline_trust_missing",
    )
    tools = ROOT / ".tools"
    _require(tools.is_dir() and not tools.is_symlink(), "fixture_offline_path_invalid")
    with tempfile.TemporaryDirectory(
        prefix=f"programme-continuity-{request.run_id}-", dir=tools
    ) as directory:
        workspace = ProgrammeOfflineWorkspace(
            Path(directory), request.run_id, fixture.deadline
        )
        workspace.write("trust.json", fixture.continuity_trust_policy)
        yield workspace
