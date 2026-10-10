"""Closed workflow vocabulary and resource bounds for announcement work."""

MAX_CHANNELS = 16
MAX_VARIANTS = 32
MAX_REVISIONS = 256
MAX_REPORTS = 2048
MAX_HISTORY = 4096
MAX_HEADLINE = 200
MAX_BODY = 8000
MAX_NOTE = 1000
MAX_STORED_TEXT_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 16 * 1024 * 1024
STATUSES = ("draft", "in_review", "changes_requested", "approved", "cancelled")
OPERATIONS = (
    "settings_update",
    "stop",
    "resume",
    "create",
    "revise",
    "request_review",
    "approve",
    "changes_requested",
    "record_publication",
    "correct_publication",
    "withdraw_report",
    "cancel",
)
OPERATION_CAPABILITIES = {
    "settings_update": "announcements.manage_settings",
    "stop": "announcements.manage_settings",
    "resume": "announcements.manage_settings",
    "create": "announcements.compose",
    "revise": "announcements.compose",
    "request_review": "announcements.compose",
    "approve": "announcements.review",
    "changes_requested": "announcements.review",
    "record_publication": "announcements.record_publication",
    "correct_publication": "announcements.record_publication",
    "withdraw_report": "announcements.record_publication",
    "cancel": "announcements.compose",
}
CAPABILITY_FIELDS = {
    "announcements.view": frozenset({"announcement"}),
    "announcements.compose": frozenset({"announcement"}),
    "announcements.review": frozenset({"announcement", "review"}),
    "announcements.record_publication": frozenset({"publication"}),
    "announcements.manage_settings": frozenset({"settings"}),
    "announcements.export_evidence": frozenset({"evidence"}),
}
EVENT_NAME = "announcements.changed.v1"
RETENTION_CLASS = "announcement-evidence"
