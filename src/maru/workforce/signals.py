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
    # Governed Position commands create the versioned opportunity explicitly so
    # both rows can share one aggregate version and one immutable receipt. Keep
    # this compatibility hook only for legacy/bootstrap fixture writers whose
    # Position has no structure-command evidence.
    if created and instance.created_in_structure_version is None:
        VolunteerOpportunity.objects.create(
            position=instance,
            headline=instance.title,
            description=instance.description,
        )
