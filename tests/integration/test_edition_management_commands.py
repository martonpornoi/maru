import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connections

import maru.events.services as event_services
from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.adoption import AdoptionProfile, AdoptionProfileCode
from maru.events.models import EditionCreationReceipt, EventEdition
from maru.events.services import (
    EventEditionDetails,
    create_event_edition,
    transition_edition,
    update_event_edition,
)
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
)
from maru.participation.models import Participation
from maru.registration.models import Registration
from maru.workforce.models import VolunteerApplication
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
    OrganizationRepresentationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _details(**changes: object) -> EventEditionDetails:
    details = EventEditionDetails(
        name="Synthetic Convention 2031",
        time_zone="Europe/Vienna",
        language_codes=("en", "de"),
        currency_codes=("EUR",),
        starts_on=date(2031, 8, 14),
        ends_on=date(2031, 8, 17),
    )
    return replace(details, **changes)


def _administrator() -> object:
    return AccountFactory(is_staff=True, is_superuser=True)


def _create(
    *,
    actor: object,
    series: ConventionSeries,
    details: EventEditionDetails | None = None,
    idempotency_key: object | None = None,
    correlation_id: object | None = None,
    adoption_profile_code: str = AdoptionProfileCode.FULL_CONVENTION,
):
    return create_event_edition(
        actor=actor,
        organization_id=series.organization_id,
        series_id=series.id,
        details=details or _details(),
        idempotency_key=idempotency_key or uuid4(),
        correlation_id=correlation_id or uuid4(),
        source_channel="test",
        adoption_profile_code=adoption_profile_code,
    )


def test_creation_commits_minimized_evidence_without_admin_participation() -> None:  # noqa: PLR0915
    administrator = _administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    series = ConventionSeriesFactory(organization=organization)
    idempotency_key = uuid4()
    correlation_id = uuid4()

    result = _create(
        actor=administrator,
        series=series,
        details=_details(
            name="  Synthetic   Convention 2031  ",
            time_zone=" Europe/Vienna ",
            language_codes=("EN", "de"),
            currency_codes=("eur",),
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )

    edition = result.edition
    assert not result.replayed
    assert edition.name == "Synthetic Convention 2031"
    assert edition.slug == "synthetic-convention-2031"
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT
    assert edition.lifecycle_version == 0
    assert edition.aggregate_version == 1
    assert edition.time_zone == "Europe/Vienna"
    assert edition.language_codes == ["en", "de"]
    assert edition.currency_codes == ["EUR"]

    receipt = EditionCreationReceipt.objects.get(edition=edition)
    assert receipt.organization_id == organization.id
    assert receipt.series_id == series.id
    assert receipt.actor_id == administrator.id
    assert receipt.idempotency_key == idempotency_key
    assert len(receipt.request_digest) == 64

    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    message = OutboxMessage.objects.get(event=event)
    assert audit.principal_id == administrator.id
    assert audit.organization_id == organization.id
    assert audit.event_edition_id == edition.id
    assert audit.target_id == edition.id
    assert audit.capability_code == "events.create"
    assert audit.operation == "events.edition.create"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert (
        audit.idempotency_key_hash
        == hashlib.sha256(str(idempotency_key).encode()).hexdigest()
    )
    assert set(audit.changed_fields) == {
        "organization",
        "series",
        "name",
        "slug",
        "lifecycle",
        "aggregate_version",
        "adoption_profile_code",
        "adoption_profile_version",
        "time_zone",
        "language_codes",
        "currency_codes",
        "starts_on",
        "ends_on",
    }
    assert event.event_name == "events.edition.created.v1"
    assert event.aggregate_id == edition.id
    assert event.aggregate_version == 1
    assert event.causation_id == audit.id
    assert event.payload == {
        "aggregate_version": "1",
        "adoption_profile_code": "full_convention",
        "adoption_profile_version": "1",
        "lifecycle": "draft",
    }
    assert message.status == OutboxMessage.Status.PENDING
    assert message.workload_pool == "core"
    assert edition.name not in str(audit.safe_metadata)
    assert edition.name not in str(event.payload)
    assert str(idempotency_key) not in str(audit.safe_metadata)
    assert str(idempotency_key) not in str(event.payload)

    assert not OrganizationMembership.objects.filter(
        account_id=administrator.id
    ).exists()
    assert not Participation.objects.filter(account_id=administrator.id).exists()
    assert not CapabilityGrant.objects.filter(principal_id=administrator.id).exists()
    assert not RoleAssignment.objects.filter(principal_id=administrator.id).exists()
    assert not Registration.objects.filter(account_id=administrator.id).exists()
    assert not VolunteerApplication.objects.filter(account_id=administrator.id).exists()


def test_creation_replay_is_normalized_and_emits_no_duplicate_evidence() -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()

    first = _create(
        actor=administrator,
        series=series,
        details=_details(),
        idempotency_key=idempotency_key,
    )
    replay = _create(
        actor=administrator,
        series=series,
        details=_details(
            name=" Synthetic   Convention 2031 ",
            time_zone=" Europe/Vienna ",
            language_codes=("EN", "DE"),
            currency_codes=("eur",),
        ),
        idempotency_key=idempotency_key,
    )

    assert replay.replayed
    assert replay.edition.id == first.edition.id
    assert EventEdition.objects.count() == 1
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


@pytest.mark.parametrize("selection_state", ["advanced", "retired"])
def test_creation_replay_uses_retained_profile_before_current_selection(
    monkeypatch: pytest.MonkeyPatch,
    selection_state: str,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()
    first = _create(
        actor=administrator,
        series=series,
        idempotency_key=idempotency_key,
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )
    selected = event_services.selectable_adoption_profile(
        AdoptionProfileCode.WORKFORCE_ONLY
    )
    assert selected is not None
    selection_calls: list[str] = []

    def changed_selection(code: str) -> AdoptionProfile | None:
        selection_calls.append(code)
        return replace(selected, version=2) if selection_state == "advanced" else None

    monkeypatch.setattr(
        event_services,
        "selectable_adoption_profile",
        changed_selection,
    )

    replay = _create(
        actor=administrator,
        series=series,
        idempotency_key=idempotency_key,
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )

    assert replay.replayed
    assert replay.edition.id == first.edition.id
    assert (
        replay.edition.adoption_profile_code,
        replay.edition.adoption_profile_version,
    ) == selected.key
    assert selection_calls == []


def test_creation_replay_rejects_unknown_retained_manifest_without_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()
    first = _create(
        actor=administrator,
        series=series,
        idempotency_key=idempotency_key,
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )
    retained_calls: list[tuple[str, int]] = []

    def unknown_retained(code: str, version: int) -> None:
        retained_calls.append((code, version))

    def current_selector_must_not_run(_code: str) -> None:
        raise AssertionError("Unknown retained replay must not consult selection.")

    monkeypatch.setattr(event_services, "adoption_profile", unknown_retained)
    monkeypatch.setattr(
        event_services,
        "selectable_adoption_profile",
        current_selector_must_not_run,
    )

    with pytest.raises(ValidationError) as captured:
        _create(
            actor=administrator,
            series=series,
            idempotency_key=idempotency_key,
            adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        )

    assert (
        captured.value.error_dict["adoption_profile_code"][0].code
        == "edition_adoption_profile_unsupported"
    )
    assert retained_calls == [
        (
            first.edition.adoption_profile_code,
            first.edition.adoption_profile_version,
        )
    ]
    assert EventEdition.objects.count() == 1
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


def test_creation_receipt_conflicts_before_current_profile_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()
    original = _create(
        actor=administrator,
        series=series,
        idempotency_key=idempotency_key,
    )

    def unavailable_selection(_code: str) -> None:
        raise AssertionError("A receipt replay must not resolve today's profile.")

    monkeypatch.setattr(
        event_services,
        "selectable_adoption_profile",
        unavailable_selection,
    )

    conflicting_inputs = (
        (AdoptionProfileCode.WORKFORCE_ONLY, _details()),
        (
            AdoptionProfileCode.FULL_CONVENTION,
            _details(name="Different Convention 2031"),
        ),
    )
    for profile_code, details in conflicting_inputs:
        with pytest.raises(ValidationError) as captured:
            _create(
                actor=administrator,
                series=series,
                details=details,
                idempotency_key=idempotency_key,
                adoption_profile_code=profile_code,
            )
        assert (
            captured.value.error_dict["idempotency_key"][0].code
            == "edition_creation_idempotency_conflict"
        )

    assert EventEdition.objects.get().id == original.edition.id
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


def test_creation_replay_precedes_changed_expansion_policy() -> None:
    actor = AccountFactory()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    series = ConventionSeriesFactory(organization=organization)
    CapabilityGrantFactory(
        organization=organization,
        principal=actor,
        capability_code="events.create",
    )
    idempotency_key = uuid4()
    first = _create(
        actor=actor,
        series=series,
        idempotency_key=idempotency_key,
    )
    OrganizationRepresentationFactory(
        organization=organization,
        code=OrganizationRepresentation.MARU_OPERATORS_CODE,
        name=OrganizationRepresentation.MARU_OPERATORS_NAME,
    )

    replay = _create(
        actor=actor,
        series=series,
        idempotency_key=idempotency_key,
    )

    assert replay.replayed
    assert replay.edition.id == first.edition.id

    with pytest.raises(ValidationError) as captured:
        _create(
            actor=actor,
            series=series,
            idempotency_key=uuid4(),
        )
    assert (
        captured.value.error_dict["adoption_profile_code"][0].code
        == "edition_adoption_expansion_requires_platform_oversight"
    )

    selected = event_services.selectable_adoption_profile(
        AdoptionProfileCode.WORKFORCE_ONLY
    )
    assert selected is not None
    workforce_result = _create(
        actor=actor,
        series=series,
        idempotency_key=uuid4(),
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )
    assert (
        workforce_result.edition.adoption_profile_code,
        workforce_result.edition.adoption_profile_version,
    ) == selected.key


@pytest.mark.django_db(transaction=True)
def test_concurrent_creation_replays_one_canonical_result() -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()
    start = Barrier(2)

    def invoke() -> object:
        close_old_connections()
        try:
            start.wait(timeout=5)
            return _create(
                actor=administrator,
                series=series,
                idempotency_key=idempotency_key,
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result() for future in [executor.submit(invoke) for _ in range(2)]
        ]

    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.edition.id for result in results}) == 1
    assert EventEdition.objects.count() == 1
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_name_allocates_distinct_stable_slugs() -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    start = Barrier(2)

    def invoke() -> object:
        close_old_connections()
        try:
            start.wait(timeout=5)
            return _create(actor=administrator, series=series)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result() for future in [executor.submit(invoke) for _ in range(2)]
        ]

    assert all(not result.replayed for result in results)
    assert {result.edition.slug for result in results} == {
        "synthetic-convention-2031",
        "synthetic-convention-2031-2",
    }
    assert EventEdition.objects.count() == 2
    assert EditionCreationReceipt.objects.count() == 2
    assert AuditEvent.objects.count() == 2
    assert DomainEvent.objects.count() == 2
    assert OutboxMessage.objects.count() == 2


@pytest.mark.parametrize(
    ("name", "expected_slug"),
    [
        ("MárúCon - Őrség 2031", "marucon-orseg-2031"),
        ("獣会", "edition"),
    ],
)
def test_creation_generates_safe_stable_slugs_for_unicode_names(
    name: str,
    expected_slug: str,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()

    result = _create(
        actor=administrator,
        series=series,
        details=_details(name=name),
    )

    assert result.edition.slug == expected_slug


def test_creation_key_conflict_changes_nothing() -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    idempotency_key = uuid4()
    original = _create(
        actor=administrator,
        series=series,
        idempotency_key=idempotency_key,
    )

    with pytest.raises(ValidationError, match="different edition details"):
        _create(
            actor=administrator,
            series=series,
            details=_details(name="Different Convention 2031"),
            idempotency_key=idempotency_key,
        )

    assert EventEdition.objects.get().id == original.edition.id
    assert EditionCreationReceipt.objects.count() == 1
    assert AuditEvent.objects.count() == 1
    assert DomainEvent.objects.count() == 1
    assert OutboxMessage.objects.count() == 1


def test_creation_key_scope_is_the_actor_and_series() -> None:
    administrator = _administrator()
    organization = OrganizationFactory()
    first_series = ConventionSeriesFactory(organization=organization)
    second_series = ConventionSeriesFactory(organization=organization)
    idempotency_key = uuid4()

    first = _create(
        actor=administrator,
        series=first_series,
        idempotency_key=idempotency_key,
    )
    second = _create(
        actor=administrator,
        series=second_series,
        idempotency_key=idempotency_key,
    )

    assert first.edition.id != second.edition.id
    assert EditionCreationReceipt.objects.count() == 2


def test_creation_rejects_cross_tenant_parent_and_denies_before_lookup() -> None:
    administrator = _administrator()
    first_organization = OrganizationFactory()
    foreign_series = ConventionSeriesFactory()

    with pytest.raises(ConventionSeries.DoesNotExist):
        create_event_edition(
            actor=administrator,
            organization_id=first_organization.id,
            series_id=foreign_series.id,
            details=_details(),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )

    ordinary = AccountFactory()
    CapabilityGrantFactory(
        organization=first_organization,
        principal=ordinary,
        capability_code="events.create",
    )
    with pytest.raises(AuthorizationDenied) as denied:
        create_event_edition(
            actor=ordinary,
            organization_id=foreign_series.organization_id,
            series_id=foreign_series.id,
            details=_details(),
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )

    assert denied.value.reason_code == "permission_absent"
    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()


@pytest.mark.parametrize(
    ("organization_lifecycle", "series_active", "message"),
    [
        (Organization.Lifecycle.CLOSED, True, "Closed organization"),
        (Organization.Lifecycle.ACTIVE, False, "inactive convention series"),
    ],
)
def test_creation_rejects_unavailable_parent(
    organization_lifecycle: str,
    series_active: bool,
    message: str,
) -> None:
    administrator = _administrator()
    organization = OrganizationFactory(lifecycle=organization_lifecycle)
    series = ConventionSeriesFactory(
        organization=organization,
        is_active=series_active,
    )

    with pytest.raises(ValidationError, match=message):
        _create(actor=administrator, series=series)

    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": " "}, "edition name"),
        ({"name": "x" * 161}, "at most 160"),
        (
            {"starts_on": date(2031, 8, 18), "ends_on": date(2031, 8, 17)},
            "before the start date",
        ),
        (
            {"ends_on": date(2031, 9, 15)},
            "cannot exceed 31 days",
        ),
        ({"time_zone": "Mars/Olympus"}, "IANA"),
        ({"language_codes": ()}, "cannot be blank"),
        ({"language_codes": ("en", "en")}, "unique"),
        (
            {
                "language_codes": (
                    "aa",
                    "ab",
                    "ae",
                    "af",
                    "ak",
                    "am",
                    "ar",
                    "as",
                    "av",
                    "ay",
                    "az",
                    "ba",
                    "be",
                    "bg",
                    "bh",
                    "bi",
                    "bm",
                )
            },
            "no more than 16",
        ),
        ({"currency_codes": ()}, "cannot be blank"),
        ({"currency_codes": ("EUR", "EUR")}, "unique"),
        ({"currency_codes": ("ZZZ",)}, "Unknown ISO 4217"),
        (
            {
                "currency_codes": (
                    "EUR",
                    "USD",
                    "GBP",
                    "HUF",
                    "CAD",
                    "AUD",
                    "JPY",
                    "CHF",
                    "SEK",
                )
            },
            "no more than 8",
        ),
    ],
)
def test_creation_service_revalidates_every_input_boundary(
    changes: dict[str, object],
    message: str,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()

    with pytest.raises(ValidationError, match=message):
        _create(
            actor=administrator,
            series=series,
            details=_details(**changes),
        )

    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


@pytest.mark.parametrize("failure_point", ["audit", "outbox"])
def test_creation_rolls_back_all_evidence_on_infrastructure_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()

    if failure_point == "audit":

        def fail_audit(*_args: object, **_kwargs: object) -> None:
            raise DatabaseError("synthetic audit failure")

        monkeypatch.setattr("maru.events.services.append_audit", fail_audit)
        expected_error: type[Exception] = DatabaseError
    else:

        def fail_outbox(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic outbox failure")

        monkeypatch.setattr("maru.events.services.publish_domain_event", fail_outbox)
        expected_error = RuntimeError

    with pytest.raises(expected_error):
        _create(actor=administrator, series=series)

    assert not EventEdition.objects.exists()
    assert not EditionCreationReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_update_changes_only_profile_and_noop_or_stale_writes_emit_nothing() -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    original_slug = edition.slug
    original_organization_id = edition.organization_id
    original_series_id = edition.series_id
    correlation_id = uuid4()
    changed = _details(
        name="  Renamed   Convention 2031 ",
        time_zone="Europe/London",
        language_codes=("en", "hu"),
        currency_codes=("HUF", "EUR"),
        starts_on=date(2031, 8, 15),
        ends_on=date(2031, 8, 18),
    )

    result = update_event_edition(
        actor=administrator,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        expected_aggregate_version=1,
        details=changed,
        correlation_id=correlation_id,
        source_channel="test",
    )

    edition.refresh_from_db()
    assert result.changed_fields == (
        "name",
        "starts_on",
        "ends_on",
        "time_zone",
        "language_codes",
        "currency_codes",
    )
    assert edition.name == "Renamed Convention 2031"
    assert edition.aggregate_version == 2
    assert edition.slug == original_slug
    assert edition.organization_id == original_organization_id
    assert edition.series_id == original_series_id
    assert edition.lifecycle == EventEdition.Lifecycle.DRAFT

    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert audit.changed_fields == [*result.changed_fields, "aggregate_version"]
    assert event.event_name == "events.edition.details_updated.v1"
    assert event.aggregate_version == 2
    assert event.causation_id == audit.id
    assert event.payload == {
        "aggregate_version": "2",
        "changed_fields": ",".join(result.changed_fields),
    }
    assert OutboxMessage.objects.filter(event=event).exists()

    counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    noop = update_event_edition(
        actor=administrator,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        expected_aggregate_version=2,
        details=replace(changed, name="Renamed Convention 2031"),
        correlation_id=uuid4(),
    )
    assert noop.changed_fields == ()
    edition.refresh_from_db()
    assert edition.aggregate_version == 2
    assert counts == (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError, match="changed after the page was loaded"):
        update_event_edition(
            actor=administrator,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            expected_aggregate_version=1,
            details=replace(changed, name="Stale overwrite"),
            correlation_id=uuid4(),
        )
    edition.refresh_from_db()
    assert edition.name == "Renamed Convention 2031"
    assert edition.aggregate_version == 2
    assert counts == (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )


def _transition_to(
    *,
    edition: EventEdition,
    actor: object,
    lifecycle: str,
) -> EventEdition:
    paths = {
        EventEdition.Lifecycle.READY: (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
        ),
        EventEdition.Lifecycle.LIVE: (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
        ),
        EventEdition.Lifecycle.CLOSING: (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
            EventEdition.Lifecycle.CLOSING,
        ),
        EventEdition.Lifecycle.ARCHIVED: (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
            EventEdition.Lifecycle.CLOSING,
            EventEdition.Lifecycle.ARCHIVED,
        ),
        EventEdition.Lifecycle.CANCELLED: (EventEdition.Lifecycle.CANCELLED,),
    }
    for state in paths[lifecycle]:
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            actor=actor,
            to_state=state,
            reason=f"Advance synthetic edition to {state}.",
            correlation_id=uuid4(),
        )
    return edition


@pytest.mark.parametrize(
    "lifecycle",
    [
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
        EventEdition.Lifecycle.CLOSING,
        EventEdition.Lifecycle.ARCHIVED,
        EventEdition.Lifecycle.CANCELLED,
    ],
)
def test_non_editable_lifecycle_refuses_profile_update(lifecycle: str) -> None:
    administrator = _administrator()
    edition = _transition_to(
        edition=EventEditionFactory(),
        actor=administrator,
        lifecycle=lifecycle,
    )
    counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError, match="Only Draft or Preparing"):
        update_event_edition(
            actor=administrator,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            expected_aggregate_version=edition.aggregate_version,
            details=_details(name="Forbidden profile rewrite"),
            correlation_id=uuid4(),
        )

    edition.refresh_from_db()
    assert edition.name != "Forbidden profile rewrite"
    assert counts == (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )


def test_creation_transition_and_preparing_update_share_one_aggregate_stream() -> None:
    administrator = _administrator()
    series = ConventionSeriesFactory()
    created = _create(actor=administrator, series=series).edition
    preparing = transition_edition(
        organization_id=created.organization_id,
        edition_id=created.id,
        actor=administrator,
        to_state=EventEdition.Lifecycle.PREPARING,
        reason="Begin synthetic preparation.",
        correlation_id=uuid4(),
    )
    updated = update_event_edition(
        actor=administrator,
        organization_id=preparing.organization_id,
        series_id=preparing.series_id,
        edition_id=preparing.id,
        expected_aggregate_version=2,
        details=_details(name="Prepared Synthetic Convention 2031"),
        correlation_id=uuid4(),
    ).edition

    assert updated.lifecycle == EventEdition.Lifecycle.PREPARING
    assert updated.lifecycle_version == 1
    assert updated.aggregate_version == 3
    assert list(
        DomainEvent.objects.filter(aggregate_id=updated.id)
        .order_by("aggregate_version")
        .values_list("event_name", "aggregate_version")
    ) == [
        ("events.edition.created.v1", 1),
        ("events.edition.lifecycle_transitioned.v1", 2),
        ("events.edition.details_updated.v1", 3),
    ]


def test_update_is_exactly_scoped_and_rolls_back_on_outbox_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _administrator()
    edition = EventEditionFactory()
    foreign = EventEditionFactory()

    with pytest.raises(AuthorizationDenied) as unavailable:
        update_event_edition(
            actor=administrator,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=foreign.id,
            expected_aggregate_version=foreign.aggregate_version,
            details=_details(name="Cross-tenant rewrite"),
            correlation_id=uuid4(),
        )
    assert unavailable.value.reason_code == "target_unavailable"

    def fail_outbox(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr("maru.events.services.publish_domain_event", fail_outbox)
    with pytest.raises(RuntimeError, match="synthetic outbox"):
        update_event_edition(
            actor=administrator,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            expected_aggregate_version=1,
            details=_details(name="Rolled back rewrite"),
            correlation_id=uuid4(),
        )

    edition.refresh_from_db()
    assert edition.name != "Rolled back rewrite"
    assert edition.aggregate_version == 1
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()
