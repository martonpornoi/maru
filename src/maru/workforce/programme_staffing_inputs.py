"""Typed exact binding intent without implicit source or lifecycle selection."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.programme.staffing_inputs import ProgrammeStaffingSource

from .programme_impact import ProgrammeStaffingAction

MAX_PROGRAMME_BINDING_REVISIONS = 1_000


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingBindingChange:
    """Pin the deliberate source, existing binding and exact work version.

    Attributes
    ----------
    action
        Explicit creation, linking, draft reconciliation or successor operation.
    source
        Exact current Programme/Scheduling source to resolve under owner authority.
    binding_id
        Retained binding identity, absent only for first creation or linking.
    expected_binding_version
        Current binding revision, zero only when no binding exists.
    demand_id
        Exact existing draft or predecessor, absent only for creation.
    expected_demand_version
        Current Workforce version, zero only when no demand is selected.
    """

    action: ProgrammeStaffingAction
    source: ProgrammeStaffingSource
    binding_id: UUID | None = None
    expected_binding_version: int = 0
    demand_id: UUID | None = None
    expected_demand_version: int = 0

    def validated(self) -> ProgrammeStaffingBindingChange:
        """Validate closed typed intent without resolving existence or authority.

        Returns
        -------
        ProgrammeStaffingBindingChange
            The unchanged valid exact selection.

        Raises
        ------
        ValidationError
            If operation, source or optimistic identity/version pairs disagree.
        """
        if not isinstance(self.action, ProgrammeStaffingAction) or not isinstance(
            self.source, ProgrammeStaffingSource
        ):
            raise ValidationError("Select an explicit staffing operation and source.")
        self.source.validated()
        for identity, version in (
            (self.binding_id, self.expected_binding_version),
            (self.demand_id, self.expected_demand_version),
        ):
            if (
                (identity is not None and not isinstance(identity, UUID))
                or type(version) is not int
                or not 0 <= version < 2**63 - 1
                or (identity is None) != (version == 0)
            ):
                raise ValidationError(
                    "Select exact staffing identities and current versions."
                )
        first = self.action in {
            ProgrammeStaffingAction.CREATE,
            ProgrammeStaffingAction.LINK,
        }
        if (
            first != (self.binding_id is None)
            or (self.action == ProgrammeStaffingAction.CREATE)
            != (self.demand_id is None)
            or self.expected_binding_version >= MAX_PROGRAMME_BINDING_REVISIONS
        ):
            raise ValidationError(
                "The staffing operation does not match its retained targets."
            )
        return self
