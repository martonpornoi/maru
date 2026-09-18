"""Recipe-to-owner seams with mocked storage; not native authorization evidence."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.venues import services


def test_room_operations_names_its_actual_breadth_without_publication():
    recipe = PROGRAMME_ROLE_RECIPES[("room-operations", 1)]
    assert recipe.target_scopes == (ScopeLevel.RESOURCE,)
    assert recipe.resource_kind == "venue.edition_space"
    assert recipe.capability_codes == (
        "venues.view_space_schedule",
        services.SPACE_MANAGE_CAPABILITY,
        "venues.view_scheduling_dependencies",
    )
    assert services.SPACE_PUBLISH_CAPABILITY not in recipe.capability_codes
    assert recipe.digest == (
        "240c680373fef31ce1d782518a3a7c2c67834f9281f2825edfb3217daf9964a0"
    )


@pytest.mark.parametrize(
    "relationship", ["creator", "modifier", "source", "independent"]
)
def test_actual_booking_approval_uses_room_management_and_retains_independence(
    monkeypatch, relationship
):
    actor = SimpleNamespace(id=uuid4())
    booking = Mock(
        aggregate_version=1,
        lifecycle=services.VenueBooking.Lifecycle.ACTIVE,
        review_state=services.VenueBooking.ReviewState.DRAFT,
        created_by_id=actor.id if relationship == "creator" else uuid4(),
        last_modified_by_id=actor.id if relationship == "modifier" else uuid4(),
    )
    decision = Mock()
    record = Mock()
    monkeypatch.setattr(services, "_space_decision", decision)
    monkeypatch.setattr(services, "_existing_receipt", Mock(return_value=None))
    monkeypatch.setattr(services, "_locked_booking", Mock(return_value=booking))
    binding = Mock()
    binding.filter.return_value.exists.side_effect = [True, relationship == "source"]
    monkeypatch.setattr(services.VenueSchedulingBinding, "objects", binding)
    monkeypatch.setattr(
        services, "resolve_active_verified_person_reference", Mock(return_value=actor)
    )
    monkeypatch.setattr(services, "venue_writer", nullcontext)
    monkeypatch.setattr(services, "_record_booking_state_change", record)
    arguments = {
        "actor": actor,
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "space_selection_id": uuid4(),
        "booking_id": uuid4(),
        "expected_version": 1,
        "reason": "Reviewed independent synthetic physical use.",
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
    }
    # Only unwrap transaction setup; execute the real owner decision logic.
    approve = services.approve_venue_booking.__wrapped__
    if relationship == "independent":
        assert approve(**arguments) is record.return_value
        assert booking.approved_by is actor
        assert booking.aggregate_version == 2
        booking.save.assert_called_once_with()
        assert (
            record.call_args.kwargs["capability_code"]
            == services.SPACE_MANAGE_CAPABILITY
        )
    else:
        with pytest.raises(services.VenueIndependentApprovalError):
            approve(**arguments)
        booking.save.assert_not_called()
        record.assert_not_called()
    assert (
        decision.call_args.kwargs["capability_code"] == services.SPACE_MANAGE_CAPABILITY
    )
    assert (
        decision.call_args.kwargs["space_selection_id"]
        == arguments["space_selection_id"]
    )
