"""Maintained native setup-reference cases; execution deferred under #102."""

from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.organizations.programme_setup_references import (
    resolve_programme_setup_foundation,
)
from maru.organizations.representation import provision_maru_operators
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
    update_convention_series,
)
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def foundation():
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = create_draft_organization(
        actor=administrator,
        details=OrganizationCreationDetails(name="Maru setup rehearsal"),
        correlation_id=uuid4(),
        source_channel="test",
    )
    series = create_convention_series(
        actor=administrator,
        organization_id=organization.id,
        details=ConventionSeriesCreationDetails(name="Maru rehearsal series"),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return administrator, organization, series


def test_draft_outer_join_preserves_absent_accountability_without_writes(foundation):
    _administrator, organization, _series = foundation
    with CaptureQueriesContext(connection) as queries:
        result = resolve_programme_setup_foundation(organization_id=organization.id)
    assert result is not None
    assert result.organization_id == organization.id
    assert result.organization_lifecycle == "draft"
    assert result.representation_id is None
    assert result.representation_version is None
    assert result.series_id is None
    assert all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)


def test_actual_series_is_scoped_to_its_exact_parent(foundation):
    administrator, organization, series = foundation
    foreign = create_draft_organization(
        actor=administrator,
        details=OrganizationCreationDetails(name="Maru other rehearsal"),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert (
        resolve_programme_setup_foundation(
            organization_id=organization.id, series_id=series.id
        ).series_id
        == series.id
    )
    assert (
        resolve_programme_setup_foundation(
            organization_id=foreign.id, series_id=series.id
        )
        is None
    )


def test_current_series_version_changes_the_source_fingerprint(foundation):
    administrator, organization, series = foundation
    before = resolve_programme_setup_foundation(
        organization_id=organization.id, series_id=series.id
    )
    update_convention_series(
        actor=administrator,
        organization_id=organization.id,
        series_id=series.id,
        expected_profile_version=series.profile_version,
        details=ConventionSeriesCreationDetails(name="Maru renamed rehearsal"),
        correlation_id=uuid4(),
        source_channel="test",
    )
    after = resolve_programme_setup_foundation(
        organization_id=organization.id, series_id=series.id
    )
    assert after.series_version == before.series_version + 1
    assert after.fingerprint != before.fingerprint
    assert before.series_name == "Maru rehearsal series"


def test_inactive_series_is_not_reused_or_returned_as_partial_context(foundation):
    administrator, organization, series = foundation
    update_convention_series(
        actor=administrator,
        organization_id=organization.id,
        series_id=series.id,
        expected_profile_version=series.profile_version,
        details=ConventionSeriesCreationDetails(name=series.name, is_active=False),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert (
        resolve_programme_setup_foundation(
            organization_id=organization.id, series_id=series.id
        )
        is None
    )
    assert (
        resolve_programme_setup_foundation(organization_id=organization.id) is not None
    )


def test_provisioning_reference_does_not_activate_or_upgrade_existing_root(foundation):
    administrator, organization, _series = foundation
    before = resolve_programme_setup_foundation(organization_id=organization.id)
    representation = provision_maru_operators(
        actor=administrator,
        organization_id=organization.id,
        reason="Prepare truthful synthetic accountability.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    with CaptureQueriesContext(connection) as queries:
        after = resolve_programme_setup_foundation(organization_id=organization.id)
    assert after.representation_id == representation.id
    assert after.representation_code == "maru_operators"
    assert after.representation_state == "provisioning"
    assert after.organization_lifecycle == "draft"
    assert after.fingerprint != before.fingerprint
    assert all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)


def test_malformed_reference_scope_performs_no_database_lookup(
    django_assert_num_queries,
):
    with django_assert_num_queries(0):
        assert resolve_programme_setup_foundation(organization_id="not-an-id") is None
