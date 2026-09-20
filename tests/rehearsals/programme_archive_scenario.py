"""P11 archive composition through actual owner commands under genuine runtime login."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import tracemalloc
import zipfile
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator

from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_provisioning import ROOT
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    approve_synthetic_role,
    scenario_from_document,
)


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveScenario:
    """Closed private handles and measured cost, never portable authority."""

    organization_id: UUID
    edition_id: UUID
    requester_id: UUID
    task_id: UUID
    request_key: UUID
    state: str
    artifact_bytes: int
    artifact_digest: str
    generation_seconds: float
    python_peak_bytes: int


def _require(condition):
    if not condition:
        raise ProgrammeHttpsError("fixture_archive_evidence_changed")


def archive_from_document(document, *, setup):
    """Require exact scope and closed bounded handles from the private child pipe."""
    try:
        result = ProgrammeArchiveScenario(
            **{
                key: UUID(value)
                if key.endswith("_id") or key == "request_key"
                else value
                for key, value in document.items()
            }
        )
        _require(
            result.organization_id == setup.organization_id
            and result.edition_id == setup.edition_id
            and result.requester_id == setup.controllers[0].account_id
            and result.task_id.int
            and result.request_key.int
            and result.state in {"ready", "cancelled"}
            and type(result.artifact_bytes) is int
            and 1 <= result.artifact_bytes <= 2_097_152
            and re.fullmatch(r"[0-9a-f]{64}", result.artifact_digest) is not None
            and type(result.generation_seconds) is float
            and math.isfinite(result.generation_seconds)
            and 0 <= result.generation_seconds < 1200
            and type(result.python_peak_bytes) is int
            and result.python_peak_bytes > 0
        )
    except (TypeError, ValueError, AttributeError):
        raise ProgrammeHttpsError("fixture_archive_evidence_changed") from None
    return result


def _approve_sources(setup):
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415

    requester = setup.controllers[0]
    # Intentionally explicit broad synthetic archive source allocation. Export
    # does not imply any of these roles; a second actual controller approves each.
    for code in ("intake", "review-setup", "decision-maker"):
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=requester,
            code=code,
            level=ScopeLevel.DEPARTMENT,
            department_id=setup.department_id,
        )
    for code in (
        "content",
        "delivery",
        "hosting",
        "staffing",
        "coverage-reader",
        "planner",
        "venue-selection",
    ):
        approve_synthetic_role(
            setup,
            people=setup.controllers,
            recipient=requester,
            code=code,
            level=ScopeLevel.EDITION,
        )
    return approve_synthetic_role(
        setup,
        people=setup.controllers,
        recipient=requester,
        code="exit-archive",
        level=ScopeLevel.EDITION,
    )


def prepare_archive_scenario(document):
    """Create or dispose derived custody without SQL/factory writes or fake grants."""
    require_programme_runtime_environment()
    _require(set(document) == {"setup", "operation", "previous"})
    _require(document["operation"] in {"prepare", "dispose"})
    setup = scenario_from_document(document["setup"], mode=document["setup"]["mode"])
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from maru.programme.archive_queries import (  # noqa: PLC0415
        inspect_programme_archive,
    )
    from maru.programme.archive_tasks import (  # noqa: PLC0415
        ProgrammeArchiveScope,
        cancel_programme_archive,
        request_programme_archive,
    )
    from maru.programme.archive_worker import (  # noqa: PLC0415
        process_archive_queue_once,
    )

    person = setup.controllers[0].authenticate()
    scope = ProgrammeArchiveScope(person.id, setup.organization_id, setup.edition_id)
    if document["operation"] == "dispose":
        previous = archive_from_document(document["previous"], setup=setup)
        _require(previous.state == "ready")
        current = inspect_programme_archive(scope=scope, task_id=previous.task_id)
        cancel_programme_archive(
            scope=scope, task_id=previous.task_id, expected_version=current.version
        )
        return ProgrammeArchiveScenario(**{**asdict(previous), "state": "cancelled"})
    _require(document["previous"] is None)
    _approve_sources(setup)
    key = uuid4()
    task_id = request_programme_archive(scope=scope, request_key=key)
    _require(request_programme_archive(scope=scope, request_key=key) == task_id)
    tracemalloc.start()
    started = time.monotonic()
    try:
        _require(process_archive_queue_once() == "ready")
        elapsed = time.monotonic() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    result = inspect_programme_archive(scope=scope, task_id=task_id)
    _require(
        result.state == "ready" and not result.expired and not result.source_changed
    )
    return ProgrammeArchiveScenario(
        setup.organization_id,
        setup.edition_id,
        person.id,
        task_id,
        key,
        "ready",
        result.size_bytes,
        result.sha256,
        elapsed,
        peak,
    )


def run_archive_phase(fixture, *, operation="prepare", previous=None):
    """Supervise an actual runtime child under the original finite fixture lease."""
    if fixture.scenario is None or not fixture._application_environment:
        raise ProgrammeHttpsError("fixture_archive_dependencies_required")
    _require(operation in {"prepare", "dispose"})
    _require((operation == "prepare") == (previous is None))
    if previous is not None:
        archive_from_document(
            json.loads(json.dumps(asdict(previous), default=str)),
            setup=fixture.scenario,
        )
    fixture.refresh_workers()
    document = {
        "setup": asdict(fixture.scenario),
        "operation": operation,
        "previous": asdict(previous) if previous else None,
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_archive_scenario"],
            cwd=ROOT,
            env=fixture._application_environment,
            input=json.dumps(document, default=str),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=min(180, remaining_lease(fixture.deadline)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ProgrammeHttpsError("fixture_archive_process_failed")
        return archive_from_document(json.loads(result.stdout), setup=fixture.scenario)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ProgrammeHttpsError("fixture_archive_process_failed") from None


def verify_archive_http(fixture, archive, *, expected_files=()):
    """Fetch the actual private attachment and check each manifest member locally."""
    setup = fixture.scenario
    _require(setup is not None)
    path = (
        f"/admin/programme/archive/{setup.organization_id}/"
        f"{setup.edition_id}/{archive.task_id}/"
    )
    anonymous = ProgrammeHttpSession(fixture)
    _require(anonymous.request(path + "download/").status == 302)
    wrong = ProgrammeHttpSession(fixture)
    wrong.login(setup.controllers[1], destination=path)
    _require(wrong.request(path + "download/").status == 404)
    session = ProgrammeHttpSession(fixture)
    session.login(setup.controllers[0], destination=path)
    _require(session.request(path).status == 200)
    response = session.request(path + "download/")
    _require(
        response.status == 200
        and response.headers.get("Content-Type") == "application/zip"
        and "private" in response.headers.get("Cache-Control", "")
        and "no-store" in response.headers.get("Cache-Control", "")
        and response.headers.get("Content-Disposition")
        == 'attachment; filename="programme-exit-archive.zip"'
        and len(response.body) == archive.artifact_bytes
        and hashlib.sha256(response.body).hexdigest() == archive.artifact_digest
    )
    with zipfile.ZipFile(io.BytesIO(response.body)) as package:
        manifest = json.loads(package.read("manifest.json"))
        _require(manifest["scope"]["requester_id"] == str(archive.requester_id))
        _require(manifest["scope"]["edition_id"] == str(setup.edition_id))
        _require(manifest["scope"]["organization_id"] == str(setup.organization_id))
        _require(manifest["contract"] == "programme.exit-archive@1")
        owners = (
            "applications",
            "audit",
            "authorization",
            "events",
            "programme",
            "scheduling",
            "venues",
            "workforce",
        )
        _require(
            manifest["owner_contracts"]
            == {owner: f"{owner}.programme-exit@1" for owner in owners}
        )
        expected = {
            f"{kind}/{owner}.json"
            for owner in owners
            for kind in ("records", "schemas")
        } | {f"files/applications/{identifier}.bin" for identifier in expected_files}
        _require(len(package.namelist()) == len(set(package.namelist())))
        _require(set(package.namelist()) == expected | {"manifest.json"})
        _require(len(manifest["members"]) == len(expected))
        _require({member["path"] for member in manifest["members"]} == expected)
        for member in manifest["members"]:
            data = package.read(member["path"])
            _require(
                len(data) == member["byte_length"]
                and hashlib.sha256(data).hexdigest() == member["sha256"]
            )
        for owner in owners:
            schema = json.loads(package.read(f"schemas/{owner}.json"))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(
                json.loads(package.read(f"records/{owner}.json"))
            )
    disposed = run_archive_phase(fixture, operation="dispose", previous=archive)
    _require(disposed.state == "cancelled")
    _require(session.request(path + "download/").status == 404)
    return disposed


def _main():
    try:
        require_programme_runtime_environment()
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            return 2
        result = prepare_archive_scenario(json.loads(raw))
    except Exception:  # noqa: BLE001 - final private child boundary never prints source or secrets.
        return 2
    sys.stdout.write(json.dumps(asdict(result), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
