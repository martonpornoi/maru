"""Prepare a fresh, local-only convention demo using the owning commands.

This is synthetic fixture preparation, not proof of independent human approval.
The launcher owns database creation and disposal. Existing data is never reset.
"""

import os
from collections.abc import Callable
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import connection, transaction
from django.utils import timezone

from maru.announcements import commands as announcements
from maru.announcements.contracts import (
    AnnouncementCommandRequest,
    AnnouncementDraftInput,
    AnnouncementSettingsInput,
    AnnouncementVariantInput,
    ManualChannel,
)
from maru.authorization.commands import grant_capability_direct
from maru.authorization.database_role_safety import probe_runtime_database_role_safety
from maru.authorization.guidance_access import (
    request_guidance_access,
    respond_to_guidance_access,
)
from maru.authorization.guidance_access_queries import load_guidance_access_request
from maru.authorization.policy import resolve_edition_target
from maru.demo.convention_plan import (
    ACCOUNT_KEYS,
    ANNOUNCEMENT_EXAMPLES,
    CONTENT_ROLES,
    DEMO_ZONE,
    GUIDE_EXAMPLES,
    PREPARATION_REASON,
    DemoEdition,
    account_identity,
    edition_plan,
)
from maru.events.announcements_adoption import (
    AnnouncementsAdoptionSetupResult,
    set_up_announcements_adoption,
)
from maru.events.announcements_setup_inputs import (
    AnnouncementsAdoptionSetupInput,
    AnnouncementsSetupMode,
)
from maru.events.guidance_activation import (
    apply_guidance_activation,
    propose_guidance_activation,
    respond_to_guidance_activation,
)
from maru.events.guidance_activation_queries import load_guidance_activation_start
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.knowledge import commands as guides
from maru.knowledge.contracts import (
    GuidanceCommandRequest,
    GuidanceDraftInput,
    GuidanceSettingsInput,
)
from maru.organizations.announcements_setup_references import (
    resolve_announcements_setup_foundation,
)
from maru.organizations.models import Organization
from maru.organizations.representation import (
    activate_representation,
    invite_representation_controller,
    respond_to_representation_invitation,
)

CHANNEL = "synthetic-convention-demo"
_LOCK_KEY = 603946035146849
_ANNOUNCEMENT_ROLES = {
    "author": ("announcements.view", "announcements.compose"),
    "reviewer": ("announcements.view", "announcements.review"),
    "reader": (),  # Announcements view includes private working history.
}
_GUIDE_ROLES = {
    "author": "guidance-editor",
    "reviewer": "guidance-reviewer",
    "reader": "guidance-reader",
}


class ConventionDemoConflictError(RuntimeError):
    """Refuse an existing, mixed, partial or unsafe fixture without changing it."""


def require_demo_environment() -> None:
    """Refuse production settings, non-loopback databases and implicit invocation.

    Raises
    ------
    ConventionDemoConflictError
        If this is not an explicitly selected local/test preview.
    """
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE")
        not in {"maru.settings.local", "maru.settings.test"}
        or os.environ.get("MARU_SYNTHETIC_CONVENTION_DEMO") != "true"
        or connection.vendor != "postgresql"
        or connection.settings_dict.get("HOST") not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ConventionDemoConflictError(
            "Use the disposable local convention preview."
        )


def _lock_empty_foundation() -> None:
    """Serialize fixture preparation and refuse any existing organization.

    Raises
    ------
    ConventionDemoConflictError
        If this database already contains a fixture or organization.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
    if Organization.objects.exists():
        raise ConventionDemoConflictError(
            "This database already contains data. Keep its edits or start"
            " a fresh preview."
        )


def _account_plan(
    scenario: Literal["convention", "workforce"],
) -> tuple[tuple[str, ...], Callable[[str], tuple[UUID, str]]]:
    if scenario == "workforce":
        from maru.demo import workforce_plan  # noqa: PLC0415 -- explicit scenario

        return workforce_plan.ACCOUNT_KEYS, workforce_plan.account_identity
    if scenario != "convention":
        raise ConventionDemoConflictError("Unknown local practice scenario.")
    return ACCOUNT_KEYS, account_identity


def bootstrap_demo_accounts(
    passwords: dict[str, str],
    *,
    scenario: Literal["convention", "workforce"] = "convention",
) -> None:
    """Create only the reserved synthetic identities in an empty database.

    Parameters
    ----------
    passwords : dict[str, str]
        Fresh in-memory credentials for the exact closed account set.
    scenario : Literal['convention', 'workforce'], default='convention'
        Explicit separate dataset; the existing Announcements/Guides default is fixed.

    Raises
    ------
    ConventionDemoConflictError
        If identities already exist or the credential set is incomplete.
    """
    require_demo_environment()
    keys, identity_for = _account_plan(scenario)
    if set(passwords) != set(keys):
        raise ConventionDemoConflictError("Provide the complete synthetic account set.")
    for password in passwords.values():
        validate_password(password)
    with transaction.atomic():
        _lock_empty_foundation()
        if Account.objects.exists():
            raise ConventionDemoConflictError("Existing accounts must not be replaced.")
        for key in keys:
            identity, email = identity_for(key)
            create = (
                Account.objects.create_superuser
                if key == "platform"
                else Account.objects.create_user
            )
            create(
                id=identity,
                email=email,
                password=passwords[key],
                display_name=f"Maru demo {key.replace('-', ' ')}",
                preferred_language="en",
                email_verified_at=timezone.now(),
            )


def _actors(
    *, scenario: Literal["convention", "workforce"] = "convention"
) -> dict[str, Account]:
    """Load the exact fixture identities without adopting collisions.

    Parameters
    ----------
    scenario : Literal['convention', 'workforce'], default='convention'
        Exact closed dataset, never a caller-provided identity resolver.

    Returns
    -------
    dict[str, Account]
        Reserved active and verified synthetic actors.

    Raises
    ------
    ConventionDemoConflictError
        If another account exists or any reserved identity changed.
    """
    keys, identity_for = _account_plan(scenario)
    accounts = {row.id: row for row in Account.objects.select_for_update().all()}
    if len(accounts) != len(keys):
        raise ConventionDemoConflictError("The synthetic account inventory differs.")
    result = {}
    for key in keys:
        identity, email = identity_for(key)
        account = accounts.get(identity)
        platform = key == "platform"
        if (
            account is None
            or account.email != email
            or not account.is_active
            or account.email_verified_at is None
            or not account.has_usable_password()
            or account.is_staff != platform
            or account.is_superuser != platform
            or account.account_kind
            != ("platform_administrator" if platform else "person")
        ):
            raise ConventionDemoConflictError("A reserved synthetic identity differs.")
        result[key] = account
    return result


def _foundation(
    platform: Account,
    plans: tuple[DemoEdition, DemoEdition],
) -> tuple[AnnouncementsAdoptionSetupResult, ...]:
    """Create two editions under one real Announcements foundation.

    Parameters
    ----------
    platform : Account
        Synthetic setup actor; content authority is never implied.
    plans : tuple[DemoEdition, DemoEdition]
        Creation-time ongoing and future dates.

    Returns
    -------
    tuple[AnnouncementsAdoptionSetupResult, ...]
        Owning setup receipts for the two editions.

    Raises
    ------
    ConventionDemoConflictError
        If the owning reference cannot be reloaded.
    """
    results: list[AnnouncementsAdoptionSetupResult] = []
    for plan in plans:
        reuse: dict[str, Any] = {
            "mode": AnnouncementsSetupMode.NEW_FOUNDATION,
            "organization_name": "MaruCon practice team",
            "series_name": "MaruCon",
        }
        if results:
            reference = resolve_announcements_setup_foundation(
                organization_id=results[0].organization_id,
                series_id=results[0].series_id,
            )
            if reference is None:
                raise ConventionDemoConflictError(
                    "The prepared foundation is unavailable."
                )
            reuse = {
                "mode": AnnouncementsSetupMode.EXISTING_SERIES,
                "organization_id": reference.organization_id,
                "series_id": reference.series_id,
                "foundation_fingerprint": reference.fingerprint,
            }
        results.append(
            set_up_announcements_adoption(
                actor=platform,
                details=AnnouncementsAdoptionSetupInput(
                    **reuse,
                    edition_name=plan.name,
                    starts_on=plan.starts_on,
                    ends_on=plan.ends_on,
                    time_zone=DEMO_ZONE,
                    language_codes=("en",),
                    reason=PREPARATION_REASON,
                ),
                idempotency_key=uuid4(),
                correlation_id=uuid4(),
                source_channel=CHANNEL,
            )
        )
    return tuple(results)


def _activate(
    actors: dict[str, Account],
    scopes: tuple[AnnouncementsAdoptionSetupResult, ...],
) -> None:
    """Exercise accepted representation and explicit combined adoption commands.

    Parameters
    ----------
    actors : dict[str, Account]
        Separate synthetic platform and accountable operator actors.
    scopes : tuple[AnnouncementsAdoptionSetupResult, ...]
        Two exact edition setup results inside the same organization.

    Raises
    ------
    ConventionDemoConflictError
        If the prepared representation cannot be resolved.
    """
    platform, first, second = (
        actors[key] for key in ("platform", "operator-a", "operator-b")
    )
    for operator in (first, second):
        invitation = invite_representation_controller(
            actor=platform,
            representation_id=scopes[0].representation_id,
            account_id=operator.id,
            reason=PREPARATION_REASON,
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
        respond_to_representation_invitation(
            actor=operator,
            appointment_id=invitation.id,
            expected_version=invitation.invitation_version,
            accept=True,
            correlation_id=uuid4(),
            source_channel=CHANNEL,
        )
    reference = resolve_announcements_setup_foundation(
        organization_id=scopes[0].organization_id
    )
    if reference is None or reference.representation_version is None:
        raise ConventionDemoConflictError("The prepared representation is unavailable.")
    activate_representation(
        actor=platform,
        representation_id=scopes[0].representation_id,
        expected_version=reference.representation_version,
        reason=PREPARATION_REASON,
        correlation_id=uuid4(),
        source_channel=CHANNEL,
    )
    for scope in scopes:
        preview = load_guidance_activation_start(
            actor=platform,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            correlation_id=uuid4(),
        )
        proposed = propose_guidance_activation(
            actor=platform,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            expected_edition_version=preview.edition_version,
            operator_ids=(first.id, second.id),
            reason=PREPARATION_REASON,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
        for operator in (first, second):
            respond_to_guidance_activation(
                actor=operator,
                request_id=proposed.request_id,
                expected_version=proposed.version,
                accept=True,
                correlation_id=uuid4(),
            )
        apply_guidance_activation(
            actor=platform,
            request_id=proposed.request_id,
            expected_version=proposed.version,
            correlation_id=uuid4(),
        )


def _grant_roles(
    actors: dict[str, Account],
    scope: AnnouncementsAdoptionSetupResult,
    key: str,
) -> None:
    """Grant each practice role only its own edition through supported commands.

    Parameters
    ----------
    actors : dict[str, Account]
        Prepared synthetic identities with accepted controller responsibilities.
    scope : AnnouncementsAdoptionSetupResult
        Exact edition being prepared.
    key : str
        Ongoing or future account prefix.

    Raises
    ------
    ConventionDemoConflictError
        If the edition cannot be resolved for an exact grant.
    """
    first, second = actors["operator-a"], actors["operator-b"]
    target = resolve_edition_target(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if target is None:
        raise ConventionDemoConflictError("The prepared edition is unavailable.")
    for role in CONTENT_ROLES:
        person = actors[f"{key}-{role}"]
        for capability in _ANNOUNCEMENT_ROLES[role]:
            grant_capability_direct(
                actor=first,
                approver=second,
                recipient=person,
                capability_code=capability,
                target=target,
                effective_from=timezone.now(),
                expires_at=None,
                reason=PREPARATION_REASON,
                correlation_id=uuid4(),
                source_channel=CHANNEL,
            )
        proposed = request_guidance_access(
            actor=first,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            recipient_email=person.email,
            approver_id=second.id,
            recipe_code=_GUIDE_ROLES[role],
            reason=PREPARATION_REASON,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
        preview = load_guidance_access_request(
            actor=second,
            request_id=proposed.request_id,
            correlation_id=uuid4(),
        )
        respond_to_guidance_access(
            actor=second,
            request_id=proposed.request_id,
            expected_digest=preview.request_digest,
            accept=True,
            correlation_id=uuid4(),
        )


def _content(
    actors: dict[str, Account],
    scope: AnnouncementsAdoptionSetupResult,
    plan: DemoEdition,
) -> dict[str, dict[str, str]]:
    """Prepare drafts, pending reviews and approved copies using real workflow commands.

    Parameters
    ----------
    actors : dict[str, Account]
        Setup operator plus separate content author and reviewer.
    scope : AnnouncementsAdoptionSetupResult
        Exact tenant and edition owning these items.
    plan : DemoEdition
        Immutable demo timeline and review deadline.

    Returns
    -------
    dict[str, dict[str, str]]
        Initial item references for the role-based trial, without private content.
    """

    def request(kind: type, actor: Account) -> Any:
        return kind(
            actor_id=actor.id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            correlation_id=uuid4(),
            idempotency_key=uuid4(),
            source_channel=CHANNEL,
        )

    manager = actors["operator-a"]
    author, reviewer = (actors[f"{plan.key}-{role}"] for role in ("author", "reviewer"))
    common: dict[str, Any] = {
        "policy_name": "Fictional practice records",
        "record_owner": "MaruCon practice team",
        "review_on": plan.review_on,
        "confirmed": True,
        "policy_description": (
            "Synthetic local practice only. Keep edits during this "
            "preview; disposal removes its owned database. No external "
            "publication or real event data."
        ),
    }
    announcements.update_announcement_settings(
        request(AnnouncementCommandRequest, manager),
        settings=AnnouncementSettingsInput(
            **common, channels=(ManualChannel("noticeboard", "Practice noticeboard"),)
        ),
        expected_version=0,
    )
    guides.update_guidance_settings(
        request(GuidanceCommandRequest, manager),
        settings=GuidanceSettingsInput(**common),
        expected_version=0,
    )
    references: dict[str, dict[str, str]] = {"announcements": {}, "guides": {}}
    for status, title, body in ANNOUNCEMENT_EXAMPLES:
        made = announcements.create_announcement(
            request(AnnouncementCommandRequest, author),
            draft=AnnouncementDraftInput(
                title,
                body,
                "en",
                (AnnouncementVariantInput("noticeboard", "en", title, body),),
            ),
            expected_settings_version=1,
        )
        references["announcements"][status] = str(made.object_id)
        if status != "draft":
            pending = announcements.request_announcement_review(
                request(AnnouncementCommandRequest, author),
                announcement_id=made.object_id,
                expected_version=made.version,
            )
            if status == "approved":
                announcements.review_announcement(
                    request(AnnouncementCommandRequest, reviewer),
                    announcement_id=made.object_id,
                    revision_id=pending.object_id,
                    expected_version=pending.version,
                    decision="approve",
                    note=(
                        "Prepared synthetic review for this practice preview; not "
                        "human acceptance."
                    ),
                )
    for status, title, body in GUIDE_EXAMPLES:
        guide = guides.create_guidance(
            request(GuidanceCommandRequest, author),
            draft=GuidanceDraftInput(title, body, "en", review_by=plan.review_on),
            expected_settings_version=1,
        )
        references["guides"][status] = str(guide.object_id)
        if status != "draft":
            pending_guide = guides.request_guidance_review(
                request(GuidanceCommandRequest, author),
                item_id=guide.object_id,
                expected_version=guide.version,
            )
            if status == "approved":
                guides.review_guidance(
                    request(GuidanceCommandRequest, reviewer),
                    item_id=guide.object_id,
                    revision_id=pending_guide.object_id,
                    expected_version=pending_guide.version,
                    decision="approve",
                    note=(
                        "Prepared synthetic review for this practice preview; not "
                        "human acceptance."
                    ),
                )
    return references


def seed_convention_demo(anchor: date) -> dict[str, Any]:
    """Atomically prepare one bounded demo, refusing reruns over existing edits.

    Parameters
    ----------
    anchor : date
        Creation date captured once by the launcher in the demo timezone.

    Returns
    -------
    dict[str, Any]
        Non-secret initial timeline and trial references, released only on commit.

    Raises
    ------
    ConventionDemoConflictError
        If the environment, login role or reserved fixture state differs.
    """
    require_demo_environment()
    plans = edition_plan(anchor)
    if (
        settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE is not True
        or not probe_runtime_database_role_safety(
            role_name=settings.RUNTIME_DATABASE_ROLE
        ).current_session_is_safe
    ):
        raise ConventionDemoConflictError(
            "Use the proved runtime login and exact provenance."
        )
    with transaction.atomic():
        _lock_empty_foundation()
        actors = _actors()
        scopes = _foundation(actors["platform"], plans)
        _activate(actors, scopes)
        result: dict[str, Any] = {
            "schema_version": 1,
            "synthetic_only": True,
            "anchor": anchor.isoformat(),
            "time_zone": DEMO_ZONE,
            "editions": [],
        }
        for plan, scope in zip(plans, scopes, strict=True):
            _grant_roles(actors, scope, plan.key)
            references = _content(actors, scope, plan)
            for state in (
                ("preparing", "ready", "live")
                if plan.key == "ongoing"
                else ("preparing",)
            ):
                transition_edition(
                    actor=actors["operator-a"],
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    to_state=state,
                    reason=PREPARATION_REASON,
                    correlation_id=uuid4(),
                    source_channel=CHANNEL,
                )
            result["editions"].append(
                {
                    "key": plan.key,
                    "name": plan.name,
                    "starts_on": plan.starts_on.isoformat(),
                    "ends_on": plan.ends_on.isoformat(),
                    "organization_id": str(scope.organization_id),
                    "edition_id": str(scope.edition_id),
                    "items": references,
                }
            )
        # Force every deferred native guard before returning a ready manifest.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return result
