"""Optional Shift return links preserve native lazy rendering and pending forms."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django import forms
from django.template import engines
from django.test import RequestFactory

from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink
from maru.workforce import programme_response as response_module


@pytest.mark.parametrize("status", [200, 400, 409])
@pytest.mark.parametrize("moved", [False, True])
def test_lazy_return_links_keep_exact_original_bound_form_and_status(
    monkeypatch, status, moved
):
    request = RequestFactory().post(
        "/synthetic-shift/", {"name": "Pending work", "retry": str(uuid4())}
    )
    request.user = SimpleNamespace(pk=uuid4())
    request.correlation_id = str(uuid4())
    request.urlconf = "synthetic-conf"

    class PendingForm(forms.Form):
        name = forms.CharField()
        retry = forms.UUIDField()
        reason = forms.CharField()

    form = PendingForm(request.POST)
    assert not form.is_valid()
    context = {
        "organization": SimpleNamespace(id=uuid4()),
        "edition": SimpleNamespace(id=uuid4()),
        "convention_series": SimpleNamespace(id=uuid4()),
        "form": form,
    }
    link = ProgrammeWorkspaceLink(
        "timetable", "Timetable planning", "/synthetic-timetable/"
    )
    links = Mock(side_effect=[(link,), () if moved else (link,)])
    monkeypatch.setattr(response_module, "programme_workspace_links", links)
    template = engines["django"].from_string(
        "{% include 'workforce/_programme_navigation.html' %}{{ form.as_p }}"
    )
    response = response_module.organizer_programme_response(
        request, template, context, status=status
    )
    response["X-Synthetic-Retained"] = "yes"
    assert not response.is_rendered
    assert links.call_count == 1
    response.render()
    assert links.call_count == 2
    assert response.status_code == status
    assert response["X-Synthetic-Retained"] == "yes"
    assert response.context_data["form"] is form
    assert form.data is request.POST
    html = response.content.decode()
    assert "Pending work" in html
    assert request.POST["retry"] in html
    assert "This field is required" in html
    assert ("/synthetic-timetable/" in html) is not moved
    scope = links.call_args.args[0]
    assert scope.actor_id == request.user.pk
    assert scope.organization_id == context["organization"].id
    assert scope.edition_id == context["edition"].id
    assert links.call_args.kwargs == {
        "current": "shifts",
        "series_id": context["convention_series"].id,
        "urlconf": "synthetic-conf",
    }
    response.render()
    assert links.call_count == 2


def test_missing_actor_omits_optional_navigation(monkeypatch):
    request = RequestFactory().get("/synthetic-shift/")
    request.user = SimpleNamespace(pk=None)
    links = Mock()
    monkeypatch.setattr(response_module, "programme_workspace_links", links)
    template = engines["django"].from_string(
        "{% include 'workforce/_programme_navigation.html' %}"
    )
    response = response_module.organizer_programme_response(request, template, {})
    response.render()
    links.assert_not_called()
    assert not response.content.strip()
