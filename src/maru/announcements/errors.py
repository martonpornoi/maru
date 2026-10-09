"""Content-free stable failures shared by all Announcements adapters."""


class AnnouncementError(RuntimeError):
    """An authorized operation could not complete."""

    reason_code = "announcement_unavailable"


class AnnouncementDeniedError(AnnouncementError):
    """Do not disclose which actor, scope, record or field caused denial."""

    reason_code = "announcement_denied"


class AnnouncementVersionConflictError(AnnouncementError):
    """The caller must compare current work before submitting another command."""

    reason_code = "announcement_version_conflict"


class AnnouncementIdempotencyConflictError(AnnouncementError):
    """One actor's retained retry key cannot express changed intent."""

    reason_code = "announcement_retry_conflict"


class AnnouncementStateConflictError(AnnouncementError):
    """The current lifecycle does not admit this transition."""

    reason_code = "announcement_state_conflict"


class AnnouncementSettingsRequiredError(AnnouncementError):
    """Current confirmed record-keeping rules are required for new content."""

    reason_code = "announcement_settings_required"


class AnnouncementLimitError(AnnouncementError):
    """A complete bounded result cannot fit; partial success is prohibited."""

    reason_code = "announcement_limit_reached"
