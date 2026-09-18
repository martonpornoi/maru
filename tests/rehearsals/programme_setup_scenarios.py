"""Real-owner synthetic setup composition; not human approval or browser acceptance."""

from __future__ import annotations

import json
import re
import secrets
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)

_CHANNEL = "programme_rehearsal"
_REASON = "Synthetic isolated Programme rehearsal; no real convention authority."
SETUP_MODES = ("new_foundation", "existing_organization", "existing_series")


class ProgrammeSetupScenarioError(RuntimeError):
    """Expose stable stage failures without credentials or private mail contents."""


@dataclass(frozen=True, slots=True)
class SyntheticProgrammePerson:
    """Separate authenticated synthetic identity, never a representative human."""

    account_id: UUID
    email: str
    password: str = field(repr=False)

    def authenticate(self):
        """Reauthenticate through the actual backend before each attributed action."""
        from django.contrib.auth import authenticate  # noqa: PLC0415

        account = authenticate(username=self.email, password=self.password)
        if (
            account is None
            or account.id != self.account_id
            or not account.is_active
            or not account.has_verified_email
            or account.is_platform_administrator
        ):
            raise ProgrammeSetupScenarioError("synthetic_person_unavailable")
        return account


@dataclass(frozen=True, slots=True)
class ProgrammeSetupScenario:
    """Owned setup identities and private personas, not an acceptance receipt."""

    mode: str
    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    department_id: UUID
    representation_id: UUID
    representation_code: str
    setup_receipt_id: UUID
    controllers: tuple[SyntheticProgrammePerson, SyntheticProgrammePerson] = field(
        repr=False
    )
    intake_person: SyntheticProgrammePerson = field(repr=False)
    role_assignment_ids: tuple[UUID, ...]


def _verification_token(messages, *, email, origin):
    matching = [message for message in messages if message.to == [email]]
    if len(matching) != 1:
        raise ProgrammeSetupScenarioError("synthetic_verification_mail_unavailable")
    links = [line.strip() for line in matching[0].body.splitlines() if "://" in line]
    if len(links) != 1:
        raise ProgrammeSetupScenarioError("synthetic_verification_link_unavailable")
    try:
        parsed = urlsplit(links[0])
        expected = urlsplit(origin)
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        raise ProgrammeSetupScenarioError(
            "synthetic_verification_link_unavailable"
        ) from None
    if (
        parsed.scheme != "https"
        or (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc)
        or parsed.path != "/accounts/verify-email/"
        or parsed.fragment
        or set(query) != {"token"}
        or len(query["token"]) != 1
        or not query["token"][0]
    ):
        raise ProgrammeSetupScenarioError("synthetic_verification_link_unavailable")
    return query["token"][0]


def _create_person(label, *, run_id):
    from django.conf import settings  # noqa: PLC0415
    from django.core import mail  # noqa: PLC0415
    from django.test import RequestFactory  # noqa: PLC0415

    from maru.identity.models import IdentityChallenge  # noqa: PLC0415
    from maru.identity.services import (  # noqa: PLC0415
        bootstrap_account,
        consume_identity_challenge,
        request_fingerprint,
    )

    email = f"programme-{label}-{run_id}@example.invalid"
    password = secrets.token_urlsafe(32)
    before = len(getattr(mail, "outbox", []))
    account, dispatch = bootstrap_account(
        email=email,
        display_name=f"Synthetic Programme {label}",
        password=password,
        fingerprint=request_fingerprint(
            RequestFactory().post(
                "/accounts/sign-up/",
                secure=True,
                HTTP_HOST="127.0.0.1",
                HTTP_USER_AGENT="Maru isolated synthetic setup",
            ),
            contact=email,
        ),
        source_channel=_CHANNEL,
    )
    if account is None or account.has_verified_email or dispatch.raw_token is not None:
        raise ProgrammeSetupScenarioError("synthetic_bootstrap_contract_changed")
    token = _verification_token(
        mail.outbox[before:], email=email, origin=settings.MARU_PUBLIC_BASE_URL
    )
    verified = consume_identity_challenge(
        raw_token=token,
        purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
        source_channel=_CHANNEL,
    )
    if verified.id != account.id:
        raise ProgrammeSetupScenarioError("synthetic_verification_subject_changed")
    person = SyntheticProgrammePerson(account.id, email, password)
    person.authenticate()
    return person


def _activate_root(administrator, *, organization_id, representation_id, people):
    from maru.organizations.programme_setup_references import (  # noqa: PLC0415
        resolve_programme_setup_foundation,
    )
    from maru.organizations.representation import (  # noqa: PLC0415
        activate_representation,
        invite_representation_controller,
        respond_to_representation_invitation,
    )

    if len({person.account_id for person in people}) != 2:
        raise ProgrammeSetupScenarioError("synthetic_controllers_not_independent")
    for person in people:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation_id,
            account_id=person.account_id,
            reason=_REASON,
            correlation_id=uuid4(),
            source_channel=_CHANNEL,
        )
        respond_to_representation_invitation(
            actor=person.authenticate(),
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel=_CHANNEL,
        )
    reference = resolve_programme_setup_foundation(organization_id=organization_id)
    if reference is None or reference.representation_id != representation_id:
        raise ProgrammeSetupScenarioError("synthetic_representation_unavailable")
    activate_representation(
        actor=administrator,
        representation_id=representation_id,
        expected_version=reference.representation_version,
        reason=_REASON,
        correlation_id=uuid4(),
        source_channel=_CHANNEL,
    )


def _approve_initial_roles(result, *, people, intake_person):
    from maru.authorization.catalog import ScopeLevel  # noqa: PLC0415

    return tuple(
        approve_synthetic_role(
            result,
            people=people,
            recipient=recipient,
            code=code,
            level=level,
            department_id=department,
        )
        for code, level, recipient, department in (
            ("edition-coordination", ScopeLevel.EDITION, people[0], None),
            ("intake", ScopeLevel.DEPARTMENT, intake_person, result.department_id),
        )
    )


def approve_synthetic_role(
    setup, *, people, recipient, code, level, department_id=None
):
    """Request then independently approve one existing immutable scoped recipe."""
    from django.utils import timezone  # noqa: PLC0415

    from maru.authorization.programme_role_commands import (  # noqa: PLC0415
        decide_programme_role,
        request_programme_role,
    )
    from maru.authorization.programme_role_inputs import (  # noqa: PLC0415
        ProgrammeRoleDecision,
        ProgrammeRoleIntent,
        ProgrammeRoleScope,
    )

    scope = ProgrammeRoleScope(
        setup.organization_id, setup.edition_id, level, department_id=department_id
    )
    request = request_programme_role(
        actor=people[0].authenticate(),
        scope=scope,
        details=ProgrammeRoleIntent(
            code,
            1,
            recipient.account_id,
            people[1].account_id,
            None,
            timezone.now() + timedelta(hours=1),
            _REASON,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_CHANNEL,
    )
    decision = decide_programme_role(
        actor=people[1].authenticate(),
        scope=scope,
        request_id=request.request_id,
        action=ProgrammeRoleDecision.APPROVE,
        reason=_REASON,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel=_CHANNEL,
    )
    if decision.role_assignment_id is None:
        raise ProgrammeSetupScenarioError("synthetic_role_not_granted")
    return decision.role_assignment_id


def _require_fresh_database():
    from django.db import connection  # noqa: PLC0415

    from maru.events.models import EventEdition  # noqa: PLC0415
    from maru.identity.models import Account  # noqa: PLC0415
    from maru.organizations.models import Organization  # noqa: PLC0415

    if (
        connection.in_atomic_block
        or not connection.get_autocommit()
        or Organization.objects.exists()
        or EventEdition.objects.exists()
        or Account.objects.count() != 1
    ):
        raise ProgrammeSetupScenarioError("synthetic_setup_requires_fresh_database")


def prepare_setup_scenario(*, mode, administrator_password):
    """Execute one closed setup mode on a genuinely ready empty owned candidate.

    Parameters
    ----------
    mode
        New foundation, existing organization with fictional Executive Board, or
        existing series with Maru operators. Only the three literal modes exist.
    administrator_password
        Ephemeral bootstrap secret passed in memory, never logged or installed in
        the web environment. Every ordinary person's password is independently made.

    Returns
    -------
    ProgrammeSetupScenario
        Original owned identities and redacted separate synthetic-person handles.
        Direct owner calls do not establish browser or representative-human evidence.

    Notes
    -----
    No fixture model factory, raw authority write, fake email verification,
    substituted policy, all-capability role or outer atomic rollback is used.
    Any partial failure requires disposal of this owned database, not adopted retry.
    """
    environment = require_programme_runtime_environment()
    if mode not in SETUP_MODES:
        raise ProgrammeSetupScenarioError("invalid_synthetic_setup_mode")
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    build_candidate_application()
    from django.contrib.auth import authenticate  # noqa: PLC0415

    from maru.events.programme_setup import setup_programme_foundation  # noqa: PLC0415
    from maru.events.programme_setup_inputs import ProgrammeSetupInput  # noqa: PLC0415
    from maru.identity.queries import (  # noqa: PLC0415
        current_platform_administrator_is_available,
    )
    from maru.organizations.programme_setup_references import (  # noqa: PLC0415
        resolve_programme_setup_foundation,
    )
    from maru.organizations.representation import (  # noqa: PLC0415
        provision_executive_board,
        provision_maru_operators,
    )
    from maru.organizations.services import (  # noqa: PLC0415
        ConventionSeriesCreationDetails,
        OrganizationCreationDetails,
        create_convention_series,
        create_draft_organization,
    )

    administrator = authenticate(
        username=f"programme-platform-{environment.run_id}@example.invalid",
        password=administrator_password,
    )
    if (
        administrator is None
        or not administrator.is_active
        or not administrator.is_platform_administrator
        or not current_platform_administrator_is_available(account_id=administrator.id)
    ):
        raise ProgrammeSetupScenarioError("synthetic_administrator_unavailable")
    _require_fresh_database()
    people = tuple(
        _create_person(label, run_id=environment.run_id)
        for label in ("controller-a", "controller-b")
    )
    intake_person = _create_person("intake", run_id=environment.run_id)
    organization_id = series_id = None
    original = None
    if mode != "new_foundation":
        organization = create_draft_organization(
            actor=administrator,
            details=OrganizationCreationDetails(name="Synthetic Programme organizer"),
            correlation_id=uuid4(),
            source_channel=_CHANNEL,
        )
        organization_id = organization.id
        provision = (
            provision_executive_board
            if mode == "existing_organization"
            else provision_maru_operators
        )
        representation = provision(
            actor=administrator,
            organization_id=organization_id,
            reason=_REASON,
            correlation_id=uuid4(),
            source_channel=_CHANNEL,
        )
        _activate_root(
            administrator,
            organization_id=organization_id,
            representation_id=representation.id,
            people=people,
        )
        if mode == "existing_series":
            series = create_convention_series(
                actor=administrator,
                organization_id=organization_id,
                details=ConventionSeriesCreationDetails(
                    name="Synthetic existing series"
                ),
                correlation_id=uuid4(),
                source_channel=_CHANNEL,
            )
            series_id = series.id
        original = resolve_programme_setup_foundation(
            organization_id=organization_id, series_id=series_id
        )
        if original is None:
            raise ProgrammeSetupScenarioError("synthetic_foundation_unavailable")
    today = datetime.now(ZoneInfo("Europe/Budapest")).date()
    details = ProgrammeSetupInput(
        mode=mode,
        edition_name="Synthetic Programme rehearsal",
        department_name="Programme",
        starts_on=today + timedelta(days=7),
        ends_on=today + timedelta(days=9),
        time_zone="Europe/Budapest",
        reason=_REASON,
        organization_name="Synthetic Programme organizer"
        if organization_id is None
        else "",
        series_name="Synthetic Programme series" if series_id is None else "",
        organization_id=organization_id,
        series_id=series_id,
        foundation_fingerprint=original.fingerprint if original is not None else "",
    )
    key = uuid4()
    result = setup_programme_foundation(
        actor=administrator,
        details=details,
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel=_CHANNEL,
    )
    replay = setup_programme_foundation(
        actor=administrator,
        details=details,
        idempotency_key=key,
        correlation_id=uuid4(),
        source_channel=_CHANNEL,
    )
    if not replay.replayed or replay.receipt_id != result.receipt_id:
        raise ProgrammeSetupScenarioError("synthetic_setup_retry_changed")
    if original is None:
        _activate_root(
            administrator,
            organization_id=result.organization_id,
            representation_id=result.representation_id,
            people=people,
        )
    reference = resolve_programme_setup_foundation(
        organization_id=result.organization_id, series_id=result.series_id
    )
    if reference is None or reference.representation_state != "active":
        raise ProgrammeSetupScenarioError("synthetic_representation_not_active")
    if original is not None and (
        reference.representation_id != original.representation_id
        or reference.representation_code != original.representation_code
        or reference.representation_version != original.representation_version
    ):
        raise ProgrammeSetupScenarioError("synthetic_existing_root_changed")
    assignments = _approve_initial_roles(
        result, people=people, intake_person=intake_person
    )
    return ProgrammeSetupScenario(
        mode,
        result.organization_id,
        result.series_id,
        result.edition_id,
        result.department_id,
        result.representation_id,
        reference.representation_code,
        result.receipt_id,
        people,
        intake_person,
        assignments,
    )


def person_from_document(value):
    """Decode the fixed synthetic-person pipe shape, not a credential from a UI."""
    if (
        set(value) != {"account_id", "email", "password"}
        or not value["email"].endswith("@example.invalid")
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", value["password"]) is None
    ):
        raise ValueError
    return SyntheticProgrammePerson(
        UUID(value["account_id"]), value["email"], value["password"]
    )


def _decode_scenario(document, mode):
    if document["mode"] != mode or mode not in SETUP_MODES:
        raise ValueError

    controllers = tuple(
        person_from_document(value) for value in document["controllers"]
    )
    intake = person_from_document(document["intake_person"])
    if (
        len(controllers) != 2
        or len({value.account_id for value in (*controllers, intake)}) != 3
    ):
        raise ValueError
    result = ProgrammeSetupScenario(
        **{
            key: UUID(value) if key.endswith("_id") else value
            for key, value in document.items()
            if key not in {"controllers", "intake_person", "role_assignment_ids"}
        },
        controllers=controllers,
        intake_person=intake,
        role_assignment_ids=tuple(
            UUID(value) for value in document["role_assignment_ids"]
        ),
    )
    if len(result.role_assignment_ids) != 2 or result.representation_code != (
        "executive_board" if mode == "existing_organization" else "maru_operators"
    ):
        raise ValueError
    return result


def scenario_from_document(document, *, mode):
    """Decode only the fixed child result, preserving private fields outside repr."""
    try:
        result = _decode_scenario(document, mode)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProgrammeSetupScenarioError("synthetic_setup_result_invalid") from None
    return result


def _read_setup_input():
    raw = sys.stdin.read(4097)
    if len(raw) > 4096:
        raise ValueError
    document = json.loads(raw)
    if (
        set(document) != {"mode", "administrator_password"}
        or document["mode"] not in SETUP_MODES
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", document["administrator_password"])
        is None
    ):
        raise ValueError
    return document


def _main():
    # A dedicated pipe carries only this owned fixture's secret. No password in
    # command-line arguments, environment, files, tracebacks or public readiness.
    require_programme_runtime_environment()
    try:
        result = prepare_setup_scenario(**_read_setup_input())
    except Exception:  # noqa: BLE001 - final private child protocol boundary
        # The parent receives a stable stage code, never private owner/mail errors.
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(asdict(result), default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
