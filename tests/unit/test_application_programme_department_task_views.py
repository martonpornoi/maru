"""Real dormant entry HTML, closed transport and final disclosure checks."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_department_task_views as views
from maru.applications import programme_department_tasks as tasks
from tests.unit.test_application_programme_call_views import shell

__all__ = ["shell"]


@pytest.fixture
def page(monkeypatch):
    actor, organization, edition, department = (UUID(int=i) for i in range(1, 5))
    root = f"/admin/applications/programme-calls/{organization}/{edition}/"
    choice = tasks.ProgrammeDepartmentTask(
        department,
        "programme",
        "Programme <synthetic>",
        "calls",
        "Manage calls",
        root + f"{department}/",
        "Direct permission",
    )
    catalog = tasks.ProgrammeDepartmentTaskCatalog(
        tasks=(choice,),
        accepts_private_planning_writes=True,
        source_fingerprint="private-source-comparison",
    )
    reader = Mock(return_value=catalog)
    monkeypatch.setattr(tasks, "list_programme_department_tasks", reader)
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        edition=edition,
        department=department,
        root=root,
        choice=choice,
        catalog=catalog,
        reader=reader,
    )


def _request(page, *, method="get", query="", authenticated=True, actor=None):
    request = getattr(RequestFactory(), method)(page.root + query)
    request.user = SimpleNamespace(
        pk=actor if actor is not None else page.actor,
        is_authenticated=authenticated,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    return views.programme_department_tasks(request, page.organization, page.edition)


def test_real_shell_links_scope_escaping_and_private_source_non_disclosure(page):
    response = _request(page)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == 1
    assert len(soup.select("main")) == 1
    assert len(soup.select("main details summary")) == 1
    assert soup.find(
        "summary", string="Access · independently authorized tasks for this edition"
    )
    assert soup.find("a", string="Manage calls")["href"] == page.choice.url
    assert "Programme <synthetic>" in soup.get_text()
    assert soup.find("synthetic") is None
    assert "private-source-comparison" not in response.content.decode()
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert page.reader.call_count == 2
    first, second = page.reader.call_args_list
    assert first.kwargs == second.kwargs
    assert first.kwargs["actor_id"] == page.actor
    assert first.kwargs["organization_id"] == page.organization
    assert first.kwargs["edition_id"] == page.edition


def test_empty_and_readonly_are_truthful_without_hidden_counts(page):
    page.reader.return_value = replace(
        page.catalog, tasks=(), accepts_private_planning_writes=False
    )
    response = _request(page)
    assert response.status_code == 200
    text = BeautifulSoup(response.content, "html.parser").get_text()
    assert "No Programme call or review tasks are currently available" in text
    assert "Private planning is read-only" in text
    assert "Programme <synthetic>" not in text


def test_duplicate_department_names_have_stable_codes_and_separate_links(page):
    second = replace(
        page.choice,
        department_id=UUID(int=99),
        department_code="stage",
        url=page.root + f"{UUID(int=99)}/",
    )
    page.reader.return_value = replace(page.catalog, tasks=(page.choice, second))
    response = _request(page)
    soup = BeautifulSoup(response.content, "html.parser")
    assert [heading.get_text() for heading in soup.select(".call-cards h2")] == [
        "Programme <synthetic> (programme)",
        "Programme <synthetic> (stage)",
    ]
    assert len(soup.select(".call-cards a")) == 2


@pytest.mark.parametrize("changed", ["source", "choices", "lifecycle"])
def test_final_revalidation_suppresses_all_prepared_private_html(page, changed):
    final = {
        "source": replace(page.catalog, source_fingerprint="changed-hidden-set"),
        "choices": replace(page.catalog, tasks=()),
        "lifecycle": replace(page.catalog, accepts_private_planning_writes=False),
    }[changed]
    page.reader.side_effect = [page.catalog, final]
    response = _request(page)
    assert response.status_code == 404
    assert "Programme &lt;synthetic&gt;" not in response.content.decode()
    assert page.choice.url not in response.content.decode()


@pytest.mark.parametrize(
    ("failure", "status"),
    [(tasks.Denied, 404), (DatabaseError, 503), (ValidationError("invalid"), 400)],
)
@pytest.mark.parametrize("final", [False, True])
def test_read_or_final_audit_failure_is_non_disclosing(page, failure, status, final):
    page.reader.side_effect = [page.catalog, failure] if final else failure
    response = _request(page)
    assert response.status_code == status
    assert page.choice.url not in response.content.decode()
    assert "synthetic" not in response.content.decode()


@pytest.mark.parametrize(
    "query", ["?purpose=decisions", "?actor=1", "?after=2", "?x=1&x=2"]
)
def test_extra_query_controls_cannot_choose_authority_or_paginate_hidden_scope(
    page, query
):
    assert _request(page, query=query).status_code == 400
    page.reader.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "delete", "head"])
def test_no_mutation_or_head_action(page, method):
    assert _request(page, method=method).status_code == 405
    page.reader.assert_not_called()


def test_signed_out_person_is_sent_to_login_without_read(page):
    assert _request(page, authenticated=False).status_code == 302
    page.reader.assert_not_called()


@pytest.mark.parametrize("actor", [UUID(int=0), "1", 42])
def test_invalid_actor_never_dispatches_an_owner_read(page, actor):
    assert _request(page, actor=actor).status_code == 404
    page.reader.assert_not_called()


def test_oversized_render_is_not_released(page, monkeypatch):
    monkeypatch.setattr(
        views, "render_to_string", Mock(return_value="x" * (8 * 1024 * 1024 + 1))
    )
    response = _request(page)
    assert response.status_code == 503
    assert len(response.content) < 200


def test_reserved_entry_and_all_task_destinations_resolve_only_in_isolation(page):
    assert (
        resolve(page.root, urlconf="maru.applications.programme_call_urls").func
        is views.programme_department_tasks
    )
    for task in tasks._TASKS:
        root = "programme-calls" if task.code == "calls" else "programme-review"
        url = (
            f"/admin/applications/{root}/{page.organization}/{page.edition}/"
            f"{page.department}/{task.suffix}"
        )
        urlconf = (
            "maru.applications.programme_call_urls"
            if task.code == "calls"
            else "maru.applications.programme_review_setup_urls"
        )
        assert resolve(url, urlconf=urlconf).func is not None
    for urlconf in ("maru.urls", "maru.baseline_urls"):
        try:
            match = resolve(page.root, urlconf=urlconf)
        except Resolver404:
            continue
        assert match.func is not views.programme_department_tasks
        assert match.func.__name__ == "catch_all_view"
