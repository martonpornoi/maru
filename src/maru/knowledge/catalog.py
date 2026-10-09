"""Closed Guidance vocabulary, fixed purpose and bounded evidence budgets."""

DIGEST_HEX_LENGTH = 64
MAX_TITLE = 160
MAX_BODY = 12000
MAX_NOTE = 1000
MAX_REVISIONS = 256
MAX_HISTORY = 4096
MAX_CONTROL_HISTORY = 4096
MAX_ITEMS = 500
MAX_PAGE_SIZE = 100
MAX_QUERY = 120
MAX_STORED_TEXT_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 16 * 1024 * 1024
PURPOSE = "internal convention guidance"
AUDIENCE_LABEL = "People with access to guides for this event"
OWNER_LABEL = "Guides team for this event"
PLACEMENTS = ("knowledge.compose", "announcements.compose")
STATUSES = ("draft", "in_review", "changes_requested", "approved", "withdrawn")
OPERATIONS = (
    "settings_update",
    "stop",
    "resume",
    "create",
    "revise",
    "request_review",
    "approve",
    "changes_requested",
    "withdraw",
)
OPERATION_CAPABILITIES = {
    "settings_update": "knowledge.manage_settings",
    "stop": "knowledge.manage_settings",
    "resume": "knowledge.manage_settings",
    "create": "knowledge.compose",
    "revise": "knowledge.compose",
    "request_review": "knowledge.compose",
    "approve": "knowledge.review",
    "changes_requested": "knowledge.review",
    "withdraw": "knowledge.withdraw",
}
CAPABILITY_FIELDS = {
    "knowledge.view_current": frozenset({"current_summary", "current_copy"}),
    "knowledge.view_working": frozenset({"draft", "review_notes", "history"}),
    "knowledge.compose": frozenset({"draft"}),
    "knowledge.review": frozenset({"review"}),
    "knowledge.withdraw": frozenset({"availability"}),
    "knowledge.manage_settings": frozenset({"settings"}),
    "knowledge.export_evidence": frozenset({"evidence"}),
}
EVENT_NAME = "knowledge.changed.v1"
RETENTION_CLASS = "guidance-evidence"
