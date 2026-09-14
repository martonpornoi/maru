"""Lossless, database-free composition for dedicated Programme call tasks.

This adapter is not a writer or an authorization boundary. Its caller obtains
the complete managed configuration through the existing protected query and
passes the resulting inputs to ``configure_programme_call`` with the original
cursor, reason and retry key. No generic definition command is admitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from .programme_inputs import (
    ProgrammeCallConfigurationInput,
    ProgrammeCallContributorFieldInput,
    ProgrammeCallDefinitionInput,
    ProgrammeCallFormatInput,
    ProgrammeCallQuestionConditionInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionOptionInput,
    ProgrammeCallSectionInput,
    ProgrammeCallTrackInput,
    require_programme_expected_version,
)

if TYPE_CHECKING:
    from .programme_queries import (
        ProgrammeCallConfigurationProjection,
        ProgrammeQuestionProjection,
    )


class ProgrammeCallEditorConflictError(RuntimeError):
    """Refuse an obsolete cursor or a non-draft call without rebasing intent."""


@dataclass(frozen=True, slots=True)
class ProgrammeCallEditorInputs:
    """Retain the complete pair consumed by the existing call command.

    Attributes
    ----------
    definition : ProgrammeCallDefinitionInput
        Complete metadata and immutable ordered question graph.
    configuration : ProgrammeCallConfigurationInput
        Exact owner, policy, track, format and contributor-field configuration.
    """

    definition: ProgrammeCallDefinitionInput
    configuration: ProgrammeCallConfigurationInput


def _condition(
    entries: tuple[tuple[str, object], ...],
) -> ProgrammeCallQuestionConditionInput | None:
    if not entries:
        return None
    values = dict(entries)
    required = {"question_key", "operator", "value"}
    if len(entries) != len(required) or set(values) != required:
        raise ValidationError("The stored question condition is not supported.")
    key, operator, value = (
        values["question_key"],
        values["operator"],
        values["value"],
    )
    if (
        not isinstance(key, str)
        or not isinstance(operator, str)
        or type(value) not in (str, bool, int)
    ):
        raise ValidationError("The stored question condition is not supported.")
    # Narrowing with isinstance follows the exact closed-type check above.
    if not isinstance(value, (str, bool, int)):
        raise ValidationError("The stored condition value is not supported.")
    return ProgrammeCallQuestionConditionInput(key, operator, value)


def _question(source: ProgrammeQuestionProjection) -> ProgrammeCallQuestionInput:
    return ProgrammeCallQuestionInput(
        key=source.key,
        field_type=source.field_type,
        label=source.label,
        help_text=source.help_text,
        position=source.position,
        required=source.required,
        options=tuple(
            ProgrammeCallQuestionOptionInput(option.code, option.label)
            for option in source.options
        ),
        minimum_length=source.minimum_length,
        maximum_length=source.maximum_length,
        minimum_value=source.minimum_value,
        maximum_value=source.maximum_value,
        maximum_choices=source.maximum_choices,
        reference_kind=source.reference_kind,
        condition=_condition(source.condition),
        purpose=source.purpose,
        classification=source.classification,
        retention_policy_code=source.retention_policy_code,
    )


def programme_call_editor_inputs(
    source: ProgrammeCallConfigurationProjection, *, expected_version: int
) -> ProgrammeCallEditorInputs:
    """Reconstruct every configured value from one authorized exact draft.

    Refusing a stale source before composition prevents a small task form from
    silently rebasing its intent onto a newer graph. The owner command must
    still check current authority, lifecycle, cursor and retry evidence.

    Parameters
    ----------
    source : ProgrammeCallConfigurationProjection
        Complete configuration returned by the protected manager query.
    expected_version : int
        Original submitted call cursor, never replaced by the latest cursor.

    Returns
    -------
    ProgrammeCallEditorInputs
        Lossless, fully revalidated inputs with no proposal or ORM state.

    Raises
    ------
    ProgrammeCallEditorConflictError
        If the source is stale or no longer a draft.
    ValidationError
        If the stored graph or cursor is not supported by the typed contract.
    """
    require_programme_expected_version(expected_version)
    if (
        source.summary.status != "draft"
        or source.summary.aggregate_version != expected_version
    ):
        raise ProgrammeCallEditorConflictError
    if source.eligibility_kind != "authenticated_person":
        raise ValidationError("The call eligibility is not supported.")
    summary = source.summary
    definition = ProgrammeCallDefinitionInput(
        code=summary.code,
        name=summary.name,
        description=summary.description,
        purpose=source.purpose,
        classification=source.classification,
        maximum_submissions_per_person=source.maximum_submissions_per_person,
        opens_at=summary.opens_at,
        closes_at=summary.closes_at,
        applicant_edit_until=summary.applicant_edit_until,
        audience_policy_code=source.audience_policy_code,
        retention_policy_code=source.retention_policy_code,
        sections=tuple(
            ProgrammeCallSectionInput(
                key=section.key,
                title=section.title,
                help_text=section.help_text,
                position=section.position,
                questions=tuple(_question(question) for question in section.questions),
            )
            for section in source.sections
        ),
    )
    configuration = ProgrammeCallConfigurationInput(
        owner_department_id=summary.owner_department_id,
        maximum_collaborators=source.maximum_collaborators,
        content_policy_code=source.content_policy_code,
        contributor_consent_policy_code=source.contributor_consent_policy_code,
        collaboration_retention_policy_code=source.collaboration_retention_policy_code,
        tracks=tuple(
            ProgrammeCallTrackInput(row.code, row.label, row.description, row.position)
            for row in source.tracks
        ),
        formats=tuple(
            ProgrammeCallFormatInput(
                row.code,
                row.label,
                row.description,
                row.position,
                row.minimum_duration_minutes,
                row.default_duration_minutes,
                row.maximum_duration_minutes,
            )
            for row in source.formats
        ),
        contributor_fields=tuple(
            ProgrammeCallContributorFieldInput(
                row.field_code,
                row.lead_requirement,
                row.collaborator_requirement,
                row.position,
            )
            for row in source.contributor_fields
        ),
    )
    return ProgrammeCallEditorInputs(definition, configuration)


def _edit_rows[
    Row: (
        ProgrammeCallTrackInput,
        ProgrammeCallFormatInput,
        ProgrammeCallContributorFieldInput,
        ProgrammeCallSectionInput,
        ProgrammeCallQuestionInput,
    )
](rows: tuple[Row, ...], *, index: int | None, value: Row | None) -> tuple[Row, ...]:
    """Replace, insert or remove one exact row and normalize explicit ordering.

    Parameters
    ----------
    rows : tuple[Row, ...]
        Complete original ordered catalog.
    index : int | None
        Exact current row or ``None`` for insertion.
    value : Row | None
        Replacement with its chosen position or ``None`` for removal.

    Returns
    -------
    tuple[Row, ...]
        Complete reordered catalog without changing other row content.

    Raises
    ------
    ValidationError
        If the selected row or position is not present in the exact catalog.
    """
    if index is not None and (type(index) is not int or not 0 <= index < len(rows)):
        raise ValidationError("Select one current row.")
    if index is None and value is None:
        raise ValidationError("Select one current row to remove.")
    remaining = [row for offset, row in enumerate(rows) if offset != index]
    if value is not None:
        if not 1 <= value.position <= len(remaining) + 1:
            raise ValidationError("Choose a position within the resulting list.")
        remaining.insert(value.position - 1, value)
    return tuple(
        replace(row, position=offset) for offset, row in enumerate(remaining, 1)
    )


def edit_programme_call_track(
    inputs: ProgrammeCallEditorInputs,
    *,
    index: int | None,
    value: ProgrammeCallTrackInput | None,
) -> ProgrammeCallEditorInputs:
    """Compose one explicit track edit without dropping unrelated configuration.

    Parameters
    ----------
    inputs : ProgrammeCallEditorInputs
        Complete validated graph for the original draft cursor.
    index : int | None
        Zero-based current row, or ``None`` to insert a new row.
    value : ProgrammeCallTrackInput | None
        Replacement with its desired position, or ``None`` for explicit removal.

    Returns
    -------
    ProgrammeCallEditorInputs
        Revalidated complete graph with only the intended catalog change.
    """
    return replace(
        inputs,
        configuration=replace(
            inputs.configuration,
            tracks=_edit_rows(inputs.configuration.tracks, index=index, value=value),
        ),
    )


def edit_programme_call_format(
    inputs: ProgrammeCallEditorInputs,
    *,
    index: int | None,
    value: ProgrammeCallFormatInput | None,
) -> ProgrammeCallEditorInputs:
    """Compose one explicit format edit and retain every other input.

    Parameters
    ----------
    inputs : ProgrammeCallEditorInputs
        Complete validated graph for the original draft cursor.
    index : int | None
        Zero-based current row, or ``None`` to insert a new row.
    value : ProgrammeCallFormatInput | None
        Replacement with its desired position, or ``None`` for explicit removal.

    Returns
    -------
    ProgrammeCallEditorInputs
        Revalidated complete graph with the requested format change.
    """
    return replace(
        inputs,
        configuration=replace(
            inputs.configuration,
            formats=_edit_rows(inputs.configuration.formats, index=index, value=value),
        ),
    )


def edit_programme_call_contributor_field(
    inputs: ProgrammeCallEditorInputs,
    *,
    index: int | None,
    value: ProgrammeCallContributorFieldInput | None,
) -> ProgrammeCallEditorInputs:
    """Compose one contributor-policy edit without editing any person's profile.

    Parameters
    ----------
    inputs : ProgrammeCallEditorInputs
        Complete validated graph for the original draft cursor.
    index : int | None
        Zero-based current row, or ``None`` to insert a new row.
    value : ProgrammeCallContributorFieldInput | None
        Replacement with its desired position, or ``None`` for explicit removal.

    Returns
    -------
    ProgrammeCallEditorInputs
        Complete graph, still requiring the lead's proposed public name.
    """
    return replace(
        inputs,
        configuration=replace(
            inputs.configuration,
            contributor_fields=_edit_rows(
                inputs.configuration.contributor_fields, index=index, value=value
            ),
        ),
    )


def edit_programme_call_section(
    inputs: ProgrammeCallEditorInputs,
    *,
    index: int | None,
    value: ProgrammeCallSectionInput | None,
) -> ProgrammeCallEditorInputs:
    """Compose a section edit, rejecting broken earlier-answer dependencies.

    Parameters
    ----------
    inputs : ProgrammeCallEditorInputs
        Complete validated graph for the original draft cursor.
    index : int | None
        Zero-based current section, or ``None`` to insert a complete section.
    value : ProgrammeCallSectionInput | None
        Complete replacement section or ``None`` for explicit removal.

    Returns
    -------
    ProgrammeCallEditorInputs
        Complete graph with contiguous ordering and validated dependencies.
    """
    return replace(
        inputs,
        definition=replace(
            inputs.definition,
            sections=_edit_rows(inputs.definition.sections, index=index, value=value),
        ),
    )


def edit_programme_call_question(
    inputs: ProgrammeCallEditorInputs,
    *,
    section_index: int,
    index: int | None,
    value: ProgrammeCallQuestionInput | None,
) -> ProgrammeCallEditorInputs:
    """Compose one question edit with whole-graph validation, never auto-repair.

    Parameters
    ----------
    inputs : ProgrammeCallEditorInputs
        Complete validated graph for the original draft cursor.
    section_index : int
        Exact zero-based section in the original graph.
    index : int | None
        Zero-based current question, or ``None`` to insert a question.
    value : ProgrammeCallQuestionInput | None
        Complete replacement question or ``None`` for explicit removal.

    Returns
    -------
    ProgrammeCallEditorInputs
        Complete graph with all untouched questions and policies retained.

    Raises
    ------
    ValidationError
        If the section is absent or the resulting graph is invalid.
    """
    if type(section_index) is not int or not 0 <= section_index < len(
        inputs.definition.sections
    ):
        raise ValidationError("Select one current section.")
    section = inputs.definition.sections[section_index]
    updated = replace(
        section, questions=_edit_rows(section.questions, index=index, value=value)
    )
    return edit_programme_call_section(inputs, index=section_index, value=updated)
