"""PostgreSQL coverage for the exact Programme authorization seam."""

from dataclasses import dataclass, field

import pytest
from django.db import connection

import maru.programme.authorization as programme_authorization
from maru.authorization.policy import PolicyDecision
from maru.programme.authorization import (
    PROGRAMME_MANAGE_ITEMS,
    PROGRAMME_VIEW_PRIVATE,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = pytest.mark.django_db


@dataclass
class _TrustedAuthorizer:
    fields: frozenset[str] = frozenset()
    calls: list[tuple[str, frozenset[str] | None]] = field(default_factory=list)

    def authorize(
        self,
        *,
        principal_id: object,
        organization_id: object,
        edition_id: object,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        self.calls.append((capability_code, requested_fields))
        return PolicyDecision(
            allowed=True,
            fields=self.fields,
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="sealed_future_profile_harness",
        )


def test_current_profile_denies_programme_even_for_verified_actor() -> None:
    """Keep every executable exact profile closed to Programme capabilities."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        authorize_programme_scope(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            capability_code=PROGRAMME_MANAGE_ITEMS,
        )


@pytest.mark.parametrize(
    "actor_overrides",
    [
        {"is_active": False},
        {"email_verified_at": None},
    ],
)
def test_inactive_or_unverified_actor_fails_before_substituted_policy(
    actor_overrides: dict[str, object],
) -> None:
    """Do not let the sealed test seam bypass persisted identity facts."""
    actor = AccountFactory(**actor_overrides)
    edition = EventEditionFactory()
    authorizer = _TrustedAuthorizer()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        authorize_programme_scope(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            capability_code=PROGRAMME_MANAGE_ITEMS,
            authorizer=authorizer,
        )

    assert authorizer.calls == []


def test_trusted_protocol_returns_a_complete_decision_not_allow_boolean() -> None:
    """Retain policy fields, obligations, and rationale in the trusted seam."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    requested_fields = frozenset({"item_summaries", "working_information"})
    authorizer = _TrustedAuthorizer(fields=requested_fields)

    scope = authorize_programme_scope(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=requested_fields,
        authorizer=authorizer,
    )

    assert scope.actor_id == actor.id
    assert scope.organization_id == edition.organization_id
    assert scope.edition_id == edition.id
    assert scope.accepts_private_planning_writes is True
    assert scope.decision.reason_code == "sealed_future_profile_harness"
    assert authorizer.calls == [(PROGRAMME_VIEW_PRIVATE, requested_fields)]


def test_test_authorizer_requires_a_live_test_prefixed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the substitute when only the test setting factor is present."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _TrustedAuthorizer()

    with monkeypatch.context() as patch:
        patch.setitem(connection.settings_dict, "NAME", "maru")
        with pytest.raises(ProgrammeAuthorizationDeniedError):
            authorize_programme_scope(
                actor_id=actor.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                capability_code=PROGRAMME_MANAGE_ITEMS,
                authorizer=authorizer,
            )

    assert authorizer.calls == []


def test_authorized_query_requires_every_requested_field() -> None:
    """A partially intersected policy decision cannot release a projection."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _TrustedAuthorizer(fields=frozenset({"item_summaries"}))

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        authorize_programme_scope(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            capability_code=PROGRAMME_VIEW_PRIVATE,
            requested_fields=frozenset({"item_summaries", "working_information"}),
            authorizer=authorizer,
        )


def test_default_authorizer_invokes_exact_policy_on_each_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove callers can reauthorize rather than reusing a stale decision."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    calls: list[tuple[object, str, frozenset[str] | None]] = []

    def allowed_decision(
        *,
        principal_id: object,
        organization_id: object,
        edition_id: object,
        capability_code: str,
        requested_fields: frozenset[str] | None,
        at: object = None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, at
        calls.append((object(), capability_code, requested_fields))
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic_exact_policy",
        )

    monkeypatch.setattr(
        programme_authorization,
        "decide_verified_principal_exact_edition",
        allowed_decision,
    )
    requested = frozenset({"item_summaries"})

    for _index in range(2):
        authorize_programme_scope(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            capability_code=PROGRAMME_VIEW_PRIVATE,
            requested_fields=requested,
        )

    assert len(calls) == 2
    assert all(call[0] is not None for call in calls)
    assert [call[1:] for call in calls] == [
        (PROGRAMME_VIEW_PRIVATE, requested),
        (PROGRAMME_VIEW_PRIVATE, requested),
    ]
