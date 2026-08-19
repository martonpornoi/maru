"""Closed JSON parser for Logistics command boundaries."""

from __future__ import annotations

import codecs
from collections.abc import Mapping, Sequence
from typing import Any, TextIO, cast

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.utils import json


class _DuplicateMemberError(ValueError):
    pass


def _closed_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateMemberError
        result[key] = value
    return result


class ClosedLogisticsJSONParser(JSONParser):
    """Reject duplicate JSON members instead of silently keeping the last one."""

    def parse(
        self,
        stream: Any,
        media_type: str | None = None,
        parser_context: Mapping[str, Any] | None = None,
    ) -> Any:
        del media_type
        context = parser_context or {}
        encoding = context.get("encoding", settings.DEFAULT_CHARSET)
        try:
            decoded_stream = cast(TextIO, codecs.getreader(encoding)(stream))
            parse_constant = json.strict_constant if self.strict else None
            return json.load(
                decoded_stream,
                parse_constant=parse_constant,
                object_pairs_hook=_closed_object,
            )
        except _DuplicateMemberError as error:
            raise ParseError("JSON parse error - duplicate object member") from error
        except ValueError as error:
            raise ParseError(f"JSON parse error - {error}") from error


__all__ = ["ClosedLogisticsJSONParser"]
