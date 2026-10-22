"""Closed version-one interchange schema for a Workforce rota snapshot."""

from __future__ import annotations

from typing import Any


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def rota_schema() -> dict[str, Any]:
    """Return the portable, closed schema shipped with every rota package.

    Returns
    -------
    dict[str, Any]
        JSON Schema 2020-12; consumers must also enforce their own authority.
    """
    identifier = {"type": "string", "format": "uuid"}
    text = {"type": "string"}
    instant = {"type": "string", "format": "date-time"}
    count = {"type": "integer", "minimum": 0}
    version = {"type": "integer", "minimum": 1}
    boolean = {"type": "boolean"}
    commitment = _object(
        {
            "id": identifier,
            "version": version,
            "display_label": text,
            "status": {"enum": ["claimed", "confirmed", "removed", "completed"]},
            "availability_current": boolean,
            "qualification_current": boolean,
            "rest_ends_at": instant,
        }
    )
    shift = _object(
        {
            "id": identifier,
            "version": version,
            "department_name": text,
            "position_id": identifier,
            "position_title": text,
            "title": text,
            "status": {"enum": ["draft", "open", "locked", "cancelled", "completed"]},
            "starts_at": instant,
            "ends_at": instant,
            "local_starts_at": instant,
            "local_ends_at": instant,
            "location": text,
            "briefing": text,
            "supervision": text,
            "required_headcount": version,
            "break_minutes": count,
            "minimum_rest_minutes": count,
            "claimed_count": count,
            "confirmed_count": count,
            "remaining_count": count,
            "commitments": {"type": "array", "items": commitment, "maxItems": 4096},
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Maru Workforce rota snapshot version 1",
        **_object(
            {
                "format": {"const": "maru.workforce-rota"},
                "version": {"const": 1},
                "observed_at": instant,
                "scope": _object(
                    {
                        "organization_id": identifier,
                        "series_id": identifier,
                        "edition_id": identifier,
                        "edition_name": text,
                        "edition_version": version,
                        "edition_lifecycle": text,
                        "starts_on": {"type": "string", "format": "date"},
                        "ends_on": {"type": "string", "format": "date"},
                        "time_zone": text,
                        "profile_code": {"const": "workforce_only"},
                        "profile_version": {"const": 1},
                    }
                ),
                "limitations": {"type": "array", "items": text},
                "shifts": {"type": "array", "items": shift, "maxItems": 1024},
            }
        ),
    }
