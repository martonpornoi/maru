from __future__ import annotations

import hashlib
import json
import re
from dataclasses import FrozenInstanceError

import pytest

from maru.workforce.structure_templates import (
    BUILTIN_STRUCTURE_TEMPLATES,
    MARUCON_REFERENCE_V1,
    BuiltinStructureTemplate,
    StructureDepartmentDefinition,
    UnknownBuiltinStructureTemplateError,
    get_builtin_structure_template,
)

EXPECTED_DEPARTMENTS = (
    ("convention-coordination", "Convention Coordination", None),
    ("attendee-services", "Attendee Services", "convention-coordination"),
    ("registration", "Registration", "convention-coordination"),
    ("programme", "Programme", "convention-coordination"),
    ("stage-production", "Stage Production", "convention-coordination"),
    ("venue-operations", "Venue Operations", "convention-coordination"),
    ("logistics", "Logistics", "convention-coordination"),
    ("volunteer-support", "Volunteer Support", "convention-coordination"),
    ("safety", "Safety", "convention-coordination"),
    ("accessibility", "Accessibility", "convention-coordination"),
    ("technology", "Technology", "convention-coordination"),
    ("communications", "Communications", "convention-coordination"),
    ("design-publications", "Design & Publications", "convention-coordination"),
    ("exhibitors", "Exhibitors", "convention-coordination"),
    ("charity", "Charity", "convention-coordination"),
    ("guest-relations", "Guest Relations", "convention-coordination"),
    ("accommodation", "Accommodation", "convention-coordination"),
    ("hospitality", "Hospitality", "convention-coordination"),
    ("finance-procurement", "Finance & Procurement", "convention-coordination"),
    ("partnerships", "Partnerships", "convention-coordination"),
    ("live-operations", "Live Operations", "convention-coordination"),
    ("archive-handover", "Archive & Handover", "convention-coordination"),
)


def test_marucon_reference_v1_has_the_accepted_exact_taxonomy() -> None:
    template = MARUCON_REFERENCE_V1

    assert template.identifier == "marucon-reference@1"
    assert (
        tuple(
            (department.code, department.name, department.parent_code)
            for department in template.departments
        )
        == EXPECTED_DEPARTMENTS
    )
    assert tuple(
        department.display_order for department in template.departments
    ) == tuple(range(22))
    assert len(template.departments) == 22
    assert all(department.description for department in template.departments)
    assert "Executive Board" not in {
        department.name for department in template.departments
    }


def test_marucon_reference_v1_fields_are_unique_and_bounded() -> None:
    departments = MARUCON_REFERENCE_V1.departments

    assert len({department.code for department in departments}) == len(departments)
    assert len({department.name.casefold() for department in departments}) == len(
        departments
    )
    assert len({department.display_order for department in departments}) == len(
        departments
    )
    assert all(
        re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", department.code)
        and len(department.code) <= 80
        and 1 <= len(department.name) <= 160
        and len(department.description) <= 1_000
        and 0 <= department.display_order <= 65_535
        for department in departments
    )


def test_marucon_reference_v1_canonical_json_and_digest_are_pinned() -> None:
    template = MARUCON_REFERENCE_V1
    decoded = template.canonical_json.decode("utf-8")
    payload = json.loads(decoded)

    assert "Design & Publications" in decoded
    assert (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        == template.canonical_json
    )
    assert hashlib.sha256(template.canonical_json).hexdigest() == template.sha256_digest
    assert (
        template.sha256_digest
        == "55f4091787215fd9eef5cc1266806a1450dd6e5449d50864340601f5ec2398ee"
    )


def test_catalog_and_template_content_are_immutable() -> None:
    template = MARUCON_REFERENCE_V1

    with pytest.raises(TypeError):
        BUILTIN_STRUCTURE_TEMPLATES["another@1"] = template  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        template.version = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        template.departments[0].name = "Changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        template.departments[0] = template.departments[0]  # type: ignore[index]


def test_catalog_uses_exact_identifiers_without_aliases() -> None:
    assert tuple(BUILTIN_STRUCTURE_TEMPLATES) == ("marucon-reference@1",)
    assert get_builtin_structure_template("marucon-reference@1") is MARUCON_REFERENCE_V1

    with pytest.raises(UnknownBuiltinStructureTemplateError):
        get_builtin_structure_template("marucon-reference")


@pytest.mark.parametrize(
    "departments",
    [
        (),
        (
            StructureDepartmentDefinition("root-a", "Root A", "A", None, 0),
            StructureDepartmentDefinition("root-b", "Root B", "B", None, 1),
        ),
        (
            StructureDepartmentDefinition(
                "executive-board", "Executive Board", "Governance", None, 0
            ),
        ),
        (
            StructureDepartmentDefinition(
                "child", "Child", "Child", "missing-parent", 0
            ),
        ),
    ],
)
def test_invalid_builtin_templates_fail_during_construction(
    departments: tuple[StructureDepartmentDefinition, ...],
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        BuiltinStructureTemplate(
            code="test-reference",
            version=1,
            departments=departments,
        )


@pytest.mark.parametrize(
    "department",
    [
        StructureDepartmentDefinition("Not-A-Slug", "Root", "Valid", None, 0),
        StructureDepartmentDefinition("root", " Root", "Valid", None, 0),
        StructureDepartmentDefinition("root", "Root", " Invalid", None, 0),
        StructureDepartmentDefinition("root", "Root", "Valid", None, -1),
    ],
    ids=("code", "name", "description", "display-order"),
)
def test_department_definition_bounds_fail_during_template_construction(
    department: StructureDepartmentDefinition,
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        BuiltinStructureTemplate(
            code="test-reference",
            version=1,
            departments=(department,),
        )


@pytest.mark.parametrize(
    ("code", "version"),
    [
        ("Not-A-Slug", 1),
        ("test-reference", 0),
    ],
    ids=("code", "version"),
)
def test_template_identity_bounds_fail_during_construction(
    code: str,
    version: int,
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        BuiltinStructureTemplate(
            code=code,
            version=version,
            departments=(
                StructureDepartmentDefinition("root", "Root", "Valid", None, 0),
            ),
        )


@pytest.mark.parametrize(
    "departments",
    [
        (
            StructureDepartmentDefinition("root", "Root", "Valid", None, 0),
            StructureDepartmentDefinition("root", "Child", "Valid", "root", 1),
        ),
        (
            StructureDepartmentDefinition("root", "Root", "Valid", None, 0),
            StructureDepartmentDefinition("child", "ROOT", "Valid", "root", 1),
        ),
        (
            StructureDepartmentDefinition("root", "Root", "Valid", None, 0),
            StructureDepartmentDefinition("child", "Child", "Valid", "root", 0),
        ),
    ],
    ids=("duplicate-code", "duplicate-name", "duplicate-display-order"),
)
def test_duplicate_department_identity_fails_during_template_construction(
    departments: tuple[StructureDepartmentDefinition, ...],
) -> None:
    with pytest.raises(ValueError, match=r".+"):
        BuiltinStructureTemplate(
            code="test-reference",
            version=1,
            departments=departments,
        )
