"""Frozen self projections use real query construction with synthetic row reads."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db.models.query import QuerySet

from maru.applications import models
from maru.applications import programme_personal_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from tests.unit import test_application_programme_personal_queries as personal_fixtures

context = personal_fixtures.context


@pytest.fixture
def frozen(context, monkeypatch):
    scope_ids = {"organization_id": UUID(int=2), "edition_id": UUID(int=3)}
    context.proposal.submission.definition_id = context.available.summary.definition_id
    context.proposal.state = context.scope.state = "sealed"
    context.proposal.sealed_revision_id = UUID(int=90)
    call_fields = Mock()
    call_fields.order_by.return_value = context.available.contributor_fields
    context.proposal.call.contributor_fields = call_fields
    selection = models.ProgrammeProposalSelectionRevision(
        id=UUID(int=91),
        **scope_ids,
        proposal_id=UUID(int=40),
        track=models.ProgrammeCallTrack(
            id=UUID(int=92), code="culture", label="Frozen track"
        ),
        format=models.ProgrammeCallFormat(
            id=UUID(int=93), code="talk", label="Frozen format"
        ),
        requested_duration_minutes=30,
        resulting_version=2,
    )
    revision = models.ProgrammeProposalRevision(
        id=UUID(int=90),
        **scope_ids,
        proposal_id=UUID(int=40),
        sequence=1,
        definition_version=1,
        selection_revision=selection,
        source_version=6,
        resulting_version=7,
        digest="a" * 64,
        sealed_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    profile = models.ProgrammeProposalContributorProfileRevision(
        id=UUID(int=94),
        **scope_ids,
        proposal_id=UUID(int=40),
        account_id=UUID(int=1),
        public_name="My frozen name",
        biography="My frozen biography",
        pronouns="",
        website="",
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code="programme.consent.v1",
        resulting_version=3,
    )
    contributor = models.ProgrammeProposalRevisionContributor(
        id=UUID(int=95),
        **scope_ids,
        revision=revision,
        account_id=UUID(int=1),
        role="lead",
        profile_revision=profile,
    )
    question = models.ApplicationQuestion(
        id=UUID(int=96),
        definition_id=context.available.summary.definition_id,
        key="title",
        field_type="short_text",
        label="Frozen title",
        options=[],
        staff_visible=False,
        staff_writable=False,
        reviewer_visible=False,
        public_after_approval=False,
        api_projection=False,
    )
    answer = models.ApplicationAnswerRevision(
        id=UUID(int=97),
        submission_id=UUID(int=41),
        question=question,
        value="Frozen answer, not a mutable latest answer",
        actor_id=UUID(int=1),
        resulting_version=4,
    )
    frozen_answer = models.ProgrammeProposalRevisionAnswer(
        id=UUID(int=98),
        **scope_ids,
        revision=revision,
        question=question,
        answer_revision=answer,
        question_key="title",
        question_type="short_text",
    )
    rows = {
        models.ProgrammeProposalRevision: [revision],
        models.ProgrammeProposalRevisionContributor: [contributor],
        models.ProgrammeProposalRevisionAnswer: [frozen_answer],
    }
    statements = []

    def fetch(query):
        # Compiling SQL validates actual model field/relationship paths. Supplying
        # rows here is not native SQL execution or proof of predicate behavior.
        sql, params = query.query.sql_with_params()
        statements.append((query.model, sql, params))
        values = rows[query.model]
        if query._fields == ("id",):
            values = [row.id for row in values]
        query._result_cache = values

    monkeypatch.setattr(QuerySet, "_fetch_all", fetch)
    return SimpleNamespace(
        context=context,
        rows=rows,
        revision=revision,
        contributor=contributor,
        profile=profile,
        answer=frozen_answer,
        statements=statements,
    )


def read(**overrides):
    values = {
        "actor_id": UUID(int=1),
        "organization_id": UUID(int=2),
        "edition_id": UUID(int=3),
        "proposal_id": UUID(int=40),
        "revision_id": UUID(int=90),
        "correlation_id": UUID(int=5),
        "source_channel": "programme-proposal-workspace",
    }
    return queries.get_self_programme_frozen_revision.__wrapped__(
        **(values | overrides)
    )


def test_exact_frozen_content_and_own_profile_are_scoped_before_values(frozen):
    result = read()
    assert result.revision.revision_id == frozen.revision.id
    assert result.revision.digest == "a" * 64
    assert result.selection.track_label == "Frozen track"
    assert result.answers[0].value == "Frozen answer, not a mutable latest answer"
    assert result.own_profile.profile_revision_id == UUID(int=94)
    assert dict(result.own_profile.values)["public_name"] == "My frozen name"
    assert result.own_contributor_id == UUID(int=95)
    frozen.context.audit.assert_called_once()
    assert frozen.context.audit.call_args.kwargs["target_id"] == UUID(int=90)
    for model, sql, params in frozen.statements:
        assert '"organization_id"' in sql
        assert '"edition_id"' in sql
        if model is models.ProgrammeProposalRevisionContributor:
            assert sql.count('"account_id" =') >= 2
            assert UUID(int=1) in params
            assert '"profile_revision_id"' in sql
        if model is models.ProgrammeProposalRevisionAnswer and '"value"' in sql:
            assert '"applicant_visible"' in sql
            assert '"staff_writable"' in sql
            assert '"public_after_approval"' in sql
            assert '"api_projection"' in sql
            assert UUID(int=41) in params


def test_invitee_refused_before_any_source_read(frozen):
    frozen.context.scope.relationship = "invited"
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    frozen.context.source_query.assert_not_called()
    assert frozen.statements == []


def test_missing_own_inclusion_does_not_load_frozen_answers(frozen):
    frozen.rows[models.ProgrammeProposalRevisionContributor] = []
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    assert not any(
        model is models.ProgrammeProposalRevisionAnswer
        for model, _, _ in frozen.statements
    )
    frozen.context.audit.assert_not_called()


def test_current_seal_removed_during_projection_discards_result(frozen):
    frozen.context.query.first.side_effect = [frozen.context.proposal, None]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    frozen.context.audit.assert_not_called()


def test_actor_cannot_review_through_changed_relationship(frozen):
    current = SimpleNamespace(
        **(vars(frozen.context.scope) | {"relationship": "collaborator"})
    )
    frozen.context.authorize.side_effect = [frozen.context.scope, current]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    frozen.context.audit.assert_not_called()


def test_blank_frozen_answer_is_explicit_not_a_latest_lookup(frozen):
    frozen.answer.answer_revision = None
    result = read()
    assert result.answers[0].value is None
    assert result.answers[0].answer_revision_id is None


def test_frozen_answer_inventory_overflow_refuses_partial_content(frozen):
    frozen.rows[models.ProgrammeProposalRevisionAnswer] *= 501
    with pytest.raises(
        queries.projections.ApplicationsProgrammeProjectionOverflowError
    ):
        read()
    frozen.context.audit.assert_not_called()


def test_declared_hidden_own_field_is_not_projected(frozen):
    frozen.context.proposal.call.contributor_fields.order_by.return_value = [
        SimpleNamespace(
            field_code="public_name",
            lead_requirement="hidden",
            collaborator_requirement="hidden",
        ),
    ]
    assert read().own_profile.values == ()
