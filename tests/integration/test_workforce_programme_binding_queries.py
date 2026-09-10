"""Real binding projections keep source identity, field ceilings and history stable."""

from dataclasses import asdict, replace
from functools import partial
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.workforce import programme_binding_queries as queries
from maru.workforce import programme_staffing_queries as work_queries
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_workforce_programme_binding import apply, create
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def load(scope, request=None):
    return queries.load_programme_bindings(
        request or scope.selection.request, authorizer=scope.selection.policy
    )


def history(scope, result, **kwargs):
    return queries.load_programme_binding_history(
        scope.selection.request,
        binding_id=result.binding_id,
        through_version=kwargs.pop("through_version", result.binding_version),
        authorizer=scope.selection.policy,
        **kwargs,
    )


def reconcile(scope, result):
    return apply(
        scope,
        ProgrammeStaffingBindingChange(
            Action.RECONCILE,
            scope.selection.source,
            result.binding_id,
            result.binding_version,
            result.demand_id,
            result.demand_version,
        ),
    )


def test_current_view_retains_exact_source_without_selecting_private_history(
    binding_world,
):
    scope = binding_world
    assert load(scope) == ()
    created = create(scope)
    with CaptureQueriesContext(connection) as captured:
        (result,) = load(scope)
    assert result.source == scope.selection.source
    assert (result.binding_id, result.revision_id, result.demand_id) == (
        created.binding_id,
        created.revision_id,
        created.demand_id,
    )
    assert result.operation == "create"
    assert not {"actor_id", "reason", "briefing"} & asdict(result).keys()
    selects = [
        q["sql"]
        for q in captured
        if q["sql"].lstrip().upper().startswith("SELECT")
        and '"workforce_programmeshiftbindingrevision"' in q["sql"]
    ]
    assert len(selects) == 1
    assert '"reason"' not in selects[0]
    assert '"actor_id"' not in selects[0]
    assert '"request_digest"' not in selects[0]
    assert (
        AuditEvent.objects.filter(operation="workforce.programme_binding.read").count()
        == 2
    )
    (entry,) = history(scope, created).entries
    assert entry.binding == result
    assert entry.actor_id == scope.actor.id
    assert entry.reason == "Explicit synthetic staffing request"
    assert entry.occurred_at is not None


def test_history_ceiling_and_pagination_never_follow_new_revisions(
    binding_world, monkeypatch
):
    scope = binding_world
    first = create(scope)
    original = history(scope, first)
    second = reconcile(scope, first)
    third = reconcile(scope, second)
    assert history(scope, first) == original
    monkeypatch.setattr(queries, "BINDING_HISTORY_PAGE_SIZE", 1)
    page = history(scope, third)
    assert page.entries[0].binding.version == 1
    assert page.next_after_version == 1
    page = history(scope, third, after_version=page.next_after_version)
    assert page.entries[0].binding.version == 2
    assert page.next_after_version == 2
    page = history(scope, third, after_version=page.next_after_version)
    assert page.entries[0].binding.version == 3
    assert page.next_after_version is None
    assert load(scope)[0].version == 3


@pytest.mark.parametrize("field", ["staffing_requirements", "staffing_history"])
def test_programme_field_ceiling_is_independent_of_workforce_permission(
    binding_world, monkeypatch, field
):
    scope = binding_world
    created = create(scope)
    original = scope.selection.policy.authorize
    monkeypatch.setattr(
        scope.selection.policy,
        "authorize",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset({field})),
    )
    if field == "staffing_requirements":
        assert load(scope)
        with pytest.raises(ProgrammeAuthorizationDeniedError):
            history(scope, created)
    else:
        assert history(scope, created).entries
        with pytest.raises(ProgrammeAuthorizationDeniedError):
            load(scope)


@pytest.mark.parametrize("history_read", [False, True])
def test_workforce_field_denial_precedes_loading_even_with_programme_permission(
    binding_world, monkeypatch, history_read
):
    scope = binding_world
    created = create(scope)
    original = work_queries.decide_verified_principal_exact_edition
    monkeypatch.setattr(
        work_queries,
        "decide_verified_principal_exact_edition",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset()),
    )
    read = (
        partial(history, scope, created, through_version="not parsed")
        if history_read
        else partial(
            load, scope, replace(scope.selection.request, item_id="not parsed")
        )
    )
    with pytest.raises(ProgrammeStaffingDeniedError):
        read()


@pytest.mark.parametrize("field", ["item_id", "organization_id", "edition_id"])
def test_foreign_scope_never_releases_binding_or_history(binding_world, field):
    scope = binding_world
    created = create(scope)
    request = replace(scope.selection.request, **{field: uuid4()})
    denied = (
        ProgrammeStaffingDeniedError,
        ProgrammeStaffingUnavailableError,
        ProgrammeQueryUnavailableError,
    )
    with pytest.raises(denied):
        load(scope, request)
    with pytest.raises(denied):
        queries.load_programme_binding_history(
            request,
            binding_id=created.binding_id,
            through_version=1,
            authorizer=scope.selection.policy,
        )


@pytest.mark.parametrize(
    ("through", "after"), [(True, 0), (2, 0), (1, True), (1, 1), (1, -1)]
)
def test_history_rejects_untyped_future_and_invalid_cursors(
    binding_world, through, after
):
    created = create(binding_world)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        history(binding_world, created, through_version=through, after_version=after)


def test_binding_overflow_never_returns_partial_or_empty_data(
    binding_world, monkeypatch
):
    create(binding_world)
    monkeypatch.setattr(queries, "MAX_STAFFING_REQUIREMENTS_PER_ITEM", 0)
    with pytest.raises(ProgrammeStaffingUnavailableError):
        load(binding_world)
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_binding.read"
    ).exists()


@pytest.mark.parametrize("history_read", [False, True])
def test_audit_failure_prevents_disclosure_and_rolls_back_read_evidence(
    binding_world, monkeypatch, history_read
):
    scope = binding_world
    created = create(scope)
    before = AuditEvent.objects.count()

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic binding audit unavailable")

    monkeypatch.setattr(queries, "append_audit", fail)
    read = partial(history, scope, created) if history_read else partial(load, scope)
    with pytest.raises(RuntimeError, match="Synthetic binding audit unavailable"):
        read()
    assert AuditEvent.objects.count() == before


def test_postload_authority_revocation_withholds_result(binding_world, monkeypatch):
    scope = binding_world
    create(scope)
    original_view = queries._view
    original_policy = work_queries.decide_verified_principal_exact_edition

    def moved_authority(*args):
        result = original_view(*args)
        monkeypatch.setattr(
            work_queries,
            "decide_verified_principal_exact_edition",
            lambda **kwargs: replace(original_policy(**kwargs), allowed=False),
        )
        return result

    monkeypatch.setattr(queries, "_view", moved_authority)
    with pytest.raises(ProgrammeStaffingDeniedError):
        load(scope)
    assert not AuditEvent.objects.filter(
        operation="workforce.programme_binding.read"
    ).exists()
