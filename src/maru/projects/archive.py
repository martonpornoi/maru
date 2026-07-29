from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone

from maru.accounts.models import (
    AccessGrant,
    RoleAssignment,
    UserConventionProfile,
    UserProfile,
    UserTileColorRule,
)
from maru.projects.models import (
    Application,
    Panel,
    Project,
    ProjectArchiveSnapshot,
    ProjectRoomCombinationSetting,
    ProjectRoomSetting,
    Subproject,
    TimetableDay,
    TimetableLayerSetting,
    VolunteerShift,
)
from maru.social.models import SocialPost


def ensure_project_archive_snapshot(project: Project) -> ProjectArchiveSnapshot | None:
    if not project.is_closed:
        return None
    snapshot, created = ProjectArchiveSnapshot.objects.get_or_create(
        project=project,
        defaults={
            "closed_at": project.closes_at,
            "snapshot": build_project_archive_snapshot(project),
        },
    )
    if created:
        return snapshot
    return snapshot


def rebuild_project_archive_snapshot(project: Project) -> ProjectArchiveSnapshot:
    snapshot, _ = ProjectArchiveSnapshot.objects.update_or_create(
        project=project,
        defaults={
            "closed_at": project.closes_at,
            "snapshot": build_project_archive_snapshot(project),
        },
    )
    return snapshot


def build_project_archive_snapshot(project: Project) -> dict:
    user_ids = set(
        UserConventionProfile.objects.filter(project=project).values_list(
            "user_id",
            flat=True,
        )
    )
    user_ids.update(
        Application.objects.filter(subproject__project=project).values_list(
            "applicant_id",
            flat=True,
        )
    )
    user_ids.update(
        RoleAssignment.objects.filter(project=project).values_list("user_id", flat=True)
    )
    user_ids.update(
        Panel.objects.filter(project=project).values_list("owner_id", flat=True)
    )
    user_ids.update(
        VolunteerShift.objects.filter(project=project)
        .values_list("assignments__user_id", flat=True)
        .exclude(assignments__user_id=None)
    )
    users = get_user_model().objects.filter(id__in=user_ids).order_by("email")
    profiles = {
        profile.user_id: profile
        for profile in UserProfile.objects.filter(user_id__in=user_ids).select_related(
            "user"
        )
    }
    account_emails = [user.email for user in users]
    grants = AccessGrant.objects.filter(email__in=account_emails).prefetch_related(
        "roles"
    )
    return {
        "accounts": [_grant_snapshot(grant) for grant in grants],
        "color_codes": [_color_rule_snapshot(rule) for rule in _color_rules(project)],
        "forms": [_form_snapshot(form) for form in _project_forms(project)],
        "generated_at": timezone.now().isoformat(),
        "hotels": [_hotel_snapshot(hotel) for hotel in project.hotels.all()],
        "project": {
            "closes_at": project.closes_at.isoformat(),
            "name": project.name,
            "opens_at": project.opens_at.isoformat(),
            "slug": project.slug,
            "timezone": project.timezone,
        },
        "role_assignments": [
            _role_assignment_snapshot(assignment)
            for assignment in RoleAssignment.objects.filter(project=project)
            .select_related("role_definition", "user")
            .order_by("role_definition__name", "user__email")
        ],
        "room_settings": _room_settings_snapshot(project),
        "social_posts": [
            _social_post_snapshot(post)
            for post in SocialPost.objects.filter(project=project)
            .select_related("author")
            .order_by("-updated_at", "title")
        ],
        "timetable": _timetable_snapshot(project),
        "user_profiles": [
            _profile_snapshot(user, profiles.get(user.pk), project) for user in users
        ],
    }


def _grant_snapshot(grant: AccessGrant) -> dict:
    return {
        "active": grant.active,
        "email": grant.email,
        "notes": grant.notes,
        "roles": sorted(grant.role_names),
    }


def _color_rule_snapshot(rule: UserTileColorRule) -> dict:
    return {
        "active": rule.active,
        "applies_to": rule.applies_to,
        "color": rule.background_color,
        "priority": rule.priority,
        "scope": "project" if rule.project_id else "global default",
        "target_type": rule.target_type,
        "target_value": rule.target_value,
    }


def _color_rules(project: Project):
    project_rules = UserTileColorRule.objects.filter(project=project).order_by(
        "-priority",
        "target_type",
        "target_value",
        "applies_to",
    )
    if project_rules.exists():
        return project_rules
    return UserTileColorRule.objects.filter(project=None).order_by(
        "-priority",
        "target_type",
        "target_value",
        "applies_to",
    )


def _project_forms(project: Project):
    return (
        Subproject.objects.filter(project=project)
        .prefetch_related("form_fields")
        .order_by("name")
    )


def _form_snapshot(form: Subproject) -> dict:
    return {
        "fields": [
            {
                "field_type": field.field_type,
                "label": field.label,
                "options": list(field.options),
                "position": field.position,
                "required": field.required,
            }
            for field in form.form_fields.all()
        ],
        "kind": form.kind,
        "name": form.name,
        "slug": form.slug,
        "status": form.form_status,
        "timetable_source": form.is_timetable_source,
    }


def _hotel_snapshot(hotel) -> dict:
    return {
        "name": hotel.name,
        "room_combinations": [
            {
                "capacity": combination.capacity,
                "name": combination.name,
                "rooms": list(combination.rooms.values_list("name", flat=True)),
            }
            for combination in hotel.room_combinations.all()
        ],
        "rooms": [
            {
                "capacity": room.capacity,
                "name": room.name,
                "properties": list(room.properties),
            }
            for room in hotel.rooms.all()
        ],
    }


def _role_assignment_snapshot(assignment: RoleAssignment) -> dict:
    return {
        "permissions": list(assignment.role_definition.permissions),
        "role": assignment.role_definition.name,
        "role_key": assignment.role_definition.key,
        "scopes": assignment.scopes,
        "user": assignment.user.email,
    }


def _room_settings_snapshot(project: Project) -> dict:
    return {
        "combinations": [
            {
                "blocked": setting.blocked,
                "display_name": setting.display_name,
                "hotel": setting.room_combination.hotel.name,
                "name": setting.room_combination.name,
                "opening_windows": _availability_snapshot(
                    setting.availability_windows.all()
                ),
            }
            for setting in ProjectRoomCombinationSetting.objects.filter(
                project=project
            )
            .select_related("room_combination__hotel")
            .prefetch_related("availability_windows")
        ],
        "rooms": [
            {
                "blocked": setting.blocked,
                "display_name": setting.display_name,
                "hotel": setting.room.hotel.name,
                "name": setting.room.name,
                "opening_windows": _availability_snapshot(
                    setting.availability_windows.all()
                ),
            }
            for setting in ProjectRoomSetting.objects.filter(project=project)
            .select_related("room__hotel")
            .prefetch_related("availability_windows")
        ],
    }


def _availability_snapshot(windows) -> list[dict]:
    return [
        {
            "ends_at": window.ends_at.isoformat(),
            "starts_at": window.starts_at.isoformat(),
        }
        for window in windows
    ]


def _timetable_snapshot(project: Project) -> dict:
    panels = Panel.objects.filter(project=project).select_related("owner")
    shifts = VolunteerShift.objects.filter(project=project).prefetch_related(
        "assignments__user"
    )
    return {
        "panels": [
            {
                "owner": panel.owner.email,
                "title": panel.title,
            }
            for panel in panels
        ],
        "volunteer_shifts": [
            {
                "assignments": [
                    {
                        "status": assignment.status,
                        "user": assignment.user.email,
                    }
                    for assignment in shift.assignments.all()
                ],
                "needed_volunteers": shift.needed_volunteers,
                "role": shift.role,
                "title": shift.title,
            }
            for shift in shifts
        ],
        "visual_days": [
            {
                "ends_at": day.ends_at.isoformat(),
                "grid_interval_minutes": day.grid_interval_minutes,
                "label": day.display_label,
                "service_date": day.service_date.isoformat(),
                "starts_at": day.starts_at.isoformat(),
            }
            for day in TimetableDay.objects.filter(project=project)
        ],
        "visual_layers": [
            {
                "label": setting.display_label,
                "layer": setting.layer,
                "locked": setting.locked,
                "opacity": str(setting.opacity),
                "position": setting.position,
                "visible": setting.visible,
            }
            for setting in TimetableLayerSetting.objects.filter(project=project)
        ],
    }


def _social_post_snapshot(post: SocialPost) -> dict:
    return {
        "author": post.author.email,
        "body": post.body,
        "published_at": post.published_at.isoformat() if post.published_at else "",
        "scheduled_for": post.scheduled_for.isoformat() if post.scheduled_for else "",
        "status": post.status,
        "title": post.title,
        "updated_at": post.updated_at.isoformat(),
    }


def _profile_snapshot(user, profile: UserProfile | None, project: Project) -> dict:
    convention_profile = UserConventionProfile.objects.filter(
        project=project,
        user=user,
    ).first()
    return {
        "bio": profile.bio if profile else "",
        "convention": _convention_profile_snapshot(convention_profile),
        "display_name": profile.display_name if profile else "",
        "email": user.email,
        "fursuit_name": profile.fursuit_name if profile else "",
        "pronouns": profile.pronouns if profile else "",
    }


def _convention_profile_snapshot(convention_profile: UserConventionProfile | None):
    if not convention_profile:
        return None
    return {
        "attendee_type": convention_profile.attendee_type,
        "fursuit_species": convention_profile.fursuit_species,
        "fursuiter_status": convention_profile.fursuiter_status,
        "roles": convention_profile.role_labels,
        "ticket_level_selected": convention_profile.ticket_level_selected,
        "ticket_level_verified": convention_profile.ticket_level_verified,
        "volunteer_type": convention_profile.volunteer_type,
    }
