from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from maru.domain import (
    AccessAccount,
    FormField,
    PermissionKey,
    Project,
    Role,
    Subproject,
    SubprojectKind,
)


class ProjectImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedRoom:
    name: str
    capacity: int | None = None
    properties: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedRoomCombination:
    name: str
    room_names: tuple[str, ...] = ()
    capacity: int | None = None


@dataclass(frozen=True)
class ImportedHotel:
    name: str
    rooms: tuple[ImportedRoom, ...] = ()
    combinations: tuple[ImportedRoomCombination, ...] = ()


@dataclass(frozen=True)
class ImportedEventGroup:
    name: str
    slug: str
    description: str = ""
    requires_order: bool = False


@dataclass(frozen=True)
class ImportedSubproject:
    subproject: Subproject
    fields: tuple[FormField, ...] = ()


@dataclass(frozen=True)
class ImportedRoleDefinition:
    key: str
    name: str
    permissions: tuple[str, ...] = ()
    description: str = ""
    active: bool = True


@dataclass(frozen=True)
class ImportedRoleAssignment:
    email: str
    role_key: str
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedBenefit:
    key: str
    label: str
    target: str
    description: str = ""
    active: bool = True


@dataclass(frozen=True)
class ImportedStatusBenefitGrant:
    status_type: str
    status_value: str
    benefit_key: str


@dataclass(frozen=True)
class ImportedLabelOverride:
    key: str
    label: str


@dataclass(frozen=True)
class ImportedProjectConfig:
    project: Project
    accounts: tuple[AccessAccount, ...]
    hotels: tuple[ImportedHotel, ...]
    event_groups: tuple[ImportedEventGroup, ...]
    subprojects: tuple[ImportedSubproject, ...]
    role_definitions: tuple[ImportedRoleDefinition, ...] = ()
    role_assignments: tuple[ImportedRoleAssignment, ...] = ()
    benefits: tuple[ImportedBenefit, ...] = ()
    status_benefits: tuple[ImportedStatusBenefitGrant, ...] = ()
    labels: tuple[ImportedLabelOverride, ...] = ()


def load_project_yaml(path: str | Path) -> ImportedProjectConfig:
    with Path(path).open(encoding="utf-8") as handle:
        return parse_project_yaml(handle.read())


def parse_project_yaml(content: str) -> ImportedProjectConfig:
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        msg = "Project YAML must contain a mapping at the top level"
        raise ProjectImportError(msg)

    return ImportedProjectConfig(
        project=_parse_project(_required_mapping(data, "project")),
        accounts=_parse_accounts(data.get("accounts", [])),
        hotels=_parse_hotels(data.get("hotels", [])),
        event_groups=_parse_event_groups(data.get("event_groups", [])),
        subprojects=_parse_subprojects(data.get("subprojects", [])),
        role_definitions=_parse_role_definitions(data.get("roles", [])),
        role_assignments=_parse_role_assignments(data.get("role_assignments", [])),
        benefits=_parse_benefits(data.get("benefits", [])),
        status_benefits=_parse_status_benefits(data.get("status_benefits", [])),
        labels=_parse_labels(data.get("labels", [])),
    )


def _required_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        msg = f"Missing required mapping: {key}"
        raise ProjectImportError(msg)
    return value


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Missing required string: {key}"
        raise ProjectImportError(msg)
    return value.strip()


def _parse_project(data: dict[str, Any]) -> Project:
    return Project(
        name=_required_string(data, "name"),
        slug=_required_string(data, "slug"),
        timezone=_required_string(data, "timezone"),
        opens_at=_required_string(data, "opens_at"),
        closes_at=_required_string(data, "closes_at"),
    )


def _parse_accounts(items: Any) -> tuple[AccessAccount, ...]:
    if not isinstance(items, list):
        msg = "accounts must be a list"
        raise ProjectImportError(msg)

    accounts = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each account must be a mapping"
            raise ProjectImportError(msg)
        role_names = item.get("roles", [])
        if not isinstance(role_names, list):
            msg = "account roles must be a list"
            raise ProjectImportError(msg)
        accounts.append(
            AccessAccount(
                email=_required_string(item, "email"),
                roles=frozenset(Role(role_name) for role_name in role_names),
            )
        )
    return tuple(accounts)


def _parse_hotels(items: Any) -> tuple[ImportedHotel, ...]:
    if not isinstance(items, list):
        msg = "hotels must be a list"
        raise ProjectImportError(msg)

    hotels = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each hotel must be a mapping"
            raise ProjectImportError(msg)
        hotels.append(
            ImportedHotel(
                name=_required_string(item, "name"),
                rooms=_parse_rooms(item.get("rooms", [])),
                combinations=_parse_room_combinations(item.get("combinations", [])),
            )
        )
    return tuple(hotels)


def _parse_rooms(items: Any) -> tuple[ImportedRoom, ...]:
    if not isinstance(items, list):
        msg = "rooms must be a list"
        raise ProjectImportError(msg)

    rooms = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each room must be a mapping"
            raise ProjectImportError(msg)
        properties = item.get("properties", [])
        if not isinstance(properties, list):
            msg = "room properties must be a list"
            raise ProjectImportError(msg)
        rooms.append(
            ImportedRoom(
                name=_required_string(item, "name"),
                capacity=item.get("capacity"),
                properties=tuple(str(prop) for prop in properties),
            )
        )
    return tuple(rooms)


def _parse_room_combinations(items: Any) -> tuple[ImportedRoomCombination, ...]:
    if not isinstance(items, list):
        msg = "room combinations must be a list"
        raise ProjectImportError(msg)

    combinations = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each room combination must be a mapping"
            raise ProjectImportError(msg)
        room_names = item.get("rooms", [])
        if not isinstance(room_names, list):
            msg = "room combination rooms must be a list"
            raise ProjectImportError(msg)
        combinations.append(
            ImportedRoomCombination(
                name=_required_string(item, "name"),
                room_names=tuple(str(room_name) for room_name in room_names),
                capacity=item.get("capacity"),
            )
        )
    return tuple(combinations)


def _parse_event_groups(items: Any) -> tuple[ImportedEventGroup, ...]:
    if not isinstance(items, list):
        msg = "event_groups must be a list"
        raise ProjectImportError(msg)

    event_groups = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each event group must be a mapping"
            raise ProjectImportError(msg)
        event_groups.append(
            ImportedEventGroup(
                name=_required_string(item, "name"),
                slug=_required_string(item, "slug"),
                description=str(item.get("description", "")),
                requires_order=bool(item.get("requires_order", False)),
            )
        )
    return tuple(event_groups)


def _parse_subprojects(items: Any) -> tuple[ImportedSubproject, ...]:
    if not isinstance(items, list):
        msg = "subprojects must be a list"
        raise ProjectImportError(msg)

    subprojects = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each subproject must be a mapping"
            raise ProjectImportError(msg)
        slug = _required_string(item, "slug")
        subprojects.append(
            ImportedSubproject(
                subproject=Subproject(
                    project_slug="",
                    name=_required_string(item, "name"),
                    slug=slug,
                    kind=SubprojectKind(_required_string(item, "kind")),
                ),
                fields=_parse_form_fields(item.get("form", {})),
            )
        )
    return tuple(subprojects)


def _parse_role_definitions(items: Any) -> tuple[ImportedRoleDefinition, ...]:
    if not isinstance(items, list):
        msg = "roles must be a list"
        raise ProjectImportError(msg)
    roles = []
    valid_permissions = {permission.value for permission in PermissionKey}
    for item in items:
        if not isinstance(item, dict):
            msg = "Each role must be a mapping"
            raise ProjectImportError(msg)
        permissions = item.get("permissions", [])
        if not isinstance(permissions, list):
            msg = "role permissions must be a list"
            raise ProjectImportError(msg)
        invalid = sorted(
            set(str(permission) for permission in permissions) - valid_permissions
        )
        if invalid:
            msg = f"invalid role permissions: {', '.join(invalid)}"
            raise ProjectImportError(msg)
        roles.append(
            ImportedRoleDefinition(
                key=_required_string(item, "key"),
                name=_required_string(item, "name"),
                permissions=tuple(str(permission) for permission in permissions),
                description=str(item.get("description", "")),
                active=bool(item.get("active", True)),
            )
        )
    return tuple(roles)


def _parse_role_assignments(items: Any) -> tuple[ImportedRoleAssignment, ...]:
    if not isinstance(items, list):
        msg = "role_assignments must be a list"
        raise ProjectImportError(msg)
    assignments = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each role assignment must be a mapping"
            raise ProjectImportError(msg)
        scopes = item.get("scopes", [])
        if not isinstance(scopes, list):
            msg = "role assignment scopes must be a list"
            raise ProjectImportError(msg)
        assignments.append(
            ImportedRoleAssignment(
                email=_required_string(item, "email").lower(),
                role_key=_required_string(item, "role"),
                scopes=tuple(str(scope) for scope in scopes),
            )
        )
    return tuple(assignments)


def _parse_benefits(items: Any) -> tuple[ImportedBenefit, ...]:
    if not isinstance(items, list):
        msg = "benefits must be a list"
        raise ProjectImportError(msg)
    benefits = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each benefit must be a mapping"
            raise ProjectImportError(msg)
        benefits.append(
            ImportedBenefit(
                key=_required_string(item, "key"),
                label=_required_string(item, "label"),
                target=_required_string(item, "target"),
                description=str(item.get("description", "")),
                active=bool(item.get("active", True)),
            )
        )
    return tuple(benefits)


def _parse_status_benefits(items: Any) -> tuple[ImportedStatusBenefitGrant, ...]:
    if not isinstance(items, list):
        msg = "status_benefits must be a list"
        raise ProjectImportError(msg)
    grants = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each status benefit must be a mapping"
            raise ProjectImportError(msg)
        grants.append(
            ImportedStatusBenefitGrant(
                status_type=_required_string(item, "status_type"),
                status_value=_required_string(item, "status_value"),
                benefit_key=_required_string(item, "benefit"),
            )
        )
    return tuple(grants)


def _parse_labels(items: Any) -> tuple[ImportedLabelOverride, ...]:
    if not isinstance(items, list):
        msg = "labels must be a list"
        raise ProjectImportError(msg)
    labels = []
    for item in items:
        if not isinstance(item, dict):
            msg = "Each label must be a mapping"
            raise ProjectImportError(msg)
        labels.append(
            ImportedLabelOverride(
                key=_required_string(item, "key"),
                label=_required_string(item, "label"),
            )
        )
    return tuple(labels)


def _parse_form_fields(form: Any) -> tuple[FormField, ...]:
    if not form:
        return ()
    if not isinstance(form, dict):
        msg = "form must be a mapping"
        raise ProjectImportError(msg)
    sections = form.get("sections", [])
    if not isinstance(sections, list):
        msg = "form sections must be a list"
        raise ProjectImportError(msg)

    fields = []
    for section in sections:
        if not isinstance(section, dict):
            msg = "Each form section must be a mapping"
            raise ProjectImportError(msg)
        for field_data in section.get("fields", []):
            if not isinstance(field_data, dict):
                msg = "Each form field must be a mapping"
                raise ProjectImportError(msg)
            options = field_data.get("options", [])
            if not isinstance(options, list):
                msg = "field options must be a list"
                raise ProjectImportError(msg)
            fields.append(
                FormField(
                    label=_required_string(field_data, "label"),
                    field_type=_required_string(field_data, "type"),
                    required=bool(field_data.get("required", False)),
                    options=tuple(str(option) for option in options),
                )
            )
    return tuple(fields)
