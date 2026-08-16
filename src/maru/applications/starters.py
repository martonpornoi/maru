"""Code-owned application starter catalogue.

Starters are copied into edition-owned drafts. They never become live shared
definitions, and the attendee registration entry remains owned by
``maru.registration`` under REG-023.
"""
# ruff: noqa: E501, FBT003

from __future__ import annotations

from dataclasses import dataclass

from maru.applications.models import (
    ApplicationClassification,
    ApplicationEligibilityKind,
    ApplicationQuestionType,
    ApplicationSourceBinding,
    ApplicationTargetKind,
)


@dataclass(frozen=True, slots=True)
class StarterQuestion:
    key: str
    label: str
    field_type: str
    purpose: str
    required: bool = False
    classification: str = ApplicationClassification.PERSONAL
    options: tuple[tuple[str, str], ...] = ()
    source_binding: str = ApplicationSourceBinding.NONE
    applicant_writable: bool = True


@dataclass(frozen=True, slots=True)
class ApplicationStarter:
    code: str
    name: str
    description: str
    purpose: str
    owner_module: str
    target_adapter_kind: str | None
    classification: str
    eligibility_kind: str
    minimum_age: int
    maximum_submissions: int
    audience_policy_code: str
    retention_policy_code: str
    age_policy_code: str
    questions: tuple[StarterQuestion, ...]

    @property
    def is_external(self) -> bool:
        return self.target_adapter_kind is None


_C2_AUDIENCE = "applications.c2.applicant-and-assigned-reviewers.v1"
_C2_RETENTION = "applications.c2.edition-support-close.v1"


def _text(
    key: str, label: str, purpose: str, *, required: bool = True
) -> StarterQuestion:
    return StarterQuestion(
        key, label, ApplicationQuestionType.SHORT_TEXT, purpose, required
    )


STARTERS: tuple[ApplicationStarter, ...] = (
    ApplicationStarter(
        code="registration",
        name="Convention registration",
        description="The edition attendee registration workspace.",
        purpose="Register exactly one attendee for an edition.",
        owner_module="registration",
        target_adapter_kind=None,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
        maximum_submissions=1,
        audience_policy_code="registration.edition-profile.v1",
        retention_policy_code="registration.edition-support-close.v1",
        age_policy_code="",
        questions=(),
    ),
    ApplicationStarter(
        code="merch-submission",
        name="T-shirt and merchandise submission",
        description="Collect an edition-owned proposal for convention merchandise.",
        purpose="Review merchandise artwork and product proposals.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.MERCH_SUBMISSION,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
        maximum_submissions=5,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            _text("title", "Submission title", "Identify the merchandise proposal."),
            StarterQuestion(
                "description",
                "Description",
                ApplicationQuestionType.LONG_TEXT,
                "Explain the proposed merchandise.",
                True,
            ),
            StarterQuestion(
                "artwork",
                "Artwork file",
                ApplicationQuestionType.SAFE_FILE,
                "Review a safety-checked proposal file.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="dj-application",
        name="DJ application",
        description="Apply for a DJ set in the edition programme.",
        purpose="Select performers and coordinate a technically feasible DJ set.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.DJ_SET,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
        maximum_submissions=2,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            _text(
                "artist-name",
                "Artist name",
                "Identify the proposed public performer name.",
            ),
            _text(
                "genre",
                "Genres",
                "Help programme reviewers understand the proposed set.",
            ),
            StarterQuestion(
                "set-length",
                "Requested set length in minutes",
                ApplicationQuestionType.INTEGER,
                "Plan a bounded programme slot.",
                True,
            ),
            StarterQuestion(
                "technical-needs",
                "Technical needs",
                ApplicationQuestionType.LONG_TEXT,
                "Prepare programme production requirements.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="fursuit-dance-competition",
        name="Fursuit Dance Competition application",
        description="Apply for the edition Fursuit Dance Competition.",
        purpose="Review a performance entry and prepare its programme placement.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.FURSUIT_DANCE_COMPETITION,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.REGISTERED_ATTENDEE,
        minimum_age=0,
        maximum_submissions=1,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            _text("stage-name", "Stage name", "Identify the performance entry."),
            StarterQuestion(
                "music",
                "Performance music",
                ApplicationQuestionType.SAFE_FILE,
                "Review and prepare the exact performance audio.",
                True,
            ),
            StarterQuestion(
                "duration",
                "Duration in seconds",
                ApplicationQuestionType.INTEGER,
                "Validate programme timing.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="maid-cafe",
        name="Maid Cafe application",
        description="Apply to participate in the edition Maid Cafe.",
        purpose="Select participants and coordinate availability.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.MAID_CAFE,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.REGISTERED_ATTENDEE,
        minimum_age=0,
        maximum_submissions=1,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            _text(
                "character-name",
                "Character name",
                "Identify the proposed cafe character.",
            ),
            StarterQuestion(
                "experience",
                "Relevant experience",
                ApplicationQuestionType.LONG_TEXT,
                "Support participant review.",
                False,
            ),
            StarterQuestion(
                "availability",
                "Availability",
                ApplicationQuestionType.LONG_TEXT,
                "Coordinate service shifts.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="adult-fursuit-striptease",
        name="Adult Fursuit Striptease application",
        description="Restricted adult performance application; local policy is mandatory.",
        purpose="Review and safeguard an explicitly adult programme application.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
        classification=ApplicationClassification.RESTRICTED,
        eligibility_kind=ApplicationEligibilityKind.CONFIRMED_ATTENDEE,
        minimum_age=18,
        maximum_submissions=1,
        audience_policy_code="",
        retention_policy_code="",
        age_policy_code="",
        questions=(
            _text(
                "stage-name", "Stage name", "Identify the restricted performance entry."
            ),
            StarterQuestion(
                "adult-attestation",
                "I meet the edition adult eligibility policy",
                ApplicationQuestionType.BOOLEAN,
                "Record the applicant attestation without storing identity evidence.",
                True,
                ApplicationClassification.RESTRICTED,
            ),
            StarterQuestion(
                "boundaries",
                "Performance boundaries",
                ApplicationQuestionType.LONG_TEXT,
                "Support restricted safeguarding review.",
                True,
                ApplicationClassification.RESTRICTED,
            ),
        ),
    ),
    ApplicationStarter(
        code="volunteer-application",
        name="Volunteer application",
        description="Express interest in edition volunteer work without creating a second registration.",
        purpose="Route a person toward separately governed workforce opportunities.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.VOLUNTEER,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
        maximum_submissions=1,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            StarterQuestion(
                "interests",
                "Areas of interest",
                ApplicationQuestionType.MULTIPLE_CHOICE,
                "Route volunteer interest to relevant teams.",
                True,
                options=(
                    ("operations", "Operations"),
                    ("programme", "Programme"),
                    ("guest-services", "Guest services"),
                ),
            ),
            StarterQuestion(
                "availability",
                "Availability",
                ApplicationQuestionType.LONG_TEXT,
                "Coordinate a possible volunteer assignment.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="feedback",
        name="Feedback collection",
        description="Collect purpose-limited edition feedback.",
        purpose="Improve edition services using accountable feedback handling.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.FEEDBACK,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.EDITION_PARTICIPANT,
        minimum_age=0,
        maximum_submissions=10,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            StarterQuestion(
                "category",
                "Category",
                ApplicationQuestionType.SINGLE_CHOICE,
                "Route feedback to an accountable owner.",
                True,
                options=(
                    ("programme", "Programme"),
                    ("venue", "Venue"),
                    ("registration", "Registration"),
                    ("other", "Other"),
                ),
            ),
            StarterQuestion(
                "feedback",
                "Feedback",
                ApplicationQuestionType.LONG_TEXT,
                "Record the participant feedback.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="idea-submission",
        name="Idea submission",
        description="Submit an edition idea for accountable review.",
        purpose="Collect and route possible improvements or programme ideas.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.IDEA,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
        maximum_submissions=10,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            _text("title", "Idea title", "Identify the idea."),
            StarterQuestion(
                "idea",
                "Idea",
                ApplicationQuestionType.LONG_TEXT,
                "Explain the proposed idea.",
                True,
            ),
        ),
    ),
    ApplicationStarter(
        code="damage-report",
        name="SecOps damage report",
        description="Restricted operational case intake for property damage.",
        purpose="Route a damage report to assigned SecOps case reviewers.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.DAMAGE_REPORT,
        classification=ApplicationClassification.RESTRICTED,
        eligibility_kind=ApplicationEligibilityKind.EDITION_PARTICIPANT,
        minimum_age=0,
        maximum_submissions=20,
        audience_policy_code="",
        retention_policy_code="",
        age_policy_code="",
        questions=(
            _text("location", "Location", "Locate the reported damage."),
            StarterQuestion(
                "observed-at",
                "Observed at",
                ApplicationQuestionType.INSTANT,
                "Order case evidence in time.",
                True,
                ApplicationClassification.RESTRICTED,
            ),
            StarterQuestion(
                "description",
                "What happened",
                ApplicationQuestionType.LONG_TEXT,
                "Record the restricted case report.",
                True,
                ApplicationClassification.RESTRICTED,
            ),
            StarterQuestion(
                "immediate-risk",
                "Immediate risk remains",
                ApplicationQuestionType.BOOLEAN,
                "Prioritize urgent case response.",
                True,
                ApplicationClassification.RESTRICTED,
            ),
        ),
    ),
    ApplicationStarter(
        code="helper-application",
        name="On-site helper application",
        description="Offer bounded on-site help without creating a volunteer position.",
        purpose="Coordinate a person offering help during explicit time windows.",
        owner_module="applications",
        target_adapter_kind=ApplicationTargetKind.HELPER,
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.REGISTERED_ATTENDEE,
        minimum_age=0,
        maximum_submissions=5,
        audience_policy_code=_C2_AUDIENCE,
        retention_policy_code=_C2_RETENTION,
        age_policy_code="",
        questions=(
            StarterQuestion(
                "name",
                "Name",
                ApplicationQuestionType.SHORT_TEXT,
                "Identify the helper from their account.",
                True,
                source_binding=ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME,
                applicant_writable=False,
            ),
            StarterQuestion(
                "telegram",
                "Telegram contact",
                ApplicationQuestionType.SHORT_TEXT,
                "Use the attendee-provided Telegram contact for coordination.",
                True,
                source_binding=ApplicationSourceBinding.REGISTRATION_TELEGRAM,
                applicant_writable=False,
            ),
            StarterQuestion(
                "available-from",
                "Available from",
                ApplicationQuestionType.INSTANT,
                "Open the helper time window.",
                True,
            ),
            StarterQuestion(
                "available-until",
                "Available until",
                ApplicationQuestionType.INSTANT,
                "Close the helper time window.",
                True,
            ),
            StarterQuestion(
                "offer",
                "What can you help with?",
                ApplicationQuestionType.LONG_TEXT,
                "Route the bounded helper offer.",
                True,
            ),
        ),
    ),
)

STARTERS_BY_CODE = {starter.code: starter for starter in STARTERS}


def application_starter(code: str) -> ApplicationStarter | None:
    return STARTERS_BY_CODE.get(code)


def starter_catalog() -> tuple[ApplicationStarter, ...]:
    return STARTERS
