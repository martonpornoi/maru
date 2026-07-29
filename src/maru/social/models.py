from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class SocialPost(models.Model):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"

    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (SCHEDULED, "Scheduled"),
        (PUBLISHED, "Published"),
    ]

    project = models.ForeignKey(
        "projects.Project",
        related_name="social_posts",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    body = models.TextField()
    embed_url = models.URLField(blank=True)
    media = models.FileField(upload_to="social/media/", blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=DRAFT)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-updated_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_published(self) -> bool:
        return self.status == self.PUBLISHED

    @property
    def is_scheduled(self) -> bool:
        return self.status == self.SCHEDULED

    def save_version(self, *, created_by, action: str) -> SocialPostVersion:
        latest = self.versions.order_by("-version_number").first()
        version_number = 1 if latest is None else latest.version_number + 1
        return SocialPostVersion.objects.create(
            post=self,
            version_number=version_number,
            title=self.title,
            body=self.body,
            embed_url=self.embed_url,
            media_name=self.media.name,
            status=self.status,
            scheduled_for=self.scheduled_for,
            published_at=self.published_at,
            action=action,
            created_by=created_by,
        )

    def publish(self, *, created_by) -> SocialPostVersion:
        self.status = self.PUBLISHED
        self.scheduled_for = None
        self.published_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "scheduled_for",
                "published_at",
                "updated_at",
            ]
        )
        version = self.save_version(
            created_by=created_by,
            action=SocialPostVersion.PUBLISH,
        )
        for channel in SocialPublicationChannel.values:
            SocialPublication.objects.create(
                post=self,
                version=version,
                channel=channel,
                payload={
                    "title": self.title,
                    "body": self.body,
                    "embed_url": self.embed_url,
                    "media": self.media.name,
                },
            )
        return version

    def schedule(self, *, scheduled_for, created_by) -> SocialPostVersion:
        self.status = self.SCHEDULED
        self.scheduled_for = scheduled_for
        self.published_at = None
        self.save(
            update_fields=[
                "status",
                "scheduled_for",
                "published_at",
                "updated_at",
            ]
        )
        return self.save_version(
            created_by=created_by,
            action=SocialPostVersion.SCHEDULE,
        )


class SocialPostVersion(models.Model):
    SAVE = "save"
    SCHEDULE = "schedule"
    PUBLISH = "publish"

    ACTION_CHOICES = [
        (SAVE, "Saved"),
        (SCHEDULE, "Scheduled"),
        (PUBLISH, "Published"),
    ]

    post = models.ForeignKey(
        SocialPost,
        related_name="versions",
        on_delete=models.CASCADE,
    )
    version_number = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    body = models.TextField()
    embed_url = models.URLField(blank=True)
    media_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=24, choices=SocialPost.STATUS_CHOICES)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["post", "version_number"],
                name="unique_social_post_version_number",
            )
        ]
        ordering = ["-version_number"]

    def __str__(self) -> str:
        return f"{self.post}: v{self.version_number}"


class SocialPublicationChannel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    BLUESKY = "bluesky", "Bluesky"
    X = "x", "X"


class SocialPublication(models.Model):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"

    STATUS_CHOICES = [
        (QUEUED, "Queued"),
        (SENT, "Sent"),
        (FAILED, "Failed"),
        (SKIPPED, "Skipped"),
    ]

    post = models.ForeignKey(
        SocialPost,
        related_name="publications",
        on_delete=models.CASCADE,
    )
    version = models.ForeignKey(
        SocialPostVersion,
        related_name="publications",
        on_delete=models.CASCADE,
    )
    channel = models.CharField(max_length=24, choices=SocialPublicationChannel.choices)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=QUEUED)
    payload = models.JSONField(default=dict)
    response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "channel"]

    def __str__(self) -> str:
        return f"{self.post}: {self.get_channel_display()} {self.status}"
