"""Compose real P02 owner commands; never substitute authority or file scanning."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from uuid import UUID, uuid4

from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)
from tests.rehearsals.programme_setup_scenarios import (
    ProgrammeSetupScenario,
    SyntheticProgrammePerson,
    _create_person,
    person_from_document,
    scenario_from_document,
)

CHANNEL = "programme_rehearsal"
REASON = "Synthetic isolated Programme proposal; no real convention submission."
CONSENT = "applications.programme.contributor-consent.v1"


class ProgrammeProposalScenarioError(RuntimeError):
    """Expose only a stable checkpoint code, never credentials or private answers."""


@dataclass(frozen=True, slots=True)
class ProgrammeProposalScenario:
    """Retain exact owner identifiers and private personas for subsequent stages."""

    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    call_id: UUID
    definition_id: UUID
    proposal_id: UUID
    revision_id: UUID
    version: int
    upload_command_receipt_id: UUID
    lead: SyntheticProgrammePerson = field(repr=False)
    collaborator: SyntheticProgrammePerson = field(repr=False)


def synthetic_supporting_pdf():
    """Build a tiny self-contained fictional PDF with actual byte-offset xrefs."""
    stream = (
        b"BT /F1 12 Tf 24 100 Td (Synthetic Programme supporting document.) Tj ET\n"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    )
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    start = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(start).encode()
        + b"\n%%EOF\n"
    )
    return bytes(data)


def _definition_and_configuration(setup):
    from django.utils import timezone  # noqa: PLC0415

    from maru.applications import programme_inputs as inputs  # noqa: PLC0415

    def question(key, kind, position):
        text = kind == inputs.ProgrammeCallQuestionType.SHORT_TEXT
        return inputs.ProgrammeCallQuestionInput(
            key=key,
            field_type=kind,
            label=key.replace("-", " ").title(),
            help_text="Fictional rehearsal material only.",
            position=position,
            required=True,
            options=(),
            minimum_length=3 if text else None,
            maximum_length=160 if text else None,
            minimum_value=None,
            maximum_value=None,
            maximum_choices=None,
            reference_kind="",
            condition=None,
            purpose="Assess a fictional Programme proposal.",
            classification=inputs.ProgrammeCallClassification.PERSONAL,
            retention_policy_code="",
        )

    now = timezone.now()
    definition = inputs.ProgrammeCallDefinitionInput(
        code="integrated-programme",
        name="Synthetic Programme proposals",
        description="One fictional call for integrated acceptance.",
        purpose="Prepare an exact acknowledged synthetic proposal.",
        classification=inputs.ProgrammeCallClassification.PERSONAL,
        maximum_submissions_per_person=4,
        opens_at=now - timedelta(minutes=1),
        applicant_edit_until=now + timedelta(days=1),
        closes_at=now + timedelta(days=2),
        audience_policy_code="applications.programme.audience.v1",
        retention_policy_code="applications.programme.retention.v1",
        sections=(
            inputs.ProgrammeCallSectionInput(
                key="proposal",
                title="Proposal",
                help_text="Synthetic material only.",
                position=1,
                questions=(
                    question(
                        "session-title", inputs.ProgrammeCallQuestionType.SHORT_TEXT, 1
                    ),
                    question(
                        "supporting-pdf", inputs.ProgrammeCallQuestionType.SAFE_FILE, 2
                    ),
                ),
            ),
        ),
    )
    configuration = inputs.ProgrammeCallConfigurationInput(
        owner_department_id=setup.department_id,
        maximum_collaborators=4,
        content_policy_code="applications.programme.content.v1",
        contributor_consent_policy_code=CONSENT,
        collaboration_retention_policy_code="applications.programme.collaboration-retention.v1",
        tracks=(
            inputs.ProgrammeCallTrackInput(
                code="general",
                label="General Programme",
                description="Synthetic track.",
                position=1,
            ),
        ),
        formats=(
            inputs.ProgrammeCallFormatInput(
                code="session",
                label="Session",
                description="Synthetic session.",
                position=1,
                minimum_duration_minutes=30,
                default_duration_minutes=60,
                maximum_duration_minutes=90,
            ),
        ),
        contributor_fields=(
            inputs.ProgrammeCallContributorFieldInput(
                field_code=inputs.ProgrammeContributorFieldCode.PUBLIC_NAME,
                lead_requirement=inputs.ProgrammeContributorFieldRequirement.REQUIRED,
                collaborator_requirement=inputs.ProgrammeContributorFieldRequirement.REQUIRED,
                position=1,
            ),
        ),
    )
    return definition, configuration


def _profile(name):
    from maru.applications.programme_inputs import (  # noqa: PLC0415
        ProgrammeProposalContributorProfileInput,
    )

    return ProgrammeProposalContributorProfileInput(
        public_name=name,
        biography="",
        pronouns="",
        website="",
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code=CONSENT,
    )


def _query_scope(setup, person):
    return {
        "actor_id": person.authenticate().id,
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
        "correlation_id": uuid4(),
        "source_channel": CHANNEL,
    }


def _command(command, setup, person, version, **values):
    return command(
        **_query_scope(setup, person),
        expected_version=version,
        reason=REASON,
        retry_key=uuid4(),
        **values,
    )


def _upload(setup, lead, proposal_id, version, configuration, question):
    from maru.applications.programme_file_commands import (  # noqa: PLC0415
        get_programme_file_upload_result,
        upload_and_use_programme_file,
    )
    from maru.applications.programme_reference_sources import (  # noqa: PLC0415
        ProgrammeAnswerReferenceIntent,
        ProgrammeAnswerReferenceRequest,
    )

    request = ProgrammeAnswerReferenceRequest(
        **_query_scope(setup, lead),
        proposal_id=proposal_id,
        question_id=question.question_id,
    )
    intent = ProgrammeAnswerReferenceIntent(
        version,
        configuration.summary.aggregate_version,
        configuration.summary.version,
        uuid4(),
    )
    result = upload_and_use_programme_file(
        request=request,
        intent=intent,
        read_bytes=synthetic_supporting_pdf,
    )
    lead.authenticate()
    replay = get_programme_file_upload_result(request=request, intent=intent)
    if replay != replace(result, replayed=True):
        raise ProgrammeProposalScenarioError("synthetic_upload_replay_changed")
    return result


def _compose_proposal(setup, *, run_id):
    from django.utils import timezone  # noqa: PLC0415

    from maru.applications import programme_commands as commands  # noqa: PLC0415
    from maru.applications import programme_inputs as inputs  # noqa: PLC0415
    from maru.applications import programme_queries as queries  # noqa: PLC0415
    from maru.applications.programme_personal_queries import (  # noqa: PLC0415
        get_self_programme_frozen_revision,
    )

    lead = _create_person("proposal-lead", run_id=run_id)
    collaborator = _create_person("proposal-collaborator", run_id=run_id)
    definition, configuration = _definition_and_configuration(setup)
    call = _command(
        commands.create_programme_call,
        setup,
        setup.intake_person,
        0,
        definition_input=definition,
        configuration=configuration,
    )
    _command(
        commands.activate_programme_call,
        setup,
        setup.intake_person,
        call.resulting_version,
        call_id=call.target_id,
        owner_department_id=setup.department_id,
    )
    configured = queries.get_managed_programme_call_configuration(
        **_query_scope(setup, setup.intake_person),
        department_id=setup.department_id,
        call_id=call.target_id,
    )
    available = queries.available_programme_calls(**_query_scope(setup, lead))
    if len(available) != 1 or available[0].summary.call_id != call.target_id:
        raise ProgrammeProposalScenarioError("synthetic_call_discovery_changed")
    discovered = available[0]
    proposal = _command(
        commands.start_programme_proposal,
        setup,
        lead,
        0,
        call_id=call.target_id,
        selection=inputs.ProgrammeProposalSelectionInput(
            track_id=discovered.tracks[0].track_id,
            format_id=discovered.formats[0].format_id,
            requested_duration_minutes=60,
        ),
        lead_profile=_profile("Synthetic proposal lead"),
    )
    proposal_id = proposal.target_id
    questions = {q.key: q for section in configured.sections for q in section.questions}
    answer = _command(
        commands.append_programme_proposal_answer,
        setup,
        lead,
        proposal.resulting_version,
        proposal_id=proposal_id,
        question_id=questions["session-title"].question_id,
        value="Fictional convention opening workshop",
    )
    upload = _upload(
        setup,
        lead,
        proposal_id,
        answer.resulting_version,
        configured,
        questions["supporting-pdf"],
    )
    invitation = _command(
        commands.invite_programme_proposal_collaborator,
        setup,
        lead,
        upload.resulting_version,
        proposal_id=proposal_id,
        invitation=inputs.ProgrammeProposalInvitationInput(
            invitee_email=collaborator.email,
            expires_at=timezone.now() + timedelta(hours=1),
        ),
    )
    accepted = _command(
        commands.accept_programme_proposal_invitation,
        setup,
        collaborator,
        invitation.resulting_version,
        proposal_id=proposal_id,
    )
    profiled = _command(
        commands.revise_programme_contributor_profile,
        setup,
        collaborator,
        accepted.resulting_version,
        proposal_id=proposal_id,
        profile=_profile("Synthetic proposal collaborator"),
    )
    sealed = _command(
        commands.seal_programme_proposal,
        setup,
        lead,
        profiled.resulting_version,
        proposal_id=proposal_id,
    )
    version = sealed.resulting_version
    for person in (lead, collaborator):
        frozen = get_self_programme_frozen_revision(
            **_query_scope(setup, person),
            proposal_id=proposal_id,
            revision_id=sealed.target_id,
        )
        responded = _command(
            commands.respond_to_programme_proposal_revision,
            setup,
            person,
            version,
            proposal_id=proposal_id,
            response=inputs.ProgrammeProposalRevisionResponseInput(
                revision_id=sealed.target_id,
                contributor_id=frozen.own_contributor_id,
                profile_revision_id=frozen.own_profile.profile_revision_id,
                decision=inputs.ProgrammeProposalRevisionResponseDecision.ACKNOWLEDGED,
            ),
        )
        version = responded.resulting_version
    submitted = _command(
        commands.submit_programme_proposal,
        setup,
        lead,
        version,
        proposal_id=proposal_id,
        revision_id=sealed.target_id,
    )
    frozen = get_self_programme_frozen_revision(
        **_query_scope(setup, lead),
        proposal_id=proposal_id,
        revision_id=sealed.target_id,
    )
    if (
        not frozen.revision.submitted
        or frozen.summary.aggregate_version != submitted.resulting_version
    ):
        raise ProgrammeProposalScenarioError("synthetic_submission_not_current")
    return ProgrammeProposalScenario(
        setup.organization_id,
        setup.edition_id,
        setup.department_id,
        call.target_id,
        call.definition_id,
        proposal_id,
        sealed.target_id,
        submitted.resulting_version,
        upload.receipt_id,
        lead,
        collaborator,
    )


def prepare_proposal_scenario(setup):
    """Submit one real acknowledged proposal on an already guarded owned setup.

    Parameters
    ----------
    setup
        Exact private setup result from the same isolated runtime. All ordinary
        owner authorization, native guards, scanner custody and audit remain on.

    Returns
    -------
    ProgrammeProposalScenario
        Exact submitted revision and private personas, not browser/human evidence.

    Notes
    -----
    No factory, direct data write, supplied authorizer, synthetic clock or scanner
    receipt is used. Partial failure requires disposing the fixture, not adopting
    partially completed state. The caller retains the original lease deadline.
    """
    environment = require_programme_runtime_environment()
    if type(setup) is not ProgrammeSetupScenario:
        raise ProgrammeProposalScenarioError("synthetic_setup_handle_required")
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    return _compose_proposal(setup, run_id=environment.run_id)


def _decode_proposal(document, setup):
    people = {
        key: person_from_document(document[key]) for key in ("lead", "collaborator")
    }
    result = ProgrammeProposalScenario(
        **{
            key: UUID(value) if key.endswith("_id") else value
            for key, value in document.items()
            if key not in people
        },
        **people,
    )
    if (
        (result.organization_id, result.edition_id, result.department_id)
        != (setup.organization_id, setup.edition_id, setup.department_id)
        or type(result.version) is not int
        or result.version < 1
        or len(
            {
                result.lead.account_id,
                result.collaborator.account_id,
                setup.intake_person.account_id,
                *[p.account_id for p in setup.controllers],
            }
        )
        != 5
    ):
        raise ValueError
    return result


def proposal_from_document(document, *, setup):
    """Decode only an exact same-scope child result; keep credentials out of repr."""
    try:
        return _decode_proposal(document, setup)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProgrammeProposalScenarioError(
            "synthetic_proposal_result_invalid"
        ) from None


def _read_setup():
    raw = sys.stdin.read(16_385)
    if len(raw) > 16_384:
        raise ValueError
    document = json.loads(raw)
    return scenario_from_document(document, mode=document["mode"])


def _main():
    require_programme_runtime_environment()
    try:
        result = prepare_proposal_scenario(_read_setup())
    except Exception:  # noqa: BLE001 - private fixed child protocol boundary
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
