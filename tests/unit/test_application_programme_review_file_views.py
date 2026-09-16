"""Real review file HTTP admission across exact roles and anonymous denial."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve

from maru.applications import programme_review_file_views as views
from maru.applications.programme_file_queries import ProgrammeFileProjection
from tests.unit import test_application_programme_proposal_views as personal
from tests.unit import test_application_programme_review_file_admission as admission

source, world = admission.source, admission.world
shell = personal.shell


@pytest.fixture(autouse=True)
def readers(monkeypatch, world, shell):
    monkeypatch.setattr(
        views,
        "get_programme_review_file",
        admission.review.get_programme_review_file.__wrapped__,
    )
    monkeypatch.setattr(views, "_return_allowed", lambda _scope: True)
    world.projection.side_effect = lambda **kw: ProgrammeFileProjection(
        source=kw["source"],
        question_label="Synthetic private supporting file",
        present=True,
        size_bytes=8,
        data=b"%PDF-1.7" if kw["include_bytes"] else None,
    )


def incoming(world, *, purpose="reviewer", download=False, query=""):
    source = world.request
    request = RequestFactory().get("/synthetic-review-file/" + query)
    request.user = SimpleNamespace(
        pk=source.actor_id, is_authenticated=True, is_staff=True
    )
    return views.programme_review_file(
        request,
        source.organization_id,
        source.edition_id,
        source.department_id,
        world.case.id,
        "topic",
        purpose=purpose,
        assignment_id=UUID(int=50) if purpose == "reviewer" else None,
        download=download,
    )


@pytest.mark.parametrize("purpose", ["reviewer", "moderator", "decider"])
@pytest.mark.parametrize("download", [False, True])
def test_roles_use_real_source_admission_before_metadata_or_attachment(
    world, purpose, download
):
    response = incoming(world, purpose=purpose, download=download)
    assert response.status_code == 200
    if download:
        assert response.content == b"%PDF-1.7"
        assert response["Content-Disposition"].startswith("attachment;")
    else:
        doc = BeautifulSoup(response.content, "html.parser")
        assert doc.select_one('a[href$="download/"]')
        assert "Synthetic private supporting file" in doc.get_text()
    assert world.projection.call_count >= 2
    assert world.projection.call_args.kwargs["include_bytes"] is False


@pytest.mark.parametrize("purpose", ["reviewer", "moderator", "decider"])
@pytest.mark.parametrize("download", [False, True])
def test_anonymous_direct_urls_deny_before_custody(world, purpose, download):
    world.case.policy.stages[0]["anonymous"] = True
    response = incoming(world, purpose=purpose, download=download)
    assert response.status_code == 404
    world.binding.assert_not_called()
    world.projection.assert_not_called()
    assert b"Synthetic private" not in response.content


@pytest.mark.parametrize("download", [False, True])
def test_sensitive_denial_precedes_metadata_and_bytes(world, download):
    world.row.classification = "C3"
    world.extra_sensitive.side_effect = views.Denied
    assert incoming(world, download=download).status_code == 404
    world.binding.assert_not_called()


@pytest.mark.parametrize("download", [False, True])
def test_source_audit_failure_withholds_entire_response(world, download):
    world.audit.side_effect = DatabaseError
    response = incoming(world, download=download)
    assert response.status_code == 503
    assert b"%PDF" not in response.content


def test_late_anonymity_change_withholds_prepared_attachment(world):
    original = world.projection.side_effect

    def prepare(**kwargs):
        result = original(**kwargs)
        world.case.policy.stages[0]["anonymous"] = True
        return result

    world.projection.side_effect = prepare
    assert incoming(world, download=True).status_code == 404


@pytest.mark.parametrize("query", ["?file=other", "?download=1", "?purpose=decider"])
def test_query_override_does_not_reach_owner(world, query):
    assert incoming(world, query=query).status_code == 400
    world.binding.assert_not_called()


@pytest.mark.parametrize("purpose", ["reviewer", "moderator", "decider"])
def test_routes_preserve_exact_role_and_stay_dormant(world, purpose):
    source = world.request
    segment = {
        "reviewer": f"mine/{world.case.id}/{UUID(int=50)}/",
        "moderator": f"moderation/{world.case.id}/",
        "decider": f"decisions/{world.case.id}/",
    }[purpose]
    path = (
        f"/admin/applications/programme-review/{source.organization_id}/"
        f"{source.edition_id}/{source.department_id}/{segment}answers/file/topic/download/"
    )
    target = resolve(path, urlconf="maru.applications.programme_review_setup_urls")
    assert target.kwargs["purpose"] == purpose
    assert target.kwargs["download"] is True
    assert resolve(path).func != views.programme_review_file
    assert resolve(path).url_name is None
