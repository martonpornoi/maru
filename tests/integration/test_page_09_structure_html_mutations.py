import re
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import Client
from django.urls import resolve, reverse
from django.utils.html import strip_tags

from maru.audit.models import AuditEvent
from maru.authorization.enforcement import FieldProjectionDeniedError
from maru.authorization.models import CapabilityGrant
from maru.authorization.policy import PolicyDecision
from maru.authorization.policy import decide as decide_policy
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department, EditionStructureControl
from maru.workforce.queries import (
    DepartmentNode,
    EditionStructureProjection,
    PositionNode,
    StructureSource,
)
from maru.workforce.structure_commands import (
    StructureAuthorizationDeniedError,
    StructureDepartmentUnavailableError,
    StructureDependencyConflictError,
    StructureDependencyUnavailableError,
    StructureLifecycleConflictError,
    StructureLimitConflictError,
    StructureRetryConflictError,
    StructureStateConflictError,
    StructureVersionConflictError,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.workforce_helpers import (
    apply_builtin_structure_template_for_test,
    create_department_for_test,
    retire_department_for_test,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _assert_private_no_store(response: Any) -> None:
    cache_control = response.headers.get("Cache-Control", "")
    assert "private" in cache_control
    assert "no-store" in cache_control


def _structure_form_actions(content: str) -> list[str]:
    return [
        action
        for action in re.findall(
            r'<form\b[^>]*\baction="([^"]+)"',
            content,
            flags=re.DOTALL,
        )
        if "/structure/" in action
    ]


def _route_args(edition: EventEdition) -> list[str]:
    return [
        edition.organization.slug,
        edition.series.slug,
        edition.slug,
    ]


def _url(
    name: str,
    edition: EventEdition,
    department: Department | None = None,
) -> str:
    args: list[object] = _route_args(edition)
    if department is not None:
        args.append(department.id)
    return reverse(name, args=args)


def _client(account: Account) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _view_grant(account: Account, edition: EventEdition) -> CapabilityGrant:
    return CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code="workforce.view_structure",
    )


def _transition_to_lifecycle(
    *,
    edition: EventEdition,
    actor: Account,
    lifecycle: str,
) -> None:
    for next_state in (
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    ):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=next_state,
            actor=actor,
            reason="Advance a synthetic Page 9 lifecycle fixture.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        if next_state == lifecycle:
            return
    raise AssertionError("Unsupported synthetic Page 9 lifecycle target.")


def _valid_create_data(
    response: Any,
    *,
    name: str = "Registration",
    parent_department_id: str = "",
) -> dict[str, str]:
    form = response.context["form"]
    return {
        "name": name,
        "description": "Synthetic operational Department.",
        "parent_department_id": parent_department_id,
        "expected_version": str(form["expected_version"].value()),
        "reason": "Establish the synthetic operational structure.",
        "retry_key": str(form["retry_key"].value()),
    }


def _valid_action_case(
    action: str,
) -> tuple[Client, EventEdition, Department | None, str, dict[str, str], str, str]:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)
    if action == "template":
        page = client.get(_url("organization-structure-template-application", edition))
        form = page.context["form"]
        return (
            client,
            edition,
            None,
            _url("apply-organization-structure-template", edition),
            {
                "template": "marucon-reference@1",
                "expected_version": str(form["expected_version"].value()),
                "confirmation_name": edition.name,
                "reason": "Apply the synthetic reference structure.",
                "retry_key": str(form["retry_key"].value()),
            },
            "apply_builtin_structure_template",
            "confirmation_name",
        )
    if action == "create":
        page = client.get(_url("organization-structure-department-create", edition))
        return (
            client,
            edition,
            None,
            _url("create-organization-structure-department", edition),
            _valid_create_data(page),
            "create_department",
            "name",
        )

    department = create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Private Mutation Target",
        expected_code="private-mutation-target",
    )
    page = client.get(_url("organization-structure-department", edition, department))
    if action == "update":
        form = page.context["update_form"]
        return (
            client,
            edition,
            department,
            _url("update-organization-structure-department", edition, department),
            {
                "name": str(form["name"].value()),
                "description": str(form["description"].value()),
                "parent_department_id": str(form["parent_department_id"].value() or ""),
                "expected_version": str(form["expected_version"].value()),
                "reason": "Review this synthetic Department without changing it.",
            },
            "update_department",
            "name",
        )
    if action == "retire":
        form = page.context["retirement_form"]
        return (
            client,
            edition,
            department,
            _url("retire-organization-structure-department", edition, department),
            {
                "expected_version": str(form["expected_version"].value()),
                "reason": "Retire this synthetic Department.",
            },
            "retire_department",
            "reason",
        )
    if action == "delete":
        form = page.context["deletion_form"]
        return (
            client,
            edition,
            department,
            _url("delete-organization-structure-department", edition, department),
            {
                "expected_version": str(form["expected_version"].value()),
                "confirmation_name": department.name,
                "reason": "Delete this unused synthetic Department.",
            },
            "delete_unused_department",
            "confirmation_name",
        )
    raise AssertionError(f"Unsupported synthetic action: {action}")


def test_page_09_html_mutation_routes_are_separate_and_method_closed() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Registration",
        expected_code="registration",
    )
    client = _client(administrator)
    routes = {
        "organization-structure-template-application": "template-application/",
        "apply-organization-structure-template": "template-applications/",
        "organization-structure-department-create": "departments/new/",
        "create-organization-structure-department": "departments/",
        "organization-structure-department": f"departments/{department.id}/",
        "update-organization-structure-department": (
            f"departments/{department.id}/update/"
        ),
        "retire-organization-structure-department": (
            f"departments/{department.id}/retire/"
        ),
        "delete-organization-structure-department": (
            f"departments/{department.id}/delete/"
        ),
    }
    department_routes = {
        "organization-structure-department",
        "update-organization-structure-department",
        "retire-organization-structure-department",
        "delete-organization-structure-department",
    }

    for name, suffix in routes.items():
        url = _url(name, edition, department if name in department_routes else None)
        assert url.endswith(f"/structure/{suffix}")
        assert resolve(url).url_name == name
        response = (
            client.post(url) if name.startswith("organization-") else client.get(url)
        )
        assert response.status_code == 405


def test_child_get_pages_repeat_manage_policy_audit_and_one_current_navigation() -> (
    None
):
    administrator = _administrator()
    edition = EventEditionFactory(name="Synthetic HTML editor edition")
    helper = create_department_for_test(
        edition=edition,
        name="Helper Board",
        expected_code="helper-board",
    )
    registration = create_department_for_test(
        edition=edition,
        parent=helper,
        name="Registration",
        expected_code="registration",
    )
    client = _client(administrator)

    template_response = client.get(
        _url("organization-structure-template-application", edition)
    )
    create_response = client.get(
        _url("organization-structure-department-create", edition)
    )
    editor_response = client.get(
        _url("organization-structure-department", edition, registration)
    )

    for response in (template_response, create_response, editor_response):
        assert response.status_code == 200
        _assert_private_no_store(response)
        assert response.content.decode().count('aria-current="page"') == 1
        assert "Synthetic HTML editor edition" in response.content.decode()
    editor_content = editor_response.content.decode()
    assert "Helper Board" in editor_content
    assert editor_content.count("<details") >= 3
    assert "Retire Department</summary>" in editor_content
    assert "Delete unused Department</summary>" in editor_content
    assert "baseline-form-actions--sticky" not in editor_content
    audits = AuditEvent.objects.filter(operation="workforce.structure.read")
    assert set(audits.values_list("safe_metadata__route_name", flat=True)) >= {
        "organization-structure-template-application",
        "organization-structure-department-create",
        "organization-structure-department",
    }


def test_query_parameters_are_rejected_after_scope_authorization_without_names() -> (
    None
):
    administrator = _administrator()
    edition = EventEditionFactory(name="Hidden query edition")
    client = _client(administrator)

    for name in (
        "organization-structure",
        "organization-structure-template-application",
        "organization-structure-department-create",
    ):
        response = client.get(f"{_url(name, edition)}?unexpected=1")
        content = response.content.decode()
        assert response.status_code == 400
        _assert_private_no_store(response)
        assert "Remove unsupported URL options" in content
        assert edition.name not in content
        assert edition.organization.name not in content


def test_manage_denial_happens_before_post_form_parsing_or_scope_disclosure() -> None:
    edition = EventEditionFactory(name="Hidden denied editor edition")
    viewer = AccountFactory()
    _view_grant(viewer, edition)

    with patch(
        "maru.workforce.views.DepartmentCreationForm",
        side_effect=AssertionError("form parsing must not run"),
    ) as form_class:
        response = _client(viewer).post(
            _url("create-organization-structure-department", edition),
            {"organization_id": str(edition.organization_id), "name": "Forged"},
        )

    assert response.status_code in {403, 404}
    assert edition.name not in response.content.decode()
    assert edition.organization.name not in response.content.decode()
    form_class.assert_not_called()


def test_post_query_is_rejected_before_projection_or_read_audit() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Hidden POST query edition")
    client = _client(administrator)

    with (
        patch(
            "maru.workforce.views.project_edition_structure",
            side_effect=AssertionError("projection must not run"),
        ) as projector,
        patch("maru.workforce.views.append_structure_read_audit") as audit,
    ):
        response = client.post(
            f"{_url('create-organization-structure-department', edition)}?x=1",
            {"name": "Forged"},
        )

    assert response.status_code == 400
    _assert_private_no_store(response)
    assert edition.name not in response.content.decode()
    projector.assert_not_called()
    audit.assert_not_called()


def test_template_application_uses_browser_retry_and_success_prg() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Synthetic reference target")
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-template-application", edition))
    form = form_page.context["form"]
    retry_key = str(form["retry_key"].value())

    response = client.post(
        _url("apply-organization-structure-template", edition),
        {
            "template": "marucon-reference@1",
            "expected_version": "0",
            "confirmation_name": edition.name,
            "reason": "Use the synthetic reference for this edition.",
            "retry_key": retry_key,
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == _url("organization-structure", edition)
    assert Department.objects.filter(edition=edition).count() == 22
    control = EditionStructureControl.objects.get(edition=edition)
    assert control.aggregate_version == 1
    assert control.origin == EditionStructureControl.Origin.BUILTIN_TEMPLATE


def test_department_create_update_retire_and_delete_success_locations() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)

    create_page = client.get(_url("organization-structure-department-create", edition))
    create_response = client.post(
        _url("create-organization-structure-department", edition),
        _valid_create_data(create_page),
    )
    registration = Department.objects.get(edition=edition, name="Registration")
    assert create_response.status_code == 302
    assert create_response.headers["Location"].endswith(
        f"/structure/#department-{registration.id}"
    )

    editor = client.get(
        _url("organization-structure-department", edition, registration)
    )
    update_form = editor.context["update_form"]
    update_response = client.post(
        _url("update-organization-structure-department", edition, registration),
        {
            "name": "Registration & Front Desk",
            "description": "Synthetic combined intake.",
            "parent_department_id": "",
            "expected_version": str(update_form["expected_version"].value()),
            "reason": "Clarify the synthetic Department scope.",
        },
    )
    assert update_response.status_code == 302
    assert update_response.headers["Location"].endswith(
        f"/structure/#department-{registration.id}"
    )
    registration.refresh_from_db()
    assert registration.name == "Registration & Front Desk"

    editor = client.get(
        _url("organization-structure-department", edition, registration)
    )
    retirement_form = editor.context["retirement_form"]
    retire_response = client.post(
        _url("retire-organization-structure-department", edition, registration),
        {
            "expected_version": str(retirement_form["expected_version"].value()),
            "reason": "Retire this unused synthetic Department.",
        },
    )
    assert retire_response.status_code == 302
    assert retire_response.headers["Location"].endswith(
        f"/structure/#department-{registration.id}"
    )
    registration.refresh_from_db()
    assert registration.retired_at is not None

    create_page = client.get(_url("organization-structure-department-create", edition))
    delete_create = client.post(
        _url("create-organization-structure-department", edition),
        _valid_create_data(create_page, name="Temporary Department"),
    )
    assert delete_create.status_code == 302
    temporary = Department.objects.get(edition=edition, name="Temporary Department")
    delete_editor = client.get(
        _url("organization-structure-department", edition, temporary)
    )
    deletion_form = delete_editor.context["deletion_form"]
    delete_response = client.post(
        _url("delete-organization-structure-department", edition, temporary),
        {
            "expected_version": str(deletion_form["expected_version"].value()),
            "confirmation_name": temporary.name,
            "reason": "Remove this unused synthetic Department.",
        },
    )
    assert delete_response.status_code == 302
    assert delete_response.headers["Location"] == _url(
        "organization-structure", edition
    )
    assert not Department.objects.filter(id=temporary.id).exists()


def test_admin_automatically_places_siblings_and_repairs_duplicate_order() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    events = create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Events",
        expected_code="events",
    )
    ceremonies = create_department_for_test(
        edition=edition,
        actor=administrator,
        parent=events,
        name="Ceremonies",
        expected_code="ceremonies",
        display_order=0,
    )
    maid_cafe = create_department_for_test(
        edition=edition,
        actor=administrator,
        parent=events,
        name="Maid Cafe",
        expected_code="maid-cafe",
        display_order=0,
    )
    create_department_for_test(
        edition=edition,
        actor=administrator,
        parent=events,
        name="Dances",
        expected_code="dances",
        display_order=3,
    )
    client = _client(administrator)

    editor = client.get(_url("organization-structure-department", edition, maid_cafe))
    update_form = editor.context["update_form"]
    assert "display_order" not in update_form.fields
    assert "Display order" not in strip_tags(editor.content.decode())

    repaired = client.post(
        _url("update-organization-structure-department", edition, maid_cafe),
        {
            "name": str(update_form["name"].value()),
            "description": str(update_form["description"].value()),
            "parent_department_id": str(events.id),
            "expected_version": str(update_form["expected_version"].value()),
            "reason": "Keep sibling placement automatic.",
        },
    )

    assert repaired.status_code == 302
    ceremonies.refresh_from_db()
    maid_cafe.refresh_from_db()
    assert ceremonies.display_order == 0
    assert maid_cafe.display_order == 1

    create_page = client.get(_url("organization-structure-department-create", edition))
    create_form = create_page.context["form"]
    assert "display_order" not in create_form.fields
    created = client.post(
        _url("create-organization-structure-department", edition),
        _valid_create_data(
            create_page,
            name="Panels",
            parent_department_id=str(events.id),
        ),
    )

    assert created.status_code == 302
    panels = Department.objects.get(edition=edition, name="Panels")
    assert panels.display_order == 4

    community = create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Community",
        expected_code="community",
    )
    create_department_for_test(
        edition=edition,
        actor=administrator,
        parent=community,
        name="Social",
        expected_code="social",
        display_order=5,
    )
    move_page = client.get(_url("organization-structure-department", edition, panels))
    move_form = move_page.context["update_form"]
    moved = client.post(
        _url("update-organization-structure-department", edition, panels),
        {
            "name": str(move_form["name"].value()),
            "description": str(move_form["description"].value()),
            "parent_department_id": str(community.id),
            "expected_version": str(move_form["expected_version"].value()),
            "reason": "Move this Department under its new parent.",
        },
    )

    assert moved.status_code == 302
    panels.refresh_from_db()
    assert panels.parent_id == community.id
    assert panels.display_order == 6


def test_invalid_create_is_audited_400_and_retains_retry_without_mutation() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Synthetic validation edition")
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    data = _valid_create_data(form_page, name="Registration\nHidden")

    response = client.post(
        _url("create-organization-structure-department", edition),
        data,
    )

    assert response.status_code == 400
    _assert_private_no_store(response)
    assert "Control characters are not allowed" in response.content.decode()
    assert response.context["form"]["retry_key"].value() == data["retry_key"]
    assert not Department.objects.filter(edition=edition).exists()
    assert (
        AuditEvent.objects.filter(
            operation="workforce.structure.read",
            safe_metadata__route_name="organization-structure-department-create",
            safe_metadata__http_method="GET",
        ).count()
        == 1
    )
    post_audit = AuditEvent.objects.filter(
        operation="workforce.structure.read",
        safe_metadata__http_method="POST",
    ).get()
    assert post_audit.safe_metadata["route_name"] == (
        "create-organization-structure-department"
    )


def test_stale_create_retains_bound_controls_and_requires_explicit_reload() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)
    stale_page = client.get(_url("organization-structure-department-create", edition))
    stale_data = _valid_create_data(stale_page, name="Stale Department")
    create_department_for_test(
        edition=edition,
        name="Winning Department",
        expected_code="winning-department",
    )

    response = client.post(
        _url("create-organization-structure-department", edition),
        stale_data,
    )

    assert response.status_code == 409
    _assert_private_no_store(response)
    assert response.context["form"]["expected_version"].value() == "0"
    assert response.context["form"]["retry_key"].value() == stale_data["retry_key"]
    content = response.content.decode()
    assert "reload the latest structure" in content.lower()
    assert "disabled" in content
    assert not Department.objects.filter(
        edition=edition, name="Stale Department"
    ).exists()


def test_internal_validation_and_audit_failures_are_name_free_503() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Private infrastructure edition")
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    valid_data = _valid_create_data(form_page)

    with patch(
        "maru.workforce.views.create_department",
        side_effect=ValidationError({"source_channel": "internal detail"}),
    ):
        internal = client.post(
            _url("create-organization-structure-department", edition),
            valid_data,
        )
    with patch(
        "maru.workforce.views.append_structure_read_audit",
        side_effect=DatabaseError("private audit detail"),
    ):
        unaudited = client.post(
            _url("create-organization-structure-department", edition),
            {**valid_data, "name": "Bad\nName"},
        )

    for response in (internal, unaudited):
        content = response.content.decode()
        assert response.status_code == 503
        _assert_private_no_store(response)
        assert "Organization structure unavailable" in content
        assert edition.name not in content
        assert edition.organization.name not in content
        assert "internal detail" not in content
        assert "private audit detail" not in content


@pytest.mark.parametrize("field_name", ["expected_version", "reason"])
def test_duplicate_critical_post_controls_return_400_without_mutation(
    field_name: str,
) -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    values = _valid_create_data(form_page)
    data = QueryDict(mutable=True)
    for name, value in values.items():
        data.setlist(name, [value])
    data.appendlist(field_name, values[field_name])

    response = client.post(
        _url("create-organization-structure-department", edition),
        data.urlencode(),
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 400
    assert "at most once" in response.content.decode()
    assert not Department.objects.filter(edition=edition).exists()


def test_pathological_integer_post_returns_400_without_mutation() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    data = _valid_create_data(form_page)
    data["expected_version"] = "9" * 10_000

    response = client.post(
        _url("create-organization-structure-department", edition),
        data,
    )

    assert response.status_code == 400
    assert "whole number" in response.content.decode()
    assert not Department.objects.filter(edition=edition).exists()


def test_unknown_and_retired_department_editors_disclose_no_department_name() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Retired private Department",
        expected_code="retired-private-department",
    )
    retire_department_for_test(department=department)
    client = _client(administrator)

    retired = client.get(_url("organization-structure-department", edition, department))
    unknown_url = reverse(
        "organization-structure-department",
        args=[*_route_args(edition), uuid4()],
    )
    unknown = client.get(unknown_url)

    for response in (retired, unknown):
        assert response.status_code == 404
        visible_text = strip_tags(response.content.decode())
        assert department.name not in visible_text
        assert str(department.id) not in visible_text


def test_overview_duplicate_labels_are_disambiguated_without_visible_uuids() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    first = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    second = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations-2",
    )

    response = _client(administrator).get(_url("organization-structure", edition))
    content = response.content.decode()
    visible_text = strip_tags(content)

    assert response.status_code == 200
    assert "Operations \u2014 hierarchy item 1" in visible_text
    assert "Operations \u2014 hierarchy item 2" in visible_text
    assert "Manage Operations Department, hierarchy item 1" in content
    assert "Manage Operations Department, hierarchy item 2" in content
    assert str(first.id) not in visible_text
    assert str(second.id) not in visible_text


def test_editor_dom_ids_are_unique_and_every_label_target_exists() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Registration",
        expected_code="registration",
    )

    response = _client(administrator).get(
        _url("organization-structure-department", edition, department)
    )
    content = response.content.decode()
    identifiers = re.findall(r'\bid="([^"]+)"', content)
    label_targets = re.findall(r'<label\b[^>]*\bfor="([^"]+)"', content)

    assert response.status_code == 200
    assert len(identifiers) == len(set(identifiers))
    assert label_targets
    assert set(label_targets) <= set(identifiers)
    assert {
        "id_department_update_reason",
        "id_department_retire_reason",
        "id_department_delete_reason",
    } <= set(identifiers)


def test_editor_parent_choices_exclude_self_descendants_retired_and_foreign() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    root = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    child = create_department_for_test(
        edition=edition,
        parent=root,
        name="Registration",
        expected_code="registration",
    )
    grandchild = create_department_for_test(
        edition=edition,
        parent=child,
        name="Badges",
        expected_code="badges",
    )
    sibling = create_department_for_test(
        edition=edition,
        name="Security",
        expected_code="security",
    )
    retired = create_department_for_test(
        edition=edition,
        name="Historical",
        expected_code="historical",
    )
    retire_department_for_test(department=retired)
    foreign_edition = EventEditionFactory()
    foreign = create_department_for_test(
        edition=foreign_edition,
        name="Foreign private Department",
        expected_code="foreign-private-department",
    )

    response = _client(administrator).get(
        _url("organization-structure-department", edition, root)
    )
    choices = tuple(
        response.context["update_form"].fields["parent_department_id"].choices
    )
    values = {value for value, _label in choices}

    assert response.status_code == 200
    assert str(sibling.id) in values
    for excluded in (root, child, grandchild, retired, foreign):
        assert str(excluded.id) not in values


def test_editor_parent_summary_disambiguates_duplicate_department_names() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        display_order=10,
    )
    second = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations-2",
        display_order=20,
    )
    child = create_department_for_test(
        edition=edition,
        parent=second,
        name="Registration",
        expected_code="registration",
    )

    response = _client(administrator).get(
        _url("organization-structure-department", edition, child)
    )

    assert response.status_code == 200
    assert "Operations \u2014 hierarchy item 2" in strip_tags(response.content.decode())


def test_concurrent_parent_loss_returns_generic_disabled_retained_choice() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    parent = create_department_for_test(
        edition=edition,
        name="Temporary parent",
        expected_code="temporary-parent",
    )
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    data = _valid_create_data(
        form_page,
        name="Concurrent child",
        parent_department_id=str(parent.id),
    )

    def lose_parent(**_kwargs: object) -> None:
        retire_department_for_test(department=parent)
        raise StructureDepartmentUnavailableError

    with patch("maru.workforce.views.create_department", side_effect=lose_parent):
        response = client.post(
            _url("create-organization-structure-department", edition),
            data,
        )

    content = response.content.decode()
    assert response.status_code == 409
    assert "Previous selection unavailable" in content
    assert re.search(
        rf'<option value="{parent.id}"[^>]*selected[^>]*disabled|'
        rf'<option value="{parent.id}"[^>]*disabled[^>]*selected',
        content,
    )
    assert parent.name not in strip_tags(content)
    assert str(parent.id) not in strip_tags(content)
    assert not Department.objects.filter(
        edition=edition,
        name="Concurrent child",
    ).exists()


@pytest.mark.parametrize(
    "lifecycle",
    [EventEdition.Lifecycle.READY, EventEdition.Lifecycle.LIVE],
)
def test_read_only_lifecycle_child_pages_render_no_structure_forms(
    lifecycle: str,
) -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Registration",
        expected_code="registration",
    )
    _transition_to_lifecycle(
        edition=edition,
        actor=administrator,
        lifecycle=lifecycle,
    )
    client = _client(administrator)

    responses = (
        client.get(_url("organization-structure-template-application", edition)),
        client.get(_url("organization-structure-department-create", edition)),
        client.get(_url("organization-structure-department", edition, department)),
    )

    for response in responses:
        content = response.content.decode()
        assert response.status_code == 200
        _assert_private_no_store(response)
        assert "Structure changes are read-only" in content
        assert _structure_form_actions(content) == []


def test_lifecycle_race_rerender_disables_the_submitted_action() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = _client(administrator)
    form_page = client.get(_url("organization-structure-department-create", edition))
    data = _valid_create_data(form_page)

    def close_lifecycle(**_kwargs: object) -> None:
        _transition_to_lifecycle(
            edition=edition,
            actor=administrator,
            lifecycle=EventEdition.Lifecycle.READY,
        )
        raise StructureLifecycleConflictError

    with patch("maru.workforce.views.create_department", side_effect=close_lifecycle):
        response = client.post(
            _url("create-organization-structure-department", edition),
            data,
        )

    content = response.content.decode()
    button = re.search(
        r'<button type="submit"([^>]*)>Create Department</button>',
        content,
    )
    assert response.status_code == 409
    _assert_private_no_store(response)
    assert response.context["structure_mutations_allowed"] is False
    assert button is not None
    assert "disabled" in button.group(1)
    assert not Department.objects.filter(edition=edition).exists()


def test_foreign_department_editor_is_name_free_like_unknown_and_retired() -> None:
    administrator = _administrator()
    local_edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    foreign = create_department_for_test(
        edition=foreign_edition,
        name="Foreign hidden Department",
        expected_code="foreign-hidden-department",
    )

    response = _client(administrator).get(
        reverse(
            "organization-structure-department",
            args=[*_route_args(local_edition), foreign.id],
        )
    )
    visible_text = strip_tags(response.content.decode())

    assert response.status_code == 404
    assert foreign.name not in visible_text
    assert str(foreign.id) not in visible_text


def test_256_department_overview_has_no_inline_mutations_and_bounded_selector() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    target = create_department_for_test(
        edition=edition,
        name="Department 000",
        expected_code="department-000",
    )
    nodes = (
        DepartmentNode(
            id=target.id,
            parent_id=None,
            code=target.code,
            name=target.name,
            description="Synthetic ceiling target.",
            display_order=0,
            state="active",
            positions=(
                PositionNode(
                    id=uuid4(),
                    reports_to_id=None,
                    reports_to_title=None,
                    code="ceiling-position",
                    title="Ceiling Position",
                    description="Synthetic collapsed Position.",
                    headcount=1,
                    status="open",
                    holders=(),
                ),
            ),
            children=(),
        ),
        *tuple(
            DepartmentNode(
                id=uuid4(),
                parent_id=None,
                code=f"department-{number:03d}",
                name=f"Department {number:03d}",
                description="Synthetic ceiling row.",
                display_order=number,
                state="active",
                positions=(),
                children=(),
            )
            for number in range(1, 256)
        ),
    )
    projection = EditionStructureProjection(
        state="complete",
        aggregate_version=1,
        source=StructureSource(kind="manual"),
        departments=nodes,
    )
    client = _client(administrator)

    with patch(
        "maru.workforce.views.project_edition_structure",
        return_value=projection,
    ):
        overview = client.get(_url("organization-structure", edition))
        editor = client.get(_url("organization-structure-department", edition, target))

    choices = tuple(
        editor.context["update_form"].fields["parent_department_id"].choices
    )
    assert overview.status_code == 200
    assert overview.content.decode().count('class="baseline-structure-node"') == 256
    assert _structure_form_actions(overview.content.decode()) == []
    assert (
        '<details class="workforce-structure-positions-disclosure">'
        in overview.content.decode()
    )
    assert editor.status_code == 200
    assert len(choices) == 256
    assert sum(bool(value) for value, _label in choices) == 255


def test_structure_create_requires_csrf_and_accepts_the_rendered_token() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    client = Client(enforce_csrf_checks=True)
    client.force_login(administrator)
    create_url = _url("create-organization-structure-department", edition)

    rejected = client.post(create_url, {"name": "Forged"})
    assert rejected.status_code == 403
    assert not Department.objects.filter(edition=edition).exists()

    form_page = client.get(_url("organization-structure-department-create", edition))
    form_page.render()
    data = _valid_create_data(form_page, name="CSRF protected Department")
    data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    accepted = client.post(create_url, data)

    assert accepted.status_code == 302
    assert Department.objects.filter(
        edition=edition,
        name="CSRF protected Department",
    ).exists()


def test_depth_32_projection_renders_with_desktop_and_narrow_indent_caps() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    root = create_department_for_test(
        edition=edition,
        name="Depth 01",
        expected_code="depth-01",
    )
    identifiers = [root.id, *(uuid4() for _number in range(31))]
    children: tuple[DepartmentNode, ...] = ()
    for index in reversed(range(32)):
        children = (
            DepartmentNode(
                id=identifiers[index],
                parent_id=identifiers[index - 1] if index else None,
                code=f"depth-{index + 1:02d}",
                name=f"Depth {index + 1:02d}",
                description="Synthetic maximum-depth row.",
                display_order=index,
                state="active",
                positions=(),
                children=children,
            ),
        )
    projection = EditionStructureProjection(
        state="complete",
        aggregate_version=1,
        source=StructureSource(kind="manual"),
        departments=children,
    )

    with patch(
        "maru.workforce.views.project_edition_structure",
        return_value=projection,
    ):
        response = _client(administrator).get(_url("organization-structure", edition))

    stylesheet = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "workforce"
        / "static"
        / "workforce"
        / "organization_structure.css"
    ).read_text(encoding="utf-8")
    assert response.status_code == 200
    assert response.content.decode().count('class="baseline-structure-node"') == 32
    assert ".baseline-structure-tree ol ol ol ol ol ol" in stylesheet
    assert "@media (max-width: 52rem)" in stylesheet
    assert ".baseline-structure-tree ol ol ol ol" in stylesheet


def test_builtin_copy_divergence_remains_explicit_after_independent_edit() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    apply_builtin_structure_template_for_test(
        edition=edition,
        actor=administrator,
    )
    create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Independent addition",
        expected_code="independent-addition",
    )

    response = _client(administrator).get(_url("organization-structure", edition))

    assert response.status_code == 200
    assert "Reference copy changed" in response.content.decode()


@pytest.mark.parametrize(
    "page_name",
    [
        "organization-structure-template-application",
        "organization-structure-department-create",
        "organization-structure-department",
    ],
)
def test_child_page_projection_failures_return_name_free_503(page_name: str) -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Private child dependency edition")
    department = create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Private child dependency Department",
        expected_code="private-child-dependency-department",
    )
    target = (
        _url(page_name, edition, department)
        if page_name == "organization-structure-department"
        else _url(page_name, edition)
    )

    with patch(
        "maru.workforce.views.project_edition_structure",
        side_effect=DatabaseError("private projection failure"),
    ):
        response = _client(administrator).get(target)

    content = response.content.decode()
    assert response.status_code == 503
    assert edition.name not in content
    assert department.name not in content
    assert "private projection failure" not in content


@pytest.mark.parametrize("action", ["template", "update", "retire", "delete"])
def test_remaining_post_query_gates_precede_projection_and_command(action: str) -> None:
    client, edition, _department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with (
        patch(
            "maru.workforce.views.project_edition_structure",
            side_effect=AssertionError("projection must not run"),
        ) as projector,
        patch(f"maru.workforce.views.{service_name}") as command,
    ):
        response = client.post(f"{target}?unsupported=1", data)

    assert response.status_code == 400
    assert edition.name not in response.content.decode()
    projector.assert_not_called()
    command.assert_not_called()


@pytest.mark.parametrize(
    "action",
    ["template", "create", "update", "retire", "delete"],
)
def test_post_preflight_projection_failures_are_name_free_503(action: str) -> None:
    client, edition, department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with (
        patch(
            "maru.workforce.views.project_edition_structure",
            side_effect=DatabaseError("private preflight projection failure"),
        ),
        patch(f"maru.workforce.views.{service_name}") as command,
    ):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 503
    assert edition.name not in content
    if department is not None:
        assert department.name not in content
    assert "private preflight projection failure" not in content
    command.assert_not_called()


@pytest.mark.parametrize("action", ["template", "update", "retire", "delete"])
def test_remaining_invalid_action_forms_rerender_audited_400(action: str) -> None:
    client, edition, department, target, _data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(f"maru.workforce.views.{service_name}") as command:
        response = client.post(target, {})

    content = response.content.decode()
    assert response.status_code == 400
    assert "Review the highlighted values" in content
    assert edition.name in content
    if department is not None:
        assert department.name in content
    command.assert_not_called()


@pytest.mark.parametrize(
    "action",
    ["template", "create", "update", "retire", "delete"],
)
def test_command_field_validation_maps_to_audited_field_local_400(
    action: str,
) -> None:
    client, edition, department, target, data, service_name, safe_field = (
        _valid_action_case(action)
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=ValidationError(
            {safe_field: "Synthetic command-level field validation."}
        ),
    ):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 400
    assert "Synthetic command-level field validation" in content
    assert edition.name in content
    if department is not None:
        assert department.name in content


@pytest.mark.parametrize(
    ("action", "error"),
    [
        ("template", ValidationError("private non-field command detail")),
        ("update", ValidationError({"source_channel": "private internal detail"})),
        ("retire", ValidationError({"source_channel": "private internal detail"})),
        ("delete", ValidationError({"source_channel": "private internal detail"})),
    ],
)
def test_remaining_internal_command_validation_is_name_free_503(
    action: str,
    error: ValidationError,
) -> None:
    client, edition, department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(f"maru.workforce.views.{service_name}", side_effect=error):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 503
    assert edition.name not in content
    if department is not None:
        assert department.name not in content
    assert "private internal detail" not in content
    assert "private non-field command detail" not in content


@pytest.mark.parametrize(
    "action",
    ["template", "create", "update", "retire", "delete"],
)
def test_command_authorization_race_returns_uniform_403(action: str) -> None:
    client, _edition, _department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=StructureAuthorizationDeniedError,
    ):
        response = client.post(target, data)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("template", 404), ("update", 409), ("retire", 404), ("delete", 404)],
)
def test_remaining_command_target_loss_is_safely_adapted(
    action: str,
    expected_status: int,
) -> None:
    client, edition, department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=StructureDepartmentUnavailableError,
    ):
        response = client.post(target, data)

    assert response.status_code == expected_status
    if expected_status == 404:
        visible_text = strip_tags(response.content.decode())
        assert edition.name not in visible_text
        if department is not None:
            assert department.name not in visible_text
    else:
        assert "Reload the latest record" in response.content.decode()


@pytest.mark.parametrize("action", ["template", "update", "retire", "delete"])
def test_remaining_version_conflicts_rerender_disabled_409(action: str) -> None:
    client, _edition, _department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=StructureVersionConflictError,
    ):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 409
    assert "reload" in content.lower()
    assert "disabled" in content


@pytest.mark.parametrize(
    ("error_type", "expected_text"),
    [
        (StructureRetryConflictError, "retry identifier"),
        (StructureStateConflictError, "stored structure state"),
        (StructureDependencyConflictError, "retained dependencies"),
        (StructureLimitConflictError, "safe size or depth limit"),
    ],
)
def test_create_conflict_messages_are_specific_and_safe(
    error_type: type[Exception],
    expected_text: str,
) -> None:
    client, _edition, _department, target, data, service_name, _field = (
        _valid_action_case("create")
    )

    with patch(f"maru.workforce.views.{service_name}", side_effect=error_type):
        response = client.post(target, data)

    assert response.status_code == 409
    assert expected_text in response.content.decode()


@pytest.mark.parametrize(
    "action",
    ["template", "create", "update", "retire", "delete"],
)
def test_command_dependency_failures_return_name_free_503(action: str) -> None:
    client, edition, department, target, data, service_name, _field = (
        _valid_action_case(action)
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=DatabaseError("private command dependency detail"),
    ):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 503
    assert edition.name not in content
    if department is not None:
        assert department.name not in content
    assert "private command dependency detail" not in content


def test_retirement_dependency_unavailability_returns_name_free_503() -> None:
    """The HTML adapter must not disclose the failed Programme dependency probe."""
    client, edition, department, target, data, service_name, _field = (
        _valid_action_case("retire")
    )

    with patch(
        f"maru.workforce.views.{service_name}",
        side_effect=StructureDependencyUnavailableError(
            "private Programme dependency detail"
        ),
    ):
        response = client.post(target, data)

    content = response.content.decode()
    assert response.status_code == 503
    assert edition.name not in content
    assert department is not None
    assert department.name not in content
    assert "private Programme dependency detail" not in content


def test_update_noop_uses_informational_success_without_new_structure_version() -> None:
    client, edition, department, target, data, _service_name, _field = (
        _valid_action_case("update")
    )
    assert department is not None
    version_before = EditionStructureControl.objects.get(
        edition=edition
    ).aggregate_version

    response = client.post(target, data, follow=True)

    assert response.status_code == 200
    assert "No Department details changed" in response.content.decode()
    assert (
        EditionStructureControl.objects.get(edition=edition).aggregate_version
        == version_before
    )


def test_populated_template_page_is_explicitly_ineligible_and_has_no_form() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    create_department_for_test(
        edition=edition,
        actor=administrator,
        name="Existing structure evidence",
        expected_code="existing-structure-evidence",
    )

    response = _client(administrator).get(
        _url("organization-structure-template-application", edition)
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "available only for an empty structure" in content
    assert _structure_form_actions(content) == []


def test_transitional_legacy_structure_explains_its_read_only_control_gap() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    transitional = EditionStructureProjection(
        state="complete",
        aggregate_version=0,
        source=StructureSource(kind="legacy_existing"),
        departments=(),
    )

    with patch(
        "maru.workforce.views.project_edition_structure",
        return_value=transitional,
    ):
        response = _client(administrator).get(_url("organization-structure", edition))

    assert response.status_code == 200
    assert "deployment backfill establishes" in response.content.decode()
    assert (
        "awaiting its durable deployment control"
        in response.context["structure_mutation_blocked_reason"]
    )


def test_closed_organization_explains_structure_read_only_lifecycle() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(
        series__organization__lifecycle=Organization.Lifecycle.CLOSED
    )

    response = _client(administrator).get(_url("organization-structure", edition))

    assert response.status_code == 200
    assert "organization lifecycle keeps" in response.content.decode()


@pytest.mark.parametrize(
    ("capability_code", "denied_occurrence"),
    [
        ("workforce.view_structure", 1),
        ("workforce.view_structure", 2),
        ("workforce.view_structure", 3),
        ("workforce.manage_structure", 3),
    ],
)
def test_each_structure_authorization_stage_can_fail_closed_without_names(
    capability_code: str,
    denied_occurrence: int,
) -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Private staged authorization edition")
    call_count = 0

    def decide_with_staged_denial(**kwargs: Any) -> PolicyDecision:
        nonlocal call_count
        decision = decide_policy(**kwargs)
        if kwargs.get("capability_code") == capability_code:
            call_count += 1
            if call_count == denied_occurrence:
                return PolicyDecision(
                    allowed=False,
                    fields=frozenset(),
                    obligations=frozenset(),
                    reason_code="synthetic_staged_denial",
                )
        return decision

    with patch("maru.workforce.views.decide", side_effect=decide_with_staged_denial):
        response = _client(administrator).get(
            _url("organization-structure-department-create", edition)
        )

    assert response.status_code == 403
    assert edition.name not in response.content.decode()


@pytest.mark.parametrize("denied_occurrence", [1, 2, 3])
def test_each_field_projection_fence_can_fail_closed_without_names(
    denied_occurrence: int,
) -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Private staged projection edition")
    call_count = 0

    def enforce_staged_projection(**_kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == denied_occurrence:
            raise FieldProjectionDeniedError

    with patch(
        "maru.workforce.views.require_complete_projection",
        side_effect=enforce_staged_projection,
    ):
        response = _client(administrator).get(
            _url("organization-structure-department-create", edition)
        )

    assert response.status_code == 403
    assert edition.name not in response.content.decode()


def test_missing_resolved_organization_target_fails_as_name_free_dependency() -> None:
    administrator = _administrator()
    edition = EventEditionFactory(name="Private missing organization target edition")

    with patch("maru.workforce.views.resolve_organization_target", return_value=None):
        response = _client(administrator).get(_url("organization-structure", edition))

    assert response.status_code == 503
    assert edition.name not in response.content.decode()
