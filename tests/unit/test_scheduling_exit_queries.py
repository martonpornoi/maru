"""Archive history is complete and bounded without claiming live serving rights."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.scheduling import exit_queries as archive
from maru.scheduling.planning_queries import SchedulingReadRequest


@pytest.fixture
def request_scope():
    return SchedulingReadRequest(*(UUID(int=i) for i in range(1, 5)))


@pytest.fixture
def candidates(monkeypatch, request_scope):
    candidate = SimpleNamespace(id=UUID(int=5), version=3)
    entries = tuple(
        SimpleNamespace(revision_id=UUID(int=10 + i), version=i, placement_count=1)
        for i in (3, 2, 1)
    )
    reader = Mock(
        side_effect=[
            SimpleNamespace(entries=entries[:2], next_before_version=2),
            SimpleNamespace(entries=entries[2:], next_before_version=None),
        ]
    )
    manifests = Mock(
        side_effect=lambda _request, revision_id, **_: SimpleNamespace(
            candidate_id=candidate.id,
            entry=next(row for row in entries if row.revision_id == revision_id),
            placements=(object(),),
        )
    )
    monkeypatch.setattr(archive, "list_scheduling_candidate_history", reader)
    monkeypatch.setattr(archive, "load_scheduling_historical_manifest", manifests)
    return SimpleNamespace(
        request=request_scope,
        snapshot=SimpleNamespace(candidates=(candidate,)),
        reader=reader,
        manifests=manifests,
        entries=entries,
    )


def test_candidate_history_complete_newest_first_without_truncation(candidates):
    result = archive._manifests(candidates.request, candidates.snapshot, Mock())
    assert [row.entry.version for row in result] == [3, 2, 1]
    assert candidates.reader.call_args.kwargs["before_version"] == 2


@pytest.mark.parametrize(
    "page",
    [
        SimpleNamespace(entries=(), next_before_version=None),
        SimpleNamespace(
            entries=(SimpleNamespace(version=2),), next_before_version=None
        ),
    ],
)
def test_missing_candidate_history_fails(candidates, page):
    candidates.reader.side_effect = None
    candidates.reader.return_value = page
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._manifests(candidates.request, candidates.snapshot, Mock())


def test_candidate_history_bad_cursor_fails(candidates):
    candidates.reader.side_effect = [
        SimpleNamespace(entries=candidates.entries[:2], next_before_version=None)
    ]
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._manifests(candidates.request, candidates.snapshot, Mock())


@pytest.mark.parametrize("field", ["candidate_id", "entry", "placements"])
def test_exact_historical_manifest_must_match_selected_history(candidates, field):
    candidates.manifests.side_effect = None
    values = {
        "candidate_id": candidates.snapshot.candidates[0].id,
        "entry": candidates.entries[0],
        "placements": (1,),
    }
    values[field] = () if field == "placements" else None
    candidates.manifests.return_value = SimpleNamespace(**values)
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._manifests(candidates.request, candidates.snapshot, Mock())


@pytest.mark.parametrize(
    "bound", ["MAX_EXIT_CANDIDATE_REVISIONS", "MAX_EXIT_PLACEMENTS"]
)
def test_candidate_history_resource_budget_is_fail_closed(
    candidates, monkeypatch, bound
):
    monkeypatch.setattr(archive, bound, 0)
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._manifests(candidates.request, candidates.snapshot, Mock())


@pytest.fixture
def metadata(monkeypatch, request_scope):
    rows = [(UUID(int=10), UUID(int=20), 1), (UUID(int=11), UUID(int=20), 2)]
    query = Mock()
    query.return_value.order_by.return_value.values_list.side_effect = lambda *_: rows
    other = Mock()
    other.return_value.order_by.return_value.values_list.return_value = []
    monkeypatch.setattr(archive.SchedulingServiceDayRevision.objects, "filter", query)
    monkeypatch.setattr(archive.SchedulingOccurrenceRevision.objects, "filter", other)
    return SimpleNamespace(
        request=request_scope,
        rows=rows,
        query=query,
        snapshot=SimpleNamespace(
            days=(SimpleNamespace(id=UUID(int=20), version=2),), occurrences=()
        ),
    )


def test_original_metadata_is_explicit_and_complete(metadata):
    assert archive._metadata(metadata.request, metadata.snapshot) == (
        tuple(metadata.rows),
        (),
    )
    assert metadata.query.call_args.kwargs == {
        "organization_id": metadata.request.organization_id,
        "edition_id": metadata.request.edition_id,
    }
    assert (
        metadata.query.return_value.order_by.return_value.values_list.call_args.args
        == archive.DAY_COLUMNS
    )


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(UUID(int=10), UUID(int=20), 2)],
        [(UUID(int=10), UUID(int=99), 1)],
        [(UUID(int=10), UUID(int=20), 1)],
    ],
)
def test_metadata_missing_sequence_parent_or_current_version_refused(metadata, rows):
    metadata.rows[:] = rows
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._metadata(metadata.request, metadata.snapshot)


def test_metadata_budget_refuses_partial_result(metadata, monkeypatch):
    monkeypatch.setattr(archive, "MAX_EXIT_METADATA_REVISIONS", 1)
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._metadata(metadata.request, metadata.snapshot)


def test_release_history_collects_complete_monotonic_pages(request_scope, monkeypatch):
    entries = tuple(SimpleNamespace(version=i) for i in (3, 2, 1))
    reader = Mock(
        side_effect=[
            SimpleNamespace(entries=entries[:2], next_before_version=2),
            SimpleNamespace(entries=entries[2:], next_before_version=None),
        ]
    )
    monkeypatch.setattr(archive, "list_release_history", reader)
    assert (
        archive._history(request_scope, SimpleNamespace(version=3), Mock()) == entries
    )
    assert reader.call_args.kwargs["before_version"] == 2


@pytest.mark.parametrize(
    "page",
    [
        SimpleNamespace(entries=(), next_before_version=None),
        SimpleNamespace(
            entries=(SimpleNamespace(version=2),), next_before_version=None
        ),
    ],
)
def test_missing_release_history_refuses(request_scope, monkeypatch, page):
    monkeypatch.setattr(archive, "list_release_history", Mock(return_value=page))
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._history(request_scope, SimpleNamespace(version=3), Mock())


def test_release_history_limit_refuses_before_queries(request_scope, monkeypatch):
    reader = Mock()
    monkeypatch.setattr(archive, "list_release_history", reader)
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._history(
            request_scope,
            SimpleNamespace(version=archive.MAX_EXIT_RELEASE_HISTORY + 1),
            Mock(),
        )
    reader.assert_not_called()


def test_empty_release_history_is_verified(request_scope, monkeypatch):
    monkeypatch.setattr(
        archive,
        "list_release_history",
        Mock(return_value=SimpleNamespace(entries=(), next_before_version=None)),
    )
    assert archive._history(request_scope, SimpleNamespace(version=0), Mock()) == ()


@pytest.fixture
def release(monkeypatch, request_scope):
    identifier = UUID(int=5)
    approval = SimpleNamespace(
        id=UUID(int=6),
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        candidate_revision_id=UUID(int=7),
        source_snapshot_digest="a" * 64,
    )
    artifact = SimpleNamespace(
        contract="programme.release.canonical@1",
        payload=b"{}",
        sha256="a" * 64,
        byte_length=2,
    )
    row = SimpleNamespace(
        id=identifier,
        approval_id=approval.id,
        approval=approval,
        previous_release_id=None,
        pointer_version=1,
        artifacts=Mock(),
    )
    row.artifacts.filter.return_value = [artifact]
    query = Mock()
    query.return_value.select_related.return_value.order_by.return_value = [row]
    verify = Mock()
    monkeypatch.setattr(archive.SchedulingRelease.objects, "filter", query)
    monkeypatch.setattr(archive, "verify_canonical_release_artifact", verify)
    monkeypatch.setattr(archive, "_placements", Mock(return_value=()))
    history = (
        SimpleNamespace(
            release_id=identifier,
            operation=archive.SchedulingOperation.RELEASE_WITHDRAW,
        ),
        SimpleNamespace(
            release_id=identifier, operation=archive.SchedulingOperation.RELEASE_PUBLISH
        ),
    )
    return SimpleNamespace(
        request=request_scope, row=row, query=query, verify=verify, history=history
    )


def test_withdrawn_release_keeps_verified_identity_evidence_not_serving_state(release):
    result = archive._releases(release.request, release.history)
    assert result[0].release_id == release.row.id
    assert result[0].artifact.payload == b"{}"
    release.verify.assert_called_once()


@pytest.mark.parametrize(
    "kind",
    [
        "artifact_missing",
        "artifact_duplicate",
        "foreign_approval",
        "wrong_previous",
        "missing_release",
    ],
)
def test_missing_or_inconsistent_release_evidence_refuses(release, kind):
    if kind == "artifact_missing":
        release.row.artifacts.filter.return_value = []
    elif kind == "artifact_duplicate":
        release.row.artifacts.filter.return_value *= 2
    elif kind == "foreign_approval":
        release.row.approval.edition_id = UUID(int=99)
    elif kind == "wrong_previous":
        release.row.previous_release_id = UUID(int=99)
    else:
        ordered = release.query.return_value.select_related.return_value.order_by
        ordered.return_value = []
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._releases(release.request, release.history)


def test_corrupt_canonical_artifact_is_not_archived(release):
    release.verify.side_effect = archive.ReleaseArtifactInvalidError()
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._releases(release.request, release.history)


def test_canonical_artifact_byte_budget_refuses(release, monkeypatch):
    monkeypatch.setattr(archive, "MAX_EXIT_ARTIFACT_BYTES", 1)
    with pytest.raises(archive.SchedulingUnavailableError):
        archive._releases(release.request, release.history)


def test_publication_after_withdrawal_has_no_active_predecessor(release):
    second = SimpleNamespace(
        **{**vars(release.row), "id": UUID(int=20), "pointer_version": 3}
    )
    ordered = release.query.return_value.select_related.return_value.order_by
    ordered.return_value = [release.row, second]
    history = (
        SimpleNamespace(
            release_id=second.id, operation=archive.SchedulingOperation.RELEASE_PUBLISH
        ),
        *release.history,
    )
    result = archive._releases(release.request, history)
    assert result[1].previous_release_id is None


@pytest.fixture
def owner(monkeypatch, request_scope):
    snapshot = SimpleNamespace(candidates=(), days=(), occurrences=())
    pointer = SimpleNamespace(version=0, active_release_id=None)
    readers = {
        "purpose": ("authorize_programme_archive_scope", Mock()),
        "source_policy": ("_authorize", Mock()),
        "planning": ("load_scheduling_planning", Mock(return_value=snapshot)),
        "metadata": ("_metadata", Mock(return_value=((), ()))),
        "manifests": ("_manifests", Mock(return_value=())),
        "pointer": ("load_release_pointer", Mock(return_value=pointer)),
        "history": ("_history", Mock(return_value=())),
        "releases": ("_releases", Mock(return_value=())),
    }
    for name, reader in readers.values():
        monkeypatch.setattr(archive, name, reader)
    outer = Mock(side_effect=lambda _request, **kw: kw["loader"](object()))
    monkeypatch.setattr(archive, "_read", outer)
    return SimpleNamespace(
        request=request_scope,
        outer=outer,
        **{key: reader for key, (_, reader) in readers.items()},
    )


def test_owner_preserves_separate_history_planning_and_archive_authority(owner):
    result = archive.load_scheduling_exit_owner(owner.request)
    assert result.planning == owner.planning.return_value
    assert owner.purpose.call_count == 3
    assert owner.outer.call_args.kwargs["capability"] == archive.VIEW_HISTORY
    assert (
        owner.outer.call_args.kwargs["fields"]
        == archive.HISTORY_FIELDS | archive.RELEASE_MANIFEST_FIELDS
    )
    assert owner.outer.call_args.kwargs["purpose"] == "exit_owner"
    assert owner.source_policy.call_args.args[1] == archive.VIEW_PLANNING
    assert owner.planning.call_count == owner.pointer.call_count == 2


@pytest.mark.parametrize(
    "boundary",
    ["purpose", "source_policy", "metadata", "manifests", "history", "releases"],
)
def test_any_required_owner_boundary_failure_refuses_whole_result(owner, boundary):
    getattr(owner, boundary).side_effect = RuntimeError("synthetic required boundary")
    with pytest.raises(RuntimeError, match="synthetic required boundary"):
        archive.load_scheduling_exit_owner(owner.request)


@pytest.mark.parametrize("boundary", ["planning", "pointer"])
def test_final_owner_source_change_is_unavailable(owner, boundary):
    reader = getattr(owner, boundary)
    reader.side_effect = [reader.return_value, SimpleNamespace(changed=True)]
    with pytest.raises(archive.SchedulingUnavailableError):
        archive.load_scheduling_exit_owner(owner.request)
