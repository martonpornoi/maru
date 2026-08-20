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
    """Every position owns a separately publishable application opportunity.

    Parameters
    ----------
    sender : type[Position]
        The delivery adapter responsible for the external send attempt.
    instance : Position
        The instance evaluated while ensure position opportunity.
    created : bool
        The created evaluated while ensure position opportunity.
    **kwargs : object
        Dispatch metadata supplied by Django's signal framework.
    """
    _ = sender, kwargs
    if created:
        VolunteerOpportunity.objects.create(
            position=instance,
            headline=instance.title,
            description=instance.description,
        )
