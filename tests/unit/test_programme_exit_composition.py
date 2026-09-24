"""Whole-owner archive identity and fail-closed composition, not source-policy proof."""

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.programme import exit_composition as composition
from maru.programme.exit_archive_protocol import (
    OWNERS,
    ProgrammeArchiveFile,
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
)
from maru.programme.queries import ProgrammeQueryUnavailableError


def sections():
    return tuple(
        ProgrammeArchiveSection(
            owner,
            f"{owner}.programme-exit@1",
            b'{"synthetic":"records"}',
            b'{"type":"object"}',
        )
        for owner in OWNERS
    )


@pytest.mark.parametrize("owner", [owner for owner in OWNERS if owner != "audit"])
@pytest.mark.parametrize("field", ["data", "schema"])
def test_every_independent_owner_content_or_schema_change_changes_identity(
    owner, field
):
    original = sections()
    changed = tuple(
        replace(row, **{field: b'{"changed":true}'}) if row.owner == owner else row
        for row in original
    )
    assert composition._source_digest(original, ()) != composition._source_digest(
        changed, ()
    )


def test_fresh_audit_receipts_are_not_source_drift_but_audit_owner_is_required():
    original = sections()
    fresh = tuple(
        replace(row, data=b'{"fresh":"receipt"}') if row.owner == "audit" else row
        for row in original
    )
    assert composition._source_digest(original, ()) == composition._source_digest(
        fresh, ()
    )
    with pytest.raises(ProgrammeArchiveInvalidError):
        composition._source_digest(
            tuple(row for row in original if row.owner != "audit"), ()
        )


def test_identity_is_order_independent_and_binds_exact_file_bytes_and_identifiers():
    original = sections()
    files = (
        ProgrammeArchiveFile(UUID(int=1), b"synthetic"),
        ProgrammeArchiveFile(UUID(int=2), b"document"),
    )
    digest = composition._source_digest(original, files)
    assert digest == composition._source_digest(original[::-1], files[::-1])
    assert digest != composition._source_digest(
        original, (replace(files[0], data=b"changed"), files[1])
    )
    assert digest != composition._source_digest(
        original, (replace(files[0], file_id=UUID(int=3)), files[1])
    )
    with pytest.raises(ProgrammeArchiveInvalidError):
        composition._source_digest(original, (files[0], files[0]))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown-contract"])
def test_bad_owner_composition_never_gets_a_valid_source_identity(kind):
    original = sections()
    changed = (
        original[:-1]
        if kind == "missing"
        else (
            (*original[:-1], original[0])
            if kind == "duplicate"
            else (
                replace(original[0], contract="programme.wrong-prefix@1"),
                *original[1:],
            )
        )
    )
    with pytest.raises(ProgrammeArchiveInvalidError):
        composition._source_digest(changed, ())


@pytest.fixture
def source(monkeypatch):
    args = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(1, 5)),
            strict=True,
        )
    )
    owners = {row.owner: row for row in sections()}
    file = SimpleNamespace(file_id=UUID(int=5), data=b"synthetic exact clean file")
    department = SimpleNamespace(cases=(SimpleNamespace(files=(file, file)),))
    applications = SimpleNamespace(departments=(department,))
    events = []
    purpose = Mock(side_effect=lambda **_: events.append("admit"))
    closure = Mock(side_effect=lambda **_: events.append("closure"))
    monkeypatch.setattr(composition, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(composition, "_lock_closure", closure)
    monkeypatch.setattr(composition.transaction, "atomic", nullcontext)
    names = {
        "applications": "load_programme_exit_applications",
        "programme": "load_programme_exit_owner",
        "scheduling": "load_scheduling_exit_owner",
        "workforce": "load_programme_exit_bindings",
        "authorization": "load_programme_exit_authorization",
        "events": "load_programme_exit_configuration",
        "venues": "load_programme_exit_venues",
        "audit": "load_programme_exit_audit",
    }
    loaders = {}
    for owner, name in names.items():

        def load(*_args, _owner=owner, **_kwargs):
            events.append(_owner)
            return applications if _owner == "applications" else owners[_owner]

        loaders[owner] = Mock(side_effect=load)
        monkeypatch.setattr(composition, name, loaders[owner])
    for owner, name in {
        "applications": "serialize_programme_exit_applications",
        "programme": "serialize_programme_exit_owner",
        "scheduling": "serialize_scheduling_exit_owner",
        "workforce": "serialize_programme_exit_bindings",
    }.items():
        monkeypatch.setattr(composition, name, Mock(return_value=owners[owner]))
    return SimpleNamespace(
        args=args,
        loaders=loaders,
        events=events,
        purpose=purpose,
        closure=closure,
        applications=applications,
        file=file,
    )


def test_all_owner_reads_follow_complete_closure_and_audit_runs_last(source):
    result = composition.collect_programme_exit(**source.args)
    assert source.events[:3] == ["admit", "closure", "admit"]
    assert source.events[-2:] == ["audit", "admit"]
    assert len(result.sections) == 8
    assert result.files == (
        ProgrammeArchiveFile(source.file.file_id, source.file.data),
    )
    assert "synthetic" not in repr(result)
    assert len(result.source_digest) == len(hashlib.sha256().hexdigest())
    assert all(loader.call_count == 1 for loader in source.loaders.values())


@pytest.mark.parametrize("owner", OWNERS)
def test_no_failed_owner_is_silently_omitted(source, owner):
    source.loaders[owner].side_effect = RuntimeError("synthetic source denied")
    with pytest.raises(RuntimeError, match="synthetic source denied"):
        composition.collect_programme_exit(**source.args)


def test_same_file_id_with_different_bytes_never_deduplicates_into_success(source):
    source.applications.departments[0].cases[0].files = (
        source.file,
        SimpleNamespace(file_id=source.file.file_id, data=b"different"),
    )
    with pytest.raises(ProgrammeArchiveInvalidError):
        composition.collect_programme_exit(**source.args)
    source.loaders["programme"].assert_not_called()


def test_final_purpose_revocation_refuses_collected_private_bytes(source):
    source.purpose.side_effect = [None, None, RuntimeError("revoked")]
    with pytest.raises(RuntimeError, match="revoked"):
        composition.collect_programme_exit(**source.args)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
def test_bad_scope_never_reaches_sources(source, field):
    with pytest.raises(ProgrammeArchiveInvalidError):
        composition.collect_programme_exit(**{**source.args, field: UUID(int=0)})
    source.closure.assert_not_called()


@pytest.mark.parametrize(
    "failure", [None, "items", "department", "people", "people-limit"]
)
def test_complete_closure_locks_departments_before_sorted_full_host_set(
    monkeypatch, failure
):
    actor, org, edition, trace = (UUID(int=i) for i in range(10, 14))
    events = []
    parent = Mock(side_effect=lambda **_: events.append("parents"))
    item_ids = (UUID(int=30), UUID(int=40))
    item_query, host_query = Mock(), Mock()
    item_query.return_value.order_by.return_value.values_list.return_value = item_ids
    host_values = host_query.return_value.order_by.return_value.values_list.return_value
    host_values.distinct.return_value = (
        UUID(int=20),
        UUID(int=1),
    )
    monkeypatch.setattr(composition.ProgrammeItem.objects, "filter", item_query)
    monkeypatch.setattr(
        composition.ProgrammeHostRelationship.objects, "filter", host_query
    )
    monkeypatch.setattr(composition, "lock_programme_staffing_scope", parent)
    monkeypatch.setattr(
        composition,
        "programme_exit_department_references",
        Mock(return_value=(UUID(int=5), UUID(int=6))),
    )

    def department(**kwargs):
        events.append(kwargs["department_id"])
        return None if failure == "department" else object()

    def people(**kwargs):
        events.append(kwargs["account_ids"])
        return None if failure == "people" else kwargs["account_ids"]

    monkeypatch.setattr(
        composition, "resolve_retained_department_reference", department
    )
    monkeypatch.setattr(composition, "lock_account_references_for_evidence", people)
    if failure == "items":
        monkeypatch.setattr(composition, "MAX_PROGRAMME_ITEMS_PER_EDITION", 1)
    if failure == "people-limit":
        monkeypatch.setattr(composition, "MAX_PERSON_REFERENCE_BATCH", 2)
    args = {
        "actor_id": actor,
        "organization_id": org,
        "edition_id": edition,
        "correlation_id": trace,
        "applications_authorizer": object(),
        "programme_authorizer": object(),
    }
    if failure:
        with pytest.raises(ProgrammeQueryUnavailableError):
            composition._lock_closure(**args)
    else:
        composition._lock_closure(**args)
        assert events == [
            "parents",
            UUID(int=5),
            UUID(int=6),
            (UUID(int=1), actor, UUID(int=20)),
        ]
        host_query.assert_called_once_with(
            organization_id=org, edition_id=edition, item_id__in=item_ids
        )
