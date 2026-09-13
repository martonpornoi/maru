"""Content-free Scheduling event contract for the retained control stream."""

from typing import Final

from django.core.exceptions import ValidationError

from .catalogs import (
    CHANGE_OPERATION_VALUES,
    PLANNING_OPERATION_VALUES,
    RELEASE_OPERATION_VALUES,
)

SCHEDULING_CHANGED_EVENT: Final = "scheduling.planning.changed.v1"
SCHEDULING_CHANGED_SCHEMA_VERSION: Final = 1
SCHEDULING_RELEASE_CHANGED_EVENT: Final = "scheduling.release.changed.v1"
SCHEDULING_NOTICE_CHANGED_EVENT: Final = "scheduling.change_notice.changed.v1"


# The shared closed validator raises the documented error for both public seams.
def validate_scheduling_changed_payload(payload: dict[str, object]) -> None:  # noqa: DOC502
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
    _validate_operation(payload, PLANNING_OPERATION_VALUES)


def validate_scheduling_release_changed_payload(payload: dict[str, object]) -> None:  # noqa: DOC502
    """Validate a release decision without treating it as private planning activity.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload before atomic durable publication.

    Raises
    ------
    ValidationError
        For unknown release operations, private fields or unserialized values.

    Notes
    -----
    This registered schema remains dormant. It sends no notification and exposes
    no artifact, person, source reference or human explanation.
    """
    _validate_operation(payload, RELEASE_OPERATION_VALUES)


def validate_scheduling_notice_changed_payload(payload: dict[str, object]) -> None:  # noqa: DOC502
    """Validate a minimized notice fact without disclosing people or change content.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload before atomic publication.

    Raises
    ------
    ValidationError
        For extra fields, untyped values or an unknown notice operation.

    Notes
    -----
    This internal event is not a recipient message or provider delivery receipt.
    No external route or current profile is activated by its registration.
    """
    _validate_operation(payload, CHANGE_OPERATION_VALUES)


def _validate_operation(
    payload: dict[str, object], operations: tuple[str, ...]
) -> None:
    if (
        set(payload) != {"operation"}
        or type(payload.get("operation")) is not str
        or payload["operation"] not in operations
    ):
        raise ValidationError(
            "Use the closed Scheduling event payload.",
            code="invalid_domain_event_payload",
        )
