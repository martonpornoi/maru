"""Host-only genuine HTTPS/setup cases; no default discovery or deferred execution."""

from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)
from tests.rehearsals.programme_setup_scenarios import SETUP_MODES

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode", SETUP_MODES)
def test_native_https_setup_preserves_root_real_people_and_narrow_decisions(
    monkeypatch, mode
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(setup_mode=mode) as fixture:
        # Context entry has already required a real TLS-verified /health/ready,
        # genuine native probe and actual worker cycle; no Django test client.
        scenario = fixture.scenario
        assert scenario.mode == mode
        assert scenario.representation_code == (
            "executive_board" if mode == "existing_organization" else "maru_operators"
        )
        certificate = fixture.certificate_path
        assert certificate.is_file()
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT session_user, current_user"
            ).fetchone() == ("maru_runtime", "maru_runtime")
            assert connection.execute(
                "SELECT count(*) FROM public.events_eventedition"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM public.identity_account"
            ).fetchone() == (4,)
            assert connection.execute(
                "SELECT count(*) FROM public.identity_account "
                "WHERE email_verified_at IS NOT NULL"
            ).fetchone() == (3,)
            rows = connection.execute(
                "SELECT recipe_code, scope_level, author_id, approver_id, recipient_id "
                "FROM public.authorization_programmerolerequest ORDER BY recipe_code"
            ).fetchall()
            assert rows == [
                (
                    "edition-coordination",
                    "edition",
                    scenario.controllers[0].account_id,
                    scenario.controllers[1].account_id,
                    scenario.controllers[0].account_id,
                ),
                (
                    "intake",
                    "department",
                    scenario.controllers[0].account_id,
                    scenario.controllers[1].account_id,
                    scenario.intake_person.account_id,
                ),
            ]
            assert connection.execute(
                "SELECT count(*) FROM public.authorization_programmeroledecisionrecord "
                "WHERE role_assignment_id IS NOT NULL"
            ).fetchone() == (2,)
        assert all(
            person.password not in repr(fixture) for person in scenario.controllers
        )
    assert not certificate.parent.exists()
