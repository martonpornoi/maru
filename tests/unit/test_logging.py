import json
import logging
from typing import TYPE_CHECKING

from maru.core.correlation import correlation_id
from maru.core.logging import SafeJsonFormatter

if TYPE_CHECKING:
    from types import TracebackType


def test_safe_json_formatter_uses_allowlist_and_correlation() -> None:
    record = logging.LogRecord(
        name="maru.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="command completed",
        args=(),
        exc_info=None,
    )
    record.capability = "edition.view"  # type: ignore[attr-defined]
    record.email = "secret@example.com"  # type: ignore[attr-defined]
    token = correlation_id.set("1d8f179f-22e4-4ca5-a181-f70ed0d3a412")
    try:
        payload = json.loads(SafeJsonFormatter().format(record))
    finally:
        correlation_id.reset(token)

    assert payload["event"] == "command completed"
    assert payload["capability"] == "edition.view"
    assert payload["correlation_id"] == "1d8f179f-22e4-4ca5-a181-f70ed0d3a412"
    assert "email" not in payload


def test_safe_json_formatter_records_exception_type_not_message() -> None:
    exception_info: tuple[
        type[BaseException],
        BaseException,
        TracebackType | None,
    ] = (ValueError, ValueError("sensitive@example.com"), None)
    record = logging.LogRecord(
        name="maru.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=12,
        msg="operation failed",
        args=(),
        exc_info=exception_info,
    )

    rendered = SafeJsonFormatter().format(record)

    assert '"exception_type":"ValueError"' in rendered
    assert "sensitive@example.com" not in rendered
