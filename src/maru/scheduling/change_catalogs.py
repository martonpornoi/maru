"""Closed Programme notice purposes and independent evidence vocabularies."""

from enum import StrEnum
from typing import Final

MAX_CHANGE_NOTICES: Final = 65_536
MAX_CHANGE_NOTICE_INVENTORY: Final = 256


class ChangeRecipientPurpose(StrEnum):
    """An exact owner relationship or operational scope, not an audience list."""

    HOST = "host"
    WORK = "work"
    ROOM = "room"
    DEPARTMENT = "department"
    EDITION = "edition"


class ChangeNoticeAction(StrEnum):
    """Closed facts; export and provider delivery are deliberately not included."""

    APPROVE = "approve"
    REJECT = "reject"
    HANDOFF = "handoff"
    ACKNOWLEDGE = "acknowledge"


class ChangeNoticeReview(StrEnum):
    """An independent review outcome is not handoff or acknowledgement."""

    APPROVED = "approved"
    REJECTED = "rejected"


class ChangeNoticeSourceState(StrEnum):
    """A suppressed comparison is not an empty release or mass cancellation."""

    AVAILABLE = "available"
    WITHDRAWN = "withdrawn"
    INVALIDATED = "invalidated"
    COMPARISON_SUPPRESSED = "comparison_suppressed"
