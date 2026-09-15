"""Real filtered review answer query precedes every exact-person resolution."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_person_references as personal_refs
from maru.applications import programme_review_person_references as refs
from maru.applications import programme_review_person_views as views
from maru.applications import programme_review_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import (
    DECIDE,
    MANAGE_REVIEW,
    MODERATE,
    REVIEW,
)
from tests.unit import test_application_programme_proposal_views as intake_tests
from tests.unit import test_application_programme_review_answer_queries as answer_tests

source = answer_tests.source
shell = intake_tests.shell


@pytest.fixture
def world(source, monkeypatch):
    source.question.field_type = source.row.question_type = "person_reference"
    source.question.reference_kind = "programme.person"
    source.row.answer_revision.value = str(UUID(int=40))
    source.case.policy_id = UUID(int=31)
    source.assignment.return_value = SimpleNamespace(id=UUID(int=50))
    source.labels = Mock(
        return_value={UUID(int=40): "Synthetic person, not frozen name"}
    )
    source.current = Mock(return_value=True)
    for name, target in (
        (
            "get_programme_review_detail",
            queries.get_programme_review_detail.__wrapped__,
        ),
        ("_locked_scope", source.locked),
        ("load_review_case", Mock(return_value=source.case)),
        ("_detail_assignment", source.assignment),
        ("revision_is_current", source.current),
        ("_audit", source.audit),
    ):
        monkeypatch.setattr(refs, name, target)
    monkeypatch.setattr(
        personal_refs, "active_verified_person_account_display_labels", source.labels
    )
    monkeypatch.setattr(
        views,
        "get_programme_review_person_reference",
        refs.get_programme_review_person_reference.__wrapped__,
    )
    monkeypatch.setattr(views, "authorize_programme_review_scope", Mock())
    return source


def read(world, **changes):
    return refs.get_programme_review_person_reference.__wrapped__(
        **(
            {
                "request": world.request,
                "case_id": world.case.id,
                "question_key": "topic",
                "assignment_id": UUID(int=50),
            }
            | changes
        )
    )


@pytest.mark.parametrize("role", [REVIEW, MODERATE, DECIDE])
def test_actual_answer_query_and_sensitive_authority_precede_minimized_viewer(
    world, role
):
    result = read(
        world,
        request=replace(world.request, capability_code=role),
        assignment_id=UUID(int=50) if role == REVIEW else None,
    )
    assert result.display_label == "Synthetic person, not frozen name"
    world.labels.assert_called_once_with((UUID(int=40),))
    assert world.sensitive.call_count == 2
    world.query.filter.assert_any_call(
        revision_id=world.case.revision_id,
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        question_key__in=["topic"],
    )
    assert world.audit.call_args.args[1] == "person_reference"


@pytest.mark.parametrize("role", [REVIEW, MODERATE, DECIDE])
def test_anonymous_sql_exclusion_and_direct_viewer_never_resolve_target(world, role):
    world.case.policy.stages[0]["anonymous"] = True
    with pytest.raises(Denied):
        read(
            world,
            request=replace(world.request, capability_code=role),
            assignment_id=UUID(int=50) if role == REVIEW else None,
        )
    world.query.exclude.assert_called_once_with(
        question_type__in=queries._ANONYMOUS_OMISSIONS
    )
    world.query.filter.assert_any_call(question__source_binding="")
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"question_key": "missing"},
        {"question_key": "../person"},
        {"question_key": "x" * 81},
        {"assignment_id": UUID(int=51)},
        {"assignment_id": None},
    ],
)
def test_exact_question_assignment_and_bounded_route_before_target_lookup(
    world, change
):
    with pytest.raises(Denied):
        read(world, **change)
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"capability_code": MANAGE_REVIEW},
        {"requested_fields": frozenset({"review_context"})},
        {"requested_fields": frozenset({"review_answers", "review_context"})},
    ],
)
def test_viewer_accepts_only_exact_content_purpose_and_field_ceiling(world, change):
    with pytest.raises(Denied):
        read(world, request=replace(world.request, **change))
    world.manager.select_related.assert_not_called()
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "guard", ["locked", "assignment", "sensitive", "extra_sensitive"]
)
def test_all_required_role_and_sensitive_guards_precede_person_resolution(world, guard):
    world.row.classification = "C3"
    getattr(world, guard).side_effect = Denied
    with pytest.raises(Denied):
        read(world)
    world.labels.assert_not_called()


def test_old_seal_and_unknown_registered_kind_cannot_use_identity_fallback(world):
    world.current.return_value = False
    with pytest.raises(Denied):
        read(world)
    world.current.return_value = True
    world.question.reference_kind = "unregistered.person"
    with pytest.raises(Denied):
        read(world)
    world.labels.assert_not_called()


def test_required_source_audit_failure_prevents_identity_lookup(world):
    world.audit.side_effect = DatabaseError
    with pytest.raises(DatabaseError):
        read(world)
    world.labels.assert_not_called()


def test_source_change_after_label_resolution_withholds_projection(world):
    def label(_ids):
        world.case.policy.stages[0]["anonymous"] = True
        return {UUID(int=40): "Do not disclose"}

    world.labels.side_effect = label
    with pytest.raises(Denied):
        read(world)


def incoming(world, *, purpose="reviewer", query="", method="get"):
    request = getattr(RequestFactory(), method)("/reference/" + query)
    request.user = SimpleNamespace(
        pk=world.request.actor_id, is_authenticated=True, is_staff=True
    )
    return views.programme_review_person_reference(
        request,
        world.request.organization_id,
        world.request.edition_id,
        world.request.department_id,
        world.case.id,
        "topic",
        purpose=purpose,
        assignment_id=UUID(int=50) if purpose == "reviewer" else None,
    )


@pytest.mark.parametrize("purpose", ["reviewer", "moderator", "decider"])
def test_real_readonly_role_viewer_keeps_shell_scope_and_protected_headers(
    world, purpose
):
    response = incoming(world, purpose=purpose)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == 1
    assert len(soup.select("main")) == 1
    assert "Synthetic person, not frozen name" in soup.get_text()
    assert "no-store" in response["Cache-Control"]
    assert "form-action 'self'" in response["Content-Security-Policy"]
    assert soup.find("a", string="Back to permitted answers")


def test_post_and_caller_account_query_are_refused_before_owner_or_identity(world):
    assert incoming(world, method="post").status_code == 405
    assert incoming(world, query="?account_id=anything").status_code == 400
    world.manager.select_related.assert_not_called()
    world.labels.assert_not_called()


def test_late_label_change_and_anonymous_state_never_release_old_html(
    world, monkeypatch
):
    original = views.render_to_string

    def render(*args, **kwargs):
        html = original(*args, **kwargs)
        world.labels.return_value = {}
        return html

    monkeypatch.setattr(views, "render_to_string", render)
    response = incoming(world)
    assert response.status_code == 404
    assert b"Synthetic person" not in response.content


def test_review_person_viewer_routes_are_absent_from_production(world):
    path = (
        f"/admin/applications/programme-review/{world.request.organization_id}/"
        f"{world.request.edition_id}/{world.request.department_id}/"
        f"mine/{world.case.id}/{UUID(int=50)}/answers/person/topic/"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_review_setup_urls").url_name
        == "programme-review-own-person-reference"
    )
    try:
        production = resolve(path, urlconf="maru.urls")
    except Resolver404:
        pass
    else:
        assert production.func != views.programme_review_person_reference
        assert production.url_name != "programme-review-own-person-reference"
