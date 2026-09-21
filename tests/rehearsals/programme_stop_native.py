"""Opt-in actual HTTPS stop confirmation and consistent stopped-state restoration."""

from uuid import uuid4

import psycopg
import pytest
from bs4 import BeautifulSoup

from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)
from tests.rehearsals.programme_stop_races import verify_stop_races
from tests.rehearsals.programme_stopped_restore import verify_stopped_logical_restore

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_stop_html_csrf_original_retry_and_consistent_restore(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(
        setup_mode="new_foundation", with_isolation=True
    ) as fixture:
        verify_stop_races(fixture)
        setup = fixture.scenario
        root = f"/admin/programme/stop/{setup.organization_id}/{setup.edition_id}/"
        anonymous = ProgrammeHttpSession(fixture)
        assert anonymous.request(root).status == 302
        session = ProgrammeHttpSession(fixture)
        session.login(setup.controllers[0], destination=root)
        response = session.request(root)
        assert response.status == 200
        assert "private" in response.headers["Cache-Control"]
        html = BeautifulSoup(response.body, "html.parser")
        assert len(html.select("h1")) == len(html.select("main")) == 1
        form = html.select_one(f'form[action="{root}"]')
        assert form is not None
        fields = {
            node["name"]: node.get("value", "") for node in form.select("input[name]")
        }
        fields.update(
            reason="Synthetic HTTP stop keeps accountable history.", confirm="on"
        )
        scope = {
            "organization_id": setup.organization_id,
            "edition_id": setup.edition_id,
        }
        assert (
            session.submit_stop(
                **scope, form={**fields, "csrfmiddlewaretoken": ""}
            ).status
            == 403
        )
        malformed = session.submit_stop(**scope, form={**fields, "reason": ""})
        assert malformed.status == 400
        invalid = BeautifulSoup(malformed.body, "html.parser")
        assert (
            invalid.select_one('input[name="idempotency_key"]')["value"]
            == fields["idempotency_key"]
        )
        result = session.submit_stop(**scope, form=fields)
        assert result.status == 302
        location = result.headers["Location"]
        assert location.startswith(root)
        assert location != root
        retry = session.submit_stop(**scope, form=fields)
        assert retry.status == 302
        assert retry.headers["Location"] == location
        history = session.request(location)
        assert history.status == 200
        retained = BeautifulSoup(history.body, "html.parser")
        assert fields["reason"] in retained.get_text()
        assert not retained.select('.programme-workbench button[type="submit"]')
        assert session.request(root).status == 200
        assert (
            session.request(
                root.replace(str(setup.organization_id), str(uuid4()))
            ).status
            == 404
        )
        wrong = ProgrammeHttpSession(fixture)
        wrong.login(setup.controllers[1], destination=root)
        assert wrong.request(location).status == 404
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT e.lifecycle, count(r.id) FROM public.events_eventedition e "
                "JOIN public.events_programmestopreceipt r ON r.edition_id = e.id "
                "WHERE e.id = %s GROUP BY e.lifecycle",
                (setup.edition_id,),
            ).fetchone() == ("archived", 1)
        fixture.verify_excluded_state()
        verify_stopped_logical_restore(fixture)
        session.logout()
        wrong.logout()
