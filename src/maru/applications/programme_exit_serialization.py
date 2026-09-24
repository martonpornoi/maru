"""Closed portable Applications records with private file bytes kept separate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from maru.programme.exit_archive_protocol import (
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
)

from . import programme_queries as calls
from . import programme_review_inputs as policies
from .programme_decider_queries import DecisionMessage
from .programme_exit_configuration_queries import (
    ProgrammeExitCall,
    ProgrammeExitConfiguration,
)
from .programme_exit_department_queries import (
    ProgrammeExitCaseBundle,
    ProgrammeExitDepartment,
)
from .programme_exit_file_queries import ProgrammeExitReviewFile
from .programme_exit_review_queries import ProgrammeExitReviewCase
from .programme_review_setup_queries import ReviewSetupPolicy

if TYPE_CHECKING:
    from collections.abc import Mapping

type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]

MAX_OWNER_JSON_BYTES: Final = 67_108_864
MAX_OWNER_VALUE_NODES: Final = 2_000_000
MAX_RECORD_DEPTH: Final = 32
EXCLUSIONS: Final = (
    "private-unreviewed-proposals",
    "stage-withheld-and-anonymous-identifying-answers",
    "contributor-invitation-secrets",
    "recipient-directory-and-private-receipt-state",
)

# Each field is selected deliberately; ordinary DTO growth never expands export.
_RECORDS: Final[Mapping[type, tuple[str, tuple[str, ...]]]] = MappingProxyType(
    {
        ProgrammeExitDepartment: ("department", ("configuration", "cases")),
        ProgrammeExitConfiguration: ("configuration", ("department_id", "calls")),
        ProgrammeExitCall: ("call", ("configuration", "policies")),
        ProgrammeExitCaseBundle: ("case_bundle", ("review", "files")),
        ProgrammeExitReviewCase: (
            "review",
            (
                "case_id",
                "version",
                "proposal_id",
                "revision_id",
                "policy_id",
                "call_id",
                "department_id",
                "context_json",
                "answers_json",
                "evidence_json",
                "evidence_lineage",
                "decisions",
            ),
        ),
        ProgrammeExitReviewFile: (
            "file_binding",
            (
                "file_id",
                "case_id",
                "revision_id",
                "question_id",
                "question_key",
                "answer_version",
                "size_bytes",
                "sha256",
            ),
        ),
        DecisionMessage: (
            "decision_message",
            (
                "decision_id",
                "version",
                "decided_at",
                "outcome",
                "message",
                "acknowledgement_required",
            ),
        ),
        calls.ProgrammeCallConfigurationProjection: (
            "call_configuration",
            (
                "summary",
                "purpose",
                "classification",
                "eligibility_kind",
                "maximum_submissions_per_person",
                "audience_policy_code",
                "retention_policy_code",
                "maximum_collaborators",
                "content_policy_code",
                "contributor_consent_policy_code",
                "collaboration_retention_policy_code",
                "tracks",
                "formats",
                "contributor_fields",
                "sections",
            ),
        ),
        calls.ProgrammeCallSummary: (
            "call_summary",
            (
                "call_id",
                "definition_id",
                "code",
                "version",
                "aggregate_version",
                "status",
                "name",
                "description",
                "opens_at",
                "closes_at",
                "applicant_edit_until",
                "owner_department_id",
            ),
        ),
        calls.ProgrammeTrackProjection: (
            "track",
            ("track_id", "code", "label", "description", "position"),
        ),
        calls.ProgrammeFormatProjection: (
            "format",
            (
                "format_id",
                "code",
                "label",
                "description",
                "position",
                "minimum_duration_minutes",
                "default_duration_minutes",
                "maximum_duration_minutes",
            ),
        ),
        calls.ProgrammeContributorFieldProjection: (
            "contributor_field",
            (
                "field_code",
                "lead_requirement",
                "collaborator_requirement",
                "position",
            ),
        ),
        calls.ProgrammeQuestionOptionProjection: ("question_option", ("code", "label")),
        calls.ProgrammeQuestionProjection: (
            "question",
            (
                "question_id",
                "key",
                "field_type",
                "label",
                "help_text",
                "position",
                "required",
                "options",
                "minimum_length",
                "maximum_length",
                "minimum_value",
                "maximum_value",
                "maximum_choices",
                "reference_kind",
                "condition",
                "purpose",
                "classification",
                "retention_policy_code",
            ),
        ),
        calls.ProgrammeSectionProjection: (
            "section",
            (
                "section_id",
                "key",
                "title",
                "help_text",
                "position",
                "questions",
            ),
        ),
        ReviewSetupPolicy: (
            "policy",
            ("policy_id", "call_id", "version", "created_at", "reason", "policy"),
        ),
        policies.ProgrammeReviewPolicyInput: (
            "policy_definition",
            ("stages", "templates"),
        ),
        policies.ProgrammeReviewStageInput: (
            "stage",
            (
                "code",
                "required_reviews",
                "criteria",
                "question_keys",
                "anonymous",
                "discussion",
            ),
        ),
        policies.ProgrammeReviewCriterionInput: (
            "criterion",
            ("code", "label", "minimum", "maximum"),
        ),
        policies.ProgrammeDecisionTemplateInput: (
            "decision_template",
            ("outcome", "text", "acknowledgement_required"),
        ),
    }
)


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ProgrammeArchiveInvalidError
    return str(value)


def _value(  # noqa: PLR0911 -- closed portable dispatch with no reflection fallback.
    value: object, budget: list[int], depth: int = 0
) -> JsonValue:
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_RECORD_DEPTH:
        raise ProgrammeArchiveInvalidError
    if value is None:
        return None
    if type(value) is str:
        budget[1] -= len(value.encode("utf-8"))
        if budget[1] < 0:
            raise ProgrammeArchiveInvalidError
        return value
    if type(value) in (int, bool):
        return cast("int | bool", value)
    if type(value) is UUID:
        if not value.int:
            raise ProgrammeArchiveInvalidError
        return str(value)
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProgrammeArchiveInvalidError
        return value.astimezone(UTC).isoformat()
    if type(value) is Decimal:
        return _value(_decimal(value), budget, depth + 1)
    if type(value) is tuple:
        return [_value(item, budget, depth + 1) for item in value]
    declaration = _RECORDS.get(type(value))
    if declaration is None:
        raise ProgrammeArchiveInvalidError
    name, fields = declaration
    return {
        "$record": name,
        **{key: _value(getattr(value, key), budget, depth + 1) for key in fields},
    }


def _schema() -> bytes:
    definitions = {
        name: {
            "type": "object",
            "properties": {
                "$record": {"const": name},
                **{key: {"$ref": "#/$defs/value"} for key in fields},
            },
            "required": ["$record", *fields],
            "additionalProperties": False,
        }
        for name, fields in _RECORDS.values()
    }
    definitions["value"] = {
        "anyOf": [
            {"type": ["string", "integer", "boolean", "null"]},
            {"type": "array", "items": {"$ref": "#/$defs/value"}},
            *({"$ref": f"#/$defs/{name}"} for name, _fields in _RECORDS.values()),
        ]
    }
    properties = {
        "scope": {"const": "reviewed-proposals@1"},
        "organization_id": {"type": "string", "format": "uuid"},
        "edition_id": {"type": "string", "format": "uuid"},
        "departments": {"type": "array", "items": {"$ref": "#/$defs/department"}},
        "purpose_exclusions": {"const": list(EXCLUSIONS)},
    }
    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Restricted Applications Programme exit evidence v1",
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
            "$defs": definitions,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def serialize_programme_exit_applications(
    *,
    organization_id: UUID,
    edition_id: UUID,
    departments: tuple[ProgrammeExitDepartment, ...],
) -> ProgrammeArchiveSection:
    """Encode only declared records and metadata, never attachment bytes or secrets.

    Parameters
    ----------
    organization_id : UUID
        Exact tenant already admitted by the owning collector.
    edition_id : UUID
        Exact edition already admitted by the owning collector.
    departments : tuple[ProgrammeExitDepartment, ...]
        Complete declared owner scope with current permissions and file custody.

    Returns
    -------
    ProgrammeArchiveSection
        Deterministic JSON and closed schema, with explicit purpose exclusions.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If types, record values, identifiers or serialization bounds are invalid.

    Notes
    -----
    This pure codec cannot prove complete Department coverage or source authority.
    File bytes remain in their original DTOs for separately bounded packaging.
    No new field discovery or generic dataclass/model serialization is permitted.
    """
    if (
        type(organization_id) is not UUID
        or type(edition_id) is not UUID
        or type(departments) is not tuple
        or any(type(row) is not ProgrammeExitDepartment for row in departments)
    ):
        raise ProgrammeArchiveInvalidError
    try:
        budget = [MAX_OWNER_VALUE_NODES, MAX_OWNER_JSON_BYTES]
        document = {
            "scope": "reviewed-proposals@1",
            "organization_id": _value(organization_id, budget),
            "edition_id": _value(edition_id, budget),
            "departments": _value(departments, budget),
            "purpose_exclusions": EXCLUSIONS,
        }
        data = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ProgrammeArchiveInvalidError from None
    if len(data) > MAX_OWNER_JSON_BYTES:
        raise ProgrammeArchiveInvalidError
    return ProgrammeArchiveSection(
        "applications", "applications.programme-exit@1", data, _schema()
    )
