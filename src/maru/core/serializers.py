"""Domain-neutral strict API input primitives."""

from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers


class StrictInputSerializer(serializers.Serializer[dict[str, object]]):
    """Reject undeclared JSON and query properties instead of ignoring them."""

    def to_internal_value(self, data: Any) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown_fields = sorted(
                str(field_name)
                for field_name in data
                if str(field_name) not in self.fields
            )
            if unknown_fields:
                raise serializers.ValidationError(
                    {
                        field_name: ["This field is not allowed."]
                        for field_name in unknown_fields
                    },
                    code="unknown_field",
                )
        return cast(dict[str, object], super().to_internal_value(data))


__all__ = ["StrictInputSerializer"]
