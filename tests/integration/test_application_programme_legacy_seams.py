"""Fail-closed legacy Applications seams for Programme-owned proposals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import maru.applications.commands as application_commands
from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationUnavailable,
    activate_definition,
    add_question,
    add_section,
    append_answer_revision,
    configure_definition,
    create_definition_from_starter,
    create_successor_definition,
    record_review_decision,
    retire_definition,
    start_submission,
    submit_application,
)
from maru.applications.models import (
    ApplicationClassification,
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationQuestion,
    ApplicationQuestionType,
    ApplicationReviewDecision,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetKind,
    ApplicationTargetRecord,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ReviewDecisionKind,
)
from maru.applications.programme_commands import (
    activate_programme_call,
    create_programme_call,
    seal_programme_proposal,
    start_programme_proposal,
    submit_programme_proposal,
)
from maru.applications.programme_inputs import (
    ProgrammeCallClassification,
    ProgrammeCallConfigurationInput,
    ProgrammeCallContributorFieldInput,
    ProgrammeCallDefinitionInput,
    ProgrammeCallFormatInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionType,
    ProgrammeCallSectionInput,
    ProgrammeCallTrackInput,
    ProgrammeContributorFieldCode,
    ProgrammeContributorFieldRequirement,
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalSelectionInput,
)
from maru.applications.queries import (
    authorize_application_review_submission_api_scope,
    authorize_application_self_submission_api_scope,
    available_applications,
    definition_detail,
    definition_workspace,
    my_application_editions,
    my_submission_detail,
    my_submissions,
    review_queue,
    review_submission_detail,
)
from maru.applications.starters import starter_catalog
from maru.authorization.policy import PolicyDecision
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from datetime import datetime

    from django.http import HttpResponse

    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

_DefinitionOperation = Literal[
    "configure",
    "add-section",
    "add-question",
    "activate",
    "retire",
    "successor",
]
_SubmissionOperation = Literal["start", "answer", "submit"]
_PROGRAMME_SENTINEL = "Programme legacy seam sentinel"


@pytest.fixture(autouse=True)
def _admit_future_programme_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit only the dormant Programme events needed to build test fixtures."""

    def allow(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        allow,
    )


@dataclass(frozen=True, slots=True)
class _TestProgrammeAuthorizer:
    """Provide complete decisions only through the sealed test-authorizer gate."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Allow one command after production scope resolvers prove every identifier."""
        del (
            principal_id,
            organization_id,
            edition_id,
            department_id,
            capability_code,
        )
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_integration_authorizer",
        )

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Allow an exact self relationship already derived by Applications."""
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
            capability_code,
        )
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_integration_authorizer",
        )

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Allow receipt lookup only after the production retry scope is proven."""
        del principal_id, organization_id, edition_id
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="sealed_integration_retry_authorizer",
        )


_PROGRAMME_AUTHORIZER = _TestProgrammeAuthorizer()


@dataclass(frozen=True, slots=True)
class _ProgrammeLegacyWorld:
    edition: EventEdition
    manager: Account
    reviewer: Account
    applicant: Account
    department_id: UUID
    call_id: UUID
    proposal_id: UUID
    definition: ApplicationDefinition
    question: ApplicationQuestion
    submission: ApplicationSubmission


@dataclass(frozen=True, slots=True)
class _LegacySideEffects:
    definition_count: int
    section_count: int
    question_count: int
    submission_count: int
    command_receipt_count: int
    review_decision_count: int
    target_count: int
    definition_version: int
    definition_status: str
    submission_version: int
    submission_state: str


def _grant(account: Account, edition: EventEdition, capability_code: str) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code=capability_code,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _programme_definition(now: datetime) -> ProgrammeCallDefinitionInput:
    question = ProgrammeCallQuestionInput(
        key="proposal-title",
        field_type=ProgrammeCallQuestionType.SHORT_TEXT,
        label=_PROGRAMME_SENTINEL,
        help_text="A deliberately private optional title for seam acceptance.",
        position=1,
        required=False,
        options=(),
        minimum_length=3,
        maximum_length=160,
        minimum_value=None,
        maximum_value=None,
        maximum_choices=None,
        reference_kind="",
        condition=None,
        purpose="Prove Programme content never enters generic Applications.",
        classification=ProgrammeCallClassification.PERSONAL,
        retention_policy_code="",
    )
    section = ProgrammeCallSectionInput(
        key="proposal",
        title="Private Programme proposal",
        help_text="Visible only through the future dedicated Programme experience.",
        position=1,
        questions=(question,),
    )
    return ProgrammeCallDefinitionInput(
        code="programme-legacy-seam",
        name=_PROGRAMME_SENTINEL,
        description="Private Programme proposal content for containment acceptance.",
        purpose="Exercise the dormant Programme ownership boundary end to end.",
        classification=ProgrammeCallClassification.PERSONAL,
        maximum_submissions_per_person=4,
        opens_at=now - timedelta(days=1),
        applicant_edit_until=now + timedelta(days=13),
        closes_at=now + timedelta(days=14),
        audience_policy_code="applications.programme.audience.v1",
        retention_policy_code="applications.programme.retention.v1",
        sections=(section,),
    )


def _programme_configuration(department_id: UUID) -> ProgrammeCallConfigurationInput:
    return ProgrammeCallConfigurationInput(
        owner_department_id=department_id,
        maximum_collaborators=0,
        content_policy_code="applications.programme.content.v1",
        contributor_consent_policy_code=(
            "applications.programme.contributor-consent.v1"
        ),
        collaboration_retention_policy_code=(
            "applications.programme.collaboration-retention.v1"
        ),
        tracks=(
            ProgrammeCallTrackInput(
                code="general",
                label="General Programme",
                description="General sessions.",
                position=1,
            ),
        ),
        formats=(
            ProgrammeCallFormatInput(
                code="session",
                label="Session",
                description="A scheduled Programme session.",
                position=1,
                minimum_duration_minutes=30,
                default_duration_minutes=60,
                maximum_duration_minutes=90,
            ),
        ),
        contributor_fields=(
            ProgrammeCallContributorFieldInput(
                field_code=ProgrammeContributorFieldCode.PUBLIC_NAME,
                lead_requirement=ProgrammeContributorFieldRequirement.REQUIRED,
                collaborator_requirement=ProgrammeContributorFieldRequirement.OPTIONAL,
                position=1,
            ),
        ),
    )


def _programme_legacy_world(*, submitted: bool = False) -> _ProgrammeLegacyWorld:
    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    reviewer = AccountFactory(display_name="Programme reviewer")
    applicant = AccountFactory(display_name="Programme lead")
    _grant(manager, edition, "applications.manage_definitions")
    _grant(reviewer, edition, "applications.review")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    created = create_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=_programme_definition(now),
        configuration=_programme_configuration(department.id),
        expected_version=0,
        reason="Create the command-authenticated Programme seam fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    activated = activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=created.resulting_version,
        reason="Open the private Programme call for containment acceptance.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    track = ProgrammeCallTrack.objects.get(call_id=created.target_id)
    programme_format = ProgrammeCallFormat.objects.get(call_id=created.target_id)
    started = start_programme_proposal(
        actor_id=applicant.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        selection=ProgrammeProposalSelectionInput(
            track_id=track.id,
            format_id=programme_format.id,
            requested_duration_minutes=programme_format.default_duration_minutes,
        ),
        lead_profile=ProgrammeProposalContributorProfileInput(
            public_name="Seam Test Presenter",
            biography="",
            pronouns="",
            website="",
            proposed_for_publication=True,
            consent_acknowledged=True,
            consent_policy_code="applications.programme.contributor-consent.v1",
        ),
        expected_version=0,
        reason="Create a private proposal through its dedicated command.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_PROGRAMME_AUTHORIZER,
    )
    submission_id = started.submission_id
    assert submission_id is not None
    resulting_version = started.resulting_version
    if submitted:
        sealed = seal_programme_proposal(
            actor_id=applicant.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            proposal_id=started.target_id,
            expected_version=resulting_version,
            reason="Seal an exact revision for legacy-review containment.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_PROGRAMME_AUTHORIZER,
        )
        submitted_result = submit_programme_proposal(
            actor_id=applicant.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            proposal_id=started.target_id,
            revision_id=sealed.target_id,
            expected_version=sealed.resulting_version,
            reason="Submit the revision without adopting a generic review layer.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_PROGRAMME_AUTHORIZER,
        )
        resulting_version = submitted_result.resulting_version
    definition = ApplicationDefinition.objects.get(id=created.definition_id)
    submission = ApplicationSubmission.objects.get(id=submission_id)
    question = ApplicationQuestion.objects.get(definition=definition)
    assert definition.aggregate_version == activated.resulting_version
    assert submission.aggregate_version == resulting_version
    return _ProgrammeLegacyWorld(
        edition=edition,
        manager=manager,
        reviewer=reviewer,
        applicant=applicant,
        department_id=department.id,
        call_id=created.target_id,
        proposal_id=started.target_id,
        definition=definition,
        question=question,
        submission=submission,
    )


def _legacy_side_effects(world: _ProgrammeLegacyWorld) -> _LegacySideEffects:
    world.definition.refresh_from_db()
    world.submission.refresh_from_db()
    edition_id = world.edition.id
    return _LegacySideEffects(
        definition_count=ApplicationDefinition.objects.filter(
            edition_id=edition_id
        ).count(),
        section_count=world.definition.sections.count(),
        question_count=world.definition.questions.count(),
        submission_count=ApplicationSubmission.objects.filter(
            edition_id=edition_id
        ).count(),
        command_receipt_count=ApplicationCommandReceipt.objects.filter(
            edition_id=edition_id
        ).count(),
        review_decision_count=ApplicationReviewDecision.objects.filter(
            submission__edition_id=edition_id
        ).count(),
        target_count=ApplicationTargetRecord.objects.filter(
            submission__edition_id=edition_id
        ).count(),
        definition_version=world.definition.aggregate_version,
        definition_status=world.definition.status,
        submission_version=world.submission.aggregate_version,
        submission_state=world.submission.state,
    )


def _assert_no_generic_side_effects(
    world: _ProgrammeLegacyWorld,
    before: _LegacySideEffects,
) -> None:
    assert _legacy_side_effects(world) == before
    assert before.command_receipt_count == 0
    assert before.review_decision_count == 0
    assert before.target_count == 0


def _legacy_definition_command(
    world: _ProgrammeLegacyWorld,
    operation: _DefinitionOperation,
) -> None:
    definition = world.definition
    common = {
        "actor": world.manager,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "definition_id": definition.id,
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    if operation == "configure":
        configure_definition(
            expected_version=definition.aggregate_version,
            name=definition.name,
            description=definition.description,
            purpose=definition.purpose,
            classification=definition.classification,
            eligibility_kind=definition.eligibility_kind,
            maximum_submissions=definition.max_submissions_per_person,
            opens_at=definition.opens_at,
            closes_at=definition.closes_at,
            applicant_edit_until=definition.applicant_edit_until,
            minimum_age=definition.minimum_age,
            audience_policy_code=definition.audience_policy_code,
            retention_policy_code=definition.retention_policy_code,
            age_policy_code=definition.age_policy_code,
            owner_department_ids=(world.department_id,),
            reviewer_role_bundle_ids=(),
            reviewer_account_ids=(),
            reason="The generic studio must not configure Programme calls.",
            **common,
        )
    elif operation == "add-section":
        add_section(
            expected_version=definition.aggregate_version,
            key="generic-section",
            title="Generic section",
            help_text="Must never be added to a Programme call.",
            reason="Exercise the generic section denial.",
            **common,
        )
    elif operation == "add-question":
        add_question(
            section_id=world.question.section_id,
            expected_version=definition.aggregate_version,
            key="generic-question",
            field_type=ApplicationQuestionType.SHORT_TEXT,
            label="Generic question",
            help_text="Must never be added to a Programme call.",
            required=False,
            options=[],
            minimum_length=1,
            maximum_length=80,
            minimum_value=None,
            maximum_value=None,
            maximum_choices=None,
            reference_kind="",
            condition={},
            purpose="Exercise the generic question denial.",
            classification=ApplicationClassification.PERSONAL,
            applicant_visible=True,
            applicant_writable=True,
            staff_visible=False,
            staff_writable=False,
            reviewer_visible=False,
            public_after_approval=False,
            api_projection=False,
            retention_policy_code="",
            reason="Exercise the generic question denial.",
            **common,
        )
    elif operation == "activate":
        activate_definition(
            expected_version=definition.aggregate_version,
            reason="The generic lifecycle must not activate Programme calls.",
            **common,
        )
    elif operation == "retire":
        retire_definition(
            expected_version=definition.aggregate_version,
            reason="The generic lifecycle must not retire Programme calls.",
            **common,
        )
    else:
        create_successor_definition(
            reason="The generic studio must not copy Programme calls.",
            **common,
        )


def _legacy_submission_command(
    world: _ProgrammeLegacyWorld,
    operation: _SubmissionOperation,
) -> None:
    common = {
        "actor": world.applicant,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    if operation == "start":
        start_submission(definition_id=world.definition.id, **common)
    elif operation == "answer":
        append_answer_revision(
            submission_id=world.submission.id,
            question_id=world.question.id,
            expected_version=world.submission.aggregate_version,
            value="Content the generic answer command must never read.",
            **common,
        )
    else:
        submit_application(
            submission_id=world.submission.id,
            expected_version=world.submission.aggregate_version,
            **common,
        )


def _client(actor: Account) -> Client:
    client = Client()
    client.force_login(actor)
    return client


def _api_client(actor: Account) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=actor)
    return client


def _assert_non_disclosing_response(
    response: HttpResponse,
    *,
    world: _ProgrammeLegacyWorld,
    expected_status: int,
) -> None:
    content = bytes(response.content).decode()
    assert response.status_code == expected_status
    assert _PROGRAMME_SENTINEL not in content
    assert str(world.definition.id) not in content
    assert str(world.submission.id) not in content


def test_programme_records_are_omitted_from_every_legacy_query_surface() -> None:
    world = _programme_legacy_world()
    scope = {
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
    }

    assert definition_workspace(actor=world.manager, **scope) == ()
    with pytest.raises(ApplicationAuthorizationDenied):
        definition_detail(
            actor=world.manager,
            definition_id=world.definition.id,
            **scope,
        )
    assert available_applications(actor=world.applicant, **scope) == ()
    assert my_submissions(actor=world.applicant, **scope) == ()
    assert my_application_editions(actor=world.applicant) == ()
    with pytest.raises(ApplicationAuthorizationDenied):
        my_submission_detail(
            actor=world.applicant,
            submission_id=world.submission.id,
            **scope,
        )
    assert review_queue(actor=world.reviewer, **scope) == ()
    with pytest.raises(ApplicationAuthorizationDenied):
        review_submission_detail(
            actor=world.reviewer,
            submission_id=world.submission.id,
            **scope,
        )
    with pytest.raises(ApplicationAuthorizationDenied):
        authorize_application_self_submission_api_scope(
            actor=world.applicant,
            submission_id=world.submission.id,
            **scope,
        )
    with pytest.raises(ApplicationAuthorizationDenied):
        authorize_application_review_submission_api_scope(
            actor=world.reviewer,
            submission_id=world.submission.id,
            **scope,
        )


@pytest.mark.parametrize(
    "operation",
    ["configure", "add-section", "add-question", "activate", "retire", "successor"],
)
def test_every_generic_definition_command_rejects_programme_before_loading(
    operation: _DefinitionOperation,
) -> None:
    world = _programme_legacy_world()
    before = _legacy_side_effects(world)

    with pytest.raises(ApplicationUnavailable):
        _legacy_definition_command(world, operation)

    _assert_no_generic_side_effects(world, before)


@pytest.mark.parametrize("operation", ["start", "answer", "submit"])
def test_every_generic_applicant_command_rejects_programme_before_loading(
    operation: _SubmissionOperation,
) -> None:
    world = _programme_legacy_world()
    before = _legacy_side_effects(world)

    with pytest.raises(ApplicationUnavailable):
        _legacy_submission_command(world, operation)

    _assert_no_generic_side_effects(world, before)


def test_generic_starter_copy_rejects_a_programme_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _programme_legacy_world()
    before = _legacy_side_effects(world)
    programme_starter = replace(
        starter_catalog()[0],
        code="programme-copy-attempt",
        name="Programme copy attempt",
        target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
    )
    monkeypatch.setattr(
        application_commands,
        "application_starter_for_profile",
        lambda **_kwargs: programme_starter,
    )
    now = timezone.now()

    with pytest.raises(ValidationError) as raised:
        create_definition_from_starter(
            actor=world.manager,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            starter_code=programme_starter.code,
            opens_at=now,
            applicant_edit_until=now + timedelta(days=1),
            closes_at=now + timedelta(days=2),
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert raised.value.message_dict == {
        "starter_code": ["Choose an applications-owned starter."]
    }
    _assert_no_generic_side_effects(world, before)


@pytest.mark.parametrize(
    "decision",
    [ReviewDecisionKind.START_REVIEW, ReviewDecisionKind.ACCEPT],
)
def test_generic_review_and_accept_target_branch_reject_programme(
    decision: str,
) -> None:
    world = _programme_legacy_world(submitted=True)
    before = _legacy_side_effects(world)
    assert before.submission_state == ApplicationState.SUBMITTED

    with pytest.raises(ApplicationUnavailable):
        record_review_decision(
            actor=world.reviewer,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            submission_id=world.submission.id,
            expected_version=world.submission.aggregate_version,
            decision=decision,
            reason="The dormant generic review layer must not see this proposal.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    _assert_no_generic_side_effects(world, before)


def test_html_get_surfaces_omit_and_hide_programme_content() -> None:
    world = _programme_legacy_world(submitted=True)
    route_scope = (world.edition.organization_id, world.edition.id)
    list_cases = (
        (world.manager, "application-definition-workspace"),
        (world.applicant, "my-applications"),
        (world.reviewer, "application-review-workspace"),
    )
    for actor, route_name in list_cases:
        response = _client(actor).get(reverse(route_name, args=route_scope))
        assert response.status_code == 200
        assert _PROGRAMME_SENTINEL not in response.content.decode()
        assert str(world.definition.id) not in response.content.decode()
        assert str(world.submission.id) not in response.content.decode()

    detail_cases = (
        (
            world.manager,
            "application-definition-detail",
            (*route_scope, world.definition.id),
        ),
        (
            world.applicant,
            "my-application-detail",
            (*route_scope, world.submission.id),
        ),
        (
            world.reviewer,
            "application-review-detail",
            (*route_scope, world.submission.id),
        ),
    )
    for actor, route_name, route_args in detail_cases:
        response = _client(actor).get(reverse(route_name, args=route_args))
        _assert_non_disclosing_response(response, world=world, expected_status=403)


def test_html_post_surfaces_reject_programme_without_generic_side_effects() -> None:
    world = _programme_legacy_world(submitted=True)
    before = _legacy_side_effects(world)
    route_scope = (world.edition.organization_id, world.edition.id)
    cases = (
        (
            world.manager,
            "application-definition-activate",
            (*route_scope, world.definition.id),
            {
                "retry_key": str(uuid4()),
                "expected_version": str(world.definition.aggregate_version),
                "reason": "Reject generic activation.",
            },
            403,
        ),
        (
            world.applicant,
            "application-submission-start",
            (*route_scope, world.definition.id),
            {"retry_key": str(uuid4())},
            404,
        ),
        (
            world.applicant,
            "application-answer-append",
            (*route_scope, world.submission.id),
            {
                "retry_key": str(uuid4()),
                "question_id": str(world.question.id),
                "expected_version": str(world.submission.aggregate_version),
                "value": "Never disclose this value.",
            },
            403,
        ),
        (
            world.applicant,
            "application-submit",
            (*route_scope, world.submission.id),
            {
                "retry_key": str(uuid4()),
                "expected_version": str(world.submission.aggregate_version),
            },
            403,
        ),
        (
            world.reviewer,
            "application-review-decision",
            (*route_scope, world.submission.id),
            {
                "retry_key": str(uuid4()),
                "expected_version": str(world.submission.aggregate_version),
                "decision": ReviewDecisionKind.ACCEPT,
                "reason": "Reject generic acceptance.",
            },
            403,
        ),
    )
    for actor, route_name, route_args, payload, expected_status in cases:
        response = _client(actor).post(reverse(route_name, args=route_args), payload)
        _assert_non_disclosing_response(
            response,
            world=world,
            expected_status=expected_status,
        )

    _assert_no_generic_side_effects(world, before)


def test_api_get_surfaces_omit_programme_content() -> None:
    world = _programme_legacy_world(submitted=True)
    route_scope = (world.edition.organization_id, world.edition.id)
    starters = _api_client(world.manager).get(
        reverse("api-application-starters", args=route_scope)
    )
    definitions = _api_client(world.manager).get(
        reverse("api-application-definitions", args=route_scope)
    )
    personal = _api_client(world.applicant).get(
        reverse("api-my-applications", args=route_scope)
    )
    reviews = _api_client(world.reviewer).get(
        reverse("api-application-review-queue", args=route_scope)
    )

    assert starters.status_code == 200
    assert all(
        item["target_adapter_kind"] != ApplicationTargetKind.PROGRAMME_ITEM
        for item in starters.json()
    )
    assert definitions.status_code == 200
    assert definitions.json() == []
    assert personal.status_code == 200
    assert personal.json() == {"available": [], "submissions": []}
    assert reviews.status_code == 200
    assert reviews.json() == []
    for response in (starters, definitions, personal, reviews):
        assert _PROGRAMME_SENTINEL not in response.content.decode()
        assert str(world.definition.id) not in response.content.decode()
        assert str(world.submission.id) not in response.content.decode()


def test_api_post_surfaces_reject_programme_without_generic_side_effects() -> None:
    world = _programme_legacy_world(submitted=True)
    before = _legacy_side_effects(world)
    route_scope = (world.edition.organization_id, world.edition.id)
    cases = (
        (
            world.manager,
            "api-application-definition-command",
            (*route_scope, world.definition.id),
            {
                "operation": "definition.activate",
                "expected_version": world.definition.aggregate_version,
                "reason": "Reject generic API activation.",
            },
            404,
        ),
        (
            world.applicant,
            "api-application-submission-create",
            (*route_scope, world.definition.id),
            {},
            404,
        ),
        (
            world.applicant,
            "api-application-answer-revision",
            (*route_scope, world.submission.id),
            {
                "question_id": str(world.question.id),
                "expected_version": world.submission.aggregate_version,
                "value": "Never disclose this value.",
            },
            403,
        ),
        (
            world.applicant,
            "api-application-submit",
            (*route_scope, world.submission.id),
            {"expected_version": world.submission.aggregate_version},
            403,
        ),
        (
            world.reviewer,
            "api-application-review-decision",
            (*route_scope, world.submission.id),
            {
                "expected_version": world.submission.aggregate_version,
                "decision": ReviewDecisionKind.ACCEPT,
                "reason": "Reject generic API acceptance.",
            },
            403,
        ),
    )
    for actor, route_name, route_args, payload, expected_status in cases:
        response = _api_client(actor).post(
            reverse(route_name, args=route_args),
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        _assert_non_disclosing_response(
            response,
            world=world,
            expected_status=expected_status,
        )

    _assert_no_generic_side_effects(world, before)
