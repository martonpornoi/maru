"""Exercise archive-purpose review composition through real native owner commands."""

import json
from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from jsonschema import Draft202012Validator

from maru.applications import programme_exit_configuration_queries as configuration
from maru.applications import programme_exit_department_queries as department
from maru.applications import programme_exit_file_queries as files
from maru.applications import programme_exit_queries as applications
from maru.applications import programme_exit_review_queries as archive
from maru.applications import programme_file_commands as file_commands
from maru.applications import programme_file_queries as file_queries
from maru.applications import programme_review_file_queries as browser_files
from maru.applications.models import ProgrammeProposal, ProgrammeReviewEntry
from maru.applications.models import ProgrammeReviewAction as Action
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import reopen_programme_proposal
from maru.applications.programme_exit_serialization import (
    serialize_programme_exit_applications,
)
from maru.applications.programme_file_preparation import ProgrammeFileUnavailableError
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
)
from maru.applications.programme_review_authorization import DECIDE, MANAGE_REVIEW
from maru.applications.programme_review_commands import apply_programme_review_command
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput as Intent,
)
from maru.audit.models import AuditEvent
from maru.programme import archive_authorization, placement_queries
from maru.programme import exit_composition as composition
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.host_commands import invite_programme_host
from maru.programme.host_inputs import ProgrammeHostInvitationInput
from maru.workforce import programme_staffing_queries
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration import test_application_programme_services as service_fixtures
from tests.integration.test_application_programme_file_custody import (
    PDF,
    command_scanner,
    file_definition,
)
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)
from tests.integration.test_programme_queries import (
    _create_layered_item,
    _TrustedAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy
from tests.support import programme_review as review_fixtures
from tests.support.programme_review import assign_and_score, create_review_world
from tests.unit.test_application_programme_review_inputs import review_policy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


@pytest.fixture
def file_source(monkeypatch, request):
    request.getfixturevalue(file_definition.__name__)
    request.getfixturevalue(command_scanner.__name__)

    def upload_fixture_answer(**values):
        return file_commands.upload_and_use_programme_file(
            request=ProgrammeAnswerReferenceRequest(
                values["actor_id"],
                values["organization_id"],
                values["edition_id"],
                values["proposal_id"],
                values["question_id"],
                values["correlation_id"],
                "test",
            ),
            intent=ProgrammeAnswerReferenceIntent(
                values["expected_version"], 2, 1, values["retry_key"]
            ),
            read_bytes=lambda: PDF,
            authorizer=_AUTHORIZER,
        )

    monkeypatch.setattr(
        review_fixtures, "append_programme_proposal_answer", upload_fixture_answer
    )
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )

    def create(*, anonymous=False):
        policy = review_policy()
        policy = replace(
            policy, stages=(replace(policy.stages[0], anonymous=anonymous),)
        )
        world = create_review_world(policy=policy)
        return world, {
            "request": world.read(
                world.decider.id, DECIDE, fields=frozenset({"review_answers"})
            ),
            "case_id": world.case_id,
            "question_key": "session-title",
            "authorizer": _AUTHORIZER,
            "programme_authorizer": _TrustedAuthorizer(),
        }

    return create


def test_native_archive_file_exact_custody_and_audit(file_source):
    world, args = file_source()
    result = files.load_programme_exit_review_file(**args)
    assert result.data == PDF
    assert result.size_bytes == len(PDF)
    assert result.case_id == world.case_id
    assert result.question_id == world.call.question_id
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme_review.query.exit_file", outcome="allow"
        ).count()
        == 1
    )


def test_native_composed_archive_private_file_and_department_before_people(
    file_source, monkeypatch
):
    world, _file_args = file_source()
    actor, edition, programme_policy = (
        world.decider,
        world.call.edition,
        _TrustedAuthorizer(),
    )
    for code in (
        "audit.view_security",
        "events.view_basic",
        "venues.view_workspace",
        "workforce.view_shifts",
    ):
        CapabilityGrantFactory(
            principal=actor,
            organization=edition.organization,
            edition=edition if code != "audit.view_security" else None,
            capability_code=code,
        )
    monkeypatch.setattr(
        programme_staffing_queries, "profile_allows_adapter", lambda *_: True
    )
    monkeypatch.setattr(placement_queries, "profile_allows_adapter", lambda *_: True)
    item = _create_layered_item(
        actor_id=actor.id, edition=edition, authorizer=programme_policy
    )
    person = AccountFactory(id=UUID(int=1))
    invite_programme_host(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        invitation=ProgrammeHostInvitationInput(
            person.id,
            "host",
            "Synthetic invitation",
            "Private invitation must be absent",
            item.aggregate_version,
        ),
        reason="Synthetic complete cross-owner lock closure",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=programme_policy,
    )
    events = []
    original_department = composition.resolve_retained_department_reference
    original_people = composition.lock_account_references_for_evidence
    original_owner = composition.load_programme_exit_applications

    def lock_department(**kwargs):
        events.append(("department", kwargs["department_id"]))
        return original_department(**kwargs)

    def lock_people(**kwargs):
        events.append(("people", kwargs["account_ids"]))
        return original_people(**kwargs)

    def read_owner(**kwargs):
        assert events == [
            ("department", world.call.department_id),
            ("people", tuple(sorted((actor.id, person.id)))),
        ]
        events.append(("owner", None))
        return original_owner(**kwargs)

    monkeypatch.setattr(
        composition, "resolve_retained_department_reference", lock_department
    )
    monkeypatch.setattr(
        composition, "lock_account_references_for_evidence", lock_people
    )
    monkeypatch.setattr(composition, "load_programme_exit_applications", read_owner)
    result = composition.collect_programme_exit(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        programme_authorizer=programme_policy,
        applications_authorizer=_AUTHORIZER,
        scheduling_authorizer=TrustedSchedulingPolicy(),
    )
    assert len(result.files) == 1
    assert result.files[0].data == PDF
    for section in result.sections:
        Draft202012Validator(json.loads(section.schema)).validate(
            json.loads(section.data)
        )
        assert b"Private invitation must be absent" not in section.data
    exported = json.loads(
        next(row.data for row in result.sections if row.owner == "applications")
    )
    assert exported["departments"][0]["cases"][0]["files"][0]["file_id"] == str(
        result.files[0].file_id
    )


def test_native_archive_file_retains_original_seal_without_widening_browser(
    file_source,
):
    world, args = file_source()
    original = files.load_programme_exit_review_file(**args)
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    reopen_programme_proposal(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=proposal.submission.aggregate_version,
        reason="Synthetic retained archive evidence after reopening.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        browser_files.get_programme_review_file(
            **{
                key: value
                for key, value in args.items()
                if key != "programme_authorizer"
            },
            include_bytes=True,
        )
    assert files.load_programme_exit_review_file(**args) == original


def test_native_anonymous_archive_file_denies_before_custody(file_source, monkeypatch):
    _world, args = file_source(anonymous=True)
    binding, projection = Mock(), Mock()
    monkeypatch.setattr(files, "_answer_binding", binding)
    monkeypatch.setattr(files, "_projection", projection)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        files.load_programme_exit_review_file(**args)
    binding.assert_not_called()
    projection.assert_not_called()


@pytest.mark.parametrize("actor", ["lead", "reviewer"])
def test_native_file_archive_cannot_impersonate_source_contributor(file_source, actor):
    world, args = file_source()
    assign_and_score(world, world.reviewer.id)
    args["request"] = replace(args["request"], actor_id=getattr(world, actor).id)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        files.load_programme_exit_review_file(**args)


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "department_id"])
def test_native_file_archive_denies_other_scope(file_source, field):
    _world, args = file_source()
    args["request"] = replace(args["request"], **{field: uuid4()})
    with pytest.raises(
        (
            ApplicationsProgrammeAuthorizationDeniedError,
            ProgrammeAuthorizationDeniedError,
        )
    ):
        files.load_programme_exit_review_file(**args)


def test_native_archive_file_missing_bytes_is_unavailable(file_source, monkeypatch):
    _world, args = file_source()
    # Inject storage-read failure, not destructive tampering with immutable custody.
    monkeypatch.setattr(
        file_queries, "_bytes", Mock(side_effect=ProgrammeFileUnavailableError)
    )
    with pytest.raises(ProgrammeFileUnavailableError):
        files.load_programme_exit_review_file(**args)
    assert not AuditEvent.objects.filter(
        operation="applications.programme_review.query.exit_file"
    ).exists()


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )
    world = create_review_world()
    assign_and_score(world, world.reviewer.id)
    return world, {
        "request": world.read(world.decider.id, DECIDE),
        "case_id": world.case_id,
        "authorizer": _AUTHORIZER,
        "programme_authorizer": _TrustedAuthorizer(),
    }


def test_native_configuration_retains_all_original_policy_versions(source):
    world, args = source
    result = apply_programme_review_command(
        actor_id=world.moderator.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        department_id=world.call.department_id,
        command=Intent(
            Action.POLICY_CREATED, world.call.call_id, policy=review_policy()
        ),
        expected_version=1,
        retry_key=uuid4(),
        reason="Synthetic second policy.",
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    snapshot = configuration.load_programme_exit_configuration(
        request=world.read(
            world.decider.id, MANAGE_REVIEW, fields=frozenset({"review_setup"})
        ),
        authorizer=_AUTHORIZER,
        programme_authorizer=args["programme_authorizer"],
    )
    assert snapshot.department_id == world.call.department_id
    assert len(snapshot.calls) == 1
    assert [policy.version for policy in snapshot.calls[0].policies] == [1, 2]
    assert snapshot.calls[0].policies[0].policy_id == world.policy_id
    assert snapshot.calls[0].policies[1].policy_id == result.target_id
    assert snapshot.calls[0].configuration.summary.call_id == world.call.call_id
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme_review.query.exit_configuration"
        ).count()
        == 1
    )


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "department_id"])
def test_native_configuration_denies_foreign_scope(source, field):
    world, args = source
    request = world.read(
        world.decider.id, MANAGE_REVIEW, fields=frozenset({"review_setup"})
    )
    with pytest.raises(
        (
            ApplicationsProgrammeAuthorizationDeniedError,
            ProgrammeAuthorizationDeniedError,
        )
    ):
        configuration.load_programme_exit_configuration(
            request=replace(request, **{field: uuid4()}),
            authorizer=_AUTHORIZER,
            programme_authorizer=args["programme_authorizer"],
        )


def test_native_department_composes_configuration_review_and_private_file(file_source):
    world, args = file_source()
    result = department.load_programme_exit_department(
        request=world.read(world.decider.id, DECIDE),
        authorizer=_AUTHORIZER,
        programme_authorizer=args["programme_authorizer"],
    )
    assert result.configuration.department_id == world.call.department_id
    assert len(result.configuration.calls) == len(result.cases) == 1
    assert result.cases[0].review.case_id == world.case_id
    assert result.cases[0].files[0].data == PDF
    assert result.cases[0].files[0].revision_id == result.cases[0].review.revision_id
    section = serialize_programme_exit_applications(
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        departments=(result,),
    )
    assert PDF not in section.data
    Draft202012Validator(json.loads(section.schema)).validate(json.loads(section.data))
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme_review.query.exit_department"
        ).count()
        == 1
    )


def test_native_department_preserves_anonymous_omission_before_file_lookup(
    file_source, monkeypatch
):
    world, args = file_source(anonymous=True)
    reader = Mock()
    monkeypatch.setattr(department, "load_programme_exit_review_file", reader)
    result = department.load_programme_exit_department(
        request=world.read(world.decider.id, DECIDE),
        authorizer=_AUTHORIZER,
        programme_authorizer=args["programme_authorizer"],
    )
    assert result.cases[0].files == ()
    assert json.loads(result.cases[0].review.answers_json) == []
    reader.assert_not_called()


def test_native_department_cannot_hide_denied_case_as_empty_success(source):
    world, args = source
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        department.load_programme_exit_department(
            request=world.read(world.reviewer.id, DECIDE),
            authorizer=_AUTHORIZER,
            programme_authorizer=args["programme_authorizer"],
        )
    assert not AuditEvent.objects.filter(
        operation="applications.programme_review.query.exit_department"
    ).exists()


def test_native_applications_owner_complete_scope_and_schema(file_source):
    world, args = file_source()
    result = applications.load_programme_exit_applications(
        actor_id=world.decider.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        correlation_id=uuid4(),
        authorizer=_AUTHORIZER,
        programme_authorizer=args["programme_authorizer"],
    )
    assert len(result.departments) == 1
    assert result.departments[0].cases[0].review.case_id == world.case_id
    section = serialize_programme_exit_applications(
        organization_id=result.organization_id,
        edition_id=result.edition_id,
        departments=result.departments,
    )
    Draft202012Validator(json.loads(section.schema)).validate(json.loads(section.data))
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme.query.exit_owner"
        ).count()
        == 1
    )


def test_native_applications_owner_locks_all_departments_before_child_reads(
    source, monkeypatch
):
    world, args = source
    create = service_fixtures.create_department_for_test

    def secondary(**kwargs):
        return create(
            **{**kwargs, "name": "Other programme", "expected_code": "other-programme"}
        )

    monkeypatch.setattr(service_fixtures, "create_department_for_test", secondary)
    other = service_fixtures._active_call(
        edition=world.call.edition, code="archive-secondary"
    )
    expected = tuple(sorted((world.call.department_id, other.department_id)))
    events = []
    original_lock = applications.lock_programme_edition_write_scope
    original_read = applications.load_programme_exit_department

    def lock(**kwargs):
        events.append(kwargs["department_ids"])
        return original_lock(**kwargs)

    def read(**kwargs):
        assert events[0] == expected
        events.append("child")
        return original_read(**kwargs)

    monkeypatch.setattr(applications, "lock_programme_edition_write_scope", lock)
    monkeypatch.setattr(applications, "load_programme_exit_department", read)
    result = applications.load_programme_exit_applications(
        actor_id=world.decider.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        correlation_id=uuid4(),
        authorizer=_AUTHORIZER,
        programme_authorizer=args["programme_authorizer"],
    )
    assert (
        tuple(row.configuration.department_id for row in result.departments) == expected
    )
    assert sum(len(row.configuration.calls) for row in result.departments) == 2
    assert sum(len(row.cases) for row in result.departments) == 1
    assert events == [expected, "child", "child"]


def test_native_complete_case_paging_lineage_and_anonymity(source, monkeypatch):
    world, args = source
    monkeypatch.setattr(archive, "_PAGE_SIZE", 2)
    result = archive.load_programme_exit_review_case(**args)
    expected = tuple(
        ProgrammeReviewEntry.objects.filter(case_id=world.case_id)
        .order_by("version")
        .values_list("id", "version", "created_at")
    )
    assert result.evidence_lineage == expected
    assert [row["version"] for row in json.loads(result.evidence_json)] == list(
        range(1, world.version + 1)
    )
    assert result.proposal_id == world.proposal_id
    assert result.policy_id == world.policy_id
    assert result.department_id == world.call.department_id
    assert "contributors" not in json.loads(result.context_json)
    assert str(world.lead.id) not in result.answers_json
    assert "Synthetic proposal lead" not in result.context_json
    assert (
        AuditEvent.objects.filter(
            operation="applications.programme_review.query.exit_case", outcome="allow"
        ).count()
        == 1
    )


def test_native_archive_retains_waitlist_and_final_outgoing_message(
    source, monkeypatch
):
    world, args = source
    assign_and_score(world, world.peer.id)
    world.command(world.moderator.id, Intent(Action.MODERATED, world.case_id))
    for outcome in ("waitlisted", "rejected"):
        world.command(
            world.decider.id,
            Intent(
                Action.DECIDED,
                world.case_id,
                outcome=outcome,
                text=f"Synthetic {outcome} message",
            ),
        )
    monkeypatch.setattr(archive, "_PAGE_SIZE", 1)
    result = archive.load_programme_exit_review_case(**args)
    assert [message.outcome for message in result.decisions] == [
        "waitlisted",
        "rejected",
    ]
    assert result.decisions[0].version < result.decisions[1].version
    assert all(message.acknowledgement_required for message in result.decisions)
    assert "Synthetic rejected message" in result.decisions[1].message


@pytest.mark.parametrize("actor", ["lead", "reviewer"])
def test_native_archive_does_not_bypass_independent_decider_relationship(source, actor):
    world, args = source
    args["request"] = replace(args["request"], actor_id=getattr(world, actor).id)
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        archive.load_programme_exit_review_case(**args)
    assert not AuditEvent.objects.filter(
        operation="applications.programme_review.query.exit_case"
    ).exists()


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "department_id"])
def test_native_case_scope_remains_exact(source, field):
    _world, args = source
    args["request"] = replace(args["request"], **{field: uuid4()})
    with pytest.raises(
        (
            ApplicationsProgrammeAuthorizationDeniedError,
            ProgrammeAuthorizationDeniedError,
        )
    ):
        archive.load_programme_exit_review_case(**args)


def test_native_case_export_still_requires_current_archive_adapter(source, monkeypatch):
    _world, args = source
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: False
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        archive.load_programme_exit_review_case(**args)
