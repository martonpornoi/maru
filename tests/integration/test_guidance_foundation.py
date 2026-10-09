"""Native two-person Guides ceremony, typed access and inverse evidence boundaries."""

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from maru.announcements.models import AnnouncementRevision
from maru.audit.models import AuditEvent
from maru.authorization.commands import grant_capability_direct
from maru.authorization.guidance_access import (
    request_guidance_access,
    respond_to_guidance_access,
    revoke_guidance_access,
)
from maru.authorization.guidance_access_queries import (
    load_guidance_access_request,
    load_guidance_access_workspace,
)
from maru.authorization.guidance_authority_queries import guidance_team_reference
from maru.authorization.models import (
    AuthorityIssuance,
    GuidanceAccessRequest,
    GuidanceAuthoritySetupReceipt,
    GuidanceRevocationReceipt,
    RoleAssignment,
)
from maru.authorization.policy import decide, resolve_edition_target
from maru.events.admin_context import admin_edition_options, admin_shell_access
from maru.events.announcements_scope import resolve_announcements_edition_scope
from maru.events.guidance_activation import apply_guidance_activation
from maru.events.guidance_setup_readiness import (
    guidance_setup_database_integrity_is_ready,
)
from maru.events.models import EventEdition, GuidanceActivationReceipt
from maru.events.services import transition_edition
from maru.organizations.models import OrganizationRepresentation
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    update_convention_series,
)
from tests.factories import AccountFactory
from tests.integration.guidance_test_support import (
    create_guidance_foundation,
    create_guidance_workspace,
    guidance_runtime,
    propose_and_accept_guidance,
)
from tests.integration.test_announcements_adoption import (
    activate_announcements_operators,
    setup_announcements,
)
from tests.integration.test_announcements_domain import approved

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def native(call, **kwargs):
    with transaction.atomic():
        result = call(**kwargs)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        return result


@pytest.fixture
def world(guidance_runtime):
    return create_guidance_workspace(platform=guidance_runtime)


def target(world):
    _platform, edition, _first, _second = world
    return resolve_edition_target(
        organization_id=edition.organization_id, edition_id=edition.id
    )


def reader_request(world, recipient=None):
    _platform, edition, first, second = world
    person = recipient or AccountFactory()
    result = native(
        request_guidance_access,
        actor=first,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        recipient_email=person.email,
        approver_id=second.id,
        recipe_code="guidance-reader",
        reason="Read the synthetic current Guides.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    return person, GuidanceAccessRequest.objects.get(id=result.request_id)


def test_ceremony_has_four_exact_outputs_and_strictly_earlier_controllers(world):
    platform, edition, first, second = world
    setup = GuidanceAuthoritySetupReceipt.objects.get(team__edition_id=edition.id)
    ids = (
        setup.controller_a_id,
        setup.controller_b_id,
        setup.content_a_id,
        setup.content_b_id,
    )
    assert len(set(ids)) == 4
    ordinals = dict(
        AuthorityIssuance.objects.filter(role_assignment_id__in=ids).values_list(
            "role_assignment_id", "ordinal"
        )
    )
    assert max(ordinals[setup.controller_a_id], ordinals[setup.controller_b_id]) < min(
        ordinals[setup.content_a_id], ordinals[setup.content_b_id]
    )
    assert guidance_team_reference(
        organization_id=edition.organization_id, edition_id=edition.id
    ).ready
    for person in (first, second):
        assert decide(
            principal=person,
            capability_code="knowledge.compose",
            resource=target(world),
        ).allowed
    assert not decide(
        principal=platform,
        capability_code="knowledge.view_current",
        resource=target(world),
    ).allowed
    assert not decide(
        principal=first, capability_code="announcements.compose", resource=target(world)
    ).allowed
    assert not decide(
        principal=first,
        capability_code="authorization.grant_direct",
        resource=target(world),
    ).allowed


def test_third_reader_requires_actual_approver_and_cannot_read_private_material(world):
    _platform, _edition, first, second = world
    person, request = reader_request(world)
    assert not decide(
        principal=person,
        capability_code="knowledge.view_current",
        resource=target(world),
    ).allowed
    with pytest.raises(PermissionDenied):
        respond_to_guidance_access(
            actor=first,
            request_id=request.id,
            expected_digest=request.request_digest,
            accept=True,
            correlation_id=uuid4(),
        )
    approved = native(
        respond_to_guidance_access,
        actor=second,
        request_id=request.id,
        expected_digest=request.request_digest,
        accept=True,
        correlation_id=uuid4(),
    )
    assert decide(
        principal=person,
        capability_code="knowledge.view_current",
        resource=target(world),
    ).allowed
    for code in (
        "knowledge.view_working",
        "knowledge.compose",
        "knowledge.export_evidence",
        "authorization.manage_guidance_access",
        "events.view_basic",
    ):
        assert not decide(
            principal=person, capability_code=code, resource=target(world)
        ).allowed
    replay = respond_to_guidance_access(
        actor=second,
        request_id=request.id,
        expected_digest=request.request_digest,
        accept=True,
        correlation_id=uuid4(),
    )
    assert replay.replayed
    assert replay.assignment_id == approved.assignment_id


@pytest.mark.parametrize(
    "capability", ["knowledge.view_current", "authorization.manage_guidance_access"]
)
def test_generic_direct_grants_cannot_issue_protected_guidance_authority(
    world, capability
):
    _platform, _edition, first, second = world
    with pytest.raises((PermissionDenied, ValidationError)):
        grant_capability_direct(
            actor=first,
            approver=second,
            recipient=AccountFactory(),
            capability_code=capability,
            target=target(world),
            effective_from=timezone.now(),
            expires_at=None,
            reason="Attempt an unsupported generic Guides assignment.",
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_recovery_does_not_rebind_revoked_descendants(
    world,
):
    platform, edition, first, second = world
    person, request = reader_request(world)
    native(
        respond_to_guidance_access,
        actor=second,
        request_id=request.id,
        expected_digest=request.request_digest,
        accept=True,
        correlation_id=uuid4(),
    )
    controller = RoleAssignment.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=first.id,
        role_bundle__code="guidance-access-controller",
    )
    old_team = guidance_team_reference(
        organization_id=edition.organization_id, edition_id=edition.id
    )
    native(
        revoke_guidance_access,
        actor=second,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        assignment_id=controller.id,
        reason="Remove the original synthetic control source.",
        correlation_id=uuid4(),
    )
    assert not decide(
        principal=person,
        capability_code="knowledge.view_current",
        resource=target(world),
    ).allowed
    proposal = propose_and_accept_guidance(platform, edition, first, second)
    native(
        apply_guidance_activation,
        actor=platform,
        request_id=proposal.request_id,
        expected_version=proposal.version,
        correlation_id=uuid4(),
    )
    current_team = guidance_team_reference(
        organization_id=edition.organization_id, edition_id=edition.id
    )
    assert current_team.ready
    assert current_team.team_id == old_team.team_id
    assert current_team.activation_receipt_id == old_team.activation_receipt_id
    assert not decide(
        principal=person,
        capability_code="knowledge.view_current",
        resource=target(world),
    ).allowed


def test_missing_access_event_rolls_back_the_request(world, monkeypatch):
    _platform, edition, first, second = world
    before = GuidanceAccessRequest.objects.count()
    monkeypatch.setattr(
        "maru.authorization.guidance_access._event", lambda *_args, **_kwargs: None
    )
    with pytest.raises(DatabaseError):
        native(
            request_guidance_access,
            actor=first,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            recipient_email=AccountFactory().email,
            approver_id=second.id,
            recipe_code="guidance-reader",
            reason="Verify missing outbox rolls back all evidence.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
    assert GuidanceAccessRequest.objects.count() == before


def test_aliasing_content_outputs_to_controllers_rolls_back_native_setup(
    guidance_runtime, monkeypatch
):
    platform, edition, first, second = create_guidance_foundation(
        platform=guidance_runtime
    )
    proposal = propose_and_accept_guidance(platform, edition, first, second)
    receipt, controller_a, controller_b = uuid4(), uuid4(), uuid4()
    values = iter((receipt, controller_a, controller_b, controller_a, controller_b))
    monkeypatch.setattr(
        "maru.authorization.guidance_bootstrap.uuid4", lambda: next(values)
    )
    with pytest.raises((DatabaseError, ValidationError)):
        native(
            apply_guidance_activation,
            actor=platform,
            request_id=proposal.request_id,
            expected_version=proposal.version,
            correlation_id=uuid4(),
        )
    assert not GuidanceActivationReceipt.objects.filter(
        request_id=proposal.request_id
    ).exists()
    edition.refresh_from_db()
    assert edition.adoption_revision == 0


__all__ = ["guidance_runtime"]


def test_reader_discovers_only_authorized_edition_and_discovery_is_audited(world):

    _platform, edition, _first, second = world
    reader, request = reader_request(world)
    native(
        respond_to_guidance_access,
        actor=second,
        request_id=request.id,
        expected_digest=request.request_digest,
        accept=True,
        correlation_id=uuid4(),
    )
    web = RequestFactory().get("/admin/")
    web.user = reader
    web.session = {}
    web.correlation_id = uuid4()
    assert admin_shell_access(web)["workspace_available"]
    options = admin_edition_options(web)
    assert {row.id for row in options["editions"]} == {edition.id}
    assert AuditEvent.objects.filter(
        operation="events.guidance.workspace_discover",
        principal_id=reader.id,
        event_edition_id=edition.id,
    ).exists()
    assert not reader.is_staff


def test_lost_source_task_is_changed_and_unauthorized_queries_do_not_load_terms(world):

    _platform, edition, first, second = world
    _reader, request = reader_request(world)
    controller = RoleAssignment.objects.get(
        edition_id=edition.id,
        principal_id=first.id,
        role_bundle__code="guidance-access-controller",
    )
    native(
        revoke_guidance_access,
        actor=second,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        assignment_id=controller.id,
        reason="Retain a stale exact source for disclosure checking.",
        correlation_id=uuid4(),
    )
    view = load_guidance_access_request(
        actor=second, request_id=request.id, correlation_id=uuid4()
    )
    assert view.state == "changed"
    assert not view.can_answer
    with CaptureQueriesContext(connection) as captured, pytest.raises(PermissionDenied):
        load_guidance_access_request(
            actor=first, request_id=request.id, correlation_id=uuid4()
        )
    assert not any(
        '"authorization_guidanceaccessrequest"."reason"' in query["sql"]
        for query in captured
    )


def test_existing_announcements_expand_in_place_without_rewriting_roots_or_content(
    guidance_runtime,
):

    platform, _key, setup = setup_announcements()
    representation = OrganizationRepresentation.objects.get(id=setup.representation_id)
    appointments = activate_announcements_operators(platform, representation)
    first, second = (appointment.account for appointment in appointments)
    approved((platform, setup, first, second))
    retained = list(AnnouncementRevision.objects.order_by("id").values())
    edition = EventEdition.objects.get(id=setup.edition_id)
    root_ids = tuple(appointment.role_assignment_id for appointment in appointments)
    proposal = propose_and_accept_guidance(platform, edition, first, second)
    native(
        apply_guidance_activation,
        actor=platform,
        request_id=proposal.request_id,
        expected_version=proposal.version,
        correlation_id=uuid4(),
    )
    edition.refresh_from_db()
    representation.refresh_from_db()
    assert edition.id == setup.edition_id
    assert edition.adoption_profile_code == "announcements_guidance"
    assert representation.code == "announcements_operators"
    assert (
        RoleAssignment.objects.filter(id__in=root_ids, revoked_at__isnull=True).count()
        == 2
    )
    assert list(AnnouncementRevision.objects.order_by("id").values()) == retained
    assert (
        resolve_announcements_edition_scope(
            organization_id=edition.organization_id, edition_id=edition.id
        ).adoption_profile_code
        == "announcements_guidance"
    )


def test_disabled_original_adoption_attachment_fails_guidance_readiness(world):

    assert guidance_setup_database_integrity_is_ready()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.events_eventedition "
                "DISABLE TRIGGER events_aggregate_version_guard"
            )
        assert not guidance_setup_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert guidance_setup_database_integrity_is_ready()


@pytest.mark.parametrize("state", ["inactive_series", "cancelled_edition"])
def test_removal_requires_active_parents_but_survives_terminal_edition(world, state):
    _platform, edition, first, second = world
    assignment = RoleAssignment.objects.get(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        principal_id=second.id,
        role_bundle__code="guidance-operator",
    )
    if state == "inactive_series":
        series = edition.series
        native(
            update_convention_series,
            actor=first,
            organization_id=edition.organization_id,
            series_id=series.id,
            expected_profile_version=series.profile_version,
            details=ConventionSeriesCreationDetails(name=series.name, is_active=False),
            correlation_id=uuid4(),
        )
        before = GuidanceRevocationReceipt.objects.count()
        retained_assignment = (
            RoleAssignment.objects.filter(id=assignment.id).values().get()
        )
        with pytest.raises(PermissionDenied, match="unavailable"):
            native(
                revoke_guidance_access,
                actor=first,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                assignment_id=assignment.id,
                reason="An inactive parent must refuse removal at admission.",
                correlation_id=uuid4(),
            )
        assert GuidanceRevocationReceipt.objects.count() == before
        assert (
            RoleAssignment.objects.filter(id=assignment.id).values().get()
            == retained_assignment
        )
        with pytest.raises(PermissionDenied, match="unavailable"):
            load_guidance_access_workspace(
                actor=first,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                correlation_id=uuid4(),
            )
    else:
        native(
            transition_edition,
            actor=first,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.CANCELLED,
            reason="Cancel the synthetic event while keeping active parents.",
            correlation_id=uuid4(),
        )
        workspace = load_guidance_access_workspace(
            actor=first,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            correlation_id=uuid4(),
        )
        assert assignment.id in {row.assignment_id for row in workspace.assignments}
        receipt_id = native(
            revoke_guidance_access,
            actor=first,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            assignment_id=assignment.id,
            reason="Remove retained access after the event was cancelled.",
            correlation_id=uuid4(),
        )
        assignment.refresh_from_db()
        assert assignment.revoked_at is not None
        assert assignment.revoked_by_id == first.id
        assert (
            GuidanceRevocationReceipt.objects.get(id=receipt_id).assignment_id
            == assignment.id
        )
