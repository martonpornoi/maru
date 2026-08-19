"""Abstract persistence primitives with no convention-domain meaning."""

from uuid import uuid4

from django.db import models


class UUIDTimeStampedModel(models.Model):
    """Store uuidtime stamped records."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True
