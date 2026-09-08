"""Content-free Scheduling event contract for the retained control stream."""

from typing import Final

from django.core.exceptions import ValidationError

from .catalogs import SchedulingOperation, scheduling_values

SCHEDULING_CHANGED_EVENT: Final = "scheduling.planning.changed.v1"
SCHEDULING_CHANGED_SCHEMA_VERSION: Final = 1


def validate_scheduling_changed_payload(payload: dict[str, object]) -> None:
    """Accept only a closed action; no timing, person or private content is delivered.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload before durable publication.

    Raises
    ------
    ValidationError
        If fields, types or the operation do not match the version-one contract.
    """
    if (
        set(payload) != {"operation"}
        or type(payload.get("operation")) is not str
        or payload["operation"] not in scheduling_values(SchedulingOperation)
    ):
        raise ValidationError(
            "Use the closed Scheduling event payload.",
            code="invalid_domain_event_payload",
        )
