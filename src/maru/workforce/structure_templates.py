"""Immutable built-in Department structure templates.

The names and order in ``marucon-reference@1`` form a repository-owned,
fictional convention taxonomy. Its descriptions derive from Maru's product
requirements rather than an external convention, public roster, or copied
organization chart. They describe workflows, not people, private reporting
lines, or authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from maru.organizations.representation_catalog import (
    ACCOUNTABLE_REPRESENTATION_NAMES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_CODE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_MAX_CODE_LENGTH = 80
_MAX_NAME_LENGTH = 160
_MAX_DESCRIPTION_LENGTH = 1_000
_MAX_DISPLAY_ORDER = 65_535


@dataclass(frozen=True, slots=True)
class StructureDepartmentDefinition:
    """One immutable Department definition inside a built-in template.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    name
        The human-readable name to normalize or persist.
    description
        The human-readable description shown to authorized readers.
    parent_code
        The stable parent code from the relevant closed catalog.
    display_order
        The deterministic display position within the owning collection.
    """

    code: str
    name: str
    description: str
    parent_code: str | None
    display_order: int


@dataclass(frozen=True, slots=True)
class BuiltinStructureTemplate:
    """A validated immutable template with pinned canonical content evidence.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    version
        The version number associated with the supplied record or contract.
    departments
        The departments retained in this immutable projection.
    canonical_json
        The canonical json retained in this immutable projection.
    sha256_digest
        The canonical digest used to verify sha256.
    """

    code: str
    version: int
    departments: tuple[StructureDepartmentDefinition, ...]
    canonical_json: bytes = field(init=False, repr=False)
    sha256_digest: str = field(init=False)

    def __post_init__(self) -> None:
        """Implement `__post_init__` for BuiltinStructureTemplate."""
        _validate_template(self)
        canonical_json = _canonical_json(self)
        object.__setattr__(self, "canonical_json", canonical_json)
        object.__setattr__(
            self,
            "sha256_digest",
            hashlib.sha256(canonical_json).hexdigest(),
        )

    @property
    def identifier(self) -> str:
        """Return the closed external template identifier.

        Returns
        -------
        str
            The normalized text for identifier.
        """
        return f"{self.code}@{self.version}"


class UnknownBuiltinStructureTemplateError(LookupError):
    """Raised when a caller requests a template outside the code-owned catalog."""


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _is_bounded_code(value: str) -> bool:
    return bool(_CODE_PATTERN.fullmatch(value)) and len(value) <= _MAX_CODE_LENGTH


def _validate_department_fields(department: StructureDepartmentDefinition) -> None:
    if not _is_bounded_code(department.code):
        raise ValueError("Department codes must be bounded lower-case slugs.")
    if (
        not department.name
        or department.name != department.name.strip()
        or len(department.name) > _MAX_NAME_LENGTH
        or _contains_control_character(department.name)
    ):
        raise ValueError("Department names must satisfy the closed input bounds.")
    if department.name.casefold() in ACCOUNTABLE_REPRESENTATION_NAMES:
        raise ValueError("An accountable representation is not a Workforce Department.")
    if (
        len(department.description) > _MAX_DESCRIPTION_LENGTH
        or department.description != department.description.strip()
        or _contains_control_character(department.description)
    ):
        raise ValueError("Department descriptions must satisfy the input bounds.")
    if type(department.display_order) is not int or not (
        0 <= department.display_order <= _MAX_DISPLAY_ORDER
    ):
        raise ValueError("Department display order is outside the accepted range.")


def _validate_template(template: BuiltinStructureTemplate) -> None:
    if not _is_bounded_code(template.code):
        raise ValueError("Template code must be a bounded lower-case slug.")
    if type(template.version) is not int or template.version < 1:
        raise ValueError("Template version must be a positive integer.")
    if not isinstance(template.departments, tuple) or not template.departments:
        raise ValueError("A built-in template requires an immutable Department tuple.")

    seen_codes: set[str] = set()
    seen_names: set[str] = set()
    seen_display_orders: set[int] = set()
    root_count = 0
    for department in template.departments:
        _validate_department_fields(department)
        if department.code in seen_codes:
            raise ValueError("Department codes must be unique within a template.")
        normalized_name = department.name.casefold()
        if normalized_name in seen_names:
            raise ValueError("Department names must be unique within a template.")
        if department.display_order in seen_display_orders:
            raise ValueError(
                "Department display orders must be unique within a template."
            )
        if department.parent_code is None:
            root_count += 1
        elif department.parent_code not in seen_codes:
            raise ValueError(
                "A Department parent must precede its child in the template."
            )

        seen_codes.add(department.code)
        seen_names.add(normalized_name)
        seen_display_orders.add(department.display_order)

    if root_count != 1:
        raise ValueError("A built-in structure template requires exactly one root.")


def _canonical_json(template: BuiltinStructureTemplate) -> bytes:
    payload = {
        "code": template.code,
        "departments": [
            {
                "code": department.code,
                "description": department.description,
                "display_order": department.display_order,
                "name": department.name,
                "parent_code": department.parent_code,
            }
            for department in template.departments
        ],
        "version": template.version,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


_BOARD_DESCRIPTION = (
    "Readiness, risks, approvals, cross-department blockers, and material changes."
)
_REGISTRATION_DESCRIPTION = (
    "Attendee lookup, payment and check-in state, badges, service requests, "
    "knowledge, and surge staffing."
)
_PROGRAMME_DESCRIPTION = (
    "Calls, proposals, review, readiness, timetable, hosts, and public copy."
)
_TECH_DESCRIPTION = (
    "Riders, cues, equipment, rehearsals, setup and teardown, operator shifts, "
    "and media consent."
)
_SAFETY_DESCRIPTION = (
    "Narrowly scoped cases, duty routing, access policy, retention, and ordinary "
    "minimum-disclosure tasks."
)
_HR_DESCRIPTION = (
    "Opportunities, applications, onboarding, qualifications, assignments, "
    "availability, hours, and handover."
)
_OPERATIONS_DESCRIPTION = (
    "Storage, boxes, kits, manifests, movements, maintenance, deployment, and return."
)
_APPLICATIONS_DESCRIPTION = (
    "Configured applications, allocations, content classification, inventory, "
    "staffing, payments, and reconciliation."
)
_CONTENT_DESCRIPTION = (
    "Briefs, assets, approvals, rights, publishing schedule, and public content "
    "renditions."
)
_SERVICE_DESCRIPTION = (
    "Service capacity, spaces, programme dependencies, queues, shifts, and run of show."
)


def _department(
    code: str,
    name: str,
    description: str,
    display_order: int,
    *,
    parent_code: str | None = "convention-coordination",
) -> StructureDepartmentDefinition:
    return StructureDepartmentDefinition(
        code=code,
        name=name,
        description=description,
        parent_code=parent_code,
        display_order=display_order,
    )


MARUCON_REFERENCE_V1 = BuiltinStructureTemplate(
    code="marucon-reference",
    version=1,
    departments=(
        _department(
            "convention-coordination",
            "Convention Coordination",
            _BOARD_DESCRIPTION,
            0,
            parent_code=None,
        ),
        _department(
            "attendee-services",
            "Attendee Services",
            _REGISTRATION_DESCRIPTION,
            1,
        ),
        _department(
            "registration",
            "Registration",
            _REGISTRATION_DESCRIPTION,
            2,
        ),
        _department(
            "programme",
            "Programme",
            _PROGRAMME_DESCRIPTION,
            3,
        ),
        _department(
            "stage-production",
            "Stage Production",
            _TECH_DESCRIPTION,
            4,
        ),
        _department(
            "venue-operations",
            "Venue Operations",
            _SERVICE_DESCRIPTION,
            5,
        ),
        _department(
            "logistics",
            "Logistics",
            _OPERATIONS_DESCRIPTION,
            6,
        ),
        _department(
            "volunteer-support",
            "Volunteer Support",
            _HR_DESCRIPTION,
            7,
        ),
        _department(
            "safety",
            "Safety",
            _SAFETY_DESCRIPTION,
            8,
        ),
        _department(
            "accessibility",
            "Accessibility",
            _SAFETY_DESCRIPTION,
            9,
        ),
        _department(
            "technology",
            "Technology",
            _OPERATIONS_DESCRIPTION,
            10,
        ),
        _department(
            "communications",
            "Communications",
            _CONTENT_DESCRIPTION,
            11,
        ),
        _department(
            "design-publications",
            "Design & Publications",
            _CONTENT_DESCRIPTION,
            12,
        ),
        _department(
            "exhibitors",
            "Exhibitors",
            _APPLICATIONS_DESCRIPTION,
            13,
        ),
        _department(
            "charity",
            "Charity",
            _APPLICATIONS_DESCRIPTION,
            14,
        ),
        _department(
            "guest-relations",
            "Guest Relations",
            _SERVICE_DESCRIPTION,
            15,
        ),
        _department(
            "accommodation",
            "Accommodation",
            _SERVICE_DESCRIPTION,
            16,
        ),
        _department(
            "hospitality",
            "Hospitality",
            _SERVICE_DESCRIPTION,
            17,
        ),
        _department(
            "finance-procurement",
            "Finance & Procurement",
            _APPLICATIONS_DESCRIPTION,
            18,
        ),
        _department(
            "partnerships",
            "Partnerships",
            _APPLICATIONS_DESCRIPTION,
            19,
        ),
        _department(
            "live-operations",
            "Live Operations",
            _OPERATIONS_DESCRIPTION,
            20,
        ),
        _department(
            "archive-handover",
            "Archive & Handover",
            _CONTENT_DESCRIPTION,
            21,
        ),
    ),
)

BUILTIN_STRUCTURE_TEMPLATES: Mapping[str, BuiltinStructureTemplate] = MappingProxyType(
    {MARUCON_REFERENCE_V1.identifier: MARUCON_REFERENCE_V1}
)


def get_builtin_structure_template(identifier: str) -> BuiltinStructureTemplate:
    """Resolve one exact code-owned template identifier without aliases.

    Parameters
    ----------
    identifier : str
        The identifier evaluated while get builtin structure template.

    Returns
    -------
    BuiltinStructureTemplate
        The resolved BuiltinStructureTemplate for the requested scope.

    Raises
    ------
    UnknownBuiltinStructureTemplateError
        If the operation encounters a unknown builtin structure template
        condition.
    """
    try:
        return BUILTIN_STRUCTURE_TEMPLATES[identifier]
    except KeyError as error:
        raise UnknownBuiltinStructureTemplateError(identifier) from error
