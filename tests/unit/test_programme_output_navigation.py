"""Current route and metadata admission never substitute for an output owner's read."""

from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.test import override_settings
from django.urls import resolve

from maru.authorization.policy import PolicyDecision
from maru.events.queries import EditionAdoptionProfileReference
from maru.scheduling import output_navigation as navigation
from maru.scheduling import personal_output_queries as personal
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.continuity_protocol import ContinuityScope
from maru.scheduling.operator_scope import OperatorScopeKind


@pytest.fixture(params=["public", "exact_person", "room", "department", "edition"])
def scope(request):
    org, edition, actor = UUID(int=1), UUID(int=2), UUID(int=3)
    if request.param == "public":
        return ContinuityScope(org, edition, "public")
    if request.param == "exact_person":
        return ContinuityScope(org, edition, "exact_person", actor, "personal")
    return ContinuityScope(
        org,
        edition,
        "private_operator",
        actor,
        request.param,
        edition if request.param == "edition" else UUID(int=4),
        ("accessibility", "staffing", "technical"),
    )


def test_real_reverse_resolve_and_explicit_layer_ceiling(scope, monkeypatch):
    admit = Mock()
    monkeypatch.setattr(navigation, "_admit", admit)
    with override_settings(ROOT_URLCONF="maru.urls"):
        links = navigation.programme_output_links(
            scope, current="notices", urlconf="tests.support.programme_output_urls"
        )
    assert {link.code for link in links} == {"timetable", "now"}
    for link in links:
        parsed = urlsplit(link.url)
        target = resolve(parsed.path, urlconf="tests.support.programme_output_urls")
        assert target.kwargs["organization_id"] == scope.organization_id
        assert target.kwargs["edition_id"] == scope.edition_id
        assert str(scope.actor_id) not in link.url
        assert parse_qs(parsed.query) == {layer: ["1"] for layer in scope.layers}
        if scope.audience == "private_operator":
            assert target.kwargs["target_id"] == scope.target_id
            assert target.kwargs["scope_kind"] == scope.kind
    assert admit.call_count == 2


def test_missing_current_configuration_omits_links_before_any_owner_admission(
    scope, monkeypatch
):
    admit = Mock(
        side_effect=AssertionError("Unmounted route must not read owner metadata")
    )
    monkeypatch.setattr(navigation, "_admit", admit)
    assert (
        navigation.programme_output_links(scope, current="notices", urlconf="maru.urls")
        == ()
    )
    admit.assert_not_called()


def test_shadowed_route_is_not_offered_or_admitted(scope, monkeypatch):
    admit = Mock()
    monkeypatch.setattr(navigation, "_admit", admit)
    monkeypatch.setattr(
        navigation,
        "resolve",
        lambda *_args, **_kwargs: SimpleNamespace(view_name="unrelated", kwargs={}),
    )
    assert (
        navigation.programme_output_links(
            scope, current="notices", urlconf="tests.support.programme_output_urls"
        )
        == ()
    )
    admit.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        SchedulingAuthorizationDeniedError,
        SchedulingUnavailableError,
        DatabaseError,
        RuntimeError,
    ],
)
def test_optional_denial_or_dependency_failure_omits_destination(
    scope, monkeypatch, error
):
    monkeypatch.setattr(navigation, "_admit", Mock(side_effect=error))
    assert (
        navigation.programme_output_links(
            scope, current="notices", urlconf="tests.support.programme_output_urls"
        )
        == ()
    )


def test_owner_field_ceiling_uses_actual_viewer_and_not_notice_authority(monkeypatch):
    request = ContinuityScope(
        UUID(int=1),
        UUID(int=2),
        "private_operator",
        UUID(int=3),
        "department",
        UUID(int=4),
        ("media", "staffing"),
    )
    admit = Mock()
    monkeypatch.setattr(navigation, "authorize_operator_scope", admit)
    navigation._admit(request, "timetable")
    fields = {
        call.kwargs["capability"]: call.kwargs["fields"]
        for call in admit.call_args_list
    }
    assert fields == {
        "scheduling.view_operator_output": frozenset({"released_geometry"}),
        "programme.view_operator_copy": frozenset({"reviewed_copy"}),
        "venues.view_operator_wayfinding": frozenset({"scope_links", "wayfinding"}),
        "programme.view_operator_delivery": frozenset({"media"}),
        "workforce.view_operator_staffing": frozenset(
            {"scope_links", "work_instructions", "coverage"}
        ),
    }
    assert all(
        call.args[0].actor_id == request.actor_id
        and call.args[0].kind is OperatorScopeKind.DEPARTMENT
        for call in admit.call_args_list
    )


@pytest.mark.parametrize("adopted", [False, True])
def test_department_membership_requires_adopted_workforce_links_without_details(
    monkeypatch, adopted
):
    request = ContinuityScope(
        UUID(int=1),
        UUID(int=2),
        "private_operator",
        UUID(int=3),
        "department",
        UUID(int=4),
    )
    admit = Mock()
    monkeypatch.setattr(navigation, "authorize_operator_scope", admit)
    monkeypatch.setattr(
        navigation, "operator_staffing_adopted", lambda _request: adopted
    )
    navigation._admit(request, "timetable")
    workforce = [
        call
        for call in admit.call_args_list
        if call.kwargs["capability"] == "workforce.view_operator_staffing"
    ]
    assert len(workforce) == int(adopted)
    if adopted:
        assert workforce[0].kwargs["fields"] == frozenset({"scope_links"})


def test_continuity_adapter_denial_precedes_other_owner_work(scope, monkeypatch):
    monkeypatch.setattr(
        navigation,
        "edition_adoption_profile_reference",
        Mock(return_value=EditionAdoptionProfileReference("synthetic", 1)),
    )
    monkeypatch.setattr(navigation, "profile_allows_adapter", Mock(return_value=False))
    with (
        patch.object(navigation, "_operator") as operator,
        patch.object(navigation, "authorize_personal_timetable_scope") as own,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        navigation._admit(scope, "now")
    operator.assert_not_called()
    own.assert_not_called()


@pytest.mark.parametrize("adopted", [(True, False), (False, True), (True, True)])
def test_personal_metadata_checks_only_adopted_owners_and_exact_self(
    monkeypatch, adopted
):
    monkeypatch.setattr(personal, "_adopted_layers", Mock(return_value=adopted))
    schedule, programme = Mock(), Mock()
    workforce = Mock(
        return_value=PolicyDecision(
            allowed=True,
            fields=frozenset({"shifts"}),
            obligations=frozenset(),
            reason_code="synthetic",
        )
    )
    monkeypatch.setattr(personal, "authorize_scheduling_scope", schedule)
    monkeypatch.setattr(personal, "authorize_programme_scope", programme)
    monkeypatch.setattr(personal, "decide_verified_principal_exact_self", workforce)
    actor = uuid4()
    personal.authorize_personal_timetable_scope(
        actor_id=actor, organization_id=uuid4(), edition_id=uuid4()
    )
    assert schedule.call_count == programme.call_count == int(adopted[0])
    assert workforce.call_count == int(adopted[1])
    if adopted[1]:
        assert (
            workforce.call_args.kwargs["principal_id"]
            == workforce.call_args.kwargs["owner_account_id"]
            == actor
        )
        assert workforce.call_args.kwargs["requested_fields"] == frozenset({"shifts"})


@pytest.mark.parametrize(
    "decision",
    [
        None,
        SimpleNamespace(allowed=True, fields=frozenset({"shifts"})),
        PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="denied",
        ),
        PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="missing",
        ),
    ],
)
def test_personal_metadata_rejects_non_decisions_denial_and_incomplete_fields(
    monkeypatch, decision
):
    monkeypatch.setattr(personal, "_adopted_layers", Mock(return_value=(False, True)))
    monkeypatch.setattr(
        personal, "decide_verified_principal_exact_self", Mock(return_value=decision)
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        personal.authorize_personal_timetable_scope(
            actor_id=uuid4(), organization_id=uuid4(), edition_id=uuid4()
        )


def test_personal_metadata_rejects_adoption_movement(monkeypatch):
    monkeypatch.setattr(
        personal, "_adopted_layers", Mock(side_effect=[(True, False), (True, True)])
    )
    monkeypatch.setattr(personal, "authorize_scheduling_scope", Mock())
    monkeypatch.setattr(personal, "authorize_programme_scope", Mock())
    with pytest.raises(SchedulingUnavailableError):
        personal.authorize_personal_timetable_scope(
            actor_id=uuid4(), organization_id=uuid4(), edition_id=uuid4()
        )
