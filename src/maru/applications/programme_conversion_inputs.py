"""Closed, explicit input for exact accepted Programme conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.applications.programme_inputs import (
    normalized_programme_text,
    require_programme_uuid,
)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeConversionInput:
    """Name one exact accepted source and deliberately supplied private copy.

    Attributes
    ----------
    decision_id
        Exact accepted decision, not an implicit latest decision selector.
    revision_id
        Exact sealed proposal revision approved by that decision.
    expected_review_version
        Current positive review-case cursor, including later acknowledgements.
    expected_programme_version
        Current edition-control cursor; zero before the first Programme item.
    internal_title
        Explicit private working title, bounded to 240 normalized characters.
    working_summary
        Optional private working summary, bounded to 2,000 characters.
    """

    decision_id: UUID
    revision_id: UUID
    expected_review_version: int
    expected_programme_version: int
    internal_title: str
    working_summary: str = ""

    def normalized(self) -> ProgrammeConversionInput:
        """Validate exact identifiers, bounded versions, and explicit private text.

        Returns
        -------
        ProgrammeConversionInput
            Immutable normalized intent; no source content is inferred or loaded.

        Raises
        ------
        ValidationError
            If an identifier, cursor, or text value violates the closed contract.
        """
        require_programme_uuid(self.decision_id, field="decision_id")
        require_programme_uuid(self.revision_id, field="revision_id")
        for name, value, minimum in (
            ("expected_review_version", self.expected_review_version, 1),
            ("expected_programme_version", self.expected_programme_version, 0),
        ):
            if type(value) is not int or not minimum <= value < 2**63 - 1:
                raise ValidationError(
                    {name: "Use the exact current bounded aggregate version."},
                    code="applications_programme_conversion_input_invalid",
                )
        return ProgrammeConversionInput(
            decision_id=self.decision_id,
            revision_id=self.revision_id,
            expected_review_version=self.expected_review_version,
            expected_programme_version=self.expected_programme_version,
            internal_title=normalized_programme_text(
                self.internal_title,
                field="internal_title",
                maximum=240,
                required=True,
                collapse=True,
            ),
            working_summary=normalized_programme_text(
                self.working_summary,
                field="working_summary",
                maximum=2_000,
                required=False,
                multiline=True,
            ),
        )


__all__ = ["ProgrammeConversionInput"]
