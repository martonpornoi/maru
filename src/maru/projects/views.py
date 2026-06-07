from __future__ import annotations

import hashlib

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from maru.accounts.models import (
    AccessGrant,
    Notification,
    UserConventionProfile,
    UserProfile,
)
from maru.accounts.permissions import has_permission, user_benefit_keys
from maru.domain import (
    ApplicationStatus,
    AssignmentStatus,
    ExportType,
    FormStatus,
    PermissionKey,
    Role,
    SubprojectKind,
    TimetableRound,
)
from maru.projects.forms import (
    ApplicationSubmissionForm,
    CloneManagedFormForm,
    EventGroupForm,
    ExportTokenForm,
    HotelFloorPlanForm,
    HotelForm,
    ManagedFormFieldForm,
    ManagedFormForm,
    PanelPlacementForm,
    PanelSchedulingMetadataForm,
    ProjectHotelsForm,
    ProjectRoomAvailabilityForm,
    ProjectRoomCombinationAvailabilityForm,
    ProjectRoomCombinationSettingForm,
    ProjectRoomSettingForm,
    RoomForm,
    SignageReminderForm,
    VolunteerShiftAssignmentForm,
    VolunteerShiftForm,
    VolunteerShiftPlacementForm,
)
from maru.projects.models import (
    Application,
    ApplicationVersion,
    EventGroup,
    ExportAccessLog,
    ExportToken,
    Hotel,
    HotelFloorPlan,
    Panel,
    Project,
    ProjectRoomAvailability,
    ProjectRoomCombinationAvailability,
    ProjectRoomCombinationSetting,
    ProjectRoomSetting,
    Room,
    RoomCombination,
    SignageReminder,
    Subproject,
    TimetablePlacement,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftPlacement,
    generate_export_token,
)
from maru.projects.review import (
    can_claim_volunteer_shifts,
    can_manage_project_setup,
    can_review_applications,
)


@login_required
def project_list_view(request):
    projects = Project.objects.prefetch_related("subprojects", "hotels")
    return render(request, "projects/list.html", {"projects": projects})


@login_required
def project_detail_view(request, slug: str):
    project = get_object_or_404(
        Project.objects.prefetch_related(
            "event_groups",
            "subprojects__form_fields",
            "hotels__rooms",
            "hotels__room_combinations__rooms",
        ),
        slug=slug,
    )
    return render(request, "projects/detail.html", {"project": project})


@login_required
def form_list_view(request, slug: str | None = None):
    project = None
    forms = (
        Subproject.objects.select_related("project", "inherited_from").prefetch_related(
            "form_fields"
        )
    )
    clone_form = None
    if slug:
        project = get_object_or_404(Project, slug=slug)
        if not _can_manage_project_module(
            request.user,
            project,
            PermissionKey.PROJECT_FORMS_MANAGE,
        ):
            raise PermissionDenied
        forms = forms.filter(project=project)
        clone_form = CloneManagedFormForm(request.POST or None, project=project)
        if request.method == "POST" and clone_form.is_valid():
            cloned_form = clone_form.save()
            messages.success(request, "Form inherited as an editable draft.")
            return redirect("projects:edit_form", pk=cloned_form.pk)
    elif not can_manage_project_setup(request.user):
        raise PermissionDenied
    return render(
        request,
        "projects/form_list.html",
        {
            "clone_form": clone_form,
            "forms": forms,
            "project": project,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_form_view(request, slug: str):
    project = get_object_or_404(Project, slug=slug)
    if not _can_manage_project_module(
        request.user,
        project,
        PermissionKey.PROJECT_FORMS_MANAGE,
    ):
        raise PermissionDenied
    form = ManagedFormForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        managed_form = form.save()
        messages.success(request, "Form created.")
        return redirect("projects:edit_form", pk=managed_form.pk)
    return render(
        request,
        "projects/form_form.html",
        {
            "form": form,
            "heading": f"Create form for {project.name}",
            "project": project,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_form_view(request, pk: int):
    managed_form = get_object_or_404(
        Subproject.objects.select_related(
            "project", "inherited_from"
        ).prefetch_related(
            "form_fields"
        ),
        pk=pk,
    )
    if not _can_manage_project_module(
        request.user,
        managed_form.project,
        PermissionKey.PROJECT_FORMS_MANAGE,
    ):
        raise PermissionDenied
    form = ManagedFormForm(
        request.POST or None,
        instance=managed_form,
        project=managed_form.project,
    )
    field_form = ManagedFormFieldForm(request.POST or None, subproject=managed_form)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "add_field" and field_form.is_valid():
            field_form.save()
            messages.success(request, "Form field added.")
            return redirect("projects:edit_form", pk=managed_form.pk)
        if action == "save" and form.is_valid():
            form.save()
            messages.success(request, "Form updated.")
            return redirect("projects:edit_form", pk=managed_form.pk)
    return render(
        request,
        "projects/form_form.html",
        {
            "field_form": field_form,
            "form": form,
            "heading": f"Edit {managed_form.name}",
            "managed_form": managed_form,
            "project": managed_form.project,
        },
    )


@login_required
def hotel_list_view(request):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    hotels = Hotel.objects.prefetch_related(
        "projects",
        "rooms",
        "room_combinations__rooms",
        "floor_plans",
    )
    return render(request, "projects/hotel_list.html", {"hotels": hotels})


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_hotel_view(request):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    form = HotelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        hotel = form.save()
        messages.success(request, "Hotel created.")
        return redirect("projects:hotel_detail", pk=hotel.pk)
    return render(
        request,
        "projects/hotel_form.html",
        {"form": form, "heading": "Add hotel"},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def hotel_detail_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    hotel = get_object_or_404(
        Hotel.objects.prefetch_related(
            "projects",
            "rooms",
            "room_combinations__rooms",
            "floor_plans",
        ),
        pk=pk,
    )
    floor_plan_form = HotelFloorPlanForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and floor_plan_form.is_valid():
        floor_plan = floor_plan_form.save(commit=False)
        floor_plan.hotel = hotel
        floor_plan.save()
        messages.success(request, "Floor layout uploaded.")
        return redirect("projects:hotel_detail", pk=hotel.pk)
    return render(
        request,
        "projects/hotel_detail.html",
        {"floor_plan_form": floor_plan_form, "hotel": hotel},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_hotel_room_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    hotel = get_object_or_404(Hotel, pk=pk)
    form = RoomForm(request.POST or None, hotel=hotel)
    if request.method == "POST" and form.is_valid():
        room = form.save()
        messages.success(request, "Room created.")
        return redirect("projects:hotel_detail", pk=room.hotel_id)
    return render(
        request,
        "projects/room_form.html",
        {"form": form, "heading": f"Add room to {hotel.name}", "hotel": hotel},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_hotel_room_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    room = get_object_or_404(Room.objects.select_related("hotel"), pk=pk)
    form = RoomForm(request.POST or None, instance=room)
    if request.method == "POST" and form.is_valid():
        room = form.save()
        messages.success(request, "Room updated.")
        return redirect("projects:hotel_detail", pk=room.hotel_id)
    return render(
        request,
        "projects/room_form.html",
        {"form": form, "heading": f"Edit {room.name}", "hotel": room.hotel},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_hotel_floor_plan_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    floor_plan = get_object_or_404(
        HotelFloorPlan.objects.select_related("hotel"),
        pk=pk,
    )
    previous_image = floor_plan.image.name
    form = HotelFloorPlanForm(
        request.POST or None,
        request.FILES or None,
        instance=floor_plan,
    )
    if request.method == "POST" and form.is_valid():
        floor_plan = form.save()
        if (
            previous_image
            and "image" in form.changed_data
            and previous_image != floor_plan.image.name
        ):
            floor_plan.image.storage.delete(previous_image)
        messages.success(request, "Floor layout updated.")
        return redirect("projects:hotel_detail", pk=floor_plan.hotel_id)
    return render(
        request,
        "projects/hotel_floor_plan_form.html",
        {
            "floor_plan": floor_plan,
            "form": form,
            "heading": f"Edit {floor_plan.floor_label}",
            "hotel": floor_plan.hotel,
        },
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def delete_hotel_floor_plan_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    floor_plan = get_object_or_404(
        HotelFloorPlan.objects.select_related("hotel"),
        pk=pk,
    )
    hotel_id = floor_plan.hotel_id
    image_name = floor_plan.image.name
    floor_plan.delete()
    if image_name:
        floor_plan.image.storage.delete(image_name)
    messages.success(request, "Floor layout removed.")
    return redirect("projects:hotel_detail", pk=hotel_id)


@login_required
def project_room_settings_view(request, slug: str):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    project = get_object_or_404(
        Project.objects.prefetch_related(
            "hotels__rooms",
            "hotels__room_combinations__rooms",
        ),
        slug=slug,
    )
    hotels_form = ProjectHotelsForm(request.POST or None, instance=project)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_hotels" and hotels_form.is_valid():
            hotels_form.save()
            _ensure_project_room_settings(project)
            messages.success(request, "Project hotel assignments updated.")
            return redirect("projects:project_room_settings", slug=project.slug)
    _ensure_project_room_settings(project)
    room_settings = ProjectRoomSetting.objects.filter(
        project=project,
        room__hotel__projects=project,
    ).select_related("room__hotel").prefetch_related("availability_windows")
    combination_settings = ProjectRoomCombinationSetting.objects.filter(
        project=project,
        room_combination__hotel__projects=project,
    ).select_related("room_combination__hotel").prefetch_related("availability_windows")
    return render(
        request,
        "projects/project_room_settings.html",
        {
            "combination_settings": combination_settings,
            "hotels_form": hotels_form,
            "project": project,
            "room_settings": room_settings,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_project_room_setting_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    setting = get_object_or_404(
        ProjectRoomSetting.objects.select_related("project", "room__hotel"),
        pk=pk,
    )
    form = ProjectRoomSettingForm(request.POST or None, instance=setting)
    availability_form = ProjectRoomAvailabilityForm(
        request.POST or None,
        project=setting.project,
    )
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "add_window" and availability_form.is_valid():
            window = availability_form.save(commit=False)
            window.setting = setting
            window.save()
            messages.success(request, "Opening window added.")
            return redirect("projects:edit_project_room_setting", pk=setting.pk)
        if action == "save" and form.is_valid():
            form.save()
            messages.success(request, "Project room settings updated.")
            return redirect("projects:project_room_settings", slug=setting.project.slug)
    return render(
        request,
        "projects/project_room_setting_form.html",
        {
            "availability_form": availability_form,
            "availability_delete_kind": "room",
            "form": form,
            "setting": setting,
            "windows": setting.availability_windows.all(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_project_room_combination_setting_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    setting = get_object_or_404(
        ProjectRoomCombinationSetting.objects.select_related(
            "project",
            "room_combination__hotel",
        ),
        pk=pk,
    )
    form = ProjectRoomCombinationSettingForm(request.POST or None, instance=setting)
    availability_form = ProjectRoomCombinationAvailabilityForm(
        request.POST or None,
        project=setting.project,
    )
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "add_window" and availability_form.is_valid():
            window = availability_form.save(commit=False)
            window.setting = setting
            window.save()
            messages.success(request, "Opening window added.")
            return redirect(
                "projects:edit_project_room_combination_setting",
                pk=setting.pk,
            )
        if action == "save" and form.is_valid():
            form.save()
            messages.success(request, "Project room settings updated.")
            return redirect("projects:project_room_settings", slug=setting.project.slug)
    return render(
        request,
        "projects/project_room_setting_form.html",
        {
            "availability_form": availability_form,
            "availability_delete_kind": "combination",
            "form": form,
            "setting": setting,
            "windows": setting.availability_windows.all(),
        },
    )


@login_required
@require_http_methods(["POST"])
def delete_project_room_availability_view(request, kind: str, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    if kind == "room":
        window = get_object_or_404(
            ProjectRoomAvailability.objects.select_related("setting__project"),
            pk=pk,
        )
        project_slug = window.setting.project.slug
    elif kind == "combination":
        window = get_object_or_404(
            ProjectRoomCombinationAvailability.objects.select_related(
                "setting__project"
            ),
            pk=pk,
        )
        project_slug = window.setting.project.slug
    else:
        raise PermissionDenied
    window.delete()
    messages.success(request, "Opening window removed.")
    return redirect("projects:project_room_settings", slug=project_slug)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def export_token_list_view(request, slug: str):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    project = get_object_or_404(
        Project.objects.prefetch_related("export_tokens__access_logs"),
        slug=slug,
    )
    form = ExportTokenForm(request.POST or None)
    new_token = None
    if request.method == "POST" and form.is_valid():
        export_token = form.save(commit=False)
        export_token.project = project
        export_token.save()
        new_token = export_token.token
        messages.success(request, "Export token created. Copy it now.")
    return render(
        request,
        "projects/export_token_list.html",
        {
            "form": form,
            "new_token": new_token,
            "project": project,
            "token_rows": _export_token_rows(project.export_tokens.all()),
        },
    )


@login_required
@require_http_methods(["POST"])
def rotate_export_token_view(request, pk: int):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    export_token = get_object_or_404(
        ExportToken.objects.select_related("project"),
        pk=pk,
    )
    export_token.token = generate_export_token()
    export_token.active = True
    export_token.save(update_fields=["token", "active", "updated_at"])
    messages.success(request, "Export token rotated. Copy the new token now.")
    return render(
        request,
        "projects/export_token_rotated.html",
        {
            "export_token": export_token,
            "new_token": export_token.token,
            "project": export_token.project,
        },
    )


@login_required
@require_http_methods(["POST"])
def set_export_token_active_view(request, pk: int, active: str):
    if not can_manage_project_setup(request.user):
        raise PermissionDenied
    export_token = get_object_or_404(
        ExportToken.objects.select_related("project"),
        pk=pk,
    )
    if active not in {"active", "inactive"}:
        raise PermissionDenied
    export_token.active = active == "active"
    export_token.save(update_fields=["active", "updated_at"])
    state = "activated" if export_token.active else "deactivated"
    messages.success(request, f"Export token {state}.")
    return redirect("projects:export_token_list", slug=export_token.project.slug)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_event_group_view(request, slug: str):
    if not can_review_applications(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, slug=slug)
    form = EventGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event_group = form.save(commit=False)
        event_group.project = project
        event_group.save()
        messages.success(request, "Event group created.")
        return redirect("projects:event_group_detail", pk=event_group.pk)
    return render(
        request,
        "projects/event_group_form.html",
        {"form": form, "project": project},
    )


@login_required
def event_group_detail_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    event_group = get_object_or_404(
        EventGroup.objects.select_related("project").prefetch_related(
            "panels__placement",
            "panels__owner__userprofile",
        ),
        pk=pk,
    )
    panels = sorted(
        event_group.panels.all(),
        key=lambda panel: (
            panel.group_order is None,
            panel.group_order or 0,
            not hasattr(panel, "placement"),
            panel.placement.starts_at if hasattr(panel, "placement") else panel.title,
        ),
    )
    return render(
        request,
        "projects/event_group_detail.html",
        {
            "event_group": event_group,
            "panel_rows": _build_event_group_panel_rows(event_group, panels),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_event_group_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    event_group = get_object_or_404(EventGroup.objects.select_related("project"), pk=pk)
    form = EventGroupForm(request.POST or None, instance=event_group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Event group updated.")
        return redirect("projects:event_group_detail", pk=event_group.pk)
    return render(
        request,
        "projects/event_group_form.html",
        {"event_group": event_group, "form": form, "project": event_group.project},
    )


@login_required
def timetable_view(request, slug: str):
    project = get_object_or_404(Project, slug=slug)
    panels = (
        Panel.objects.filter(project=project)
        .select_related(
            "event_group",
            "owner",
            "owner__userprofile",
            "application__subproject",
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .order_by("placement__starts_at", "title")
    )
    can_manage_all = can_review_applications(request.user)
    panels = _visible_panels_for_timetable(
        panels=panels,
        project=project,
        user=request.user,
        can_manage_all=can_manage_all,
    )
    rows = _build_timetable_rows(panels, request.user, can_manage_all)
    shift_rows = []
    if can_manage_all:
        shifts = (
            VolunteerShift.objects.filter(project=project)
            .select_related(
                "placement__room",
                "placement__room_combination",
            )
            .prefetch_related("placement__room_combination__rooms")
            .prefetch_related("assignments__user")
            .order_by("placement__starts_at", "title")
        )
        shift_rows = _build_volunteer_shift_rows(shifts)

    return render(
        request,
        "projects/timetable.html",
        {
            "can_manage_all": can_manage_all,
            "rounds": list(TimetableRound),
            "rows": rows,
            "shift_rows": shift_rows,
            "project": project,
        },
    )


@login_required
def timetable_print_view(request, slug: str):
    project = get_object_or_404(Project, slug=slug)
    can_manage_all = can_review_applications(request.user)
    panels = (
        Panel.objects.filter(project=project)
        .select_related(
            "event_group",
            "owner",
            "owner__userprofile",
            "application__subproject",
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .order_by("placement__starts_at", "title")
    )
    panels = _visible_panels_for_timetable(
        panels=panels,
        project=project,
        user=request.user,
        can_manage_all=can_manage_all,
    )
    shifts = []
    if can_manage_all:
        shifts = (
            VolunteerShift.objects.filter(project=project)
            .select_related(
                "placement__room",
                "placement__room_combination",
            )
            .prefetch_related("placement__room_combination__rooms")
            .order_by("placement__starts_at", "title")
        )
    return render(
        request,
        "projects/timetable_print.html",
        {
            "entries": _build_print_entries(panels, shifts, can_manage_all),
            "project": project,
            "shows_staff_layers": can_manage_all,
        },
    )


def public_timetable_export_view(request, token: str):
    export_token = _get_export_token(request, token, ExportType.PUBLIC_TIMETABLE)
    project = export_token.project
    panels = (
        Panel.objects.filter(project=project, placement__isnull=False)
        .select_related(
            "application",
            "event_group",
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .order_by("placement__starts_at", "title")
    )
    if project.timetable_round != TimetableRound.PUBLIC.value:
        panels = panels.none()
    return JsonResponse(
        {
            "export_type": ExportType.PUBLIC_TIMETABLE.value,
            "project": _project_export(project),
            "entries": [_panel_export(panel) for panel in panels],
        }
    )


def public_profile_export_view(request, token: str):
    export_token = _get_export_token(request, token, ExportType.PUBLIC_PROFILES)
    project = export_token.project
    profiles = UserProfile.objects.none()
    if project.profile_exports_enabled:
        approved_user_ids = (
            Application.objects.filter(
                subproject__project=project,
                status=ApplicationStatus.APPROVED.value,
            )
            .values_list("applicant_id", flat=True)
            .distinct()
        )
        profiles = (
            UserProfile.objects.filter(
                user_id__in=approved_user_ids,
                profile_unlocked=True,
                show_profile_publicly=True,
            )
            .select_related("user")
            .order_by("display_name", "user__email")
        )
    return JsonResponse(
        {
            "export_type": ExportType.PUBLIC_PROFILES.value,
            "project": _project_export(project),
            "entries": [
                _public_profile_export(profile, project) for profile in profiles
            ],
        }
    )


def volunteer_shift_export_view(request, token: str):
    export_token = _get_export_token(request, token, ExportType.VOLUNTEER_SHIFTS)
    project = export_token.project
    shifts = (
        VolunteerShift.objects.filter(project=project, placement__isnull=False)
        .select_related(
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .order_by("placement__starts_at", "title")
    )
    return JsonResponse(
        {
            "export_type": ExportType.VOLUNTEER_SHIFTS.value,
            "project": _project_export(project),
            "entries": [_volunteer_shift_export(shift) for shift in shifts],
        }
    )


def signage_reminder_export_view(request, token: str):
    export_token = _get_export_token(request, token, ExportType.SIGNAGE_REMINDERS)
    now = timezone.now()
    reminders = SignageReminder.objects.filter(
        project=export_token.project,
        active=True,
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("-priority", "starts_at", "title")
    return JsonResponse(
        {
            "export_type": ExportType.SIGNAGE_REMINDERS.value,
            "project": _project_export(export_token.project),
            "generated_at": now.isoformat(),
            "reminders": [_signage_reminder_export(reminder) for reminder in reminders],
        }
    )


def role_status_export_view(request, token: str):
    export_token = _get_export_token(request, token, ExportType.ROLE_STATUS)
    project = export_token.project
    convention_profiles = (
        UserConventionProfile.objects.filter(project=project)
        .select_related("user", "user__userprofile")
        .order_by("user__email")
    )
    public_rows = []
    benefit_counts: dict[str, int] = {}
    for convention_profile in convention_profiles:
        benefits = user_benefit_keys(convention_profile.user, project)
        for benefit in benefits:
            benefit_counts[benefit] = benefit_counts.get(benefit, 0) + 1
        profile = getattr(convention_profile.user, "userprofile", None)
        if profile and profile.profile_unlocked and profile.show_profile_publicly:
            public_rows.append(
                {
                    "benefits": benefits,
                    "display_name": (
                        _profile_display_name(profile) or "Convention participant"
                    ),
                    "fursuiter_status": convention_profile.fursuiter_status,
                    "ticket_level": convention_profile.ticket_level_verified,
                }
            )
    return JsonResponse(
        {
            "benefit_counts": [
                {"key": key, "total": total}
                for key, total in sorted(benefit_counts.items())
            ],
            "export_type": ExportType.ROLE_STATUS.value,
            "fursuiter_statuses": list(
                convention_profiles.values("fursuiter_status")
                .annotate(total=Count("id"))
                .order_by("fursuiter_status")
            ),
            "project": _project_export(project),
            "public_profiles": public_rows,
            "ticket_levels": list(
                convention_profiles.values("ticket_level_verified")
                .annotate(total=Count("id"))
                .order_by("ticket_level_verified")
            ),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_signage_reminder_view(request, slug: str):
    if not can_review_applications(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, slug=slug)
    form = SignageReminderForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        reminder = form.save(commit=False)
        reminder.project = project
        reminder.save()
        messages.success(request, "Signage reminder created.")
        return redirect("projects:detail", slug=project.slug)
    return render(
        request,
        "projects/create_signage_reminder.html",
        {"form": form, "project": project},
    )


@login_required
@require_http_methods(["POST"])
def change_timetable_round_view(request, slug: str, round_key: str):
    if not can_review_applications(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, slug=slug)
    try:
        round_ = TimetableRound(round_key)
    except ValueError as exc:
        raise PermissionDenied from exc
    project.timetable_round = round_.value
    project.save(update_fields=["timetable_round", "updated_at"])
    messages.success(request, f"Timetable round changed to {round_.value}.")
    return redirect("projects:timetable", slug=project.slug)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def place_panel_view(request, pk: int):
    panel = get_object_or_404(
        Panel.objects.select_related("project", "owner", "application__subproject"),
        pk=pk,
    )
    if not _can_place_panel(panel, request.user):
        raise PermissionDenied

    placement = TimetablePlacement.objects.filter(panel=panel).first()
    form = PanelPlacementForm(
        request.POST or None,
        project=panel.project,
        placement=placement,
    )
    if request.method == "POST" and form.is_valid():
        form.save(panel)
        messages.success(request, "Panel placement saved.")
        return redirect("projects:timetable", slug=panel.project.slug)

    return render(
        request,
        "projects/place_panel.html",
        {"form": form, "panel": panel},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_panel_metadata_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    panel = get_object_or_404(
        Panel.objects.select_related("project", "event_group", "application"),
        pk=pk,
    )
    form = PanelSchedulingMetadataForm(
        request.POST or None,
        panel=panel,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Panel scheduling metadata saved.")
        return redirect("projects:timetable", slug=panel.project.slug)
    return render(
        request,
        "projects/edit_panel_metadata.html",
        {"form": form, "panel": panel},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def create_volunteer_shift_view(request, slug: str):
    if not can_review_applications(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, slug=slug)
    form = VolunteerShiftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        shift = form.save(commit=False)
        shift.project = project
        shift.save()
        messages.success(request, "Volunteer shift created.")
        return redirect("projects:place_volunteer_shift", pk=shift.pk)
    return render(
        request,
        "projects/create_volunteer_shift.html",
        {"form": form, "project": project},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def place_volunteer_shift_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    shift = get_object_or_404(VolunteerShift.objects.select_related("project"), pk=pk)
    placement = VolunteerShiftPlacement.objects.filter(shift=shift).first()
    form = VolunteerShiftPlacementForm(
        request.POST or None,
        project=shift.project,
        placement=placement,
    )
    if request.method == "POST" and form.is_valid():
        form.save(shift)
        messages.success(request, "Volunteer shift placement saved.")
        return redirect("projects:timetable", slug=shift.project.slug)
    return render(
        request,
        "projects/place_volunteer_shift.html",
        {"form": form, "shift": shift},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def assign_volunteer_shift_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    shift = get_object_or_404(
        VolunteerShift.objects.select_related("project")
        .prefetch_related("assignments__user"),
        pk=pk,
    )
    form = VolunteerShiftAssignmentForm(request.POST or None, shift=shift)
    if request.method == "POST" and shift.locked:
        messages.error(request, "This shift is locked.")
    elif request.method == "POST" and form.is_valid():
        assignment, _ = VolunteerShiftAssignment.objects.update_or_create(
            shift=shift,
            user=form.cleaned_data["user"],
            defaults={
                "assigned_by": request.user,
                "notes": form.cleaned_data["notes"],
                "status": AssignmentStatus.CONFIRMED.value,
            },
        )
        Notification.objects.create(
            user=assignment.user,
            title="Volunteer shift assigned",
            body=f"You were assigned to {shift.title} for {shift.project.name}.",
            link_url=reverse("projects:volunteer_shift_detail", args=[shift.pk]),
            link_label="Open shift",
        )
        messages.success(request, "Volunteer assigned.")
        return redirect("projects:assign_volunteer_shift", pk=shift.pk)
    return render(
        request,
        "projects/assign_volunteer_shift.html",
        {"assignments": shift.assignments.all(), "form": form, "shift": shift},
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def change_volunteer_assignment_status_view(request, pk: int, status: str):
    if not can_review_applications(request.user):
        raise PermissionDenied
    try:
        status_ = AssignmentStatus(status)
    except ValueError as exc:
        raise PermissionDenied from exc
    if status_ == AssignmentStatus.CLAIMED:
        raise PermissionDenied
    assignment = get_object_or_404(
        VolunteerShiftAssignment.objects.select_related("shift__project", "user"),
        pk=pk,
    )
    assignment.status = status_.value
    assignment.save(update_fields=["status"])
    Notification.objects.create(
        user=assignment.user,
        title="Volunteer shift updated",
        body=(
            f"{assignment.shift.title} for {assignment.shift.project.name} "
            f"is now {status_.value}."
        ),
        link_url=reverse(
            "projects:volunteer_shift_detail",
            args=[assignment.shift.pk],
        ),
        link_label="Open shift",
    )
    messages.success(request, f"Volunteer assignment marked {status_.value}.")
    return redirect("projects:assign_volunteer_shift", pk=assignment.shift.pk)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def lock_volunteer_shift_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    shift = get_object_or_404(VolunteerShift.objects.select_related("project"), pk=pk)
    locked = request.POST.get("locked") == "1"
    shift.locked = locked
    shift.save(update_fields=["locked", "updated_at"])
    messages.success(
        request,
        "Volunteer shift locked." if locked else "Volunteer shift reopened.",
    )
    return redirect("projects:assign_volunteer_shift", pk=shift.pk)


@login_required
def volunteer_shift_list_view(request, slug: str):
    if not can_claim_volunteer_shifts(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, slug=slug)
    shifts = (
        VolunteerShift.objects.filter(project=project, placement__isnull=False)
        .select_related(
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .prefetch_related("assignments__user")
        .order_by("placement__starts_at", "title")
    )
    return render(
        request,
        "projects/volunteer_shift_list.html",
        {
            "project": project,
            "rows": _build_claimable_shift_rows(shifts, request.user),
        },
    )


@login_required
def volunteer_shift_detail_view(request, pk: int):
    if not can_claim_volunteer_shifts(request.user):
        raise PermissionDenied
    shift = get_object_or_404(
        VolunteerShift.objects.select_related(
            "project",
            "placement__room",
            "placement__room_combination",
        )
        .prefetch_related("placement__room_combination__rooms")
        .prefetch_related("assignments__user"),
        pk=pk,
    )
    can_manage_all = can_review_applications(request.user)
    user_assignment = VolunteerShiftAssignment.objects.filter(
        shift=shift,
        user=request.user,
    ).first()
    return render(
        request,
        "projects/volunteer_shift_detail.html",
        {
            "blocker": _volunteer_claim_blocker(shift, request.user),
            "can_manage_all": can_manage_all,
            "shift": shift,
            "user_assignment": user_assignment,
            "visible_assignments": shift.assignments.all() if can_manage_all else [],
        },
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def claim_volunteer_shift_view(request, pk: int):
    if not can_claim_volunteer_shifts(request.user):
        raise PermissionDenied
    shift = get_object_or_404(
        VolunteerShift.objects.select_for_update().select_related(
            "project",
            "placement__room",
            "placement__room_combination",
        ),
        pk=pk,
    )
    blocker = _volunteer_claim_blocker(shift, request.user)
    if blocker:
        messages.error(request, blocker)
    else:
        VolunteerShiftAssignment.objects.update_or_create(
            shift=shift,
            user=request.user,
            defaults={
                "assigned_by": None,
                "status": AssignmentStatus.CLAIMED.value,
            },
        )
        Notification.objects.create(
            user=request.user,
            title="Volunteer shift claimed",
            body=f"You claimed {shift.title} for {shift.project.name}.",
            link_url=reverse("projects:volunteer_shift_detail", args=[shift.pk]),
            link_label="Open shift",
        )
        messages.success(request, "Volunteer shift claimed.")
    return redirect("projects:volunteer_shift_detail", pk=shift.pk)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def submit_application_view(request, project_slug: str, subproject_slug: str):
    subproject = get_object_or_404(
        Subproject.objects.select_related("project").prefetch_related("form_fields"),
        project__slug=project_slug,
        slug=subproject_slug,
    )
    if subproject.form_status != FormStatus.PUBLISHED.value:
        raise Http404
    form_fields = list(subproject.form_fields.all())
    form = ApplicationSubmissionForm(
        request.POST or None,
        request.FILES or None,
        form_fields=form_fields,
    )

    if request.method == "POST" and form.is_valid():
        answers = form.answers_by_label()
        application = Application.objects.create(
            subproject=subproject,
            applicant=request.user,
            title=_application_title(answers, subproject.name),
            event_header_image=form.cleaned_data.get("event_header_image") or "",
        )
        ApplicationVersion.objects.create(
            application=application, version=1, answers=answers
        )
        messages.success(request, "Application submitted.")
        return redirect("projects:application_detail", pk=application.pk)

    return render(
        request,
        "projects/submit_application.html",
        {"subproject": subproject, "form": form},
    )


@login_required
def application_detail_view(request, pk: int):
    application = get_object_or_404(
        Application.objects.select_related("subproject__project", "applicant")
        .prefetch_related("versions"),
        pk=pk,
        applicant=request.user,
    )
    latest_version = application.versions.first()
    versions = application.versions.all()
    return render(
        request,
        "projects/application_detail.html",
        {
            "application": application,
            "can_edit": application.status == ApplicationStatus.REOPENED.value,
            "latest_version": latest_version,
            "versions": versions,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_application_view(request, pk: int):
    application = get_object_or_404(
        Application.objects.select_related("subproject__project", "applicant")
        .prefetch_related("subproject__form_fields", "versions"),
        pk=pk,
        applicant=request.user,
    )
    if application.status != ApplicationStatus.REOPENED.value:
        raise PermissionDenied

    form_fields = list(application.subproject.form_fields.all())
    latest_version = application.versions.first()
    form = ApplicationSubmissionForm(
        request.POST or None,
        request.FILES or None,
        application=application,
        form_fields=form_fields,
        initial_answers=latest_version.answers if latest_version else {},
    )
    if request.method == "POST" and form.is_valid():
        answers = form.answers_by_label()
        application.title = _application_title(answers, application.subproject.name)
        application.status = ApplicationStatus.SUBMITTED.value
        update_fields = ["title", "status", "updated_at"]
        if form.cleaned_data.get("event_header_image"):
            application.event_header_image = form.cleaned_data["event_header_image"]
            update_fields.append("event_header_image")
        application.save(update_fields=update_fields)
        ApplicationVersion.objects.create(
            application=application,
            version=_next_application_version(application),
            answers=answers,
        )
        _notify_reviewers_application_resubmitted(application)
        messages.success(request, "Application resubmitted.")
        return redirect("projects:application_detail", pk=application.pk)

    return render(
        request,
        "projects/submit_application.html",
        {
            "application": application,
            "form": form,
            "is_editing": True,
            "submit_label": "Resubmit application",
            "subproject": application.subproject,
        },
    )


@login_required
def review_application_list_view(request):
    if not can_review_applications(request.user):
        raise PermissionDenied
    applications = Application.objects.select_related(
        "applicant", "subproject__project"
    )
    return render(
        request,
        "projects/review_list.html",
        {"applications": applications},
    )


@login_required
def review_application_detail_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    application = get_object_or_404(
        Application.objects.select_related(
            "applicant",
            "panel__event_group",
            "subproject__project",
        )
        .select_related("applicant__userprofile")
        .prefetch_related("versions"),
        pk=pk,
    )
    latest_version = application.versions.first()
    applicant_profile = getattr(application.applicant, "userprofile", None)
    return render(
        request,
        "projects/review_detail.html",
        {
            "applicant_profile": applicant_profile,
            "application": application,
            "latest_version": latest_version,
        },
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def review_application_decision_view(request, pk: int, decision: str):
    if not can_review_applications(request.user):
        raise PermissionDenied

    application = get_object_or_404(
        Application.objects.select_related("applicant", "subproject__project"),
        pk=pk,
    )
    if decision == "approve":
        _approve_application(application)
        messages.success(request, "Application approved.")
    elif decision == "reject":
        _reject_application(application)
        messages.success(request, "Application rejected.")
    else:
        raise PermissionDenied

    return redirect("projects:review_application_detail", pk=application.pk)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def reopen_application_view(request, pk: int):
    if not can_review_applications(request.user):
        raise PermissionDenied
    application = get_object_or_404(
        Application.objects.select_related("applicant", "subproject__project"),
        pk=pk,
    )
    if not application.subproject.accepts_reopen_requests:
        raise PermissionDenied
    application.status = ApplicationStatus.REOPENED.value
    application.save(update_fields=["status", "updated_at"])
    Notification.objects.create(
        user=application.applicant,
        title="Application reopened",
        body=(
            f"{application.title} was reopened for "
            f"{application.subproject.project.name}. Please update and resubmit it."
        ),
        link_url=reverse("projects:application_detail", args=[application.pk]),
        link_label="Edit application",
    )
    messages.success(request, "Application reopened for applicant edits.")
    return redirect("projects:review_application_detail", pk=application.pk)


def _application_title(
    answers: dict[str, str | bool | list[str]], fallback: str
) -> str:
    for key in ("Display - Title", "DJ Name"):
        value = answers.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _next_application_version(application: Application) -> int:
    latest_version = application.versions.first()
    if latest_version is None:
        return 1
    return latest_version.version + 1


def _notify_reviewers_application_resubmitted(application: Application) -> None:
    reviewer_emails = (
        AccessGrant.objects.filter(
            active=True,
            roles__role__in=[
                Role.ADMIN.value,
                Role.BOARD.value,
                Role.EVENT_MANAGER.value,
            ],
        )
        .values_list("email", flat=True)
        .distinct()
    )
    reviewers = get_user_model().objects.filter(email__in=reviewer_emails)
    notifications = [
        Notification(
            user=reviewer,
            title="Application resubmitted",
            body=(
                f"{application.title} was resubmitted for "
                f"{application.subproject.project.name}."
            ),
            link_url=reverse(
                "projects:review_application_detail",
                args=[application.pk],
            ),
            link_label="Review application",
        )
        for reviewer in reviewers
        if reviewer.pk != application.applicant_id
    ]
    Notification.objects.bulk_create(notifications)


def _can_manage_project_module(
    user,
    project: Project,
    permission: PermissionKey,
) -> bool:
    return has_permission(user, permission, project) or has_permission(
        user,
        PermissionKey.PROJECT_SETUP_MANAGE,
        project,
    )


def _approve_application(application: Application) -> None:
    application.status = ApplicationStatus.APPROVED.value
    application.save(update_fields=["status", "updated_at"])
    _create_panel_for_application(application)
    profile, _ = UserProfile.objects.get_or_create(user=application.applicant)
    if not profile.profile_unlocked:
        profile.profile_unlocked = True
        profile.save(update_fields=["profile_unlocked"])
    Notification.objects.create(
        user=application.applicant,
        title="Application approved",
        body=(
            f"{application.title} was approved for "
            f"{application.subproject.project.name}."
        ),
        link_url=reverse("projects:application_detail", args=[application.pk]),
        link_label="Open application",
    )


def _create_panel_for_application(application: Application) -> Panel | None:
    if application.subproject.kind != SubprojectKind.EVENT_SUBMISSION.value:
        return None
    panel, _ = Panel.objects.update_or_create(
        application=application,
        defaults={
            "project": application.subproject.project,
            "owner": application.applicant,
            "title": application.title,
        },
    )
    return panel


def _can_place_panel(panel: Panel, user) -> bool:
    if can_review_applications(user):
        return True
    if panel.owner_id != user.id:
        return False
    return panel.project.timetable_round == TimetableRound.PRIVATE_PLACEMENT.value


def _visible_panels_for_timetable(*, panels, project: Project, user, can_manage_all):
    if can_manage_all:
        return panels
    if project.timetable_round == TimetableRound.PRIVATE_PLACEMENT.value:
        return panels.filter(owner=user)
    if project.timetable_round == TimetableRound.HOST_NEGOTIATION.value:
        if Panel.objects.filter(project=project, owner=user).exists():
            return panels
        return panels.none()
    if project.timetable_round == TimetableRound.PUBLIC.value:
        return panels
    return panels.none()


def _ensure_project_room_settings(project: Project) -> None:
    rooms = Room.objects.filter(hotel__projects=project)
    for room in rooms:
        ProjectRoomSetting.objects.get_or_create(project=project, room=room)
    combinations = RoomCombination.objects.filter(hotel__projects=project)
    for combination in combinations:
        ProjectRoomCombinationSetting.objects.get_or_create(
            project=project,
            room_combination=combination,
        )


def _build_timetable_rows(panels, user, can_manage_all: bool) -> list[dict]:
    panel_list = list(panels)
    conflicting_panel_ids = _conflicting_panel_ids(panel_list)
    group_order_problem_ids = _group_order_problem_ids(panel_list)
    return [
        {
            "can_place": _can_place_panel(panel, user),
            "group_order_problem": panel.pk in group_order_problem_ids,
            "has_conflict": panel.pk in conflicting_panel_ids,
            "host": _panel_host_context(panel, can_manage_all),
            "location": _placement_location_name(
                getattr(panel, "placement", None),
                panel.project,
            ),
            "panel": panel,
        }
        for panel in panel_list
    ]


def _build_volunteer_shift_rows(shifts) -> list[dict]:
    shift_list = list(shifts)
    conflicting_shift_ids = _conflicting_shift_ids(shift_list)
    return [
        {
            "assigned_count": shift.assignment_count,
            "has_conflict": shift.pk in conflicting_shift_ids,
            "location": _placement_location_name(
                getattr(shift, "placement", None),
                shift.project,
            ),
            "open_spots": shift.open_spots,
            "shift": shift,
        }
        for shift in shift_list
    ]


def _placement_location_name(placement, project: Project) -> str:
    if not placement:
        return "Unplaced"
    if placement.room_id:
        setting = ProjectRoomSetting.objects.filter(
            project=project,
            room_id=placement.room_id,
        ).first()
        if setting:
            return setting.display_name
        return placement.room.name
    if placement.room_combination_id:
        setting = ProjectRoomCombinationSetting.objects.filter(
            project=project,
            room_combination_id=placement.room_combination_id,
        ).first()
        if setting:
            return setting.display_name
        return placement.room_combination.name
    return "Unplaced"


def _build_claimable_shift_rows(shifts, user) -> list[dict]:
    return [
        {
            "blocker": _volunteer_claim_blocker(shift, user),
            "assigned_count": shift.assignment_count,
            "open_spots": shift.open_spots,
            "shift": shift,
        }
        for shift in shifts
    ]


def _build_print_entries(panels, shifts, can_manage_all: bool) -> list[dict]:
    entries = []
    panel_list = list(panels)
    group_order_problem_ids = _group_order_problem_ids(panel_list)
    for panel in panel_list:
        placement = getattr(panel, "placement", None)
        detail = _panel_host_label(panel, can_manage_all)
        if panel.event_group_id:
            detail = f"{detail} - {_panel_group_label(panel)}"
        if panel.pk in group_order_problem_ids:
            detail = f"{detail} - Group order warning"
        entries.append(
            {
                "detail": detail,
                "ends_at": placement.ends_at if placement else None,
                "kind": "Panel",
                "location": _placement_location_name(placement, panel.project),
                "starts_at": placement.starts_at if placement else None,
                "title": panel.title,
            }
        )
    for shift in shifts:
        placement = getattr(shift, "placement", None)
        entries.append(
            {
                "detail": (
                    f"{shift.role} - {shift.assignment_count}/"
                    f"{shift.needed_volunteers} assigned"
                ),
                "ends_at": placement.ends_at if placement else None,
                "kind": "Volunteer Shift",
                "location": _placement_location_name(placement, shift.project),
                "starts_at": placement.starts_at if placement else None,
                "title": shift.title,
            }
        )
    return sorted(
        entries,
        key=lambda entry: (
            entry["starts_at"] is None,
            entry["starts_at"],
            entry["kind"],
            entry["title"],
        ),
    )


def _build_event_group_panel_rows(event_group: EventGroup, panels: list[Panel]):
    order_problem_ids = _group_order_problem_ids(panels)
    return [
        {
            "has_order_warning": panel.pk in order_problem_ids,
            "is_missing_order": event_group.requires_order
            and panel.group_order is None,
            "panel": panel,
        }
        for panel in panels
    ]


def _group_order_problem_ids(panels: list[Panel]) -> set[int]:
    grouped: dict[int, list[Panel]] = {}
    for panel in panels:
        if (
            panel.event_group_id
            and panel.event_group.requires_order
            and panel.group_order is not None
            and hasattr(panel, "placement")
        ):
            grouped.setdefault(panel.event_group_id, []).append(panel)
    problem_ids = set()
    for group_panels in grouped.values():
        ordered = sorted(group_panels, key=lambda panel: panel.group_order)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.placement.starts_at > current.placement.starts_at:
                problem_ids.update({previous.pk, current.pk})
    return problem_ids


def _panel_host_context(panel: Panel, can_manage_all: bool) -> dict:
    profile = _owner_profile(panel)
    can_link_profile = bool(
        profile and (can_manage_all or _is_public_profile(profile))
    )
    return {
        "label": _panel_host_label(panel, can_manage_all),
        "profile_pk": profile.pk if can_link_profile else None,
    }


def _panel_host_label(panel: Panel, can_manage_all: bool) -> str:
    profile = _owner_profile(panel)
    display_name = _profile_display_name(profile)
    if can_manage_all:
        if display_name:
            return f"{display_name} ({panel.owner.email})"
        return panel.owner.email
    if profile and _is_public_profile(profile):
        return display_name or "Convention participant"
    return "Host"


def _owner_profile(panel: Panel) -> UserProfile | None:
    return getattr(panel.owner, "userprofile", None)


def _is_public_profile(profile: UserProfile) -> bool:
    return profile.profile_unlocked and profile.show_profile_publicly


def _profile_display_name(profile: UserProfile | None) -> str:
    if not profile:
        return ""
    return profile.display_name or profile.fursuit_name


def _panel_group_label(panel: Panel) -> str:
    if not panel.event_group_id:
        return ""
    parts = [panel.event_group.name]
    if panel.group_order is not None:
        parts.append(f"#{panel.group_order}")
    if panel.recurrence_label:
        parts.append(panel.recurrence_label)
    return " ".join(parts)


def _get_export_token(request, token: str, export_type: ExportType) -> ExportToken:
    export_token = (
        ExportToken.objects.select_related("project").filter(token=token).first()
    )
    if (
        export_token is None
        or not export_token.active
        or export_token.export_type != export_type.value
    ):
        _record_export_access(
            request=request,
            token=token,
            export_type=export_type,
            export_token=export_token,
            success=False,
            status_code=404,
        )
        raise Http404

    _record_export_access(
        request=request,
        token=token,
        export_type=export_type,
        export_token=export_token,
        success=True,
        status_code=200,
    )
    return export_token


def _record_export_access(
    *,
    request,
    token: str,
    export_type: ExportType,
    export_token: ExportToken | None,
    success: bool,
    status_code: int,
) -> None:
    ExportAccessLog.objects.create(
        project=export_token.project if export_token else None,
        export_token=export_token,
        export_type=export_type.value,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        success=success,
        status_code=status_code,
        remote_address=request.META.get("REMOTE_ADDR", ""),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )


def _export_token_rows(tokens) -> list[dict]:
    rows = []
    for token in tokens:
        successful_hits = [
            log.created_at for log in token.access_logs.all() if log.success
        ]
        failed_hits = [log for log in token.access_logs.all() if not log.success]
        rows.append(
            {
                "last_success_at": max(successful_hits) if successful_hits else None,
                "failed_count": len(failed_hits),
                "token": token,
                "token_hint": token.token[-8:],
            }
        )
    return rows


def _project_export(project: Project) -> dict:
    return {
        "name": project.name,
        "slug": project.slug,
        "timezone": project.timezone,
        "opens_at": project.opens_at.isoformat(),
        "closes_at": project.closes_at.isoformat(),
    }


def _panel_export(panel: Panel) -> dict:
    placement = panel.placement
    payload = {
        "type": "panel",
        "title": panel.title,
        "header_image": _file_url(panel.application.event_header_image),
        "starts_at": placement.starts_at.isoformat(),
        "ends_at": placement.ends_at.isoformat(),
        "location": _placement_location_name(placement, panel.project),
    }
    if panel.event_group_id:
        payload["group"] = {
            "name": panel.event_group.name,
            "slug": panel.event_group.slug,
            "order": panel.group_order,
            "recurrence_label": panel.recurrence_label,
        }
    return payload


def _public_profile_export(profile: UserProfile, project: Project) -> dict:
    payload = {
        "type": "profile",
        "display_name": _profile_display_name(profile) or "Convention participant",
        "fursuit_name": profile.fursuit_name,
        "bio": profile.bio,
        "profile_picture": _file_url(profile.profile_picture),
    }
    if profile.show_fursuit_picture:
        payload["fursuit_picture"] = _file_url(profile.fursuit_picture)
    if project.profile_contact_exports_enabled and profile.show_contact_handles:
        payload["contact"] = {
            "telegram": profile.telegram,
            "discord": profile.discord,
        }
    return payload


def _volunteer_shift_export(shift: VolunteerShift) -> dict:
    placement = shift.placement
    return {
        "type": "volunteer_shift",
        "title": shift.title,
        "role": shift.role,
        "starts_at": placement.starts_at.isoformat(),
        "ends_at": placement.ends_at.isoformat(),
        "location": _placement_location_name(placement, shift.project),
        "needed_volunteers": shift.needed_volunteers,
        "confirmed_assignments": shift.assignments.filter(
            status=AssignmentStatus.CONFIRMED.value
        ).count(),
    }


def _file_url(field) -> str:
    if not field:
        return ""
    return field.url


def _signage_reminder_export(reminder: SignageReminder) -> dict:
    return {
        "title": reminder.title,
        "body": reminder.body,
        "starts_at": reminder.starts_at.isoformat(),
        "ends_at": reminder.ends_at.isoformat(),
        "priority": reminder.priority,
    }


def _volunteer_claim_blocker(shift: VolunteerShift, user) -> str:
    if not can_claim_volunteer_shifts(user):
        return "You are not approved for volunteer shift claiming yet."
    if not hasattr(shift, "placement"):
        return "This shift is not scheduled yet."
    if shift.locked:
        return "Shift is locked"
    if VolunteerShiftAssignment.objects.filter(
        shift=shift,
        user=user,
    ).exclude(status=AssignmentStatus.REMOVED.value).exists():
        return "Already assigned"
    if shift.open_spots <= 0:
        return "Shift is full"
    if _user_has_overlapping_shift(user, shift):
        return "Conflicts with one of your assigned shifts"
    return ""


def _user_has_overlapping_shift(user, shift: VolunteerShift) -> bool:
    if not hasattr(shift, "placement"):
        return False
    return (
        VolunteerShiftAssignment.objects.filter(
            user=user,
            shift__placement__starts_at__lt=shift.placement.ends_at,
            shift__placement__ends_at__gt=shift.placement.starts_at,
        )
        .exclude(status=AssignmentStatus.REMOVED.value)
        .exclude(shift=shift)
        .exists()
    )


def _conflicting_panel_ids(panels: list[Panel]) -> set[int]:
    placed = [
        panel
        for panel in panels
        if hasattr(panel, "placement") and _placement_room_ids(panel.placement)
    ]
    conflicts = set()
    for index, panel in enumerate(placed):
        for other in placed[index + 1 :]:
            if _placements_conflict(panel.placement, other.placement):
                conflicts.update({panel.pk, other.pk})
    return conflicts


def _conflicting_shift_ids(shifts: list[VolunteerShift]) -> set[int]:
    placed = [
        shift
        for shift in shifts
        if hasattr(shift, "placement") and _placement_room_ids(shift.placement)
    ]
    conflicts = set()
    for index, shift in enumerate(placed):
        for other in placed[index + 1 :]:
            if _placements_conflict(shift.placement, other.placement):
                conflicts.update({shift.pk, other.pk})
    return conflicts


def _placements_conflict(first: TimetablePlacement, second: TimetablePlacement) -> bool:
    if not (_placement_room_ids(first) & _placement_room_ids(second)):
        return False
    return first.starts_at < second.ends_at and second.starts_at < first.ends_at


def _placement_room_ids(placement: TimetablePlacement) -> set[int]:
    if placement.room_id:
        return {placement.room_id}
    if placement.room_combination_id:
        return set(placement.room_combination.rooms.values_list("id", flat=True))
    return set()


def _reject_application(application: Application) -> None:
    application.status = ApplicationStatus.REJECTED.value
    application.save(update_fields=["status", "updated_at"])
    Notification.objects.create(
        user=application.applicant,
        title="Application rejected",
        body=(
            f"{application.title} was rejected for "
            f"{application.subproject.project.name}."
        ),
        link_url=reverse("projects:application_detail", args=[application.pk]),
        link_label="Open application",
    )
