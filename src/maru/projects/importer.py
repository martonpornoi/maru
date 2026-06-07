from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.dateparse import parse_datetime

from maru.accounts.access_config import ensure_default_access_configuration
from maru.accounts.models import (
    AccessBenefit,
    AccessGrant,
    AccessRole,
    LabelOverride,
    RoleAssignment,
    RoleDefinition,
    StatusBenefitGrant,
)
from maru.domain import FormStatus, SubprojectKind
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
    role_definitions: int = 0
    role_assignments: int = 0
    benefits: int = 0
    status_benefits: int = 0
    labels: int = 0


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
    access_counts = _import_access_configuration(project, config)

    return ProjectSetupImportResult(
        project=project,
        accounts=accounts,
        hotels=hotel_count,
        rooms=room_count,
        room_combinations=combination_count,
        event_groups=event_group_count,
        subprojects=subproject_count,
        form_fields=field_count,
        role_definitions=access_counts["role_definitions"],
        role_assignments=access_counts["role_assignments"],
        benefits=access_counts["benefits"],
        status_benefits=access_counts["status_benefits"],
        labels=access_counts["labels"],
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
        hotel = Hotel.objects.filter(name=imported_hotel.name).first()
        if hotel is None:
            hotel = Hotel.objects.create(name=imported_hotel.name)
        project.hotels.add(hotel)
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
                "form_status": FormStatus.PUBLISHED.value,
                "is_timetable_source": (
                    source.kind.value == SubprojectKind.EVENT_SUBMISSION.value
                ),
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


def _import_access_configuration(
    project: Project,
    config: ImportedProjectConfig,
) -> dict[str, int]:
    ensure_default_access_configuration()
    role_count = 0
    assignment_count = 0
    benefit_count = 0
    grant_count = 0
    label_count = 0

    for imported_role in config.role_definitions:
        RoleDefinition.objects.update_or_create(
            project=project,
            key=imported_role.key,
            defaults={
                "active": imported_role.active,
                "description": imported_role.description,
                "name": imported_role.name,
                "permissions": list(imported_role.permissions),
                "system_default": False,
            },
        )
        role_count += 1

    for imported_benefit in config.benefits:
        AccessBenefit.objects.update_or_create(
            project=project,
            key=imported_benefit.key,
            defaults={
                "active": imported_benefit.active,
                "description": imported_benefit.description,
                "label": imported_benefit.label,
                "target": imported_benefit.target,
            },
        )
        benefit_count += 1

    for imported_grant in config.status_benefits:
        benefit = AccessBenefit.objects.filter(
            project=project,
            key=imported_grant.benefit_key,
        ).first()
        if not benefit:
            msg = f"Unknown benefit in status_benefits: {imported_grant.benefit_key}"
            raise ProjectSetupImportError(msg)
        StatusBenefitGrant.objects.get_or_create(
            project=project,
            status_type=imported_grant.status_type,
            status_value=imported_grant.status_value,
            benefit=benefit,
        )
        grant_count += 1

    user_model = get_user_model()
    for imported_assignment in config.role_assignments:
        user = user_model.objects.filter(email=imported_assignment.email).first()
        if not user:
            msg = f"Unknown user in role_assignments: {imported_assignment.email}"
            raise ProjectSetupImportError(msg)
        role = RoleDefinition.objects.filter(
            project=project,
            key=imported_assignment.role_key,
        ).first()
        if not role:
            msg = f"Unknown role in role_assignments: {imported_assignment.role_key}"
            raise ProjectSetupImportError(msg)
        RoleAssignment.objects.update_or_create(
            project=project,
            role_definition=role,
            user=user,
            defaults={"scopes": list(imported_assignment.scopes)},
        )
        assignment_count += 1

    for imported_label in config.labels:
        LabelOverride.objects.update_or_create(
            project=project,
            key=imported_label.key.replace(".", "-").replace("_", "-"),
            defaults={"label": imported_label.label},
        )
        label_count += 1

    return {
        "benefits": benefit_count,
        "labels": label_count,
        "role_assignments": assignment_count,
        "role_definitions": role_count,
        "status_benefits": grant_count,
    }
