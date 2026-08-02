from uuid import UUID, uuid4

import pytest
from django.http import QueryDict

from maru.workforce.forms import (
    DepartmentCreationForm,
    DepartmentDeletionForm,
    DepartmentRetirementForm,
    DepartmentUpdateForm,
    StructureTemplateApplicationForm,
)


def _create_data(**overrides: str) -> dict[str, str]:
    data = {
        "name": "Registration",
        "description": "Attendee intake and badge support.",
        "parent_department_id": "",
        "display_order": "20",
        "expected_version": "0",
        "reason": "Establish the operational structure.",
        "retry_key": str(uuid4()),
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("display_order", "+1"),
        ("display_order", " 1"),
        ("display_order", "01"),
        ("display_order", "1.0"),
        ("display_order", "\uff11"),
        ("expected_version", "-1"),
    ],
)
def test_structure_integer_fields_require_canonical_ascii_base10(
    field_name: str,
    value: str,
) -> None:
    form = DepartmentCreationForm(
        _create_data(**{field_name: value}),
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert field_name in form.errors


@pytest.mark.parametrize(
    "retry_key",
    [
        "A7CBF0A8-B0B1-4991-A650-6DD8E12E8810",
        "a7cbf0a8b0b14991a6506dd8e12e8810",
        "{a7cbf0a8-b0b1-4991-a650-6dd8e12e8810}",
        "not-a-uuid",
    ],
)
def test_structure_retry_key_requires_canonical_lower_case_hyphenated_uuid(
    retry_key: str,
) -> None:
    form = DepartmentCreationForm(
        _create_data(retry_key=retry_key),
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "retry_key" in form.errors


def test_structure_uuid_field_accepts_future_version_agnostic_canonical_shape() -> None:
    nil_uuid = "00000000-0000-0000-0000-000000000000"
    form = DepartmentCreationForm(
        _create_data(retry_key=nil_uuid),
        parent_choices=(),
        expected_version=0,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["retry_key"] == UUID(nil_uuid)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("name", "Registration\nHidden"),
        ("description", "Attendee intake\tprivate"),
        ("reason", "Create\rDepartment"),
    ],
)
def test_structure_text_fields_do_not_strip_forbidden_controls_before_validation(
    field_name: str,
    value: str,
) -> None:
    form = DepartmentCreationForm(
        _create_data(**{field_name: value}),
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "Control characters are not allowed" in str(form.errors[field_name])


def test_department_parent_is_one_closed_scoped_choice() -> None:
    permitted_parent = uuid4()
    foreign_parent = uuid4()
    form = DepartmentCreationForm(
        _create_data(parent_department_id=str(foreign_parent)),
        parent_choices=((str(permitted_parent), "Helper Board - top-level"),),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "available Department" in str(form.errors["parent_department_id"])
    assert str(foreign_parent) not in str(form.errors)


def test_template_application_accepts_only_version_zero_and_exact_confirmation() -> (
    None
):
    form = StructureTemplateApplicationForm(
        {
            "template": "awoostria-reference@1",
            "expected_version": "1",
            "confirmation_name": "Synthetic Edition ",
            "reason": "Copy the reference.",
            "retry_key": str(uuid4()),
        },
        edition_name="Synthetic Edition",
        expected_version=0,
    )

    assert not form.is_valid()
    assert "expected_version" in form.errors
    assert "confirmation_name" in form.errors


def test_creation_form_rejects_unknown_scope_and_preserves_retry_value() -> None:
    retry_key = str(uuid4())
    form = DepartmentCreationForm(
        _create_data(
            retry_key=retry_key,
            organization_id=str(uuid4()),
        ),
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "unsupported input fields" in str(form.non_field_errors()).lower()
    assert form["retry_key"].value() == retry_key


def test_department_action_forms_use_unique_unprefixed_dom_identifiers() -> None:
    update = DepartmentUpdateForm(
        parent_choices=(),
        expected_version=3,
    )
    retirement = DepartmentRetirementForm(expected_version=3)
    deletion = DepartmentDeletionForm(
        expected_version=3,
        department_name="Registration",
    )

    identifiers = {
        update["reason"].id_for_label,
        retirement["reason"].id_for_label,
        deletion["reason"].id_for_label,
    }
    assert len(identifiers) == 3
    assert all(identifier.startswith("id_department_") for identifier in identifiers)
    assert "No parent \u2014 top-level Department" in str(update)


def test_existing_department_actions_require_a_positive_structure_version() -> None:
    update = DepartmentUpdateForm(
        {
            "name": "Registration",
            "description": "",
            "parent_department_id": "",
            "display_order": "0",
            "expected_version": "0",
            "reason": "Update the Department.",
        },
        parent_choices=(),
        expected_version=1,
    )
    retirement = DepartmentRetirementForm(
        {"expected_version": "0", "reason": "Retire the Department."},
        expected_version=1,
    )
    deletion = DepartmentDeletionForm(
        {
            "expected_version": "0",
            "confirmation_name": "Registration",
            "reason": "Delete the unused Department.",
        },
        expected_version=1,
        department_name="Registration",
    )

    for form in (update, retirement, deletion):
        assert not form.is_valid()
        assert "expected_version" in form.errors


def test_deletion_confirmation_is_exact_and_field_local() -> None:
    form = DepartmentDeletionForm(
        {
            "expected_version": "1",
            "confirmation_name": "Registration ",
            "reason": "Delete the unused Department.",
        },
        expected_version=1,
        department_name="Registration",
    )

    assert not form.is_valid()
    assert "confirmation_name" in form.errors
    assert "exact current name" in str(form.errors["confirmation_name"])


def test_unavailable_bound_parent_is_retained_as_generic_disabled_option() -> None:
    unavailable_parent = str(uuid4())
    form = DepartmentUpdateForm(
        _create_data(
            parent_department_id=unavailable_parent,
            expected_version="2",
        ),
        parent_choices=(),
        expected_version=2,
    )
    assert not form.is_valid()

    form.set_parent_choices((), retain_bound_unavailable=True)
    rendered = str(form["parent_department_id"])

    assert "Previous selection unavailable" in rendered
    assert "disabled" in rendered
    assert f">{unavailable_parent}<" not in rendered


@pytest.mark.parametrize("field_name", ["expected_version", "retry_key", "reason"])
def test_creation_rejects_duplicate_single_value_controls(field_name: str) -> None:
    values = _create_data()
    data = QueryDict(mutable=True)
    for name, value in values.items():
        data.setlist(name, [value])
    data.appendlist(field_name, values[field_name])

    form = DepartmentCreationForm(
        data,
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "at most once" in str(form.non_field_errors())


def test_deletion_rejects_duplicate_exact_confirmation() -> None:
    data = QueryDict(mutable=True)
    data.setlist("expected_version", ["1"])
    data.setlist("confirmation_name", ["Registration", "Registration"])
    data.setlist("reason", ["Delete this unused synthetic Department."])

    form = DepartmentDeletionForm(
        data,
        expected_version=1,
        department_name="Registration",
    )

    assert not form.is_valid()
    assert "at most once" in str(form.non_field_errors())


def test_structure_integer_field_rejects_pathological_digit_input() -> None:
    form = DepartmentCreationForm(
        _create_data(expected_version="9" * 10_000),
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert "expected_version" in form.errors
