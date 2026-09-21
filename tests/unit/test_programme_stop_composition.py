"""Complete immutable preview identity and bounded canonical lock preparation."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.authorization.programme_stop_queries import ProgrammeStopAuthorityImpact
from maru.events import programme_stop_composition as composition
from maru.events.programme_stop_inventory import ProgrammeStopInventory
from maru.scheduling.programme_stop_queries import ProgrammeStopSchedulingImpact


@pytest.fixture
def preview():
    return composition.ProgrammeStopPreview(
        uuid4(),
        uuid4(),
        uuid4(),
        "preparing",
        3,
        1,
        ProgrammeStopAuthorityImpact((), 0, 0, 0, "a" * 64),
        ProgrammeStopSchedulingImpact(
            ProgrammeStopInventory("scheduling", (), "b" * 64),
            None,
            0,
            withdrawal_authorized=False,
        ),
        tuple(
            ProgrammeStopInventory(owner, (), "c" * 64)
            for owner in ("applications", "programme", "workforce", "venues", "effects")
        ),
    )


def test_preview_document_is_an_independent_minimized_copy(preview):
    original = preview.fingerprint
    document = preview.document()
    assert document["contract"] == "events.programme-stop-preview@1"
    assert document["actor_id"] == str(preview.actor_id)
    document["inventories"][0]["source_fingerprint"] = "d" * 64
    assert original == preview.fingerprint
    assert preview.document() != document


@pytest.mark.parametrize("field", ["actor_id", "organization_id", "edition_id"])
def test_scope_and_actual_actor_are_part_of_complete_preview_identity(preview, field):
    assert replace(preview, **{field: uuid4()}).fingerprint != preview.fingerprint


@pytest.mark.parametrize("field", ["aggregate_version", "lifecycle_version"])
def test_both_events_versions_are_bound(preview, field):
    assert replace(preview, **{field: 7}).fingerprint != preview.fingerprint


def test_source_or_withdrawal_authority_change_requires_new_confirmation(preview):
    assert (
        replace(
            preview, scheduling=replace(preview.scheduling, withdrawal_authorized=True)
        ).fingerprint
        != preview.fingerprint
    )
    assert (
        replace(
            preview, authority=replace(preview.authority, source_fingerprint="d" * 64)
        ).fingerprint
        != preview.fingerprint
    )


def test_oversized_preview_is_never_partially_hashed(preview, monkeypatch):
    monkeypatch.setattr(composition, "MAX_STOP_PREVIEW_BYTES", 10)
    with pytest.raises(ValidationError):
        preview.document()
    with pytest.raises(ValidationError):
        _ = preview.fingerprint


def test_complete_person_union_precedes_controller_and_narrower_owner_locks(
    monkeypatch,
):
    scope = {key: uuid4() for key in ("actor_id", "organization_id", "edition_id")}
    people = tuple(sorted((scope["actor_id"], uuid4(), uuid4())))
    calls = []
    foundation = SimpleNamespace(
        fingerprint="a" * 64,
        organization_lifecycle="active",
        representation_state="active",
    )
    cursor = SimpleNamespace(
        execute=lambda _: calls.append("isolation"),
        fetchone=lambda: ("read committed",),
    )
    monkeypatch.setattr(composition.connection, "cursor", lambda: nullcontext(cursor))
    monkeypatch.setattr(composition.transaction, "atomic", nullcontext)
    for name, value in (
        ("require_programme_stop_preflight", None),
        ("lock_retired_department_authority_boundaries", None),
        ("resolve_programme_setup_foundation", foundation),
        ("lock_programme_setup_foundation", foundation),
        ("lock_programme_staffing_scope", None),
        ("resolve_programme_stop_release_people", people),
        ("require_programme_stop_controller", None),
        ("programme_stop_preparation_is_ready", True),
    ):

        def stub(*, _name=name, _value=value, **_):
            calls.append(_name)
            return _value

        monkeypatch.setattr(composition, name, stub)

    def lock_people(*, account_ids):
        assert account_ids == people
        calls.append("people")
        return account_ids

    monkeypatch.setattr(
        composition, "lock_account_references_for_evidence", lock_people
    )
    monkeypatch.setattr(composition.EventEdition.objects, "get", lambda **_: "edition")
    with composition._locked_stop_scope(**scope) as edition:
        assert edition == "edition"
        calls.append("composed-owner-work")
    assert calls == [
        "require_programme_stop_preflight",
        "isolation",
        "lock_retired_department_authority_boundaries",
        "resolve_programme_setup_foundation",
        "lock_programme_setup_foundation",
        "lock_programme_staffing_scope",
        "resolve_programme_stop_release_people",
        "people",
        "require_programme_stop_controller",
        "programme_stop_preparation_is_ready",
        "composed-owner-work",
    ]
