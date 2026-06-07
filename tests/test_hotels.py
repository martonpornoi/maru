from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import (
    Hotel,
    HotelFloorPlan,
    Panel,
    Project,
    ProjectRoomAvailability,
    ProjectRoomSetting,
    Room,
)


@pytest.mark.django_db
def test_admin_can_upload_multiple_floor_layouts(client, tmp_path) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    hotel = Hotel.objects.get(
        projects__slug="awoostria-2026",
        name="Main Convention Hotel",
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        first = client.post(
            reverse("projects:hotel_detail", args=[hotel.pk]),
            {
                "floor_label": "Level 1",
                "image": _image_upload("level-1.png"),
                "notes": "Main event floor.",
            },
        )
        second = client.post(
            reverse("projects:hotel_detail", args=[hotel.pk]),
            {
                "floor_label": "Level 2",
                "image": _image_upload("level-2.png"),
                "notes": "Workshop floor.",
            },
        )
        response = client.get(reverse("projects:hotel_detail", args=[hotel.pk]))

    content = response.content.decode()
    assert first.status_code == 302
    assert second.status_code == 302
    assert response.status_code == 200
    assert HotelFloorPlan.objects.filter(hotel=hotel).count() == 2
    assert "Level 1" in content
    assert "Level 2" in content


@pytest.mark.django_db
def test_admin_can_edit_and_remove_floor_layout(client, tmp_path) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    hotel = Hotel.objects.get(
        projects__slug="awoostria-2026",
        name="Main Convention Hotel",
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        floor_plan = HotelFloorPlan.objects.create(
            hotel=hotel,
            floor_label="Level 1",
            image=_image_upload("level-1.png"),
            notes="Old notes.",
        )
        edit_response = client.post(
            reverse("projects:edit_hotel_floor_plan", args=[floor_plan.pk]),
            {
                "floor_label": "Lobby Level",
                "image": _image_upload("lobby.png"),
                "notes": "Updated notes.",
            },
        )
        floor_plan.refresh_from_db()
        delete_response = client.post(
            reverse("projects:delete_hotel_floor_plan", args=[floor_plan.pk])
        )

    assert edit_response.status_code == 302
    assert floor_plan.floor_label == "Lobby Level"
    assert floor_plan.notes == "Updated notes."
    assert floor_plan.image.name.endswith("lobby.png")
    assert delete_response.status_code == 302
    assert not HotelFloorPlan.objects.filter(pk=floor_plan.pk).exists()


@pytest.mark.django_db
def test_project_can_select_reusable_hotels(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="neon-paws-2027")
    hotel = Hotel.objects.get(name="Main Convention Hotel")

    response = client.post(
        reverse("projects:project_room_settings", args=[project.slug]),
        {
            "action": "update_hotels",
            "hotels": [str(hotel.pk)],
        },
    )

    assert response.status_code == 302
    assert project.hotels.filter(pk=hotel.pk).exists()


@pytest.mark.django_db
def test_project_hotel_settings_link_to_general_hotel_database(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.get(
        reverse("projects:project_room_settings", args=[project.slug])
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Add hotel to database" in content
    assert reverse("projects:create_hotel") in content
    assert "Open general hotels" in content
    assert reverse("projects:hotel_list") in content


@pytest.mark.django_db
def test_regular_user_cannot_access_hotels_page(client) -> None:
    call_command("seed_demo")
    _allow_user("regularhost@gmail.com")
    client.post(reverse("accounts:login"), {"email": "regularhost@gmail.com"})

    response = client.get(reverse("projects:hotel_list"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_can_rename_and_block_room_for_project_only(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    room = Room.objects.get(hotel__projects=project, name="Panel Room A")
    response = client.get(
        reverse("projects:project_room_settings", args=[project.slug])
    )
    setting = ProjectRoomSetting.objects.get(project=project, room=room)

    response = client.post(
        reverse("projects:edit_project_room_setting", args=[setting.pk]),
        {
            "action": "save",
            "local_name": "Blue Stage",
            "blocked": "on",
            "notes": "Reserved for hotel operations this year.",
        },
    )

    room.refresh_from_db()
    setting.refresh_from_db()
    assert response.status_code == 302
    assert room.name == "Panel Room A"
    assert setting.display_name == "Blue Stage"
    assert setting.blocked


@pytest.mark.django_db
def test_timetable_uses_project_local_room_name(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    panel = Panel.objects.get(title="Fursuit Cooling 101")
    setting, _ = ProjectRoomSetting.objects.get_or_create(
        project=project,
        room=panel.placement.room,
    )
    setting.local_name = "Blue Stage"
    setting.save(update_fields=["local_name"])

    response = client.get(reverse("projects:timetable", args=[project.slug]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Blue Stage" in content
    assert "Fursuit Cooling 101" in content


@pytest.mark.django_db
def test_room_opening_windows_limit_panel_placement(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")
    panel = Panel.objects.get(title="Fursuit Cooling 101")
    setting, _ = ProjectRoomSetting.objects.get_or_create(
        project=project,
        room=panel.placement.room,
    )
    ProjectRoomAvailability.objects.create(
        setting=setting,
        starts_at="2026-07-22T12:00:00+02:00",
        ends_at="2026-07-22T13:00:00+02:00",
    )

    response = client.post(
        reverse("projects:place_panel", args=[panel.pk]),
        {
            "location": f"room:{panel.placement.room_id}",
            "starts_at": "2026-07-22T11:00",
            "ends_at": "2026-07-22T12:00",
        },
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "This room is not open for the selected time" in content


def _allow_user(email: str) -> None:
    grant = AccessGrant.objects.create(email=email)
    AccessRole.objects.create(grant=grant, role=Role.REGISTERED_USER.value)


def _image_upload(name: str) -> SimpleUploadedFile:
    image_file = io.BytesIO()
    image = Image.new("RGB", (1600, 900), color="#d7eef7")
    image.save(image_file, format="PNG")
    return SimpleUploadedFile(
        name,
        image_file.getvalue(),
        content_type="image/png",
    )
