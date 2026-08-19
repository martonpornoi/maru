"""Conservative structured logging for operational metadata."""

import json
import logging
from datetime import UTC, datetime
from typing import ClassVar

from maru.core.correlation import correlation_id


class SafeJsonFormatter(logging.Formatter):
    """Serialize an allowlist of technical log fields as one JSON object."""

    allowed_extra_fields: ClassVar[tuple[str, ...]] = (
        "service",
        "release",
        "environment",
        "capability",
        "organization_id",
        "event_edition_id",
        "principal_kind",
        "result",
        "reason_code",
        "duration_ms",
        "dependency",
        "safe_error_code",
        "workload_pool",
        "outbox_status",
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as structured JSON.

        Parameters
        ----------
        record : logging.LogRecord
            The domain record to validate, persist, or project.

        Returns
        -------
        str
            The normalized text for format.
        """
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        request_id = correlation_id.get()
        if request_id is not None:
            payload["correlation_id"] = request_id

        for field_name in self.allowed_extra_fields:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value

        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
