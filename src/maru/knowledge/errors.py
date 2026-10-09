"""Non-disclosing unavailable and explicit authorized Guidance conflict results."""


class GuidanceError(Exception):
    """The complete authorized result is unavailable; do not return partial data."""


class GuidanceDeniedError(GuidanceError):
    """Current actor, exact scope or required field admission is unavailable."""


class GuidanceNotAvailableError(GuidanceError):
    """No current reader copy is available, without exposing private existence."""


class GuidanceVersionConflictError(GuidanceError):
    """An authorized command observed a stale item or settings cursor."""


class GuidanceStateConflictError(GuidanceError):
    """The authorized action cannot proceed from the current workflow state."""


class GuidanceIdempotencyConflictError(GuidanceError):
    """An actor reused a retained retry key for a different normalized intent."""


class GuidanceSettingsRequiredError(GuidanceError):
    """Current confirmed rules and an accepted Guidance team are required."""


class GuidanceLimitError(GuidanceError):
    """The complete result exceeds a declared content or evidence bound."""
