"""Curation and incomplete readiness do not become release success."""

from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.programme import release_queries as sources
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.catalogs import ProgrammeReadinessConcern
from maru.programme.commands import (
    approve_programme_public_rendition,
    configure_programme_readiness,
    revise_programme_working,
)
from maru.programme.models import (
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammeWorkingRevision,
)
from maru.programme.queries import ProgrammeQueryUnavailableError
from tests.factories import AccountFactory
from tests.integration.test_programme_placement_decisions import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_programme_release_sources import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def release_scope(assessed, monkeypatch):
    return configure_release_scope(assessed, monkeypatch)


def configure_release_scope(assessed, monkeypatch):
    monkeypatch.setattr(sources, "profile_allows_adapter", lambda *_args: True)
    item = ProgrammeItem.objects.get(id=assessed.selection.item_id)
    for concern in ProgrammeReadinessConcern:
        configured = configure_programme_readiness(
            **assessed.common,
            item_id=item.id,
            concern=concern,
            disposition="required",
            expected_version=item.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            authorizer=assessed.policy,
        )
        item.aggregate_version = configured.resulting_item_version
    assessed.selection = replace(
        assessed.selection, expected_item_version=item.aggregate_version
    )
    return assessed


def load(scope, request=None):
    return sources.load_programme_release_item_sources(
        request or scope.request,
        item_ids=(scope.selection.item_id,),
        authorizer=scope.policy,
    )[0]


def public_copy(scope, reviewer_id):
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    working = (
        ProgrammeWorkingRevision.objects.filter(item=item).order_by("-sequence").first()
    )
    return approve_programme_public_rendition(
        **(scope.common | {"actor_id": reviewer_id}),
        item_id=item.id,
        source_working_revision_id=working.id,
        public_title="Synthetic public opening",
        expected_version=item.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=scope.policy,
    )


def test_missing_copy_does_not_hide_complete_seven_concern_readiness(release_scope):
    result = load(release_scope)
    assert result.public_copy_state == "unavailable"
    assert result.public_rendition_id is None
    assert len(result.readiness) == 7
    assert result == load(release_scope)


def test_self_curated_copy_is_retained_but_not_independent_release_evidence(
    release_scope,
):
    original = public_copy(release_scope, release_scope.request.actor_id)
    assert load(release_scope).public_copy_state == "blocked"
    reviewer = AccountFactory()
    independent = public_copy(release_scope, reviewer.id)
    result = load(release_scope)
    assert result.public_copy_state == "satisfied"
    assert result.public_rendition_id == independent.result_object_id
    assert ProgrammePublicRendition.objects.filter(
        id=original.result_object_id
    ).exists()


def test_working_copy_change_stales_the_exact_independently_reviewed_source(
    release_scope,
):
    public_copy(release_scope, AccountFactory().id)
    before = load(release_scope)
    revise_programme_working(
        **release_scope.common,
        item_id=release_scope.selection.item_id,
        internal_title="Changed private working copy",
        expected_version=before.item_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=release_scope.policy,
    )
    after = load(release_scope)
    assert after.public_copy_state == "stale"
    assert after.public_rendition_id == before.public_rendition_id
    assert after.evidence_digest != before.evidence_digest


def test_inactive_reviewer_cannot_supply_current_release_copy(release_scope):
    reviewer = AccountFactory()
    public_copy(release_scope, reviewer.id)
    assert load(release_scope).public_copy_state == "satisfied"
    reviewer.is_active = False
    reviewer.save(update_fields=("is_active",))
    assert load(release_scope).public_copy_state == "unavailable"


def test_retained_authorship_is_not_erased_by_author_deactivation(release_scope):
    author_id = release_scope.request.actor_id
    public_copy(release_scope, author_id)
    from maru.identity.models import Account  # noqa: PLC0415

    author = Account.objects.get(id=author_id)
    author.is_active = False
    author.save(update_fields=("is_active",))
    current = replace(release_scope.request, actor_id=AccountFactory().id)
    assert load(release_scope, current).public_copy_state == "blocked"


def test_person_closure_contains_reviewers_and_all_current_hosts_before_locks(
    release_scope,
):
    reviewer = AccountFactory()
    public_copy(release_scope, reviewer.id)
    selected = tuple(
        row.host_id for row in release_scope.world.placement.host_presences
    )
    result = sources.collect_programme_release_person_references(
        release_scope.request,
        item_ids=(release_scope.selection.item_id,),
        host_ids=selected,
        authorizer=release_scope.policy,
    )
    assert {row.host_id for row in result.selected_hosts} == set(selected)
    assert set(result.account_ids) == {
        release_scope.request.actor_id,
        reviewer.id,
        *(row.account_id for row in result.selected_hosts),
    }


def test_person_closure_refuses_a_foreign_selected_host(release_scope):
    with pytest.raises(ProgrammeQueryUnavailableError):
        sources.collect_programme_release_person_references(
            release_scope.request,
            item_ids=(release_scope.selection.item_id,),
            host_ids=(uuid4(),),
            authorizer=release_scope.policy,
        )


def test_source_never_selects_private_working_or_public_copy_text(release_scope):
    public_copy(release_scope, AccountFactory().id)
    with CaptureQueriesContext(connection) as captured:
        result = load(release_scope)
    assert "Synthetic public opening" not in str(asdict(result))
    queries = [row["sql"] for row in captured if row["sql"].startswith("SELECT")]
    assert queries
    for query in queries:
        assert all(
            f'"{field}"' not in query
            for field in (
                "internal_title",
                "working_summary",
                "public_title",
                "public_summary",
                "review_reason",
            )
        )


def test_incomplete_concern_membership_fails_closed(release_scope, monkeypatch):
    original = sources.load_programme_readiness
    monkeypatch.setattr(
        sources, "load_programme_readiness", lambda **kwargs: original(**kwargs)[:-1]
    )
    with pytest.raises(ProgrammeQueryUnavailableError):
        load(release_scope)


def test_person_overflow_is_unavailable_not_partial_source(release_scope, monkeypatch):
    monkeypatch.setattr(sources, "MAX_PERSON_REFERENCE_BATCH", 1)
    with pytest.raises(ProgrammeQueryUnavailableError):
        load(release_scope)


def test_ordinary_public_copy_field_does_not_grant_release_consequences(
    release_scope, monkeypatch
):
    original = release_scope.policy.authorize

    def policy(**kwargs):
        result = original(**kwargs)
        if kwargs["capability_code"] == "programme.view_public_copy":
            return replace(result, fields=frozenset({"latest_public_rendition"}))
        return result

    monkeypatch.setattr(release_scope.policy, "authorize", policy)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load(release_scope)


def test_current_profiles_deny_new_owner_release_sources(assessed):
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load(assessed)
