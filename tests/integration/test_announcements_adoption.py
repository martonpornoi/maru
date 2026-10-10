"""Native standalone setup, two-person authority and isolation boundaries."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.commands import grant_capability_direct
from maru.authorization.models import RoleBundle
from maru.authorization.policy import decide, resolve_edition_target
from maru.events.announcements_adoption import set_up_announcements_adoption
from maru.events.announcements_scope import resolve_announcements_edition_scope
from maru.events.announcements_setup_inputs import (
    AnnouncementsAdoptionSetupInput,
    AnnouncementsSetupMode,
)
from maru.events.models import AnnouncementsAdoptionSetupReceipt, EventEdition
from maru.organizations.announcements_setup_references import (
    resolve_announcements_setup_foundation,
)
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
)
from maru.organizations.representation import (
    activate_representation,
    invite_representation_controller,
    respond_to_representation_invitation,
)
from maru.organizations.representation_catalog import (
    ANNOUNCEMENTS_OPERATOR_CAPABILITIES,
)
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def setup_details(**changes):
    return replace(
        AnnouncementsAdoptionSetupInput(
            mode=AnnouncementsSetupMode.NEW_FOUNDATION,
            organization_name="Synthetic Announcements organizers",
            series_name="Synthetic announcements convention",
            edition_name="Synthetic announcement rehearsal",
            starts_on=date(2032, 8, 12),
            ends_on=date(2032, 8, 15),
            time_zone="Europe/Budapest",
            language_codes=("en", "hu"),
            reason="Prepare a synthetic standalone announcements workflow.",
        ),
        **changes,
    )


def setup_announcements():
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    key = uuid4()
    result = set_up_announcements_adoption(
        actor=administrator,
        details=setup_details(),
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    return administrator, key, result


def activate_announcements_operators(administrator, representation):
    for _index in range(2):
        operator = AccountFactory()
        invitation = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=operator.id,
            reason="Invite an accountable synthetic Announcements operator.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        respond_to_representation_invitation(
            actor=operator,
            appointment_id=invitation.id,
            expected_version=invitation.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel="test",
        )
    representation.refresh_from_db()
    return activate_representation(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate the synthetic Announcements operators.",
        correlation_id=uuid4(),
        source_channel="test",
    ).appointments


def unrelated_counts():
    return {
        model._meta.label: model.objects.count()
        for app in (
            "workforce",
            "registration",
            "participation",
            "programme",
            "communications",
            "applications",
        )
        for model in apps.get_app_config(app).get_models()
    }


def test_setup_is_atomic_minimal_explicit_and_replayable():
    before = unrelated_counts()
    administrator, key, result = setup_announcements()
    assert unrelated_counts() == before
    edition = EventEdition.objects.get(id=result.edition_id)
    assert (edition.adoption_profile_code, edition.adoption_profile_version) == (
        "announcements_only",
        1,
    )
    assert edition.language_codes == ["en", "hu"]
    assert edition.time_zone == "Europe/Budapest"
    assert edition.currency_codes == ["XXX"]
    assert edition.lifecycle == "draft"
    representation = OrganizationRepresentation.objects.get(id=result.representation_id)
    assert representation.code == "announcements_operators"
    assert representation.state == "provisioning"
    assert not OrganizationMembership.objects.filter(
        organization_id=result.organization_id
    ).exists()
    assert not RoleBundle.objects.filter(
        organization_id=result.organization_id
    ).exists()
    assert (
        result.organization_slug
        == Organization.objects.get(id=result.organization_id).slug
    )
    replay = set_up_announcements_adoption(
        actor=administrator,
        details=setup_details(),
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    with pytest.raises(ValidationError):
        set_up_announcements_adoption(
            actor=administrator,
            details=setup_details(language_codes=("hu",)),
            idempotency_key=key,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert AnnouncementsAdoptionSetupReceipt.objects.count() == 1


def test_two_person_root_is_exact_and_applies_only_to_announcements_edition():
    administrator, _key, result = setup_announcements()
    representation = OrganizationRepresentation.objects.get(id=result.representation_id)
    appointments = activate_announcements_operators(administrator, representation)
    actor, approver = (appointment.account for appointment in appointments)
    bundle = RoleBundle.objects.get(
        organization_id=result.organization_id, code="announcements-operators"
    )
    assert tuple(bundle.capability_codes) == ANNOUNCEMENTS_OPERATOR_CAPABILITIES
    assert bundle.version == 1
    target = resolve_edition_target(
        organization_id=result.organization_id, edition_id=result.edition_id
    )
    assert decide(
        principal=actor, capability_code="announcements.compose", resource=target
    ).allowed
    assert not decide(
        principal=actor, capability_code="workforce.manage_structure", resource=target
    ).allowed
    recipient = AccountFactory()
    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=recipient,
        capability_code="announcements.compose",
        target=target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Delegate this exact synthetic edition.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert grant.edition_id == result.edition_id
    assert decide(
        principal=recipient, capability_code="announcements.compose", resource=target
    ).allowed
    foreign_administrator, _foreign_key, foreign = setup_announcements()
    del foreign_administrator
    foreign_target = resolve_edition_target(
        organization_id=foreign.organization_id, edition_id=foreign.edition_id
    )
    assert not decide(
        principal=actor,
        capability_code="announcements.compose",
        resource=foreign_target,
    ).allowed


def test_setup_reuse_is_exact_and_stale_source_rolls_back():
    administrator, _key, result = setup_announcements()
    reference = resolve_announcements_setup_foundation(
        organization_id=result.organization_id, series_id=result.series_id
    )
    details = setup_details(
        mode=AnnouncementsSetupMode.EXISTING_SERIES,
        organization_name="",
        series_name="",
        organization_id=result.organization_id,
        series_id=result.series_id,
        foundation_fingerprint=reference.fingerprint,
    )
    second = set_up_announcements_adoption(
        actor=administrator,
        details=details,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert second.organization_id == result.organization_id
    assert second.series_id == result.series_id
    assert second.edition_id != result.edition_id
    assert not second.created_organization
    assert not second.created_series
    with pytest.raises(ValidationError):
        set_up_announcements_adoption(
            actor=administrator,
            details=replace(details, foundation_fingerprint="0" * 64),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert EventEdition.objects.count() == 2


def test_setup_integrity_failure_rolls_back_every_foundation_write(monkeypatch):
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    before = (
        Organization.objects.count(),
        EventEdition.objects.count(),
        AuditEvent.objects.count(),
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic receipt failure")

    monkeypatch.setattr(AnnouncementsAdoptionSetupReceipt.objects, "create", fail)
    with pytest.raises(RuntimeError, match="Synthetic receipt failure"):
        set_up_announcements_adoption(
            actor=administrator,
            details=setup_details(),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert (
        Organization.objects.count(),
        EventEdition.objects.count(),
        AuditEvent.objects.count(),
    ) == before


def test_inactive_platform_actor_cannot_replay_or_discover_setup():
    administrator, key, result = setup_announcements()
    type(administrator).objects.filter(id=administrator.id).update(is_active=False)
    with pytest.raises(PermissionDenied):
        set_up_announcements_adoption(
            actor=administrator,
            details=setup_details(),
            idempotency_key=key,
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert AnnouncementsAdoptionSetupReceipt.objects.get(id=result.receipt_id)


def test_native_receipt_cannot_be_rewritten_and_scope_is_fail_closed():
    _administrator, _key, result = setup_announcements()
    with pytest.raises(DatabaseError), transaction.atomic():
        AnnouncementsAdoptionSetupReceipt.objects.filter(id=result.receipt_id).update(
            reason="Changed evidence"
        )
    scope = resolve_announcements_edition_scope(
        organization_id=result.organization_id, edition_id=result.edition_id
    )
    assert scope is not None
    assert scope.edition_version == 1
    assert not scope.accepts_writes
    assert (
        resolve_announcements_edition_scope(
            organization_id=uuid4(), edition_id=result.edition_id
        )
        is None
    )


def test_native_capabilities_require_exact_edition_scope():

    capabilities = tuple(
        code
        for code in ANNOUNCEMENTS_OPERATOR_CAPABILITIES
        if code.startswith("announcements.")
    )
    with connection.cursor() as cursor:
        for code in capabilities:
            cursor.execute(
                "SELECT public.maru_authorization_capability_min_scope(%s)", [code]
            )
            assert cursor.fetchone() == (1,)
