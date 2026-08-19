"""Branch contracts for Applications command authorization and validation helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.applications import commands
from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationIdempotencyConflict,
    ApplicationVersionConflict,
)
from maru.applications.models import (
    ApplicationClassification,
    ReviewerBasis,
)
from maru.identity.models import Account


def _actor() -> Account:
    return Account(id=uuid4(), email="application-command@example.invalid")


def _receipt(*, digest: str = "digest") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        definition_id=uuid4(),
        submission_id=uuid4(),
        target_id=uuid4(),
        resulting_version=3,
        request_digest=digest,
    )


def _first(value: object | None) -> MagicMock:
    queryset = MagicMock()
    queryset.filter.return_value.first.return_value = value
    queryset.select_for_update.return_value.filter.return_value.first.return_value = (
        value
    )
    queryset.select_related.return_value.filter.return_value.first.return_value = value
    locked = queryset.select_for_update.return_value.select_related.return_value
    locked.filter.return_value.first.return_value = value
    return queryset


def test_replay_absence_conflict_and_exact_result() -> None:
    actor = _actor()
    values = {
        "actor": actor,
        "edition_id": uuid4(),
        "retry_key": uuid4(),
        "request_digest": "digest",
    }
    with patch.object(commands.ApplicationCommandReceipt, "objects", _first(None)):
        assert commands._replay(**values) is None
    with (
        patch.object(
            commands.ApplicationCommandReceipt,
            "objects",
            _first(_receipt(digest="different")),
        ),
        pytest.raises(ApplicationIdempotencyConflict),
    ):
        commands._replay(**values)
    with patch.object(
        commands.ApplicationCommandReceipt, "objects", _first(_receipt())
    ):
        assert commands._replay(**values).replayed is True


def test_authorization_targets_deny_missing_actor_edition_target_or_grant() -> None:
    actor = _actor()
    organization_id, edition_id = uuid4(), uuid4()
    edition = SimpleNamespace(id=edition_id)
    for helper, resolver_name in (
        (commands._edition_target, "resolve_edition_target"),
        (commands._self_target, "resolve_self_target"),
    ):
        for current_actor, current_edition, target, allowed in (
            (None, edition, object(), True),
            (actor, None, object(), True),
            (actor, edition, None, True),
            (actor, edition, object(), False),
        ):
            with (
                patch.object(commands.Account, "objects", _first(current_actor)),
                patch.object(commands.EventEdition, "objects", _first(current_edition)),
                patch.object(commands, resolver_name, return_value=target),
                patch.object(
                    commands, "decide", return_value=SimpleNamespace(allowed=allowed)
                ),
                pytest.raises(ApplicationAuthorizationDenied),
            ):
                helper(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    capability_code="applications.test",
                )


def test_evidence_and_locked_aggregate_fail_closed() -> None:
    actor = _actor()
    receipt = _receipt()
    with (
        patch.object(
            commands.ApplicationCommandReceipt.objects, "create", return_value=receipt
        ),
        pytest.raises(RuntimeError, match="requires one aggregate"),
    ):
        commands._record_evidence(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            action="test",
            capability_code="applications.test",
            request_digest="digest",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            resulting_version=1,
        )

    with (
        patch.object(commands.ApplicationDefinition, "objects", _first(None)),
        pytest.raises(commands.ApplicationUnavailable),
    ):
        commands._locked_definition(
            organization_id=uuid4(),
            edition_id=uuid4(),
            definition_id=uuid4(),
        )
    with pytest.raises(ApplicationVersionConflict):
        commands._check_version(2, 1)


def _relation(*, exists: bool = True, values: tuple[object, ...] = ()) -> MagicMock:
    relation = MagicMock()
    relation.exists.return_value = exists
    relation.select_related.return_value.order_by.return_value = values
    relation.values_list.return_value = values
    return relation


def _question(
    key: str = "motivation",
    *,
    classification: str = ApplicationClassification.PERSONAL,
    required: bool = False,
    applicant_visible: bool = True,
    retention_policy_code: str = "retention.v1",
    condition: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        classification=classification,
        required=required,
        applicant_visible=applicant_visible,
        retention_policy_code=retention_policy_code,
        condition=condition or {},
    )


def _definition(
    questions: tuple[object, ...],
    *,
    owner: bool = True,
    reviewer: bool = True,
    sections: bool = True,
    classification: str = ApplicationClassification.PERSONAL,
    sensitive: bool = False,
    retention_policy_code: str = "retention.v1",
    audience_policy_code: str = "audience.v1",
) -> SimpleNamespace:
    return SimpleNamespace(
        questions=_relation(values=questions),
        owner_department_links=_relation(exists=owner),
        reviewer_roles=_relation(exists=reviewer),
        reviewer_people=_relation(exists=False),
        sections=_relation(exists=sections),
        classification=classification,
        is_sensitive=sensitive,
        retention_policy_code=retention_policy_code,
        audience_policy_code=audience_policy_code,
    )


@pytest.mark.parametrize(
    "definition",
    [
        _definition((_question(),), owner=False),
        _definition((_question(),), reviewer=False),
        _definition((), sections=False),
        _definition(
            (_question(),),
            sensitive=True,
            retention_policy_code="",
            audience_policy_code="",
        ),
        _definition(
            (_question(classification=ApplicationClassification.RESTRICTED),),
        ),
        _definition((_question(required=True, applicant_visible=False),)),
        _definition(
            (
                _question(
                    classification=ApplicationClassification.RESTRICTED,
                    retention_policy_code="",
                ),
            ),
            classification=ApplicationClassification.RESTRICTED,
            retention_policy_code="",
        ),
        _definition((_question(condition={"question_key": "missing"}),)),
        _definition((_question(condition={"question_key": "motivation"}),)),
        _definition(
            (
                _question("first", condition={"question_key": "second"}),
                _question("second", condition={"question_key": "first"}),
            )
        ),
    ],
)
def test_activation_rejects_incomplete_or_unsafe_definitions(
    definition: SimpleNamespace,
) -> None:
    with pytest.raises(ValidationError):
        commands._validate_definition_activation(definition)


def test_activation_accepts_acyclic_conditions() -> None:
    definition = _definition(
        (
            _question("country"),
            _question("city", condition={"question_key": "country"}),
        )
    )
    commands._validate_definition_activation(definition)


def test_latest_answers_keeps_only_the_newest_revision() -> None:
    submission = SimpleNamespace(answer_revisions=MagicMock())
    submission.answer_revisions.order_by.return_value = (
        SimpleNamespace(question_key="motivation", value="new"),
        SimpleNamespace(question_key="motivation", value="old"),
        SimpleNamespace(question_key="skills", value=["first-aid"]),
    )
    assert commands._latest_answers(submission) == {
        "motivation": "new",
        "skills": ["first-aid"],
    }


def test_reviewer_basis_supports_named_and_current_role_assignments_only() -> None:
    actor = _actor()
    evaluated_at = timezone.now()
    definition = SimpleNamespace(
        reviewer_people=MagicMock(),
        reviewer_roles=MagicMock(),
        owner_department_links=MagicMock(),
        edition_id=uuid4(),
        organization_id=uuid4(),
    )
    definition.reviewer_people.filter.return_value.exists.return_value = True
    assert commands._reviewer_basis(
        actor=actor,
        definition=definition,
        evaluated_at=evaluated_at,
    ) == (ReviewerBasis.NAMED_PERSON, None)

    definition.reviewer_people.filter.return_value.exists.return_value = False
    definition.reviewer_roles.values_list.return_value = ()
    with pytest.raises(ApplicationAuthorizationDenied):
        commands._reviewer_basis(
            actor=actor,
            definition=definition,
            evaluated_at=evaluated_at,
        )

    role = SimpleNamespace(id=uuid4(), role_bundle=SimpleNamespace(id=uuid4()))
    definition.reviewer_roles.values_list.return_value = (role.role_bundle.id,)
    definition.owner_department_links.values_list.return_value = (uuid4(),)
    assignments = MagicMock()
    assignments.filter.return_value.order_by.return_value = (role,)
    with (
        patch.object(commands.RoleAssignment, "objects", assignments),
        patch.object(commands, "current_role_assignment_ids", return_value={role.id}),
    ):
        basis, bundle = commands._reviewer_basis(
            actor=actor,
            definition=definition,
            evaluated_at=evaluated_at,
        )
    assert basis == ReviewerBasis.IMMUTABLE_ROLE
    assert bundle is role.role_bundle

    with (
        patch.object(commands.RoleAssignment, "objects", assignments),
        patch.object(commands, "current_role_assignment_ids", return_value=set()),
        pytest.raises(ApplicationAuthorizationDenied),
    ):
        commands._reviewer_basis(
            actor=actor,
            definition=definition,
            evaluated_at=evaluated_at,
        )
