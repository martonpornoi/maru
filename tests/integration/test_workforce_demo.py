"""Real Workforce preparation; actual restricted-login proof remains a launcher run."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.utils import timezone

from maru.authorization.activation import activate_authority_provenance
from maru.authorization.policy import decide, resolve_edition_target
from maru.demo import workforce_fixture, workforce_plan
from maru.demo.convention_fixture import (
    ConventionDemoConflictError,
    bootstrap_demo_accounts,
)
from maru.demo.convention_plan import current_anchor
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignment,
    ShiftCommitment,
)
from maru.workforce.operating_home import load_workforce_home_guidance
from tests.factories import AccountFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def actors(monkeypatch, settings, proves_safe_runtime_database_role):
    monkeypatch.setenv("MARU_SYNTHETIC_CONVENTION_DEMO", "true")
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
    # Native guards/provenance stay real. A normal test schema owner is not the
    # runtime login; the separate launcher/browser run proves that login.
    monkeypatch.setattr(
        workforce_fixture,
        "probe_runtime_database_role_safety",
        lambda **_: SimpleNamespace(current_session_is_safe=True),
    )
    bootstrap_demo_accounts(
        dict.fromkeys(workforce_plan.ACCOUNT_KEYS, "Fictional-practice-password-42!"),
        scenario="workforce",
    )
    accounts = {
        key: Account.objects.get(pk=workforce_plan.account_identity(key)[0])
        for key in workforce_plan.ACCOUNT_KEYS
    }
    activate_authority_provenance(
        actor=accounts["platform"],
        reason="Activate exact synthetic Workforce practice lineage.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )
    return accounts


def _read(actor, edition):
    return load_workforce_home_guidance(
        actor=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
        http_method="GET",
    )


def test_two_workforce_only_editions_have_real_independent_work_and_no_attendee_effects(
    actors,
):
    anchor = current_anchor(timezone.now())
    manifest = workforce_fixture.seed_workforce_demo(anchor)
    assert manifest["scenario"] == "workforce"
    assert len(manifest["editions"]) == 2
    ungranted = AccountFactory()
    for entry in manifest["editions"]:
        edition = EventEdition.objects.get(pk=entry["edition_id"])
        assert edition.adoption_profile_code == "workforce_only"
        assert edition.lifecycle == (
            "live" if entry["key"] == "ongoing" else "preparing"
        )
        manager = actors[f"{entry['key']}-manager"]
        reviewer = actors[f"{entry['key']}-reviewer"]
        volunteer = actors[f"{entry['key']}-volunteer"]
        target = resolve_edition_target(
            organization_id=edition.organization_id, edition_id=edition.id
        )
        assert decide(
            principal=manager,
            capability_code="workforce.manage_structure",
            resource=target,
        ).allowed
        assert not decide(
            principal=reviewer,
            capability_code="workforce.manage_structure",
            resource=target,
        ).allowed
        assert not decide(
            principal=volunteer,
            capability_code="workforce.view_shifts",
            resource=target,
        ).allowed
        other = actors[
            "future-reviewer" if entry["key"] == "ongoing" else "ongoing-reviewer"
        ]
        assert _read(other, edition) is None
        assert _read(ungranted, edition) is None
        # The retained Workforce policy permits platform oversight, unlike the
        # Guides purpose boundary. It still creates no volunteer relationship.
        platform = decide(
            principal=actors["platform"],
            capability_code="workforce.view_shifts",
            resource=target,
        )
        assert platform.allowed
        assert platform.reason_code == "platform_administration"
        assert _read(actors["platform"], edition) is not None
        assert not PositionAssignment.objects.filter(
            account=actors["platform"]
        ).exists()
        result = _read(reviewer, edition)
        codes = {item.code for item in result.operating}
        if entry["key"] == "future":
            assert {"assignment_review", "availability_wait", "shift_draft"} <= codes
            assert (
                PersonAvailabilityPlan.objects.get(
                    edition=edition, account=volunteer
                ).status
                == "draft"
            )
        else:
            assert {"assignment_active", "availability_shared", "shift_claims"} <= codes
            assert ShiftCommitment.objects.filter(
                demand_id=UUID(entry["items"]["shift"]), status="confirmed"
            ).exists()
    for label in (
        "participation",
        "registration",
        "communications",
        "announcements",
        "knowledge",
        "programme",
    ):
        assert all(
            not model.objects.exists()
            for model in apps.get_app_config(label).get_models()
        )
    before = tuple(EventEdition.objects.values_list("id", "starts_on", "ends_on"))
    with pytest.raises(ConventionDemoConflictError, match="already contains data"):
        workforce_fixture.seed_workforce_demo(anchor + timedelta(days=1))
    assert (
        tuple(EventEdition.objects.values_list("id", "starts_on", "ends_on")) == before
    )


def test_interrupted_workforce_preparation_rolls_back_without_adopting_partial_edits(
    actors, monkeypatch
):
    original = workforce_fixture._content

    def stop(people, edition, plan):
        if plan.key == "future":
            raise RuntimeError("Deliberate practice interruption")
        return original(people, edition, plan)

    monkeypatch.setattr(workforce_fixture, "_content", stop)
    with pytest.raises(RuntimeError, match="Deliberate"):
        workforce_fixture.seed_workforce_demo(current_anchor(timezone.now()))
    assert not EventEdition.objects.exists()
    assert Account.objects.count() == len(workforce_plan.ACCOUNT_KEYS)
