"""Prove complete Applications owner scope and Department-before-actor closure."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_exit_queries as archive


def test_composer_reference_admits_every_department_without_actor_locks(source):
    result = archive.programme_exit_department_references(**source.args)
    assert result == source.departments
    assert [
        call.args[0].department_id for call in source.admission.call_args_list
    ] == list(source.departments)
    source.lock.assert_not_called()
    source.parent.assert_not_called()
    source.reader.assert_not_called()
    source.purpose.assert_called_once()


def test_composer_reference_never_omits_denied_department(source):
    source.admission.side_effect = [None, RuntimeError("source denied")]
    with pytest.raises(RuntimeError, match="source denied"):
        archive.programme_exit_department_references(**source.args)


def test_composer_reference_refuses_oversized_department_closure(source, monkeypatch):
    monkeypatch.setattr(archive, "MAX_EXIT_DEPARTMENTS", 1)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        archive.programme_exit_department_references(**source.args)
    source.admission.assert_not_called()


@pytest.fixture
def source(monkeypatch):
    args = {
        name: UUID(int=index)
        for index, name in enumerate(
            ("actor_id", "organization_id", "edition_id", "correlation_id"), start=1
        )
    }
    departments = (UUID(int=10), UUID(int=20))
    inventory = [(UUID(int=30), departments[1]), (UUID(int=40), departments[0])]
    query = Mock()
    query.return_value.order_by.return_value.values_list.side_effect = lambda *_: (
        inventory
    )
    monkeypatch.setattr(archive.ProgrammeCall.objects, "filter", query)
    events = []
    purpose = Mock(
        return_value=SimpleNamespace(
            decision=SimpleNamespace(
                reason_code="allowed", obligations=frozenset({"audit_sensitive_read"})
            )
        )
    )
    parent = Mock(side_effect=lambda **_: events.append("parents"))
    lock = Mock(
        side_effect=lambda **kw: (
            events.append(kw["department_ids"]),
            SimpleNamespace(department_ids=kw["department_ids"]),
        )[1]
    )
    admission = Mock()

    def collect(**kw):
        events.append("child")
        department_id = kw["request"].department_id
        return SimpleNamespace(
            configuration=SimpleNamespace(
                department_id=department_id,
                calls=tuple(
                    SimpleNamespace(
                        configuration=SimpleNamespace(
                            summary=SimpleNamespace(call_id=call_id)
                        )
                    )
                    for call_id, owner in inventory
                    if owner == department_id
                ),
            ),
            cases=(
                SimpleNamespace(
                    review=SimpleNamespace(evidence_lineage=(1,)),
                    files=(SimpleNamespace(data=b"PDF"),),
                ),
            ),
        )

    reader = Mock(side_effect=collect)
    audit = Mock()
    monkeypatch.setattr(archive, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(archive, "lock_programme_staffing_scope", parent)
    monkeypatch.setattr(archive, "lock_programme_edition_write_scope", lock)
    monkeypatch.setattr(archive, "_admit_sources", admission)
    monkeypatch.setattr(archive, "load_programme_exit_department", reader)
    monkeypatch.setattr(archive, "append_audit", audit)
    return SimpleNamespace(
        args=args,
        read=archive.load_programme_exit_applications.__wrapped__,
        departments=departments,
        inventory=inventory,
        query=query,
        events=events,
        purpose=purpose,
        parent=parent,
        lock=lock,
        admission=admission,
        reader=reader,
        audit=audit,
    )


def test_all_sorted_departments_are_locked_before_any_audited_child(source):
    result = source.read(**source.args)
    assert source.events == ["parents", source.departments, "child", "child"]
    assert (
        tuple(row.configuration.department_id for row in result.departments)
        == source.departments
    )
    assert source.admission.call_count == 6
    assert source.purpose.call_count == 3
    assert source.query.call_args.kwargs == {
        "organization_id": source.args["organization_id"],
        "edition_id": source.args["edition_id"],
    }
    assert (
        source.audit.call_args.args[0].operation
        == "applications.programme.query.exit_owner"
    )
    assert str(source.departments[0]) not in repr(result)


def test_empty_owner_still_admitted_locked_and_audited(source):
    source.inventory.clear()
    assert source.read(**source.args).departments == ()
    source.reader.assert_not_called()
    source.audit.assert_called_once()
    assert source.lock.call_args.kwargs["department_ids"] == ()


@pytest.mark.parametrize(
    "boundary", ["purpose", "parent", "lock", "admission", "reader", "audit"]
)
def test_any_mandatory_boundary_failure_prevents_complete_owner(source, boundary):
    getattr(source, boundary).side_effect = RuntimeError("synthetic boundary failure")
    with pytest.raises(RuntimeError, match="synthetic boundary failure"):
        source.read(**source.args)


@pytest.mark.parametrize(
    "bound",
    [
        "MAX_EXIT_DEPARTMENTS",
        "MAX_EXIT_CALLS",
        "MAX_EXIT_OWNER_CASES",
        "MAX_EXIT_OWNER_ENTRIES",
        "MAX_EXIT_OWNER_FILES",
        "MAX_EXIT_OWNER_FILE_BYTES",
    ],
)
def test_owner_bounds_never_truncate(source, monkeypatch, bound):
    monkeypatch.setattr(archive, bound, 0)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_lock_closure_must_be_exact(source):
    source.lock.side_effect = None
    source.lock.return_value = SimpleNamespace(department_ids=(source.departments[0],))
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.reader.assert_not_called()


def test_missing_call_cannot_be_claimed_complete(source):
    collect = source.reader.side_effect

    def omit(**kwargs):
        result = collect(**kwargs)
        result.configuration.calls = ()
        return result

    source.reader.side_effect = omit
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_foreign_department_projection_is_refused(source):
    collect = source.reader.side_effect

    def foreign(**kwargs):
        result = collect(**kwargs)
        result.configuration.department_id = UUID(int=900)
        return result

    source.reader.side_effect = foreign
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_final_inventory_drift_is_refused(source):
    source.query.return_value.order_by.return_value.values_list.side_effect = [
        source.inventory,
        [],
    ]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_source_admission_uses_call_manager_and_independent_review_purposes(
    monkeypatch,
):
    request = archive.ProgrammeReviewReadRequest(
        *(UUID(int=i) for i in range(1, 5)),
        archive.DECIDE,
        archive.REVIEW_FIELDS,
        UUID(int=5),
        "programme-exit",
    )
    calls, reviews = Mock(), Mock()
    monkeypatch.setattr(archive, "authorize_programme_call_scope", calls)
    monkeypatch.setattr(archive, "_scope", reviews)
    archive._admit_sources(request, Mock())
    calls.assert_called_once()
    assert [call.args[0].capability_code for call in reviews.call_args_list] == [
        archive.DECIDE,
        archive.MANAGE_REVIEW,
    ]
    assert reviews.call_args.args[0].requested_fields == frozenset(
        {"review_context", "review_setup"}
    )
