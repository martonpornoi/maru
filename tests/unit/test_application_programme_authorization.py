"""Database-free coverage for Programme call and proposal authorization."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.applications import programme_authorization
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_PROGRAMME_PROPOSAL_CAPABILITY_CODES,
    APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
    APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
    ExactPolicyApplicationsProgrammeAuthorizer,
    authorize_programme_call_scope,
    authorize_programme_proposal_scope,
    authorize_programme_recovery_retry_scope,
    authorize_programme_recovery_scope,
    authorize_programme_retry_scope,
    authorize_programme_self_entry_scope,
)
from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.workforce.queries import CurrentDepartmentReference


@dataclass
class _TrustedAuthorizer:
    calls: list[tuple[str, frozenset[str] | None]] = field(default_factory=list)

    def authorize_department(self, **kwargs: object) -> PolicyDecision:
        capability_code = str(kwargs["capability_code"])
        requested_fields = kwargs["requested_fields"]
        assert requested_fields is None or isinstance(requested_fields, frozenset)
        self.calls.append((capability_code, requested_fields))
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_unit_authorizer",
        )

    def authorize_self(self, **kwargs: object) -> PolicyDecision:
        return self.authorize_department(**kwargs)

    def authorize_recovery(self, **kwargs: object) -> PolicyDecision:
        requested_fields = kwargs["requested_fields"]
        assert requested_fields is None
        self.calls.append((APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP, None))
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_unit_recovery_authorizer",
        )

    def authorize_retry(self, **_kwargs: object) -> PolicyDecision:
        self.calls.append(("programme_retry", frozenset()))
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="sealed_unit_retry_authorizer",
        )

    def authorize_recovery_retry(self, **_kwargs: object) -> PolicyDecision:
        self.calls.append(("programme_recovery_retry", frozenset()))
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_unit_recovery_retry_authorizer",
        )


def _mount_references(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, object, object, object]:
    actor_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()
    monkeypatch.setattr(
        programme_authorization,
        "resolve_active_verified_person_reference",
        lambda **_kwargs: ActiveVerifiedPersonReference(account_id=actor_id),
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_private_planning_edition_reference",
        lambda **_kwargs: PrivatePlanningEditionReference(
            edition_id=edition_id,
            organization_id=organization_id,
            accepts_private_planning_writes=True,
        ),
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_current_department_reference",
        lambda **_kwargs: CurrentDepartmentReference(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        ),
    )
    monkeypatch.setitem(
        programme_authorization.connection.settings_dict,
        "NAME",
        "test_unit",
    )
    return actor_id, organization_id, edition_id, department_id


def test_call_scope_requires_complete_department_decision(monkeypatch) -> None:
    """Retain exact scope facts without accepting an allow boolean."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
        authorizer=authorizer,
    )

    assert scope.department_id == department_id
    assert scope.accepts_private_planning_writes is True
    assert scope.decision.reason_code == "sealed_unit_authorizer"


def test_self_entry_scope_is_exact_and_field_bounded(monkeypatch) -> None:
    """Authorize discovery without inventing a proposal relationship."""
    actor_id, organization_id, edition_id, _department_id = _mount_references(
        monkeypatch
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=frozenset({"available_calls"}),
        authorizer=authorizer,
    )

    assert scope.actor_id == actor_id
    assert scope.edition_id == edition_id
    assert scope.decision.fields == frozenset({"available_calls"})


def test_self_entry_scope_rejects_non_entry_capability(monkeypatch) -> None:
    """Keep relationship-only proposal capabilities out of the entry seam."""
    actor_id, organization_id, edition_id, _department_id = _mount_references(
        monkeypatch
    )
    authorizer = _TrustedAuthorizer()

    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        authorize_programme_self_entry_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
            authorizer=authorizer,
        )
    assert authorizer.calls == []


def test_recovery_capability_never_enters_proposal_self_authority() -> None:
    """Keep exact-ID break-glass recovery out of retained proposal relationships."""
    assert (
        APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP
        not in APPLICATIONS_PROGRAMME_PROPOSAL_CAPABILITY_CODES
    )


def test_retry_scope_proves_no_resource_fields_or_relationship(monkeypatch) -> None:
    """Keep receipt lookup bounded to current identity and exact edition."""
    actor_id, organization_id, edition_id, _department_id = _mount_references(
        monkeypatch
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_retry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )

    assert scope.actor_id == actor_id
    assert scope.edition_id == edition_id
    assert scope.decision.reason_code == "sealed_unit_retry_authorizer"
    assert authorizer.calls == [("programme_retry", frozenset())]


def test_recovery_scope_is_lifecycle_neutral_and_content_free(monkeypatch) -> None:
    """Prove exact-Edition recovery without requiring open planning or a target read."""
    actor_id, organization_id, edition_id, _department_id = _mount_references(
        monkeypatch
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_private_planning_edition_reference",
        lambda **_kwargs: PrivatePlanningEditionReference(
            edition_id=edition_id,
            organization_id=organization_id,
            accepts_private_planning_writes=False,
        ),
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_recovery_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )

    assert scope.actor_id == actor_id
    assert scope.edition_id == edition_id
    assert scope.decision.reason_code == "sealed_unit_recovery_authorizer"
    assert authorizer.calls == [
        (APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP, None)
    ]


def test_recovery_retry_reproves_recovery_capability(monkeypatch) -> None:
    """Keep recovery replay separate from adoption-only ordinary replay."""
    actor_id, organization_id, edition_id, _department_id = _mount_references(
        monkeypatch
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_recovery_retry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )

    assert scope.decision.reason_code == "sealed_unit_recovery_retry_authorizer"
    assert authorizer.calls == [("programme_recovery_retry", frozenset())]


def test_default_retry_requires_target_adoption_not_proposal_self(
    monkeypatch,
) -> None:
    """Replay call-only receipts without inventing proposal-self authority."""
    monkeypatch.setattr(
        programme_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_target",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_programme_self",
        lambda *_args: False,
    )

    decision = ExactPolicyApplicationsProgrammeAuthorizer().authorize_retry(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
    )

    assert decision.allowed is True


def test_default_retry_denies_self_purpose_without_programme_target(
    monkeypatch,
) -> None:
    """Do not let a self-only purpose replay a foreign target receipt."""
    monkeypatch.setattr(
        programme_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_target",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_programme_self",
        lambda *_args: True,
    )

    decision = ExactPolicyApplicationsProgrammeAuthorizer().authorize_retry(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
    )

    assert decision.allowed is False


def test_default_recovery_is_exact_edition_and_profile_gated(monkeypatch) -> None:
    """Route recovery only through the fixed Edition capability after adoption."""
    principal_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        programme_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_target",
        lambda *_args: True,
    )

    def decide(**kwargs: object) -> PolicyDecision:
        captured.update(kwargs)
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_exact_edition_recovery",
        )

    monkeypatch.setattr(
        programme_authorization,
        "decide_verified_principal_exact_edition",
        decide,
    )

    decision = ExactPolicyApplicationsProgrammeAuthorizer().authorize_recovery(
        principal_id=principal_id,
        organization_id=organization_id,
        edition_id=edition_id,
        requested_fields=None,
    )

    assert decision.allowed is True
    assert captured == {
        "principal_id": principal_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "capability_code": (APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP),
        "requested_fields": None,
    }


def test_default_department_authority_needs_target_not_self_purpose(
    monkeypatch,
) -> None:
    """Keep call management independent from proposal-self adoption."""
    monkeypatch.setattr(
        programme_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_target",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_programme_self",
        lambda *_args: False,
    )
    expected = PolicyDecision(
        allowed=True,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="exact_department",
    )
    monkeypatch.setattr(
        programme_authorization,
        "decide_verified_principal_exact_department",
        lambda **_kwargs: expected,
    )

    decision = ExactPolicyApplicationsProgrammeAuthorizer().authorize_department(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
        capability_code="applications.manage_programme_calls",
        requested_fields=None,
    )

    assert decision == expected


def test_default_proposal_self_authority_needs_both_purpose_and_target(
    monkeypatch,
) -> None:
    """Deny relationship rights when only the generic target adapter is adopted."""
    monkeypatch.setattr(
        programme_authorization,
        "edition_adoption_profile_reference",
        lambda **_kwargs: SimpleNamespace(code="future", version=1),
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_target",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        programme_authorization,
        "profile_allows_application_programme_self",
        lambda *_args: False,
    )

    decision = ExactPolicyApplicationsProgrammeAuthorizer().authorize_self(
        principal_id=uuid4(),
        owner_account_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=frozenset({"proposal_summary"}),
    )

    assert decision.allowed is False


def test_invitee_view_is_field_limited_and_expiry_derived(monkeypatch) -> None:
    """Do not disclose answers to an invitee or trust a cached current flag."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    proposal_id = uuid4()
    monkeypatch.setattr(
        programme_authorization,
        "_proposal_row",
        lambda **_kwargs: {
            "id": proposal_id,
            "state": "draft",
            "submission_id": uuid4(),
            "submission__account_id": uuid4(),
            "submission__aggregate_version": 3,
            "call_id": uuid4(),
            "call__owner_department_id": department_id,
        },
    )
    monkeypatch.setattr(
        programme_authorization,
        "_collaborator_row",
        lambda **_kwargs: {
            "state": "invited",
            "invite_expires_at": datetime.now(tz=UTC) + timedelta(hours=1),
        },
    )
    authorizer = _TrustedAuthorizer()

    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=frozenset({"proposal_summary", "own_invitation"}),
        authorizer=authorizer,
    )
    assert scope.relationship == "invited"
    assert scope.decision.fields == frozenset({"proposal_summary", "own_invitation"})

    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        authorize_programme_proposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=frozenset({"answers"}),
            authorizer=authorizer,
        )


def test_injected_invitation_time_controls_authorization(monkeypatch) -> None:
    """Use the command/query instant instead of a second wall-clock read."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    proposal_id = uuid4()
    effective_now = datetime(2032, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(
        programme_authorization,
        "_proposal_row",
        lambda **_kwargs: {
            "id": proposal_id,
            "state": "draft",
            "submission_id": uuid4(),
            "submission__account_id": uuid4(),
            "submission__aggregate_version": 3,
            "call_id": uuid4(),
            "call__owner_department_id": department_id,
        },
    )
    monkeypatch.setattr(
        programme_authorization,
        "_collaborator_row",
        lambda **_kwargs: {
            "state": "invited",
            "invite_expires_at": effective_now + timedelta(seconds=1),
        },
    )
    monkeypatch.setattr(
        programme_authorization.timezone,
        "now",
        lambda: effective_now + timedelta(days=1),
    )

    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        authorizer=_TrustedAuthorizer(),
        now=effective_now,
    )

    assert scope.relationship == "invited"

    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        authorize_programme_proposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            authorizer=_TrustedAuthorizer(),
            now=effective_now + timedelta(seconds=1),
        )


def test_lead_cannot_use_invitation_response_capability(monkeypatch) -> None:
    """Keep invitation accept or decline strictly invitee-owned."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    proposal_id = uuid4()
    monkeypatch.setattr(
        programme_authorization,
        "_proposal_row",
        lambda **_kwargs: {
            "id": proposal_id,
            "state": "draft",
            "submission_id": uuid4(),
            "submission__account_id": actor_id,
            "submission__aggregate_version": 2,
            "call_id": uuid4(),
            "call__owner_department_id": department_id,
        },
    )
    authorizer = _TrustedAuthorizer()

    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        authorize_programme_proposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
            authorizer=authorizer,
        )
    assert authorizer.calls == []


def test_existing_proposal_self_scope_survives_owner_department_retirement(
    monkeypatch,
) -> None:
    """Keep retained subject rights independent of Workforce lifecycle."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    proposal_id = uuid4()
    monkeypatch.setattr(
        programme_authorization,
        "_proposal_row",
        lambda **_kwargs: {
            "id": proposal_id,
            "state": "draft",
            "submission_id": uuid4(),
            "submission__account_id": actor_id,
            "submission__aggregate_version": 2,
            "call_id": uuid4(),
            "call__owner_department_id": department_id,
        },
    )
    monkeypatch.setattr(
        programme_authorization,
        "resolve_current_department_reference",
        lambda **_kwargs: None,
    )

    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        authorizer=_TrustedAuthorizer(),
    )

    assert scope.relationship == "lead"
    assert scope.department_id == department_id


def test_accepted_collaborator_can_reach_edit_policy_for_sealed_response(
    monkeypatch,
) -> None:
    """Let commands add exact revision ownership before acknowledge or decline."""
    actor_id, organization_id, edition_id, department_id = _mount_references(
        monkeypatch
    )
    proposal_id = uuid4()
    monkeypatch.setattr(
        programme_authorization,
        "_proposal_row",
        lambda **_kwargs: {
            "id": proposal_id,
            "state": "sealed",
            "submission_id": uuid4(),
            "submission__account_id": uuid4(),
            "submission__aggregate_version": 8,
            "call_id": uuid4(),
            "call__owner_department_id": department_id,
        },
    )
    monkeypatch.setattr(
        programme_authorization,
        "_collaborator_row",
        lambda **_kwargs: {
            "state": "accepted",
            "invite_expires_at": datetime.now(tz=UTC) - timedelta(days=1),
        },
    )

    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=_TrustedAuthorizer(),
    )

    assert scope.relationship == "collaborator"
    assert scope.state == "sealed"
