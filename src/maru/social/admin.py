from __future__ import annotations

from django.contrib import admin

from maru.social.models import SocialPost, SocialPostVersion, SocialPublication


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "author",
        "status",
        "scheduled_for",
        "published_at",
        "updated_at",
    ]
    list_filter = ["status"]
    search_fields = ["title", "body", "author__email"]


@admin.register(SocialPostVersion)
class SocialPostVersionAdmin(admin.ModelAdmin):
    list_display = ["post", "version_number", "action", "created_by", "created_at"]
    list_filter = ["action", "status"]
    search_fields = ["post__title", "title", "created_by__email"]


@admin.register(SocialPublication)
class SocialPublicationAdmin(admin.ModelAdmin):
    list_display = ["post", "channel", "status", "created_at", "updated_at"]
    list_filter = ["channel", "status"]
    search_fields = ["post__title"]
