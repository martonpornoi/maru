"""Native fixture contracts; genuine runtime-login proof is the launcher smoke run."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.utils import timezone

from maru.announcements.contracts import AnnouncementReadRequest
from maru.announcements.errors import AnnouncementDeniedError
from maru.announcements.queries import load_approved_announcement_copy
from maru.authorization.activation import activate_authority_provenance
from maru.authorization.policy import decide, resolve_edition_target
from maru.demo import convention_fixture
from maru.demo.convention_fixture import (
    ConventionDemoConflictError,
    bootstrap_demo_accounts,
    seed_convention_demo,
)
from maru.demo.convention_plan import ACCOUNT_KEYS, account_identity, current_anchor
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.knowledge.commands import revise_guidance
from maru.knowledge.contracts import (
    GuidanceCommandRequest,
    GuidanceDraftInput,
    GuidanceReadRequest,
)
from maru.knowledge.errors import GuidanceDeniedError
from maru.knowledge.queries import (
    download_current_guidance,
    list_current_guidance,
    load_working_guidance,
)
from maru.organizations.models import Organization

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@pytest.fixture
def prepared_accounts(monkeypatch, settings, proves_safe_runtime_database_role):
    monkeypatch.setenv("MARU_SYNTHETIC_CONVENTION_DEMO", "true")
    settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE = True
    # Ordinary integration shards run as a schema owner. Native constraints and
    # exact provenance stay active; the genuine login is exercised by the preview.
    monkeypatch.setattr(
        convention_fixture,
        "probe_runtime_database_role_safety",
        lambda **_: SimpleNamespace(current_session_is_safe=True),
    )
    bootstrap_demo_accounts(
        dict.fromkeys(ACCOUNT_KEYS, "Fictional-practice-password-42!")
    )
    actors = {
        key: Account.objects.get(pk=account_identity(key)[0]) for key in ACCOUNT_KEYS
    }
    activate_authority_provenance(
        actor=actors["platform"],
        reason="Activate exact lineage for the isolated demo fixture test.",
        correlation_id=uuid4(),
        acknowledge_processes_stopped=True,
        source_channel="test",
    )
    return actors


def counts():
    return {
        model._meta.label: model.objects.count()
        for name in (
            "workforce",
            "registration",
            "participation",
            "programme",
            "communications",
            "applications",
        )
        for model in apps.get_app_config(name).get_models()
    }


def request(kind, actor, edition, **kwargs):
    return kind(
        actor_id=actor.id,
        organization_id=UUID(edition["organization_id"]),
        edition_id=UUID(edition["edition_id"]),
        correlation_id=uuid4(),
        **kwargs,
    )


def test_two_editions_real_examples_scope_denials_and_rerun_preserve_edits(
    prepared_accounts,
):
    actors = prepared_accounts
    before = counts()
    anchor = current_anchor(timezone.now())
    manifest = seed_convention_demo(anchor)
    assert counts() == before
    assert Organization.objects.count() == 1
    assert EventEdition.objects.count() == 2
    assert manifest["anchor"] == anchor.isoformat()
    for edition in manifest["editions"]:
        row = EventEdition.objects.get(pk=edition["edition_id"])
        assert row.adoption_profile_code == "announcements_guidance"
        assert row.lifecycle == ("live" if edition["key"] == "ongoing" else "preparing")
        assert (row.starts_on <= anchor <= row.ends_on) == (edition["key"] == "ongoing")
        author, reviewer, reader = (
            actors[f"{edition['key']}-{role}"]
            for role in ("author", "reviewer", "reader")
        )
        target = resolve_edition_target(
            organization_id=row.organization_id, edition_id=row.id
        )
        assert decide(
            principal=author, capability_code="knowledge.compose", resource=target
        ).allowed
        assert not decide(
            principal=author, capability_code="knowledge.review", resource=target
        ).allowed
        assert decide(
            principal=reviewer, capability_code="knowledge.review", resource=target
        ).allowed
        for denied in (
            "knowledge.view_working",
            "knowledge.manage_settings",
            "knowledge.export_evidence",
            "announcements.view",
        ):
            assert not decide(
                principal=reader, capability_code=denied, resource=target
            ).allowed
        for person in (reader, actors["platform"]):
            with pytest.raises(GuidanceDeniedError):
                load_working_guidance(
                    request(GuidanceReadRequest, person, edition),
                    item_id=UUID(edition["items"]["guides"]["draft"]),
                )
        current = list_current_guidance(request(GuidanceReadRequest, reader, edition))
        assert len(current.items) == 1
        artifact = download_current_guidance(
            request(GuidanceReadRequest, reader, edition),
            item_id=UUID(edition["items"]["guides"]["approved"]),
        )
        assert b"Helping someone find a room" in artifact.content
        assert b"Prepared synthetic review" not in artifact.content
        announcement = load_approved_announcement_copy(
            request(AnnouncementReadRequest, reviewer, edition),
            announcement_id=UUID(edition["items"]["announcements"]["approved"]),
        )
        assert b"Welcome to MaruCon" in announcement.content
        other = actors[
            "future-reader" if edition["key"] == "ongoing" else "ongoing-reader"
        ]
        with pytest.raises(GuidanceDeniedError):
            list_current_guidance(request(GuidanceReadRequest, other, edition))
        with pytest.raises(AnnouncementDeniedError):
            load_approved_announcement_copy(
                request(AnnouncementReadRequest, reader, edition),
                announcement_id=UUID(edition["items"]["announcements"]["approved"]),
            )
    ongoing = manifest["editions"][0]
    author = actors["ongoing-author"]
    item = UUID(ongoing["items"]["guides"]["draft"])
    original = load_working_guidance(
        request(GuidanceReadRequest, author, ongoing), item_id=item
    )
    revise_guidance(
        request(
            GuidanceCommandRequest,
            author,
            ongoing,
            idempotency_key=uuid4(),
            source_channel="test",
        ),
        item_id=item,
        expected_version=original.version,
        expected_settings_version=1,
        reason="Retain this fictional practice edit after a refused reseed.",
        draft=GuidanceDraftInput(
            "My practice edit",
            "Keep this edit after a refused reseed.",
            "en",
            anchor + timedelta(days=7),
        ),
    )
    with pytest.raises(ConventionDemoConflictError, match="already contains data"):
        seed_convention_demo(anchor + timedelta(days=2))
    after = load_working_guidance(
        request(GuidanceReadRequest, author, ongoing), item_id=item
    )
    assert after.draft.title == "My practice edit"
    assert EventEdition.objects.count() == 2
    assert counts() == before


def test_mid_seed_failure_rolls_back_every_edition_and_can_retry(
    prepared_accounts, monkeypatch
):
    original = convention_fixture._content

    def fail_on_future(actors, scope, plan):
        if plan.key == "future":
            raise RuntimeError("Deliberate fixture interruption")
        return original(actors, scope, plan)

    before = counts()
    with monkeypatch.context() as patch:
        patch.setattr(convention_fixture, "_content", fail_on_future)
        with pytest.raises(RuntimeError, match="Deliberate fixture interruption"):
            seed_convention_demo(current_anchor(timezone.now()))
    assert not Organization.objects.exists()
    assert not EventEdition.objects.exists()
    assert counts() == before
    assert Account.objects.count() == len(ACCOUNT_KEYS)
    assert len(seed_convention_demo(current_anchor(timezone.now()))["editions"]) == 2
