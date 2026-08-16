from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationUnavailable,
    activate_definition,
    append_answer_revision,
    configure_definition,
    create_definition_from_starter,
    record_review_decision,
    start_submission,
    submit_application,
)
from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationReviewDecision,
    ApplicationState,
    ApplicationTargetRecord,
    ReviewerBasis,
)
from maru.applications.queries import (
    authorize_application_review_submission_api_scope,
    authorize_application_self_submission_api_scope,
    my_submissions,
    review_queue,
)
from maru.applications.serializers import latest_answers
from maru.audit.models import AuditEvent
from maru.authorization.models import RoleBundle
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import Department
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _DraftWorld:
    edition: EventEdition
    manager: Account
    reviewer: Account
    department: Department
    definition: ApplicationDefinition
    reviewer_role: RoleBundle | None
    opens_at: datetime
    closes_at: datetime
    applicant_edit_until: datetime
    create_retry_key: UUID


def _configured_draft(
    starter_code: str,
    *,
    named_reviewer: bool = False,
    audience_policy_code: str | None = None,
    retention_policy_code: str | None = None,
    age_policy_code: str | None = None,
) -> _DraftWorld:
    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Application Manager")
    reviewer = AccountFactory(display_name="Assigned Reviewer")
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=manager,
        capability_code="applications.manage_definitions",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    department = create_department_for_test(
        edition=edition,
        name="Programme Applications",
        expected_code="programme-applications",
    )
    role: RoleBundle | None = None
    if not named_reviewer:
        role = RoleBundleFactory(
            organization=edition.organization,
            code="application-reviewer",
            name="Application Reviewer",
            capability_codes=["applications.review"],
        )
        RoleAssignmentFactory(
            organization=edition.organization,
            edition=edition,
            principal=reviewer,
            role_bundle=role,
            effective_from=timezone.now() - timedelta(minutes=1),
        )

    now = timezone.now()
    opens_at = now - timedelta(days=1)
    closes_at = now + timedelta(days=10)
    applicant_edit_until = now + timedelta(days=9)
    create_retry_key = uuid4()
    created = create_definition_from_starter(
        actor=manager,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        starter_code=starter_code,
        opens_at=opens_at,
        closes_at=closes_at,
        applicant_edit_until=applicant_edit_until,
        retry_key=create_retry_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    definition = ApplicationDefinition.objects.get(id=created.definition_id)
    configure_definition(
        actor=manager,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_id=definition.id,
        expected_version=definition.aggregate_version,
        name=definition.name,
        description=definition.description,
        purpose=definition.purpose,
        classification=definition.classification,
        eligibility_kind=definition.eligibility_kind,
        maximum_submissions=definition.max_submissions_per_person,
        opens_at=opens_at,
        closes_at=closes_at,
        applicant_edit_until=applicant_edit_until,
        minimum_age=definition.minimum_age,
        audience_policy_code=(
            definition.audience_policy_code
            if audience_policy_code is None
            else audience_policy_code
        ),
        retention_policy_code=(
            definition.retention_policy_code
            if retention_policy_code is None
            else retention_policy_code
        ),
        age_policy_code=(
            definition.age_policy_code if age_policy_code is None else age_policy_code
        ),
        owner_department_ids=(department.id,),
        reviewer_role_bundle_ids=(() if role is None else (role.id,)),
        reviewer_account_ids=((reviewer.id,) if named_reviewer else ()),
        reason="Assign accountable edition owners and reviewers.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    definition.refresh_from_db()
    return _DraftWorld(
        edition=edition,
        manager=manager,
        reviewer=reviewer,
        department=department,
        definition=definition,
        reviewer_role=role,
        opens_at=opens_at,
        closes_at=closes_at,
        applicant_edit_until=applicant_edit_until,
        create_retry_key=create_retry_key,
    )


def _activate(world: _DraftWorld) -> None:
    activate_definition(
        actor=world.manager,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        definition_id=world.definition.id,
        expected_version=world.definition.aggregate_version,
        reason="Open this reviewed edition workflow.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    world.definition.refresh_from_db()


def test_api_preflight_requires_exact_applicant_and_reviewer_assignment() -> None:
    world = _configured_draft("dj-application")
    _activate(world)
    applicant = AccountFactory(display_name="Submission owner")
    foreign_applicant = AccountFactory(display_name="Different applicant")
    started = start_submission(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        definition_id=world.definition.id,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert started.submission_id is not None

    authorize_application_self_submission_api_scope(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=started.submission_id,
    )
    with pytest.raises(ApplicationAuthorizationDenied):
        authorize_application_self_submission_api_scope(
            actor=foreign_applicant,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            submission_id=started.submission_id,
        )

    authorize_application_review_submission_api_scope(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=started.submission_id,
    )
    unassigned_reviewer = AccountFactory(display_name="Unassigned reviewer")
    CapabilityGrantFactory(
        organization=world.edition.organization,
        edition=world.edition,
        principal=unassigned_reviewer,
        capability_code="applications.review",
        effective_from=timezone.now() - timedelta(minutes=1),
    )
    with pytest.raises(ApplicationAuthorizationDenied):
        authorize_application_review_submission_api_scope(
            actor=unassigned_reviewer,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            submission_id=started.submission_id,
        )


def test_sensitive_adult_definition_rejects_generic_policy_before_activation() -> None:
    world = _configured_draft(
        "adult-fursuit-striptease",
        named_reviewer=True,
        audience_policy_code="generic",
        retention_policy_code="standard",
        age_policy_code="default",
    )

    with pytest.raises(ValidationError):
        _activate(world)

    world.definition.refresh_from_db()
    assert world.definition.status == ApplicationDefinitionStatus.DRAFT
    assert world.definition.aggregate_version == 2

    configure_definition(
        actor=world.manager,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        definition_id=world.definition.id,
        expected_version=world.definition.aggregate_version,
        name=world.definition.name,
        description=world.definition.description,
        purpose=world.definition.purpose,
        classification=world.definition.classification,
        eligibility_kind=world.definition.eligibility_kind,
        maximum_submissions=world.definition.max_submissions_per_person,
        opens_at=world.opens_at,
        closes_at=world.closes_at,
        applicant_edit_until=world.applicant_edit_until,
        minimum_age=18,
        audience_policy_code="applications.adult.assigned-reviewers.v1",
        retention_policy_code="applications.adult.case-close-90-days.v1",
        age_policy_code="applications.adult.age-attestation.v1",
        owner_department_ids=(world.department.id,),
        reviewer_role_bundle_ids=(),
        reviewer_account_ids=(world.reviewer.id,),
        reason="Replace placeholders with edition-approved policy versions.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    world.definition.refresh_from_db()
    _activate(world)

    assert world.definition.status == ApplicationDefinitionStatus.ACTIVE
    assert world.definition.reviewer_people.get().account_id == world.reviewer.id


def test_versioned_application_submission_review_and_typed_transition() -> None:  # noqa: PLR0915
    world = _configured_draft("dj-application")
    assert world.reviewer_role is not None
    hidden_from_reviewer = world.definition.questions.get(key="technical-needs")
    hidden_from_reviewer.reviewer_visible = False
    hidden_from_reviewer.save(update_fields=("reviewer_visible", "updated_at"))
    _activate(world)

    replay = create_definition_from_starter(
        actor=world.manager,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        starter_code="dj-application",
        opens_at=world.opens_at,
        closes_at=world.closes_at,
        applicant_edit_until=world.applicant_edit_until,
        retry_key=world.create_retry_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert replay.replayed is True
    assert replay.definition_id == world.definition.id
    assert (
        ApplicationDefinition.objects.filter(
            edition=world.edition, code="dj-application"
        ).count()
        == 1
    )

    applicant = AccountFactory(display_name="Night Fox")
    started = start_submission(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        definition_id=world.definition.id,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    submission_id = started.submission_id
    assert submission_id is not None
    version = started.resulting_version
    answers: dict[str, object] = {
        "artist-name": "Night Fox",
        "genre": "House",
        "set-length": 60,
        "technical-needs": "Two media players and a mixer.",
    }
    first_retry_key = uuid4()
    first_result = None
    for key, value in answers.items():
        question = world.definition.questions.get(key=key)
        retry_key = first_retry_key if first_result is None else uuid4()
        result = append_answer_revision(
            actor=applicant,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            submission_id=submission_id,
            question_id=question.id,
            expected_version=version,
            value=value,
            retry_key=retry_key,
            correlation_id=uuid4(),
            source_channel="test",
        )
        if first_result is None:
            first_result = (result, question.id, value, version)
        version = result.resulting_version

    assert first_result is not None
    repeated = append_answer_revision(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=submission_id,
        question_id=first_result[1],
        expected_version=first_result[3],
        value=first_result[2],
        retry_key=first_retry_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert repeated.replayed is True
    assert repeated.receipt_id == first_result[0].receipt_id

    submitted = submit_application(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=submission_id,
        expected_version=version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert submitted.resulting_version == version + 1

    applicant_projection = my_submissions(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    reviewer_projection = review_queue(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    applicant_keys = {
        item["key"]
        for item in latest_answers(applicant_projection[0], audience="applicant")
    }
    reviewer_keys = {
        item["key"]
        for item in latest_answers(reviewer_projection[0], audience="reviewer")
    }
    assert "technical-needs" in applicant_keys
    assert "technical-needs" not in reviewer_keys

    accepted = record_review_decision(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=submission_id,
        expected_version=submitted.resulting_version,
        decision="accept",
        reason="The programme and technical review are complete.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    decision = ApplicationReviewDecision.objects.get(submission_id=submission_id)
    target = ApplicationTargetRecord.objects.get(submission_id=submission_id)
    assert decision.reviewer_basis == ReviewerBasis.IMMUTABLE_ROLE
    assert decision.reviewer_role_bundle_id == world.reviewer_role.id
    assert decision.to_state == ApplicationState.ACCEPTED
    assert accepted.target_id == target.id
    assert target.adapter_kind == world.definition.target_adapter_kind
    assert AuditEvent.objects.filter(
        target_id=submission_id, operation__startswith="applications."
    ).exists()
    events = DomainEvent.objects.filter(aggregate_id=submission_id)
    assert events.count() == 7
    assert OutboxMessage.objects.filter(event__in=events).count() == 7

    revision = ApplicationAnswerRevision.objects.filter(
        submission_id=submission_id
    ).first()
    assert revision is not None
    with pytest.raises(DatabaseError), transaction.atomic():
        ApplicationAnswerRevision.objects.filter(id=revision.id).update(
            value="tampered"
        )

    foreign_edition = EventEditionFactory()
    with pytest.raises(ApplicationUnavailable):
        start_submission(
            actor=applicant,
            organization_id=foreign_edition.organization_id,
            edition_id=foreign_edition.id,
            definition_id=world.definition.id,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
