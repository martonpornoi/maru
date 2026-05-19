from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils.dateparse import parse_datetime

from maru.accounts.models import AccessGrant, AccessRole
from maru.project_import import ImportedProjectConfig
from maru.projects.models import (
    EventGroup,
    FormField,
    Hotel,
    Project,
    Room,
    RoomCombination,
    Subproject,
)


class ProjectSetupImportError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectSetupImportResult:
    project: Project
    accounts: int = 0
    hotels: int = 0
    rooms: int = 0
    room_combinations: int = 0
    event_groups: int = 0
    subprojects: int = 0
    form_fields: int = 0


@transaction.atomic
def import_project_setup(config: ImportedProjectConfig) -> ProjectSetupImportResult:
    opens_at = _parse_required_datetime(config.project.opens_at, "project.opens_at")
    closes_at = _parse_required_datetime(config.project.closes_at, "project.closes_at")

    project, _ = Project.objects.update_or_create(
        slug=config.project.slug,
        defaults={
            "name": config.project.name,
            "timezone": config.project.timezone,
            "opens_at": opens_at,
            "closes_at": closes_at,
        },
    )

    accounts = _import_accounts(config)
    hotel_count, room_count, combination_count = _import_hotels(project, config)
    event_group_count = _import_event_groups(project, config)
    subproject_count, field_count = _import_subprojects(project, config)

    return ProjectSetupImportResult(
        project=project,
        accounts=accounts,
        hotels=hotel_count,
        rooms=room_count,
        room_combinations=combination_count,
        event_groups=event_group_count,
        subprojects=subproject_count,
        form_fields=field_count,
    )


def _parse_required_datetime(value: str, field_name: str):
    parsed = parse_datetime(value)
    if parsed is None:
        msg = f"{field_name} must be an ISO datetime"
        raise ProjectSetupImportError(msg)
    return parsed


def _import_accounts(config: ImportedProjectConfig) -> int:
    count = 0
    for account in config.accounts:
        grant, _ = AccessGrant.objects.update_or_create(
            email=account.email, defaults={"active": account.active}
        )
        for role in account.roles:
            AccessRole.objects.get_or_create(grant=grant, role=role.value)
        count += 1
    return count


def _import_hotels(
    project: Project, config: ImportedProjectConfig
) -> tuple[int, int, int]:
    hotel_count = 0
    room_count = 0
    combination_count = 0

    for imported_hotel in config.hotels:
        hotel, _ = Hotel.objects.update_or_create(
            project=project, name=imported_hotel.name, defaults={}
        )
        hotel_count += 1

        rooms_by_name = {}
        for imported_room in imported_hotel.rooms:
            room, _ = Room.objects.update_or_create(
                hotel=hotel,
                name=imported_room.name,
                defaults={
                    "capacity": imported_room.capacity,
                    "properties": list(imported_room.properties),
                },
            )
            rooms_by_name[room.name] = room
            room_count += 1

        for imported_combination in imported_hotel.combinations:
            combination, _ = RoomCombination.objects.update_or_create(
                hotel=hotel,
                name=imported_combination.name,
                defaults={"capacity": imported_combination.capacity},
            )
            combination.rooms.set(
                [
                    rooms_by_name[room_name]
                    for room_name in imported_combination.room_names
                    if room_name in rooms_by_name
                ]
            )
            combination_count += 1

    return hotel_count, room_count, combination_count


def _import_event_groups(project: Project, config: ImportedProjectConfig) -> int:
    count = 0
    for imported_group in config.event_groups:
        EventGroup.objects.update_or_create(
            project=project,
            slug=imported_group.slug,
            defaults={
                "name": imported_group.name,
                "description": imported_group.description,
                "requires_order": imported_group.requires_order,
            },
        )
        count += 1
    return count


def _import_subprojects(
    project: Project, config: ImportedProjectConfig
) -> tuple[int, int]:
    subproject_count = 0
    field_count = 0

    for imported_subproject in config.subprojects:
        source = imported_subproject.subproject
        subproject, _ = Subproject.objects.update_or_create(
            project=project,
            slug=source.slug,
            defaults={
                "name": source.name,
                "kind": source.kind.value,
                "accepts_reopen_requests": source.accepts_reopen_requests,
            },
        )
        subproject_count += 1

        for position, imported_field in enumerate(imported_subproject.fields, start=1):
            FormField.objects.update_or_create(
                subproject=subproject,
                label=imported_field.label,
                defaults={
                    "field_type": imported_field.field_type,
                    "required": imported_field.required,
                    "options": list(imported_field.options),
                    "position": position,
                },
            )
            field_count += 1

    return subproject_count, field_count
