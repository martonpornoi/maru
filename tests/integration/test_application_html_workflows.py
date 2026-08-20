"""Executable same-shell journeys for the typed Applications studio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

import maru.applications.queries as application_queries
from maru.applications.commands import (
    activate_definition,
    add_question,
    append_answer_revision,
    configure_definition,
    create_definition_from_starter,
    start_submission,
    submit_application,
)
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationEligibilityKind,
    ApplicationQuestionType,
    ApplicationReviewDecision,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetRecord,
    ReviewerBasis,
)
from maru.applications.queries import my_application_editions
from maru.identity.models import Account, NavigationPin
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.authorization.models import RoleBundle
    from maru.events.models import EventEdition
    from maru.workforce.models import Department

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _World:
    edition: EventEdition
    manager: Account
    reviewer: Account
    department: Department
    role: RoleBundle | None
    definition: ApplicationDefinition


def _grant(account: Account, edition: EventEdition, capability_code: str) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code=capability_code,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _active_world(
    starter_code: str,
    *,
    edition: EventEdition | None = None,
    named_reviewer: bool = False,
    eligibility_kind: str = ApplicationEligibilityKind.AUTHENTICATED_PERSON,
    hidden_reviewer_field: bool = False,
) -> _World:
    edition = edition or EventEditionFactory(time_zone="Europe/Budapest")
    manager = AccountFactory(display_name=f"{starter_code} Manager")
    reviewer = AccountFactory(display_name=f"{starter_code} Reviewer")
    _grant(manager, edition, "applications.manage_definitions")
    _grant(reviewer, edition, "applications.review")
    department = create_department_for_test(
        edition=edition,
        name=f"{starter_code} Owners",
        expected_code=f"{starter_code}-owners",
    )
    role: RoleBundle | None = None
    if not named_reviewer:
        role = RoleBundleFactory(
            organization=edition.organization,
            code=f"{starter_code}-reviewers",
            name=f"{starter_code} Reviewers",
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
    created = create_definition_from_starter(
        actor=manager,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        starter_code=starter_code,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=10),
        applicant_edit_until=now + timedelta(days=9),
        retry_key=uuid4(),
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
        eligibility_kind=eligibility_kind,
        maximum_submissions=definition.max_submissions_per_person,
        opens_at=definition.opens_at,
        closes_at=definition.closes_at,
        applicant_edit_until=definition.applicant_edit_until,
        minimum_age=definition.minimum_age,
        audience_policy_code=definition.audience_policy_code,
        retention_policy_code=definition.retention_policy_code,
        age_policy_code=definition.age_policy_code,
        owner_department_ids=(department.id,),
        reviewer_role_bundle_ids=(() if role is None else (role.id,)),
        reviewer_account_ids=((reviewer.id,) if named_reviewer else ()),
        reason="Assign exact owners and reviewer basis for the browser journey.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    definition.refresh_from_db()
    if hidden_reviewer_field:
        section = definition.sections.order_by("position", "id").first()
        assert section is not None
        add_question(
            actor=manager,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            definition_id=definition.id,
            section_id=section.id,
            expected_version=definition.aggregate_version,
            key="applicant-private-note",
            field_type=ApplicationQuestionType.LONG_TEXT,
            label="Applicant-only note",
            help_text="Synthetic field excluded from review projection.",
            required=False,
            options=[],
            minimum_length=None,
            maximum_length=500,
            minimum_value=None,
            maximum_value=None,
            maximum_choices=None,
            reference_kind="",
            condition={},
            purpose="Prove reviewer field filtering.",
            classification=definition.classification,
            applicant_visible=True,
            applicant_writable=True,
            staff_visible=False,
            staff_writable=False,
            reviewer_visible=False,
            public_after_approval=False,
            api_projection=False,
            retention_policy_code=definition.retention_policy_code,
            reason="Add one applicant-only synthetic field.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        definition.refresh_from_db()
    activate_definition(
        actor=manager,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_id=definition.id,
        expected_version=definition.aggregate_version,
        reason="Open the fully reviewed browser workflow.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    definition.refresh_from_db()
    return _World(edition, manager, reviewer, department, role, definition)


def _client(account: Account) -> Client:
    client = Client()
    client.force_login(account)
    return client


def _local(value: datetime, zone_name: str) -> str:
    return value.astimezone(ZoneInfo(zone_name)).strftime("%Y-%m-%dT%H:%M")


def _submit_dj(world: _World, applicant: Account) -> ApplicationSubmission:
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
    version = started.resulting_version
    values: dict[str, object] = {
        "artist-name": "Synthetic Night Fox",
        "genre": "House",
        "set-length": 60,
        "technical-needs": "Two media players and a mixer.",
        "applicant-private-note": "Reviewer must never receive this answer.",
    }
    for key, value in values.items():
        question = world.definition.questions.filter(key=key).first()
        if question is None:
            continue
        result = append_answer_revision(
            actor=applicant,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            submission_id=started.submission_id,
            question_id=question.id,
            expected_version=version,
            value=value,
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        version = result.resulting_version
    submit_application(
        actor=applicant,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        submission_id=started.submission_id,
        expected_version=version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return ApplicationSubmission.objects.get(id=started.submission_id)


def test_organizer_html_copy_configure_lifecycle_and_shell_are_executable() -> (  # noqa: PLR0915
    None
):
    edition = EventEditionFactory(
        name="Synthetic Applications Edition",
        time_zone="Europe/Budapest",
    )
    manager = AccountFactory(display_name="Synthetic Form Organizer")
    _grant(manager, edition, "applications.manage_definitions")
    client = _client(manager)
    workspace_url = reverse(
        "application-definition-workspace",
        args=(edition.organization_id, edition.id),
    )

    workspace = client.get(workspace_url)

    assert workspace.status_code == 200
    content = workspace.content.decode()
    assert "Shared form studio" in content
    assert "Review and copy" in content
    assert "My applications" in content
    assert "Access" in content
    now = timezone.now()
    retry_key = uuid4()
    copy_payload = {
        "retry_key": str(retry_key),
        "opens_at": _local(now - timedelta(hours=1), edition.time_zone),
        "closes_at": _local(now + timedelta(days=10), edition.time_zone),
        "applicant_edit_until": _local(now + timedelta(days=9), edition.time_zone),
    }
    copy_url = reverse(
        "application-starter-copy",
        args=(edition.organization_id, edition.id, "feedback"),
    )

    created = client.post(copy_url, copy_payload)
    replay = client.post(copy_url, copy_payload)

    assert created.status_code == 302
    assert replay.status_code == 302
    definition = ApplicationDefinition.objects.get(
        edition=edition,
        code="feedback",
    )
    assert ApplicationDefinition.objects.filter(edition=edition).count() == 1
    detail_url = reverse(
        "application-definition-detail",
        args=(edition.organization_id, edition.id, definition.id),
    )
    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert "Lifecycle and provenance" in detail.content.decode()
    assert "Save complete draft configuration" in detail.content.decode()

    department = create_department_for_test(
        edition=edition,
        name="Feedback Owners",
        expected_code="feedback-owners",
    )
    role = RoleBundleFactory(
        organization=edition.organization,
        code="feedback-reviewers",
        name="Feedback Reviewers",
        capability_codes=["applications.review"],
    )
    configure_payload = {
        "retry_key": str(uuid4()),
        "expected_version": "1",
        "name": definition.name,
        "description": definition.description,
        "purpose": definition.purpose,
        "classification": definition.classification,
        "eligibility_kind": definition.eligibility_kind,
        "maximum_submissions": str(definition.max_submissions_per_person),
        "opens_at": _local(definition.opens_at, edition.time_zone),
        "closes_at": _local(definition.closes_at, edition.time_zone),
        "applicant_edit_until": _local(
            definition.applicant_edit_until, edition.time_zone
        ),
        "minimum_age": str(definition.minimum_age),
        "audience_policy_code": definition.audience_policy_code,
        "retention_policy_code": definition.retention_policy_code,
        "age_policy_code": definition.age_policy_code,
        "owner_department_ids": [str(department.id)],
        "reviewer_role_bundle_ids": [str(role.id)],
        "reviewer_emails": "",
        "reason": "Set exact owners and immutable reviewer role version.",
    }
    configure_url = reverse(
        "application-definition-configure",
        args=(edition.organization_id, edition.id, definition.id),
    )
    closed = client.post(
        configure_url,
        {**configure_payload, "unexpected_preview_person": str(manager.id)},
    )
    assert closed.status_code == 400
    definition.refresh_from_db()
    assert definition.aggregate_version == 1

    configured = client.post(configure_url, configure_payload)
    assert configured.status_code == 302
    definition.refresh_from_db()
    assert definition.aggregate_version == 2
    stale = client.post(
        configure_url,
        {**configure_payload, "retry_key": str(uuid4())},
    )
    assert stale.status_code == 409

    activated = client.post(
        reverse(
            "application-definition-activate",
            args=(edition.organization_id, edition.id, definition.id),
        ),
        {
            "retry_key": str(uuid4()),
            "expected_version": "2",
            "reason": "Open the reviewed feedback workflow.",
        },
    )
    assert activated.status_code == 302
    definition.refresh_from_db()
    assert definition.status == "active"
    active_page = client.get(detail_url).content.decode()
    assert "Save complete draft configuration" not in active_page
    assert "Create a successor" in active_page

    retired = client.post(
        reverse(
            "application-definition-retire",
            args=(edition.organization_id, edition.id, definition.id),
        ),
        {
            "retry_key": str(uuid4()),
            "expected_version": str(definition.aggregate_version),
            "reason": "Close the synthetic feedback window.",
        },
    )
    assert retired.status_code == 302
    successor = client.post(
        reverse(
            "application-definition-successor",
            args=(edition.organization_id, edition.id, definition.id),
        ),
        {
            "retry_key": str(uuid4()),
            "reason": "Prepare the next independently reviewed definition.",
        },
    )
    assert successor.status_code == 302
    assert ApplicationDefinition.objects.filter(
        edition=edition,
        code="feedback",
        status="draft",
        version=2,
    ).exists()


def test_personal_index_nav_source_visibility_answers_and_submit_are_isolated() -> (  # noqa: PLR0915
    None
):
    world = _active_world("dj-application")
    helper_world = _active_world("helper-application", edition=world.edition)
    applicant = AccountFactory(display_name="Synthetic Applicant")
    foreign = _active_world(
        "feedback",
        eligibility_kind=ApplicationEligibilityKind.REGISTERED_ATTENDEE,
    )
    client = _client(applicant)

    home = client.get(reverse("my-maru-home"))
    assert home.status_code == 200
    home_content = home.content.decode()
    assert "My applications" in home_content
    assert home_content.count('value="my.applications"') == 1
    assert 'data-navigation-search="' in home_content
    pinned = client.post(
        reverse("update-navigation-pin"),
        {
            "destination_code": "my.applications",
            "action": "pin",
            "next": reverse("my-maru-home"),
        },
    )
    assert pinned.status_code == 302
    assert NavigationPin.objects.filter(
        account=applicant,
        destination_code="my.applications",
    ).exists()

    index = client.get(reverse("my-application-index"))
    index_content = index.content.decode()
    assert index.status_code == 200
    assert world.edition.name in index_content
    assert foreign.edition.name not in index_content
    assert foreign.edition.organization.name not in index_content
    assert "Administration</strong>" not in index_content

    workspace_url = reverse(
        "my-applications",
        args=(world.edition.organization_id, world.edition.id),
    )
    workspace = client.get(workspace_url)
    assert workspace.status_code == 200
    assert "Start application" in workspace.content.decode()
    helper_start = client.post(
        reverse(
            "application-submission-start",
            args=(
                helper_world.edition.organization_id,
                helper_world.edition.id,
                helper_world.definition.id,
            ),
        ),
        {"retry_key": str(uuid4())},
    )
    assert helper_start.status_code == 302
    helper_submission = ApplicationSubmission.objects.get(
        definition=helper_world.definition,
        account=applicant,
    )
    helper_detail = client.get(
        reverse(
            "my-application-detail",
            args=(
                world.edition.organization_id,
                world.edition.id,
                helper_submission.id,
            ),
        )
    )
    helper_content = helper_detail.content.decode()
    assert "Automatically sourced" in helper_content
    assert "Account display name" in helper_content
    assert "Synthetic Applicant" in helper_content

    started = client.post(
        reverse(
            "application-submission-start",
            args=(world.edition.organization_id, world.edition.id, world.definition.id),
        ),
        {"retry_key": str(uuid4())},
    )
    assert started.status_code == 302
    submission = ApplicationSubmission.objects.get(
        definition=world.definition,
        account=applicant,
    )
    answer_url = reverse(
        "application-answer-append",
        args=(world.edition.organization_id, world.edition.id, submission.id),
    )
    values: dict[str, object] = {
        "artist-name": "Synthetic Night Fox",
        "genre": "House",
        "set-length": "60",
        "technical-needs": "Two media players and a mixer.",
    }
    for key, value in values.items():
        question = world.definition.questions.get(key=key)
        submission.refresh_from_db()
        payload = {
            "retry_key": str(uuid4()),
            "question_id": str(question.id),
            "expected_version": str(submission.aggregate_version),
            "value": value,
        }
        if key == "artist-name":
            closed = client.post(
                answer_url,
                {**payload, "actor": str(world.manager.id)},
            )
            assert closed.status_code == 400
            submission.refresh_from_db()
            assert submission.aggregate_version == 1
        saved = client.post(answer_url, payload)
        assert saved.status_code == 302
    submission.refresh_from_db()
    submitted = client.post(
        reverse(
            "application-submit",
            args=(world.edition.organization_id, world.edition.id, submission.id),
        ),
        {
            "retry_key": str(uuid4()),
            "expected_version": str(submission.aggregate_version),
        },
    )
    assert submitted.status_code == 302
    submission.refresh_from_db()
    assert submission.state == ApplicationState.SUBMITTED

    other = AccountFactory()
    denied = _client(other).get(
        reverse(
            "my-application-detail",
            args=(world.edition.organization_id, world.edition.id, submission.id),
        )
    )
    assert denied.status_code == 403
    assert "Synthetic Night Fox" not in denied.content.decode()


@pytest.mark.parametrize(
    ("named_reviewer", "expected_basis"),
    [
        (False, ReviewerBasis.IMMUTABLE_ROLE),
        (True, ReviewerBasis.NAMED_PERSON),
    ],
)
def test_reviewer_html_filters_fields_and_records_typed_acceptance_provenance(
    named_reviewer: bool,
    expected_basis: str,
) -> None:
    world = _active_world(
        "dj-application",
        named_reviewer=named_reviewer,
        hidden_reviewer_field=True,
    )
    applicant = AccountFactory(display_name="Synthetic DJ Applicant")
    submission = _submit_dj(world, applicant)
    client = _client(world.reviewer)
    queue = client.get(
        reverse(
            "application-review-workspace",
            args=(world.edition.organization_id, world.edition.id),
        )
    )
    assert queue.status_code == 200
    assert "Synthetic DJ Applicant" in queue.content.decode()
    detail_url = reverse(
        "application-review-detail",
        args=(world.edition.organization_id, world.edition.id, submission.id),
    )
    detail = client.get(detail_url)
    detail_content = detail.content.decode()
    assert detail.status_code == 200
    assert "Two media players and a mixer." in detail_content
    assert "Reviewer must never receive this answer." not in detail_content
    assert "Immutable review provenance" in detail_content
    accepted = client.post(
        reverse(
            "application-review-decision",
            args=(world.edition.organization_id, world.edition.id, submission.id),
        ),
        {
            "retry_key": str(uuid4()),
            "expected_version": str(submission.aggregate_version),
            "decision": "accept",
            "reason": "The synthetic programme review is complete.",
        },
    )
    assert accepted.status_code == 302
    decision = ApplicationReviewDecision.objects.get(submission=submission)
    target = ApplicationTargetRecord.objects.get(submission=submission)
    assert decision.reviewer_basis == expected_basis
    assert (decision.reviewer_role_bundle_id is not None) is (not named_reviewer)
    assert target.adapter_kind == world.definition.target_adapter_kind
    assert target.created_by_id == world.reviewer.id

    outsider = AccountFactory(display_name="Unassigned Reviewer")
    _grant(outsider, world.edition, "applications.review")
    denied = _client(outsider).get(detail_url)
    assert denied.status_code == 403
    assert "Two media players and a mixer." not in denied.content.decode()


def test_personal_edition_candidate_cap_is_distinct_scope_not_definition_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _active_world("dj-application")
    _active_world("feedback", edition=first.edition)
    second = _active_world("idea-submission")
    applicant = AccountFactory()
    monkeypatch.setattr(application_queries, "MAX_PERSONAL_EDITION_CANDIDATES", 2)

    editions = my_application_editions(actor=applicant)

    assert {item.id for item in editions} == {first.edition.id, second.edition.id}
