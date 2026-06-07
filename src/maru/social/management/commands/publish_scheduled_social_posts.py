from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from maru.social.models import SocialPost


class Command(BaseCommand):
    help = "Publish scheduled social media posts whose scheduled time has arrived."

    def handle(self, *args, **options):
        due_posts = SocialPost.objects.filter(
            status=SocialPost.SCHEDULED,
            scheduled_for__lte=timezone.now(),
        ).select_related("author")
        published_count = 0
        for post in due_posts:
            post.publish(created_by=post.author)
            published_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {published_count} scheduled social media posts."
            )
        )
