from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

SEED_ACCESS_EMAIL = "marton.pornoi@gmail.com"


class Role(StrEnum):
    ADMIN = "Admin"
    BOARD = "Board"
    EVENT_MANAGER = "Event Manager"
    SECURITY = "Security"
    FURSUIT_SUPPORT = "Fursuit Support"
    THEMEING = "Themeing"
    HOST = "Host"
    VOLUNTEER = "Volunteer"
    REGISTERED_USER = "Registered User"


class AttendeeType(StrEnum):
    ATTENDEE = "Attendee"
    SPONSOR = "Sponsor"
    SUPER_SPONSOR = "Super Sponsor"
    FURSUITER = "Fursuiter"


class Pronouns(StrEnum):
    NOT_SET = ""
    HE_HIM = "he/him"
    SHE_HER = "she/her"
    THEY_THEM = "they/them"
    HE_THEY = "he/they"
    SHE_THEY = "she/they"
    ANY = "any pronouns"
    ASK_ME = "ask me"


class VolunteerType(StrEnum):
    NONE = "None"
    VOLUNTEER = "Volunteer"
    DEPUTY = "Deputy"
    LEAD = "Lead"
    BOARD_MEMBER = "Board Member"


class PermissionKey(StrEnum):
    ACCOUNTS_MANAGE = "accounts.manage"
    PROJECTS_CREATE = "projects.create"
    PROJECT_SETUP_MANAGE = "project.setup.manage"
    PROJECT_ROLES_MANAGE = "project.roles.manage"
    PROJECT_ROLES_ASSIGN = "project.roles.assign"
    PROJECT_LABELS_MANAGE = "project.labels.manage"
    PROJECT_FORMS_MANAGE = "project.forms.manage"
    PROJECT_APPLICATIONS_REVIEW = "project.applications.review"
    PROJECT_TIMETABLE_MANAGE = "project.timetable.manage"
    PROJECT_VOLUNTEERS_MANAGE = "project.volunteers.manage"
    PROJECT_SPACES_MANAGE = "project.spaces.manage"
    PROJECT_STATUSES_MANAGE = "project.statuses.manage"
    PROJECT_FURSUITERS_VALIDATE = "project.fursuiters.validate"
    PROJECT_REGISTRATION_MANAGE = "project.registration.manage"
    PROJECT_EXPORTS_MANAGE = "project.exports.manage"
    PROJECT_SOCIAL_MANAGE = "project.social.manage"
    PROJECT_SIGNAGE_MANAGE = "project.signage.manage"
    PROFILES_PRIVATE_VIEW = "profiles.private.view"


class TicketLevel(StrEnum):
    PENDING = "Pending"
    PAID = "Paid"
    SPONSOR = "Sponsor"
    SUPER_SPONSOR = "Super Sponsor"
    INFINITY = "Infinity"


class FursuiterStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BenefitTarget(StrEnum):
    SPACE_ACCESS = "space_access"
    CHECK_IN = "check_in"
    EXPORT = "export"


FULL_CONTROL_ROLES = frozenset({Role.ADMIN, Role.BOARD})

TICKET_LEVEL_RANK = {
    TicketLevel.PENDING.value: 0,
    TicketLevel.PAID.value: 1,
    TicketLevel.SPONSOR.value: 2,
    TicketLevel.SUPER_SPONSOR.value: 3,
    TicketLevel.INFINITY.value: 4,
}


class SubprojectKind(StrEnum):
    EVENT_SUBMISSION = "event_submission"
    VOLUNTEER_REGISTRATION = "volunteer_registration"
    DJ_APPLICATION = "dj_application"
    DANCE_COMPETITION = "dance_competition"
    GENERIC_APPLICATION = "generic_application"


class FormStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REOPENED = "reopened"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class TimetableRound(StrEnum):
    PRIVATE_PLACEMENT = "private_placement"
    HOST_NEGOTIATION = "host_negotiation"
    PUBLIC = "public"


class TimetableLayer(StrEnum):
    PANELS = "panels"
    VOLUNTEER_SHIFTS = "volunteer_shifts"
    SIGNAGE = "signage"


class AssignmentStatus(StrEnum):
    CLAIMED = "claimed"
    CONFIRMED = "confirmed"
    REMOVED = "removed"


class ExportType(StrEnum):
    PUBLIC_TIMETABLE = "public_timetable"
    PUBLIC_PROFILES = "public_profiles"
    VOLUNTEER_SHIFTS = "volunteer_shifts"
    SIGNAGE_REMINDERS = "signage_reminders"
    ROLE_STATUS = "role_status"


@dataclass(frozen=True)
class AccessAccount:
    email: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    active: bool = True

    def __post_init__(self) -> None:
        normalized = self.email.strip().lower()
        if not normalized.endswith("@gmail.com") and not normalized.endswith(
            "@googlemail.com"
        ):
            msg = "maru accounts must use a Google email address"
            raise ValueError(msg)
        object.__setattr__(self, "email", normalized)

    @property
    def can_start_project(self) -> bool:
        return bool(self.roles & FULL_CONTROL_ROLES)

    @property
    def can_submit_forms(self) -> bool:
        return self.active


@dataclass(frozen=True)
class Project:
    name: str
    slug: str
    timezone: str
    opens_at: str
    closes_at: str


@dataclass(frozen=True)
class Subproject:
    project_slug: str
    name: str
    slug: str
    kind: SubprojectKind
    accepts_reopen_requests: bool = True


@dataclass(frozen=True)
class FormField:
    label: str
    field_type: str
    required: bool = False
    options: tuple[str, ...] = ()

    @property
    def google_forms_key(self) -> str:
        return self.label


@dataclass(frozen=True)
class TimetableVisibility:
    round: TimetableRound

    def can_view_panel(
        self, *, viewer_email: str, owner_email: str, viewer_roles: frozenset[Role]
    ) -> bool:
        if viewer_roles & FULL_CONTROL_ROLES:
            return True
        if self.round == TimetableRound.PRIVATE_PLACEMENT:
            return viewer_email.strip().lower() == owner_email.strip().lower()
        return self.round in {
            TimetableRound.HOST_NEGOTIATION,
            TimetableRound.PUBLIC,
        }

    def exposes_full_timetable_to_registered_users(self) -> bool:
        return self.round == TimetableRound.PUBLIC


def seeded_accounts() -> tuple[AccessAccount, ...]:
    return (
        AccessAccount(
            email=SEED_ACCESS_EMAIL,
            roles=frozenset({Role.ADMIN, Role.BOARD, Role.EVENT_MANAGER}),
        ),
    )
