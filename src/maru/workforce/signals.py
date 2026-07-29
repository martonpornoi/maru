"""Small invariant-preserving workforce signals."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from maru.workforce.models import Position, VolunteerOpportunity


@receiver(post_save, sender=Position)
def ensure_position_opportunity(
    sender: type[Position],
    instance: Position,
    created: bool,  # noqa: FBT001
    **kwargs: object,
) -> None:
    """Every position owns a separately publishable application opportunity."""

    _ = sender, kwargs
    if created:
        VolunteerOpportunity.objects.create(
            position=instance,
            headline=instance.title,
            description=instance.description,
        )
