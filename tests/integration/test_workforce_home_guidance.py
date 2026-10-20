"""Native authority, lifecycle and owner state behind the Workforce home."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.workforce import home_guidance, structure_snapshot
from maru.workforce.models import (
    EditionStructureControl,
    Position,
    PositionTemplate,
)
from maru.workforce.structure_commands import (
    close_position,
    create_position,
    update_position_opportunity,
)
from maru.workforce.structure_snapshot import StructureSnapshotChangedError
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import (
    create_department_for_test,
    retire_department_for_test,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _world():
    actor = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only", adoption_profile_version=1
    )
    return actor, edition


def _read(actor, edition):
    return home_guidance.load_workforce_setup_guidance(
        actor=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        http_method="GET",
    )


def _department(actor, edition):
    return create_department_for_test(
        actor=actor,
        edition=edition,
        name="Volunteer care",
        expected_code="volunteer-care",
    )


def _position(actor, edition, department):
    _a, _b, bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="home-volunteer",
        name="Home volunteer",
        capability_codes=("workforce.view_structure",),
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="home-volunteer",
        name="Home volunteer",
        description="Synthetic home fixture.",
        role_bundle=bundle,
        default_capacity_codes=["volunteer"],
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    version = EditionStructureControl.objects.get(edition=edition).aggregate_version
    result = create_position(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_id=template.id,
        department_id=department.id,
        reports_to_id=None,
        title="Volunteer care",
        description="Help synthetic volunteers.",
        headcount=2,
        expected_version=version,
        reason="Prepare the synthetic volunteer team.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return Position.objects.get(id=result.position_id)


def _publish(actor, edition, position):
    version = EditionStructureControl.objects.get(edition=edition).aggregate_version
    update_position_opportunity(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        status="published",
        headline="Help volunteers",
        description="Support the synthetic convention team.",
        applications_open_at=timezone.now() - timedelta(days=1),
        applications_close_at=timezone.now() + timedelta(days=1),
        visible_when_filled=True,
        expected_version=version,
        reason="Publish the synthetic opportunity.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_real_commands_move_guidance_from_structure_to_published_copy():
    actor, edition = _world()
    assert _read(actor, edition).step == "departments"
    department = _department(actor, edition)
    assert _read(actor, edition).step == "positions"
    position = _position(actor, edition, department)
    draft = _read(actor, edition)
    assert draft.step == "opportunities"
    assert draft.position_id == position.id
    _publish(actor, edition, position)
    assert _read(actor, edition).step == "published"
    events = AuditEvent.objects.filter(
        operation="workforce.structure.read", event_edition_id=edition.id
    )
    assert events.count() == 4
    assert all(event.safe_metadata["route_name"] == "admin:index" for event in events)


def test_home_rendered_link_reauthorizes_and_contains_no_holder_names():
    actor, edition = _world()
    client = Client()
    client.force_login(actor)
    session = client.session
    session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    session.save()
    response = client.get("/admin/")
    assert response.status_code == 200
    text = response.content.decode()
    assert "Set up your Departments" in text
    assert "Team setup · Ready" in text
    url = reverse(
        "organization-structure",
        args=(edition.organization.slug, edition.series.slug, edition.slug),
    )
    assert f'href="{url}"' in text
    assert client.get(url).status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]


def test_read_only_actor_can_see_state_but_cannot_get_management_hint():
    _actor, edition = _world()
    viewer = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=viewer,
        capability_code="workforce.view_structure",
    )
    item = _read(viewer, edition)
    assert item.step == "departments"
    assert not item.can_manage


def test_same_tenant_other_edition_and_foreign_authority_do_not_read_owner_facts():
    _actor, edition = _world()
    viewer = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=viewer,
        capability_code="workforce.view_structure",
    )
    other = EventEditionFactory(
        series=edition.series, adoption_profile_code="workforce_only"
    )
    foreign = EventEditionFactory(adoption_profile_code="workforce_only")
    with patch.object(
        home_guidance.Department.objects,
        "filter",
        side_effect=AssertionError("No private facts before policy"),
    ):
        for target in (other, foreign):
            with pytest.raises(PermissionDenied):
                _read(viewer, target)


def test_manage_only_authority_does_not_imply_structure_read():
    _actor, edition = _world()
    manager = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=manager,
        capability_code="workforce.manage_structure",
    )
    with pytest.raises(PermissionDenied):
        _read(manager, edition)


@pytest.mark.parametrize("profile", ["full_convention", "announcements_only"])
def test_persisted_unadopted_profile_never_reads_workforce_state(profile):
    actor = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory(adoption_profile_code=profile)
    with patch.object(
        home_guidance.Department.objects,
        "filter",
        side_effect=AssertionError("Unadopted query"),
    ):
        assert _read(actor, edition) is None


def test_lifecycle_change_removes_edit_continuation():
    actor, edition = _world()
    for state in (EventEdition.Lifecycle.PREPARING, EventEdition.Lifecycle.READY):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=actor,
            reason="Advance the synthetic home-read fixture.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    item = _read(actor, edition)
    assert item.step == "read_only"
    assert item.position_id is None


def test_retired_department_does_not_count_as_current_setup():
    actor, edition = _world()
    department = _department(actor, edition)
    retire_department_for_test(department=department, actor=actor)
    assert _read(actor, edition).step == "departments"
    # A legacy retained row without its control must not look like empty setup.
    with patch.object(home_guidance, "EditionStructureControl") as control:
        control_query = control.objects.filter.return_value
        control_query.values_list.return_value.first.return_value = None
        snapshot = home_guidance._snapshot(actor, edition.organization_id, edition.id)
        assert snapshot.value.step == "unavailable"


def test_department_overflow_returns_no_partial_ready_state(monkeypatch):
    actor, edition = _world()
    _department(actor, edition)
    monkeypatch.setattr(home_guidance, "MAX_STRUCTURE_DEPARTMENTS", 0)
    assert _read(actor, edition).step == "unavailable"


def test_position_overflow_returns_no_identifier(monkeypatch):
    actor, edition = _world()
    position = _position(actor, edition, _department(actor, edition))
    monkeypatch.setattr(home_guidance, "MAX_STRUCTURE_POSITIONS", 0)
    result = _read(actor, edition)
    assert result.step == "unavailable"
    assert result.position_id is None
    assert Position.objects.filter(id=position.id).exists()


def test_required_audit_failure_prevents_guidance_release():
    actor, edition = _world()
    with (
        patch.object(
            home_guidance,
            "append_structure_read_audit",
            side_effect=DatabaseError("Synthetic evidence failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        _read(actor, edition)


def test_revocation_at_final_policy_check_prevents_disclosure():
    actor, edition = _world()
    original = home_guidance._authorize
    calls = 0

    def authorize(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionDenied
        return original(*args)

    with (
        patch.object(home_guidance, "_authorize", side_effect=authorize),
        pytest.raises(PermissionDenied),
    ):
        _read(actor, edition)
    assert not AuditEvent.objects.filter(
        operation="workforce.structure.read", event_edition_id=edition.id
    ).exists()


def test_retained_department_rows_are_included_in_the_complete_bound(monkeypatch):
    actor, edition = _world()
    old = _department(actor, edition)
    retire_department_for_test(department=old, actor=actor)
    create_department_for_test(
        actor=actor,
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    monkeypatch.setattr(home_guidance, "MAX_STRUCTURE_DEPARTMENTS", 1)
    assert _read(actor, edition).step == "unavailable"


def test_incomplete_field_policy_never_loads_owner_facts():
    actor, edition = _world()
    partial = PolicyDecision(
        allowed=True,
        fields=frozenset({"departments"}),
        obligations=frozenset(),
        reason_code="synthetic_partial",
    )
    with (
        patch.object(home_guidance, "decide", return_value=partial),
        patch.object(
            home_guidance.Department.objects,
            "filter",
            side_effect=AssertionError("No partial-field disclosure"),
        ),
        pytest.raises(PermissionDenied),
    ):
        _read(actor, edition)


def test_persistent_structure_movement_never_releases_stale_guidance():
    actor, edition = _world()
    with (
        patch.object(
            structure_snapshot, "current_structure_version", return_value=99
        ) as probe,
        pytest.raises(StructureSnapshotChangedError),
    ):
        _read(actor, edition)
    assert probe.call_count == 2
    assert not AuditEvent.objects.filter(
        operation="workforce.structure.read",
        event_edition_id=edition.id,
    ).exists()


def test_suspended_organization_has_no_setup_action_hint():
    actor, edition = _world()
    edition.organization.lifecycle = "suspended"
    edition.organization.save()
    assert _read(actor, edition).step == "read_only"


def test_closed_position_is_review_not_a_published_or_ready_promise():
    actor, edition = _world()
    position = _position(actor, edition, _department(actor, edition))
    version = EditionStructureControl.objects.get(edition=edition).aggregate_version
    close_position(
        confirmation_name=position.title,
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        expected_version=version,
        reason="Close the unused synthetic Position.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert _read(actor, edition).step == "review"


def test_withdrawn_opportunity_never_looks_published():
    actor, edition = _world()
    position = _position(actor, edition, _department(actor, edition))
    _publish(actor, edition, position)
    opportunity = position.opportunity
    version = EditionStructureControl.objects.get(edition=edition).aggregate_version
    update_position_opportunity(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        position_id=position.id,
        status="withdrawn",
        headline=opportunity.headline,
        description=opportunity.description,
        applications_open_at=opportunity.applications_open_at,
        applications_close_at=opportunity.applications_close_at,
        visible_when_filled=opportunity.visible_when_filled,
        expected_version=version,
        reason="Withdraw the synthetic recruitment copy.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert _read(actor, edition).step == "review"
