"""Opt-in owned runtime archive proof, not the populated P01-P12 acceptance."""

from uuid import uuid4

import pytest

from tests.rehearsals.programme_archive_scenario import (
    run_archive_phase,
    verify_archive_http,
)
from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_archive_custody_under_actual_requester_and_runtime(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(setup_mode="new_foundation") as fixture:
        archive = run_archive_phase(fixture)
        assert verify_archive_http(fixture, archive).state == "cancelled"
