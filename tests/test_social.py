from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from maru.accounts.models import AccessGrant, AccessRole
from maru.domain import SEED_ACCESS_EMAIL, Role
from maru.projects.models import Project
from maru.social.models import SocialPost, SocialPostVersion, SocialPublication


@pytest.mark.django_db
def test_social_media_is_listed_under_public_navigation(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("accounts:my_profile"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Social Media" in content
    assert reverse("social:list") in content


@pytest.mark.django_db
def test_social_media_new_post_button_is_in_admin_section(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.get(reverse("social:list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Admin" in content
    assert f'class="button" href="{reverse("social:create")}"' in content
    assert "New post" in content


@pytest.mark.django_db
def test_user_can_save_social_media_draft_with_version(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("social:create"),
        {
            "title": "Dance deadline update",
            "body": "Applications close tonight.",
            "embed_url": "https://example.com/countdown.gif",
            "action": "save",
        },
        follow=True,
    )

    post = SocialPost.objects.get(title="Dance deadline update")
    version = SocialPostVersion.objects.get(post=post)
    content = response.content.decode()
    assert response.status_code == 200
    assert post.status == SocialPost.DRAFT
    assert version.version_number == 1
    assert version.action == SocialPostVersion.SAVE
    assert version.embed_url == "https://example.com/countdown.gif"
    assert "Social media draft saved" in content
    assert "Dance deadline update" in content


@pytest.mark.django_db
def test_publish_social_media_post_queues_publications(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})

    response = client.post(
        reverse("social:create"),
        {
            "title": "Main stage opens",
            "body": "Doors open in ten minutes.",
            "embed_url": "https://video.example/stage",
            "action": "publish",
        },
        follow=True,
    )

    post = SocialPost.objects.get(title="Main stage opens")
    version = SocialPostVersion.objects.get(post=post)
    publications = SocialPublication.objects.filter(post=post)
    content = response.content.decode()
    assert response.status_code == 200
    assert post.status == SocialPost.PUBLISHED
    assert post.published_at is not None
    assert version.action == SocialPostVersion.PUBLISH
    assert publications.count() == 3
    assert set(publications.values_list("channel", flat=True)) == {
        "telegram",
        "bluesky",
        "x",
    }
    assert set(publications.values_list("status", flat=True)) == {"queued"}
    assert "Publication Queue" in content
    assert "Published externally?" in content
    assert "No" in content
    assert "Telegram" in content
    assert "Bluesky" in content
    assert "X" in content


@pytest.mark.django_db
def test_social_media_post_can_be_scheduled_for_future_publication(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    scheduled_for = timezone.localtime(timezone.now() + timezone.timedelta(days=1))

    response = client.post(
        reverse("social:create"),
        {
            "title": "Future announcement",
            "body": "This goes out tomorrow.",
            "scheduled_for": scheduled_for.strftime("%Y-%m-%dT%H:%M"),
            "action": "publish",
        },
        follow=True,
    )

    post = SocialPost.objects.get(title="Future announcement")
    version = SocialPostVersion.objects.get(post=post)
    content = response.content.decode()
    assert response.status_code == 200
    assert post.status == SocialPost.SCHEDULED
    assert post.scheduled_for is not None
    assert post.published_at is None
    assert version.action == SocialPostVersion.SCHEDULE
    assert version.scheduled_for is not None
    assert not SocialPublication.objects.filter(post=post).exists()
    assert "Social media post scheduled for publication" in content
    assert "Scheduled for" in content


@pytest.mark.django_db
def test_project_social_media_posts_stay_project_scoped(client) -> None:
    call_command("seed_demo")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    project = Project.objects.get(slug="awoostria-2026")

    response = client.post(
        reverse("social:project_create", args=[project.slug]),
        {
            "title": "Project-only update",
            "body": "This belongs to Awoostria.",
            "action": "save",
        },
        follow=True,
    )

    post = SocialPost.objects.get(title="Project-only update")
    content = response.content.decode()
    assert response.status_code == 200
    assert post.project == project
    assert reverse("social:project_list", args=[project.slug]) in content
    assert reverse("social:project_edit", args=[project.slug, post.pk]) in content

    project_response = client.get(reverse("social:project_list", args=[project.slug]))
    global_response = client.get(reverse("social:list"))

    assert "Project-only update" in project_response.content.decode()
    assert "Project-only update" not in global_response.content.decode()


@pytest.mark.django_db
def test_publish_scheduled_social_posts_command_publishes_due_posts() -> None:
    call_command("seed_maru")
    _create_access_user("social.author@gmail.com")
    author = get_user_model().objects.create(
        username="social.author@gmail.com",
        email="social.author@gmail.com",
    )
    due_post = SocialPost.objects.create(
        author=author,
        title="Due post",
        body="Ready now.",
        status=SocialPost.SCHEDULED,
        scheduled_for=timezone.now() - timezone.timedelta(minutes=5),
    )
    future_post = SocialPost.objects.create(
        author=author,
        title="Future post",
        body="Not yet.",
        status=SocialPost.SCHEDULED,
        scheduled_for=timezone.now() + timezone.timedelta(minutes=5),
    )

    call_command("publish_scheduled_social_posts")

    due_post.refresh_from_db()
    future_post.refresh_from_db()
    assert due_post.status == SocialPost.PUBLISHED
    assert due_post.published_at is not None
    assert due_post.scheduled_for is None
    assert due_post.versions.get().action == SocialPostVersion.PUBLISH
    assert due_post.publications.count() == 3
    assert future_post.status == SocialPost.SCHEDULED
    assert not future_post.publications.exists()


@pytest.mark.django_db
def test_other_registered_user_cannot_view_unpublished_draft(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    response = client.post(
        reverse("social:create"),
        {
            "title": "Private draft",
            "body": "Not ready.",
            "action": "save",
        },
    )
    post = SocialPost.objects.get(title="Private draft")
    client.post(reverse("accounts:logout"))
    _create_access_user("regular.viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "regular.viewer@gmail.com"})

    response = client.get(reverse("social:detail", args=[post.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_published_social_media_post_is_visible_to_registered_users(client) -> None:
    call_command("seed_maru")
    client.post(reverse("accounts:login"), {"email": SEED_ACCESS_EMAIL})
    client.post(
        reverse("social:create"),
        {
            "title": "Published reminder",
            "body": "Bring your badge.",
            "action": "publish",
        },
    )
    client.post(reverse("accounts:logout"))
    _create_access_user("regular.viewer@gmail.com")
    client.post(reverse("accounts:login"), {"email": "regular.viewer@gmail.com"})

    response = client.get(reverse("social:list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Published reminder" in content
    assert "Bring your badge." in content


def _create_access_user(email: str) -> AccessGrant:
    grant = AccessGrant.objects.create(email=email)
    AccessRole.objects.create(grant=grant, role=Role.REGISTERED_USER.value)
    return grant
