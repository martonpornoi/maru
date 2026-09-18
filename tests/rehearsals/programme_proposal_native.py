"""Host-only call-to-private-item composition; uncollected/unexecuted while deferred."""

from uuid import uuid4

import psycopg
import pytest

from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_real_call_review_private_items_and_confirmed_hosting(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(
        setup_mode="new_foundation", with_scanner=True
    ) as fixture:
        result = fixture.prepare_proposal()
        assert result.organization_id == fixture.scenario.organization_id
        assert result.lead.account_id != result.collaborator.account_id
        # Independent read under genuine runtime login; no SQL/factory writes.
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT session_user, current_user"
            ).fetchone() == ("maru_runtime", "maru_runtime")
            assert connection.execute(
                "SELECT state, submitted_revision_id "
                "FROM public.applications_programmeproposal "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (result.proposal_id, result.organization_id, result.edition_id),
            ).fetchone() == ("submitted", result.revision_id)
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmefileintake "
                "WHERE proposal_id = %s",
                (result.proposal_id,),
            ).fetchone() == (1,)
        assert result.lead.password not in repr(result)
        reviewed = fixture.prepare_review(result)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            assert connection.execute(
                "SELECT revision_id, decision_id, programme_item_id "
                "FROM public.applications_programmeacceptedtransition "
                "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                (reviewed.transition_id, reviewed.organization_id, reviewed.edition_id),
            ).fetchone() == (result.revision_id, reviewed.decision_id, reviewed.item_id)
            assert connection.execute(
                "SELECT count(*) FROM public.programme_programmereadinessrequirement "
                "WHERE item_id = %s",
                (reviewed.item_id,),
            ).fetchone() == (7,)
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmeacceptedtransition "
                "WHERE revision_id = %s",
                (result.revision_id,),
            ).fetchone() == (1,)
        items = fixture.prepare_items(result, reviewed)
        with psycopg.connect(
            fixture.runtime.database_url, connect_timeout=5
        ) as connection:
            for item, kind in (
                (items.accepted, "accepted_proposal"),
                (items.ceremony, "ceremony"),
            ):
                assert connection.execute(
                    "SELECT kind, aggregate_version "
                    "FROM public.programme_programmeitem "
                    "WHERE id = %s AND organization_id = %s AND edition_id = %s",
                    (item.item_id, items.organization_id, items.edition_id),
                ).fetchone() == (kind, item.version)
                assert connection.execute(
                    "SELECT state, version, availability_state "
                    "FROM public.programme_programmehostrelationship WHERE id = %s",
                    (item.host_id,),
                ).fetchone() == ("confirmed", item.host_version, "shared")
            assert connection.execute(
                "SELECT count(*) FROM public.applications_programmeacceptedtransition "
                "WHERE programme_item_id = %s",
                (items.ceremony.item_id,),
            ).fetchone() == (0,)
    # This proves no actual HTTPS form, representative human, complete cross-tenant
    # inventory or P05-P12 outcome. Those remain separate acceptance checkpoints.
