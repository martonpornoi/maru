from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F

from maru.core.localization import (
    grouped_language_choices,
    grouped_time_zone_choices,
    phone_region_choices,
)
from maru.events.models import EventEdition
from maru.organizations.forms import OrganizationAdminForm
from maru.organizations.models import ConventionSeries, Organization
from maru.participation.models import Participation
from tests.factories import (
    AccountFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_slugs_are_normalized_and_case_insensitively_unique() -> None:
    organization = OrganizationFactory(slug="FUR-EVENTS")

    assert organization.slug == "fur-events"
    with transaction.atomic(), pytest.raises((IntegrityError, ValidationError)):
        OrganizationFactory(slug="Fur-Events")


def test_series_slug_is_unique_only_inside_organization() -> None:
    first_organization = OrganizationFactory()
    second_organization = OrganizationFactory()
    ConventionSeriesFactory(organization=first_organization, slug="gathering")
    ConventionSeriesFactory(organization=second_organization, slug="gathering")

    with transaction.atomic(), pytest.raises((IntegrityError, ValidationError)):
        ConventionSeriesFactory(
            organization=first_organization,
            slug="GATHERING",
        )


def test_organization_localization_defaults_are_bounded_and_readable() -> None:
    organization = OrganizationFactory(
        country_code="hu",
        default_language_codes=["EN", "HU"],
    )

    assert organization.country_code == "HU"
    assert organization.default_language_codes == ["en", "hu"]

    language_groups = grouped_language_choices()
    assert language_groups[0] == ("Pinned", (("en", "en (English)"),))
    assert any(label == "Europe" for label, _choices in language_groups)

    time_zone_labels = {
        value: label
        for _group, choices in grouped_time_zone_choices()
        for value, label in choices
    }
    assert "UTC+01:00" in time_zone_labels["Europe/Budapest"]
    assert "UTC+02:00" in time_zone_labels["Europe/Budapest"]
    assert "Europe/Budapest" in time_zone_labels["Europe/Budapest"]

    phone_labels = dict(phone_region_choices())
    assert phone_labels["HU"].startswith("HU 🇭🇺 (+36)")

    form = OrganizationAdminForm()
    assert form.fields["default_language_codes"].initial == ("en",)
    assert form.fields["default_time_zone"].widget.attrs["data-filterable-select"] == ""


def test_organization_rejects_unknown_localization_codes() -> None:
    with pytest.raises(ValidationError, match="valid ISO 3166"):
        OrganizationFactory(country_code="XX")

    with pytest.raises(ValidationError, match="Unknown ISO 639-1"):
        OrganizationFactory(default_language_codes=["zz"])


def test_edition_rejects_series_from_another_organization() -> None:
    edition_organization = OrganizationFactory()
    other_series = ConventionSeriesFactory()

    with pytest.raises(ValidationError, match="series must belong"):
        EventEditionFactory(
            organization=edition_organization,
            series=other_series,
        )


def test_database_trigger_rejects_edition_scope_bypass() -> None:
    edition = EventEditionFactory()
    other_series = ConventionSeriesFactory()

    with transaction.atomic(), pytest.raises(IntegrityError):
        EventEdition.objects.filter(pk=edition.pk).update(series=other_series)


def test_edition_date_constraint_is_enforced() -> None:
    with pytest.raises(ValidationError):
        EventEditionFactory(
            starts_on=date(2030, 8, 4),
            ends_on=date(2030, 8, 1),
        )


def test_participation_rejects_mismatched_organization() -> None:
    edition = EventEditionFactory()

    with pytest.raises(ValidationError, match="edition must belong"):
        ParticipationFactory(
            edition=edition,
            organization=OrganizationFactory(),
        )


def test_database_trigger_rejects_participation_scope_bypass() -> None:
    participation = ParticipationFactory()

    with transaction.atomic(), pytest.raises(IntegrityError):
        Participation.objects.filter(pk=participation.pk).update(
            organization=OrganizationFactory()
        )


def test_participation_and_capacity_codes_are_unique() -> None:
    participation = ParticipationFactory()
    ParticipationCapacityFactory(participation=participation, code="volunteer")

    with transaction.atomic(), pytest.raises((IntegrityError, ValidationError)):
        ParticipationCapacityFactory(
            participation=participation,
            code="volunteer",
        )

    with transaction.atomic(), pytest.raises((IntegrityError, ValidationError)):
        ParticipationFactory(
            account=participation.account,
            edition=participation.edition,
            organization=participation.organization,
        )


def test_historical_labels_are_snapshots() -> None:
    participation = ParticipationFactory()
    original_edition_name = participation.edition_name_snapshot
    original_series_name = participation.series_name_snapshot

    ConventionSeries.objects.filter(pk=participation.edition.series_id).update(
        name="Renamed Series", profile_version=F("profile_version") + 1
    )
    EventEdition.objects.filter(pk=participation.edition_id).update(
        name="Renamed Edition", aggregate_version=F("aggregate_version") + 1
    )
    participation.refresh_from_db()

    assert participation.edition_name_snapshot == original_edition_name
    assert participation.series_name_snapshot == original_series_name


def test_organization_cannot_be_deleted_with_series() -> None:
    organization = OrganizationFactory()
    ConventionSeriesFactory(organization=organization)

    with transaction.atomic(), pytest.raises(IntegrityError):
        Organization.objects.filter(pk=organization.pk).delete()


def test_account_cannot_have_duplicate_participation() -> None:
    account = AccountFactory()
    edition = EventEditionFactory()
    ParticipationFactory(
        account=account,
        edition=edition,
        organization=edition.organization,
    )

    with pytest.raises(ValidationError):
        ParticipationFactory(
            account=account,
            edition=edition,
            organization=edition.organization,
        )
