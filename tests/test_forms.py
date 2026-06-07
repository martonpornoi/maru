from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from maru.domain import FormStatus, SubprojectKind
from maru.projects.models import FormField, Project, Subproject


@pytest.mark.django_db
def test_general_forms_page_lists_all_project_forms(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})

    response = client.get(reverse("projects:form_list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "All forms ever used across projects" in content
    assert "Event Submissions" in content
    assert "Cozy Panels" in content
    assert "Performance Applications" in content


@pytest.mark.django_db
def test_project_forms_page_only_lists_project_forms(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})

    response = client.get(
        reverse("projects:project_form_list", args=["awoostria-2026"])
    )

    content = response.content.decode()
    form_table = content.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert response.status_code == 200
    assert "Awoostria 2026 Forms" in content
    assert "Event Submissions" in form_table
    assert "Dance Competition Volunteers" in form_table
    assert "Cozy Panels" not in form_table


@pytest.mark.django_db
def test_admin_can_create_project_form_and_add_google_style_field(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})

    response = client.post(
        reverse("projects:create_form", args=["awoostria-2026"]),
        {
            "name": "Dealers Den Applications",
            "slug": "dealers-den",
            "kind": SubprojectKind.GENERIC_APPLICATION.value,
            "form_status": FormStatus.DRAFT.value,
            "accepts_reopen_requests": "on",
        },
        follow=True,
    )

    managed_form = Subproject.objects.get(slug="dealers-den")
    assert response.status_code == 200
    assert managed_form.form_status == FormStatus.DRAFT.value
    assert "Edit Dealers Den Applications" in response.content.decode()

    response = client.post(
        reverse("projects:edit_form", args=[managed_form.pk]),
        {
            "action": "add_field",
            "label": "Dealer category",
            "field_type": "single_choice",
            "required": "on",
            "options_text": "Prints\nPlush\nCrafts",
            "position": "1",
        },
        follow=True,
    )

    field = FormField.objects.get(subproject=managed_form, label="Dealer category")
    assert response.status_code == 200
    assert field.options == ["Prints", "Plush", "Crafts"]
    assert "Dealer category" in response.content.decode()


@pytest.mark.django_db
def test_project_can_inherit_form_as_editable_draft(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    source = Subproject.objects.get(
        project__slug="cozy-furcon-2025",
        slug="cozy-panels",
    )

    response = client.post(
        reverse("projects:project_form_list", args=["awoostria-2026"]),
        {"source_form": str(source.pk)},
        follow=True,
    )

    clone = Subproject.objects.get(
        project__slug="awoostria-2026",
        inherited_from=source,
    )
    assert response.status_code == 200
    assert clone.form_status == FormStatus.DRAFT.value
    assert clone.form_fields.count() == source.form_fields.count()
    assert "Edit Cozy Panels" in response.content.decode()


@pytest.mark.django_db
def test_project_keeps_at_least_one_timetable_form(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": "marton.pornoi@gmail.com"})
    project = Project.objects.get(slug="awoostria-2026")
    Subproject.objects.filter(project=project).update(is_timetable_source=False)

    response = client.post(
        reverse("projects:create_form", args=[project.slug]),
        {
            "name": "Operations Requests",
            "slug": "ops-requests",
            "kind": SubprojectKind.GENERIC_APPLICATION.value,
            "form_status": FormStatus.DRAFT.value,
            "accepts_reopen_requests": "on",
        },
    )

    form = Subproject.objects.get(project=project, slug="ops-requests")
    assert response.status_code == 302
    assert form.is_timetable_source
