"""Fast exact-purpose and field-ceiling review policy contract tests."""

from dataclasses import replace
from uuid import uuid4

import pytest

from maru.applications import (
    programme_authorization,
)
from maru.applications import (
    programme_review_authorization as review,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_review_queries import (
    ProgrammeReviewReadRequest,
    get_programme_review_detail,
    list_programme_review_cases,
    list_self_programme_decisions,
)
from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.workforce.queries import CurrentDepartmentReference
from tests.unit.test_application_programme_authorization import _TrustedAuthorizer


def _scope(monkeypatch):
    ids = {
        name: uuid4()
        for name in ("actor_id", "organization_id", "edition_id", "department_id")
    }
    monkeypatch.setattr(
        review,
        "resolve_active_verified_person_reference",
        lambda **_kwargs: ActiveVerifiedPersonReference(account_id=ids["actor_id"]),
    )
    monkeypatch.setattr(
        review,
        "resolve_private_planning_edition_reference",
        lambda **_kwargs: PrivatePlanningEditionReference(
            organization_id=ids["organization_id"],
            edition_id=ids["edition_id"],
            accepts_private_planning_writes=True,
        ),
    )
    monkeypatch.setattr(
        review,
        "resolve_current_department_reference",
        lambda **_kwargs: CurrentDepartmentReference(
            organization_id=ids["organization_id"],
            edition_id=ids["edition_id"],
            department_id=ids["department_id"],
        ),
    )
    monkeypatch.setitem(
        programme_authorization.connection.settings_dict, "NAME", "test_unit"
    )
    return ids


@pytest.mark.parametrize("capability", sorted(review.REVIEW_STAFF_CAPABILITIES))
def test_review_staff_scope_requires_exact_current_department_and_fields(
    monkeypatch, capability
):
    ids = _scope(monkeypatch)
    authorizer = _TrustedAuthorizer()
    fields = (
        frozenset({"review_context"})
        if capability == review.MANAGE_REVIEW
        else review.REVIEW_FIELDS
    )
    scope = review.authorize_programme_review_scope(
        **ids,
        capability_code=capability,
        requested_fields=fields,
        authorizer=authorizer,
    )
    assert scope.department_id == ids["department_id"]
    assert authorizer.calls == [(capability, fields)]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **{**ids, "department_id": None},
            capability_code=capability,
            authorizer=authorizer,
        )


@pytest.mark.parametrize("capability", sorted(review.REVIEW_SELF_CAPABILITIES))
def test_review_recipient_scope_never_accepts_department_or_staff_fields(
    monkeypatch, capability
):
    ids = _scope(monkeypatch)
    authorizer = _TrustedAuthorizer()
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **ids, capability_code=capability, authorizer=authorizer
        )
    ids["department_id"] = None
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **ids,
            capability_code=capability,
            requested_fields=review.REVIEW_FIELDS,
            authorizer=authorizer,
        )
    scope = review.authorize_programme_review_scope(
        **ids,
        capability_code=capability,
        requested_fields=review.DECISION_SELF_FIELDS,
        authorizer=authorizer,
    )
    assert scope.department_id is None


@pytest.mark.parametrize(
    "resolver",
    [
        "resolve_active_verified_person_reference",
        "resolve_private_planning_edition_reference",
        "resolve_current_department_reference",
    ],
)
def test_absent_current_reference_denies_before_policy(monkeypatch, resolver):
    ids = _scope(monkeypatch)
    monkeypatch.setattr(review, resolver, lambda **_kwargs: None)
    authorizer = _TrustedAuthorizer()
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **ids, capability_code=review.REVIEW, authorizer=authorizer
        )
    assert authorizer.calls == []


@pytest.mark.parametrize(
    "decision",
    [
        True,
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
            reason_code="partial",
        ),
    ],
)
def test_boolean_or_incomplete_review_decision_is_never_authority(
    monkeypatch, decision
):
    ids = _scope(monkeypatch)
    authorizer = _TrustedAuthorizer()
    monkeypatch.setattr(authorizer, "authorize_department", lambda **_kwargs: decision)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **ids,
            capability_code=review.REVIEW,
            requested_fields=review.REVIEW_FIELDS,
            authorizer=authorizer,
        )


@pytest.mark.parametrize(
    ("flag", "database"), [(False, "test_unit"), (True, "maru"), (False, "maru")]
)
def test_custom_review_authorizer_requires_both_isolated_test_factors(
    monkeypatch, settings, flag, database
):
    ids = _scope(monkeypatch)
    settings.MARU_ALLOW_APPLICATIONS_PROGRAMME_TEST_AUTHORIZER = flag
    monkeypatch.setitem(
        programme_authorization.connection.settings_dict, "NAME", database
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        review.authorize_programme_review_scope(
            **ids, capability_code=review.REVIEW, authorizer=_TrustedAuthorizer()
        )


@pytest.mark.parametrize("limit", [0, 101, True, 1.5, "1"])
def test_invalid_query_bounds_fail_before_payload_lookup(limit):
    request = ProgrammeReviewReadRequest(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        review.REVIEW,
        frozenset({"review_context"}),
        uuid4(),
        "test",
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        list_programme_review_cases.__wrapped__(request=request, limit=limit)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail.__wrapped__(
            request=request, case_id=uuid4(), limit=limit
        )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        list_self_programme_decisions.__wrapped__(
            request=replace(
                request, capability_code=review.VIEW_DECISION_SELF, department_id=None
            ),
            limit=limit,
        )
