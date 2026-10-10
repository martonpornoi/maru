"""Database-free setup admission; native atomicity has separate integration proof."""

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.core import views
from maru.events import announcements_adoption as command
from maru.events import api, services
from maru.events.announcements_setup_inputs import (
    AnnouncementsAdoptionSetupInput,
    AnnouncementsSetupMode,
)
from maru.events.announcements_setup_writer import _require_announcements_edition_setup
from maru.events.forms import EventEditionCreationForm
from maru.events.models import EventEdition
from maru.events.serializers import EditionCreateRequestSerializer
from maru.identity.models import Account


def test_generic_creation_does_not_offer_the_setup_only_profile():
    form = EventEditionCreationForm()
    serializer = EditionCreateRequestSerializer()
    assert "announcements_only" not in dict(
        form.fields["adoption_profile_code"].choices
    )
    assert (
        "announcements_only" not in serializer.fields["adoption_profile_code"].choices
    )


@pytest.mark.parametrize("source_channel", ["service", "api", "html"])
def test_generic_creation_refuses_announcements_before_persistence(
    monkeypatch, source_channel
):
    monkeypatch.setattr(
        services, "_require_edition_capability", Mock(return_value=("allow", ()))
    )
    atomic = Mock(side_effect=AssertionError("Generic setup reached persistence."))
    monkeypatch.setattr(services.transaction, "atomic", atomic)
    with pytest.raises(ValidationError) as failure:
        services.create_event_edition(
            actor=SimpleNamespace(id=UUID(int=1), is_platform_administrator=True),
            organization_id=UUID(int=2),
            series_id=UUID(int=3),
            details=services.EventEditionDetails(
                name="Synthetic announcement edition",
                starts_on=date(2032, 8, 12),
                ends_on=date(2032, 8, 15),
                time_zone="UTC",
                language_codes=("en",),
                currency_codes=("XXX",),
            ),
            idempotency_key=UUID(int=4),
            correlation_id=UUID(int=5),
            source_channel=source_channel,
            adoption_profile_code="announcements_only",
        )
    assert (
        failure.value.error_dict["adoption_profile_code"][0].code
        == "edition_adoption_profile_requires_setup"
    )
    atomic.assert_not_called()


@pytest.fixture
def setup_world(monkeypatch):
    actor = Account(
        id=UUID(int=1),
        is_active=True,
        is_staff=True,
        is_superuser=True,
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
    )
    organization = SimpleNamespace(id=UUID(int=2), slug="synthetic", lifecycle="draft")
    series = SimpleNamespace(id=UUID(int=3), is_active=True)
    edition = EventEdition(
        id=UUID(int=6),
        organization_id=organization.id,
        series_id=series.id,
        adoption_profile_code="announcements_only",
        adoption_profile_version=1,
    )
    managers = {}
    for model in (
        services.Organization,
        services.ConventionSeries,
        services.OrganizationRepresentation,
        services.EditionCreationReceipt,
        command.AnnouncementsAdoptionSetupReceipt,
    ):
        manager = MagicMock()
        monkeypatch.setattr(model, "objects", manager)
        managers[model.__name__] = manager
    managers[
        "Organization"
    ].select_for_update.return_value.get.return_value = organization
    managers[
        "ConventionSeries"
    ].select_for_update.return_value.get.return_value = series
    managers[
        "OrganizationRepresentation"
    ].filter.return_value.values_list.return_value.first.return_value = (
        "announcements_operators"
    )
    child_receipts = managers["EditionCreationReceipt"]
    retained_child = child_receipts.select_related.return_value.filter.return_value
    retained_child.first.return_value = None
    child_receipts.get.return_value = SimpleNamespace(id=UUID(int=7))
    setup_receipts = managers["AnnouncementsAdoptionSetupReceipt"]
    setup_receipts.filter.return_value.first.return_value = None
    setup_receipts.create.side_effect = command.AnnouncementsAdoptionSetupReceipt
    monkeypatch.setattr(services.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        services, "_require_edition_capability", Mock(return_value=("allow", ()))
    )
    create_edition = Mock(return_value=edition)
    monkeypatch.setattr(services, "_create_edition_with_generated_slug", create_edition)
    monkeypatch.setattr(
        services, "append_audit", Mock(return_value=SimpleNamespace(id=UUID(int=8)))
    )
    monkeypatch.setattr(services, "publish_domain_event", Mock())
    for name in ("_lock_key", "lock_retired_department_authority_boundaries"):
        monkeypatch.setattr(command, name, Mock())
    monkeypatch.setattr(
        command, "current_platform_administrator_is_available", Mock(return_value=True)
    )
    monkeypatch.setattr(
        command,
        "announcements_setup_database_integrity_is_ready",
        Mock(return_value=True),
    )
    monkeypatch.setattr(
        command, "create_draft_organization", Mock(return_value=organization)
    )
    monkeypatch.setattr(command, "create_convention_series", Mock(return_value=series))
    provision = Mock(return_value=SimpleNamespace(id=UUID(int=9), aggregate_version=1))
    monkeypatch.setattr(command, "provision_representation", provision)
    monkeypatch.setattr(
        command,
        "audited_mutation",
        Mock(return_value=nullcontext(SimpleNamespace(audit_id=UUID(int=10)))),
    )
    return SimpleNamespace(
        actor=actor,
        create_edition=create_edition,
        provision=provision,
        setup_receipts=setup_receipts,
        child_receipts=child_receipts,
    )


def run_setup(world):
    return command.set_up_announcements_adoption(
        actor=world.actor,
        details=AnnouncementsAdoptionSetupInput(
            mode=AnnouncementsSetupMode.NEW_FOUNDATION,
            organization_name="Synthetic organizers",
            series_name="Synthetic convention",
            edition_name="Synthetic announcement edition",
            starts_on=date(2032, 8, 12),
            ends_on=date(2032, 8, 15),
            time_zone="UTC",
            language_codes=("en",),
            reason="Prepare the synthetic Announcements workflow.",
        ),
        idempotency_key=UUID(int=4),
        correlation_id=UUID(int=5),
    )


def test_dedicated_setup_admits_the_real_child_command_and_retains_complete_replay(
    setup_world,
    monkeypatch,
):
    result = run_setup(setup_world)
    assert not result.replayed
    assert result.edition_id == UUID(int=6)
    assert result.representation_id == UUID(int=9)
    assert (
        setup_world.provision.call_args.kwargs["representation_code"]
        == "announcements_operators"
    )
    setup_world.child_receipts.create.assert_called_once()
    setup_world.setup_receipts.create.assert_called_once()
    receipt = command.AnnouncementsAdoptionSetupReceipt(
        **setup_world.setup_receipts.create.call_args.kwargs
    )
    assert receipt.edition_id == result.edition_id
    assert receipt.edition_creation_id == UUID(int=7)
    setup_world.setup_receipts.filter.return_value.first.return_value = receipt
    monkeypatch.setattr(
        command,
        "selectable_adoption_profile",
        Mock(side_effect=AssertionError("Replay consulted new selection.")),
    )
    replay = run_setup(setup_world)
    assert replay.replayed
    assert replay.receipt_id == result.receipt_id
    setup_world.create_edition.assert_called_once()
    setup_world.provision.assert_called_once()
    with pytest.raises(ValidationError, match="Set up Announcements"):
        _require_announcements_edition_setup()


def test_failed_dedicated_child_does_not_leave_generic_admission_open(setup_world):
    setup_world.create_edition.side_effect = RuntimeError("Synthetic child failure.")
    with pytest.raises(RuntimeError, match="Synthetic child failure"):
        run_setup(setup_world)
    setup_world.setup_receipts.create.assert_not_called()
    with pytest.raises(ValidationError, match="Set up Announcements"):
        _require_announcements_edition_setup()


def test_generic_api_maps_the_real_command_refusal_without_writes(
    setup_world, monkeypatch
):
    monkeypatch.setattr(api, "resolve_organization_target", Mock())
    monkeypatch.setattr(
        api,
        "decide",
        Mock(
            return_value=SimpleNamespace(
                allowed=True,
                fields=api.EDITION_BASIC_RESPONSE_FIELDS,
            )
        ),
    )
    request = APIRequestFactory().post(
        "/api/v1/organizations/synthetic/editions",
        {
            "series_id": str(UUID(int=3)),
            "name": "Synthetic announcement edition",
            "starts_on": "2032-08-12",
            "ends_on": "2032-08-15",
            "time_zone": "UTC",
            "language_codes": ["en"],
            "currency_codes": ["XXX"],
            "adoption_profile_code": "announcements_only",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(UUID(int=4)),
    )
    request.correlation_id = str(UUID(int=5))
    force_authenticate(request, user=setup_world.actor)
    response = api.EditionListView.as_view()(request, organization_id=UUID(int=2))
    assert response.status_code == 400
    assert response.data["code"] == "edition_adoption_profile_requires_setup"
    setup_world.create_edition.assert_not_called()
    setup_world.child_receipts.create.assert_not_called()
    setup_world.setup_receipts.create.assert_not_called()


def test_generic_page_maps_the_real_command_refusal_without_writes(
    setup_world, monkeypatch
):
    organization = SimpleNamespace(
        id=UUID(int=2),
        lifecycle="draft",
        default_time_zone="UTC",
        default_language_codes=["en"],
    )
    series = SimpleNamespace(id=UUID(int=3), is_active=True)
    for name in ("_require_possible_organization_authority", "_require_capability"):
        monkeypatch.setattr(views, name, Mock())
    monkeypatch.setattr(views, "_active_account", Mock(return_value=setup_world.actor))
    monkeypatch.setattr(
        views, "_organization_for_authorized_route", Mock(return_value=organization)
    )
    monkeypatch.setattr(views, "_series_for_record", Mock(return_value=series))
    rendered = Mock(return_value=HttpResponse())
    monkeypatch.setattr(views, "_baseline_page_response", rendered)
    request = RequestFactory().post(
        "/admin/organizations/synthetic/series/synthetic/editions/new/",
        {
            "name": "Synthetic announcement edition",
            "starts_on": "2032-08-12",
            "ends_on": "2032-08-15",
            "time_zone": "UTC",
            "language_codes": ["en"],
            "currency_codes": "XXX",
            "adoption_profile_code": "announcements_only",
            "idempotency_key": str(UUID(int=4)),
        },
    )
    request.user = setup_world.actor
    request.correlation_id = str(UUID(int=5))
    response = views.baseline_create_event_edition(request, "synthetic", "synthetic")
    assert response.status_code == 200
    form = rendered.call_args.args[2]["form"]
    assert form.errors["adoption_profile_code"] == [
        "Use Set up Announcements to create this edition."
    ]
    assert 'value="announcements_only"' not in str(form["adoption_profile_code"])
    setup_world.create_edition.assert_not_called()
    setup_world.child_receipts.create.assert_not_called()
    setup_world.setup_receipts.create.assert_not_called()
