"""Real owner metadata admission keeps proposal, hosting and work purposes separate."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.urls import resolve

from maru.applications import programme_authorization as applications
from maru.authorization.policy import PolicyDecision
from maru.events.queries import (
    EditionAdoptionProfileReference,
    PrivatePlanningEditionReference,
)
from maru.identity.queries import (
    ActiveVerifiedAccountReference,
    ActiveVerifiedPersonReference,
)
from maru.programme import authorization as programme
from maru.scheduling import output_navigation
from maru.scheduling import personal_navigation as navigation
from maru.scheduling import personal_output_queries as timetable
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.continuity_protocol import ContinuityScope

URLCONF = "tests.support.programme_personal_urls"


@pytest.fixture
def boundary(monkeypatch):
    actor, organization, edition = (UUID(int=i) for i in (1, 2, 3))
    scope = {"actor_id": actor, "organization_id": organization, "edition_id": edition}
    person = Mock(return_value=ActiveVerifiedPersonReference(actor))
    monkeypatch.setattr(
        navigation, "resolve_active_verified_person_reference", Mock(return_value=None)
    )
    account = Mock(return_value=ActiveVerifiedAccountReference(actor))
    reference = Mock(
        return_value=PrivatePlanningEditionReference(
            edition, organization, accepts_private_planning_writes=True
        )
    )
    monkeypatch.setattr(
        applications, "resolve_active_verified_person_reference", person
    )
    monkeypatch.setattr(programme, "resolve_active_verified_account_reference", account)
    for owner in (applications, programme):
        monkeypatch.setattr(
            owner, "resolve_private_planning_edition_reference", reference
        )
    monkeypatch.setattr(
        applications,
        "edition_adoption_profile_reference",
        Mock(return_value=EditionAdoptionProfileReference("synthetic", 1)),
    )
    for name in (
        "profile_allows_application_programme_self",
        "profile_allows_application_target",
    ):
        monkeypatch.setattr(applications, name, Mock(return_value=True))

    def allowed(**kwargs):
        assert kwargs["principal_id"] == kwargs["owner_account_id"] == actor
        assert kwargs["organization_id"] == organization
        assert kwargs["edition_id"] == edition
        return PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="exact_self",
        )

    proposal_policy, host_policy, work_policy = (
        Mock(side_effect=allowed) for _ in range(3)
    )
    monkeypatch.setattr(
        applications, "decide_verified_principal_exact_self", proposal_policy
    )
    monkeypatch.setattr(programme, "decide_verified_principal_exact_self", host_policy)
    # Use the real timetable metadata admission for a Workforce-only layer.
    monkeypatch.setattr(timetable, "_adopted_layers", Mock(return_value=(False, True)))
    monkeypatch.setattr(timetable, "decide_verified_principal_exact_self", work_policy)
    return SimpleNamespace(
        scope=scope,
        person=person,
        account=account,
        reference=reference,
        proposal=proposal_policy,
        host=host_policy,
        work=work_policy,
    )


@pytest.mark.parametrize("current", ["proposals", "hosting", "timetable"])
def test_exact_self_current_routes_minimal_fields_and_no_other_task_policy(
    boundary, current
):
    links = navigation.personal_programme_task_links(
        **boundary.scope, current=current, urlconf=URLCONF
    )
    assert {row.code for row in links} == {"proposals", "hosting", "timetable"} - {
        current
    }
    for row in links:
        target = resolve(row.url, urlconf=URLCONF)
        assert target.kwargs == {
            key: boundary.scope[key] for key in ("organization_id", "edition_id")
        }
        assert str(boundary.scope["actor_id"]) not in row.url
        assert "?" not in row.url
    expected = {
        "proposals": (
            boundary.proposal,
            {"proposal_summary", "selection", "own_invitation"},
        ),
        "hosting": (boundary.host, {"own_host_relationship", "own_host_invitation"}),
        "timetable": (boundary.work, {"shifts"}),
    }
    for code, (policy, fields) in expected.items():
        assert policy.call_count == int(code != current)
        if code != current:
            assert policy.call_args.kwargs["requested_fields"] == fields


@pytest.mark.parametrize(
    "missing",
    [
        "proposal_summary",
        "selection",
        "own_invitation",
        "own_host_relationship",
        "own_host_invitation",
        "shifts",
    ],
)
def test_each_independent_field_denial_omits_only_its_destination(boundary, missing):
    code = (
        "proposals"
        if missing in {"proposal_summary", "selection", "own_invitation"}
        else "timetable"
        if missing == "shifts"
        else "hosting"
    )
    policy = {
        "proposals": boundary.proposal,
        "hosting": boundary.host,
        "timetable": boundary.work,
    }[code]
    original = policy.side_effect
    policy.side_effect = lambda **kwargs: replace(
        original(**kwargs), fields=kwargs["requested_fields"] - {missing}
    )
    current = "hosting" if code != "hosting" else "proposals"
    links = navigation.personal_programme_task_links(
        **boundary.scope, current=current, urlconf=URLCONF
    )
    assert {row.code for row in links} == {"proposals", "hosting", "timetable"} - {
        current,
        code,
    }


@pytest.mark.parametrize(
    "error",
    [DatabaseError, ValidationError, RuntimeError, SchedulingAuthorizationDeniedError],
)
def test_unavailable_optional_task_does_not_hide_independent_task(boundary, error):
    boundary.work.side_effect = error("synthetic unavailable")
    links = navigation.personal_programme_task_links(
        **boundary.scope, current="proposals", urlconf=URLCONF
    )
    assert [row.code for row in links] == ["hosting"]


@pytest.mark.parametrize("current", ["proposals", "hosting", "timetable"])
def test_unmounted_current_profiles_do_no_optional_owner_work(boundary, current):
    assert (
        navigation.personal_programme_task_links(
            **boundary.scope, current=current, urlconf="maru.urls"
        )
        == ()
    )
    for policy in (boundary.proposal, boundary.host, boundary.work):
        policy.assert_not_called()


@pytest.mark.parametrize("key", ["actor_id", "organization_id", "edition_id"])
@pytest.mark.parametrize("invalid", [None, UUID(int=0), "not-an-identifier"])
def test_invalid_scope_does_no_optional_work(boundary, key, invalid):
    assert (
        navigation.personal_programme_task_links(
            **(boundary.scope | {key: invalid}), current="hosting", urlconf=URLCONF
        )
        == ()
    )
    boundary.proposal.assert_not_called()
    boundary.work.assert_not_called()


@pytest.mark.parametrize("key", ["actor_id", "organization_id", "edition_id"])
def test_foreign_owner_reference_cannot_retarget_a_link(boundary, key):
    if key == "actor_id":
        boundary.account.return_value = ActiveVerifiedAccountReference(UUID(int=99))
        boundary.host.side_effect = lambda **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset(),
            reason_code="synthetic",
        )
    else:
        boundary.reference.return_value = replace(
            boundary.reference.return_value, **{key: UUID(int=99)}
        )
        boundary.host.side_effect = lambda **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset(),
            reason_code="synthetic",
        )
    links = navigation.personal_programme_task_links(
        **boundary.scope, current="proposals", urlconf=URLCONF
    )
    assert "hosting" not in {row.code for row in links}


def test_profile_denial_does_not_query_proposal_policy(boundary, monkeypatch):
    monkeypatch.setattr(
        applications, "profile_allows_application_programme_self", lambda *_args: False
    )
    links = navigation.personal_programme_task_links(
        **boundary.scope, current="hosting", urlconf=URLCONF
    )
    assert [row.code for row in links] == ["timetable"]
    boundary.proposal.assert_not_called()


def test_shadowed_route_is_omitted_before_optional_policy(boundary, monkeypatch):
    original = navigation.resolve

    def shadowed(url, **kwargs):
        target = original(url, **kwargs)
        return (
            SimpleNamespace(view_name="different-task", kwargs=target.kwargs)
            if "hosting" in url
            else target
        )

    monkeypatch.setattr(navigation, "resolve", shadowed)
    links = navigation.personal_programme_task_links(
        **boundary.scope, current="proposals", urlconf=URLCONF
    )
    assert [row.code for row in links] == ["timetable"]
    boundary.host.assert_not_called()


@pytest.mark.parametrize("current", ["timetable", "now", "notices"])
def test_personal_outputs_add_reciprocal_tasks_for_actual_viewer(
    boundary, monkeypatch, current
):
    monkeypatch.setattr(output_navigation, "_admit", Mock())
    scope = ContinuityScope(
        boundary.scope["organization_id"],
        boundary.scope["edition_id"],
        "exact_person",
        boundary.scope["actor_id"],
        "personal",
    )
    links = output_navigation.programme_output_links(
        scope, current=current, urlconf=URLCONF
    )
    assert {row.code for row in links} == {
        "proposals",
        "hosting",
        "timetable",
        "now",
        "notices",
    } - {current}
    assert len(links) == 4
    # Existing output admission owns timetable checks.
    boundary.work.assert_not_called()
