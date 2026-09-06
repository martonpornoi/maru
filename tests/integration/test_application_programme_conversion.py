"""Real PostgreSQL conversion of independently reviewed synthetic proposals."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

import maru.applications.programme_conversion_authorization as conversion_authorization
import maru.applications.programme_conversion_commands as conversion_commands
import maru.programme.commands as programme_commands
from maru.applications.models import (
    ProgrammeAcceptedTransition,
    ProgrammeReviewAction,
    ProgrammeReviewDecision,
    ProgrammeReviewReceipt,
)
from maru.applications.models import (
    ProgrammeCommandReceipt as ApplicationProgrammeReceipt,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
    retire_programme_call,
)
from maru.applications.programme_conversion_commands import (
    convert_accepted_programme_proposal,
)
from maru.applications.programme_conversion_inputs import ProgrammeConversionInput
from maru.applications.programme_conversion_sources import (
    ProgrammeConversionConflictError,
    ProgrammeConversionUnavailableError,
)
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import ProgrammeVersionConflictError
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeEditionControl,
    ProgrammeItem,
    ProgrammeItemSourceBinding,
    ProgrammePublicRendition,
    ProgrammeReadinessEvidence,
    ProgrammeReadinessRequirement,
    ProgrammeReadinessRequirementRevision,
    ProgrammeWorkingRevision,
)
from tests.factories import EventEditionFactory
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
from tests.support.programme_review import assign_and_score, create_review_world

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


@pytest.fixture
def accepted(monkeypatch):
    """Use real review commands; substitute only unavailable future profile pins."""
    monkeypatch.setattr(
        conversion_authorization, "profile_allows_adapter", lambda *_: True
    )
    world = create_review_world()
    assignment_id = assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id)
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.MODERATED,
            target_id=world.case_id,
        ),
    )
    result = world.command(
        world.decider.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.DECIDED,
            target_id=world.case_id,
            outcome="accepted",
            text="Accepted for private planning, not publication.",
        ),
    )
    decision = ProgrammeReviewDecision.objects.get(id=result.target_id)
    intent = ProgrammeConversionInput(
        decision_id=decision.id,
        revision_id=decision.revision_id,
        expected_review_version=world.version,
        expected_programme_version=0,
        internal_title="Deliberately supplied private title",
        working_summary="Private planning notes",
    )
    kwargs = {
        "actor_id": world.call.manager.id,
        "organization_id": world.call.edition.organization_id,
        "edition_id": world.call.edition.id,
        "department_id": world.call.department_id,
        "command": intent,
        "retry_key": uuid4(),
        "reason": "Accountable conversion.",
        "correlation_id": uuid4(),
        "source_channel": "test",
        "authorizer": _AUTHORIZER,
        "programme_authorizer": _TrustedProgrammeAuthorizer(),
    }
    return world, assignment_id, kwargs


def test_conversion_creates_one_private_source_bound_unready_item(accepted):
    _, _, kwargs = accepted
    excluded_models = tuple(
        model
        for label in (
            "identity",
            "participation",
            "registration",
            "workforce",
            "venues",
            "logistics",
        )
        for model in apps.get_app_config(label).get_models()
    )
    before = tuple(model.objects.count() for model in excluded_models)
    result = convert_accepted_programme_proposal(**kwargs)
    assert tuple(model.objects.count() for model in excluded_models) == before
    source = ProgrammeAcceptedTransition.objects.get(id=result.transition_id)
    item = ProgrammeItem.objects.get(id=result.programme_item_id)
    binding = ProgrammeItemSourceBinding.objects.get(item=item)
    assert source.revision_id == kwargs["command"].revision_id
    assert source.decision_id == kwargs["command"].decision_id
    assert source.programme_item_id == item.id
    assert (item.kind, item.provenance_kind, item.aggregate_version) == (
        "accepted_proposal",
        "applications_accepted",
        1,
    )
    assert (binding.source_object_id, binding.source_version) == (source.id, 1)
    assert (
        ProgrammeWorkingRevision.objects.get(item=item).internal_title
        == kwargs["command"].internal_title
    )
    assert (
        ProgrammeReadinessRequirement.objects.filter(
            item=item, disposition="required"
        ).count()
        == 7
    )
    assert (
        ProgrammeReadinessRequirementRevision.objects.filter(
            item=item, sequence=1, item_version=1
        ).count()
        == 7
    )
    assert not ProgrammeReadinessEvidence.objects.exists()
    assert not ProgrammePublicRendition.objects.exists()
    assert ProgrammeCommandReceipt.objects.get(item=item).operation == "item_accept"
    assert ProgrammeEditionControl.objects.get().aggregate_version == 1
    assert not result.replayed
    assert source.audit_event.operation == "applications.programme_conversion.completed"
    assert source.domain_event.payload == {
        "transition_id": str(source.id),
        "programme_item_id": str(item.id),
    }
    assert OutboxMessage.objects.filter(event=source.domain_event).exists()


def test_same_intent_retries_are_minimal_and_duplicate_source_is_rejected(accepted):
    _, _, kwargs = accepted
    result = convert_accepted_programme_proposal(**kwargs)
    audit_count, event_count = AuditEvent.objects.count(), DomainEvent.objects.count()
    replay = convert_accepted_programme_proposal(
        **{**kwargs, "correlation_id": uuid4()}
    )
    assert replay == replace(result, replayed=True)
    assert (AuditEvent.objects.count(), DomainEvent.objects.count()) == (
        audit_count,
        event_count,
    )
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        convert_accepted_programme_proposal(**{**kwargs, "reason": "Different intent"})
    with pytest.raises(ProgrammeConversionConflictError):
        convert_accepted_programme_proposal(**{**kwargs, "retry_key": uuid4()})
    assert (
        ProgrammeAcceptedTransition.objects.count()
        == ProgrammeItem.objects.count()
        == 1
    )


def test_late_recusal_blocks_fresh_conversion_but_preserves_completed_retry(accepted):
    world, assignment, kwargs = accepted
    result = convert_accepted_programme_proposal(**kwargs)
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.REVIEWER_RECUSED,
            target_id=world.case_id,
            reference_id=assignment,
        ),
    )
    assert convert_accepted_programme_proposal(**kwargs) == replace(
        result, replayed=True
    )
    with pytest.raises(ProgrammeConversionConflictError):
        convert_accepted_programme_proposal(
            **{
                **kwargs,
                "retry_key": uuid4(),
                "command": replace(
                    kwargs["command"], expected_review_version=world.version
                ),
            }
        )


def test_reciprocal_target_failure_rolls_back_all_success(accepted, monkeypatch):
    _, _, kwargs = accepted
    original = conversion_commands.create_accepted_programme_item
    count = DomainEvent.objects.count()

    def fail_after_target(**values):
        original(**values)
        raise RuntimeError("Synthetic target failure")

    monkeypatch.setattr(
        conversion_commands, "create_accepted_programme_item", fail_after_target
    )
    with pytest.raises(RuntimeError, match="Synthetic target failure"):
        convert_accepted_programme_proposal(**kwargs)
    assert not ProgrammeAcceptedTransition.objects.exists()
    assert not ProgrammeItem.objects.exists()
    assert not ProgrammeReadinessRequirement.objects.exists()
    assert not ProgrammeEditionControl.objects.exists()
    assert DomainEvent.objects.count() == count
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme_conversion.failed"
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    "missing",
    [
        "applications.target.programme_item@1",
        "programme.accepted-application-source@1",
    ],
)
def test_each_exact_adapter_is_independently_required(accepted, monkeypatch, missing):
    _, _, kwargs = accepted
    monkeypatch.setattr(
        conversion_authorization,
        "profile_allows_adapter",
        lambda _code, _version, adapter: adapter != missing,
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        convert_accepted_programme_proposal(**kwargs)
    assert not ProgrammeAcceptedTransition.objects.exists()


def test_conversion_commits_reciprocal_foreign_keys_together(accepted):
    _, _, kwargs = accepted
    with transaction.atomic():
        result = convert_accepted_programme_proposal(**kwargs)
    assert (
        ProgrammeItemSourceBinding.objects.get(
            item_id=result.programme_item_id
        ).source_object_id
        == result.transition_id
    )


@pytest.mark.parametrize("owner", ["applications", "programme"])
def test_independent_authority_denies_before_private_source_lookup(
    accepted, monkeypatch, owner
):
    _, _, kwargs = accepted
    denial = PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="synthetic_denial",
    )
    if owner == "applications":
        monkeypatch.setattr(
            type(_AUTHORIZER), "authorize_department", lambda _self, **_: denial
        )
    else:
        monkeypatch.setattr(
            kwargs["programme_authorizer"], "authorize", lambda **_: denial
        )
    with (
        CaptureQueriesContext(connection) as queries,
        pytest.raises(
            (
                ApplicationsProgrammeAuthorizationDeniedError,
                ProgrammeAuthorizationDeniedError,
            )
        ),
    ):
        convert_accepted_programme_proposal(**kwargs)
    assert not any(
        'FROM "applications_programmereviewdecision"' in query["sql"]
        for query in queries
    )
    assert not ProgrammeItem.objects.exists()
    failure = AuditEvent.objects.get(
        operation="applications.programme_conversion.failed"
    )
    assert failure.target_id is None


@pytest.mark.parametrize(
    "cursor", ["expected_review_version", "expected_programme_version"]
)
def test_stale_source_or_target_cursor_cannot_leave_half_conversion(accepted, cursor):
    _, _, kwargs = accepted
    with pytest.raises(
        (ProgrammeConversionConflictError, ProgrammeVersionConflictError)
    ):
        convert_accepted_programme_proposal(
            **{
                **kwargs,
                "command": replace(kwargs["command"], **{cursor: 99}),
            }
        )
    assert not ProgrammeAcceptedTransition.objects.exists()
    assert not ProgrammeItem.objects.exists()


@pytest.mark.parametrize("other_organization", [True, False])
def test_exact_source_ids_are_unavailable_in_another_edition(
    accepted, other_organization
):
    world, _, kwargs = accepted
    other = EventEditionFactory(
        **(
            {}
            if other_organization
            else {
                "organization": world.call.edition.organization,
                "series": world.call.edition.series,
            }
        )
    )
    # Scope proof denies the old Department before the foreign source is loaded.
    with (
        CaptureQueriesContext(connection) as queries,
        pytest.raises(ApplicationsProgrammeAuthorizationDeniedError),
    ):
        convert_accepted_programme_proposal(
            **{
                **kwargs,
                "organization_id": other.organization_id,
                "edition_id": other.id,
            }
        )
    assert not any(
        'FROM "applications_programmereviewdecision"' in query["sql"]
        for query in queries
    )
    assert not ProgrammeItem.objects.exists()


def test_wrong_exact_decision_cannot_convert_the_valid_revision(accepted):
    _, _, kwargs = accepted
    with pytest.raises(ProgrammeConversionUnavailableError):
        convert_accepted_programme_proposal(
            **{
                **kwargs,
                "command": replace(kwargs["command"], decision_id=uuid4()),
            }
        )
    assert not ProgrammeAcceptedTransition.objects.exists()


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE public.applications_programmeacceptedtransition SET reason = 'rewrite'",
        "DELETE FROM public.applications_programmeacceptedtransition",
    ],
)
def test_conversion_evidence_is_immutable_even_for_the_migration_owner(
    accepted, operation
):
    _, _, kwargs = accepted
    result = convert_accepted_programme_proposal(**kwargs)
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        programme_application_database_writer(),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(operation)
    assert (
        ProgrammeAcceptedTransition.objects.get(id=result.transition_id).reason
        == kwargs["reason"]
    )


def test_missing_programme_success_evidence_rolls_back_both_owners(
    accepted, monkeypatch
):
    _, _, kwargs = accepted
    original = programme_commands._record_success

    def no_programme_event(**values):
        # Preserve creation receipts but simulate an omitted target-side outbox/event.
        with monkeypatch.context() as patch:
            patch.setattr(
                programme_commands,
                "publish_domain_event",
                lambda *_args, **_kwargs: None,
            )
            return original(**values)

    monkeypatch.setattr(programme_commands, "_record_success", no_programme_event)
    with pytest.raises(IntegrityError, match="both owners"):
        convert_accepted_programme_proposal(**kwargs)
    assert not ProgrammeAcceptedTransition.objects.exists()
    assert not ProgrammeItem.objects.exists()


@pytest.mark.parametrize(
    "receipt_model", [ApplicationProgrammeReceipt, ProgrammeReviewReceipt]
)
def test_conversion_and_existing_programme_retry_namespaces_conflict_both_ways(
    accepted, receipt_model
):
    world, _, kwargs = accepted
    prior = receipt_model.objects.filter(
        actor_id=kwargs["actor_id"], edition_id=kwargs["edition_id"]
    ).first()
    assert prior is not None
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        convert_accepted_programme_proposal(**{**kwargs, "retry_key": prior.retry_key})
    result = convert_accepted_programme_proposal(**kwargs)

    def competing_command():
        if receipt_model is ProgrammeReviewReceipt:
            world.command(
                kwargs["actor_id"],
                ProgrammeReviewCommandInput(
                    action=ProgrammeReviewAction.MODERATED,
                    target_id=world.case_id,
                ),
                retry_key=kwargs["retry_key"],
            )
        else:
            retire_programme_call(
                actor_id=kwargs["actor_id"],
                organization_id=kwargs["organization_id"],
                edition_id=kwargs["edition_id"],
                call_id=world.call.call_id,
                owner_department_id=world.call.department_id,
                expected_version=2,
                reason="Competing command with a consumed retry identity.",
                retry_key=kwargs["retry_key"],
                correlation_id=uuid4(),
                source_channel="test",
                authorizer=_AUTHORIZER,
            )

    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        competing_command()
    assert ProgrammeAcceptedTransition.objects.get().id == result.transition_id
