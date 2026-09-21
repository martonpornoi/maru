"""Non-vacuous P12 verifier checks, not claims about a running native fixture."""

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from tests.rehearsals import programme_object_isolation as isolation
from tests.rehearsals import programme_object_preparation as preparation
from tests.rehearsals.programme_http_session import ProgrammeHttpResponse
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_isolation_scopes import IsolationScopes
from tests.unit.test_programme_change_scenario import _sources


def _form_html(path, *, version=1):
    return (
        f'<form method="post" action="{path}" data-programme-command>'
        f'<input name="csrfmiddlewaretoken" value="{"a" * 64}">'
        f'<input name="expected_version" value="{version}">'
        f'<input name="idempotency_key" value="{uuid4()}"></form>'
    )


@pytest.mark.parametrize(
    "fault",
    [None, "action", "method", "duplicate", "missing", "csrf", "version", "key", "nil"],
)
def test_only_the_actual_closed_working_form_supplies_positive_control(fault):
    path = "/admin/programme/items/scope/item/working/"
    text = _form_html(path)
    if fault == "action":
        text = text.replace(path, "https://elsewhere.invalid/")
    elif fault == "method":
        text = text.replace('method="post"', 'method="get"')
    elif fault == "duplicate":
        text *= 2
    elif fault == "missing":
        text = text.replace('name="expected_version"', 'name="other"')
    elif fault == "csrf":
        text = text.replace("a" * 64, "invalid")
    elif fault == "version":
        text = text.replace('value="1"', 'value="0"')
    elif fault in {"key", "nil"}:
        start = text.index('name="idempotency_key" value="') + len(
            'name="idempotency_key" value="'
        )
        end = text.index('"', start)
        text = (
            text[:start]
            + ("invalid" if fault == "key" else str(UUID(int=0)))
            + text[end:]
        )
    if fault:
        with pytest.raises(ProgrammeHttpsError, match="form_invalid"):
            isolation._form(text, path)
    else:
        values = isolation._form(text, path)
        assert values["expected_version"] == "1"
        assert values["csrfmiddlewaretoken"] == "a" * 64
        assert UUID(values["idempotency_key"]).int


def _references():
    sources = _sources()
    setup, review = sources[0], sources[2]
    scopes = IsolationScopes(*(uuid4() for _ in range(6)))
    objects = (
        preparation.IsolatedProgrammeObject(
            scopes.organization_id, scopes.edition_id, uuid4(), review.people[0]
        ),
        preparation.IsolatedProgrammeObject(
            setup.organization_id, scopes.sibling_edition_id, uuid4(), review.people[1]
        ),
    )
    return sources, scopes, objects


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "length",
        "envelope",
        "extra",
        "scope",
        "nil",
        "alias",
        "person",
        "uppercase",
        "password",
    ],
)
def test_object_references_are_closed_distinct_and_exact_scope(fault):
    sources, scopes, objects = _references()
    document = json.loads(json.dumps([asdict(row) for row in objects], default=str))
    if fault == "length":
        document.pop()
    elif fault == "envelope":
        document = {}
    elif fault == "extra":
        document[0]["secret"] = "not a valid field"
    elif fault == "scope":
        document[0]["edition_id"] = str(sources[0].edition_id)
    elif fault == "nil":
        document[0]["item_id"] = str(UUID(int=0))
    elif fault == "alias":
        document[0]["item_id"] = document[1]["item_id"]
    elif fault == "person":
        document[0]["owner"] = document[1]["owner"]
    elif fault == "uppercase":
        document[0]["item_id"] = "ABCDEFAB-1234-4321-ABCD-123456789012"
    elif fault == "password":
        document[0]["owner"]["password"] = "private invalid password"
    if fault:
        with pytest.raises(ProgrammeHttpsError, match="reference_invalid"):
            preparation.objects_from_document(document, setup=sources[0], scopes=scopes)
    else:
        assert (
            preparation.objects_from_document(document, setup=sources[0], scopes=scopes)
            == objects
        )
        assert all(row.owner.password not in repr(row) for row in objects)


@pytest.mark.parametrize("fault", [None, "redirect", "missing", "version"])
def test_real_owner_control_requires_successful_mutation_and_new_version(
    monkeypatch, fault
):
    _, _, objects = _references()
    record = objects[0]
    path = isolation._path(record.organization_id, record.edition_id, record.item_id)
    session = Mock()
    session.submit_working_item.return_value = ProgrammeHttpResponse(
        302, {"Location": path if fault != "redirect" else "/other/"}, b""
    )
    before = _form_html(path)
    after = _form_html(path, version=1 if fault == "version" else 2)
    if fault != "missing":
        after += "Private successful scope-owner edit"
    monkeypatch.setattr(isolation, "_read", Mock(side_effect=[before, after]))
    if fault:
        with pytest.raises(ProgrammeHttpsError):
            isolation._owner_control(session, record, forbidden=("private secret",))
    else:
        isolation._owner_control(session, record, forbidden=("private secret",))
        values = session.submit_working_item.call_args.kwargs
        assert values["item_id"] == record.item_id
        assert values["organization_id"] == record.organization_id
        assert values["edition_id"] == record.edition_id
        assert values["form"]["expected_version"] == "1"
    session.logout.assert_called_once()


@pytest.mark.parametrize(
    "fault", [None, "csrf_denied", "unexpected_success", "private", "write"]
)
def test_four_object_posts_use_real_targets_and_leave_full_owner_rows_unchanged(
    monkeypatch, fault
):
    sources, scopes, objects = _references()
    setup, review, items = sources[0], sources[2], sources[3]
    fixture = SimpleNamespace(scenario=setup, verify_excluded_state=Mock())
    session = Mock()
    original = isolation._path(
        setup.organization_id, setup.edition_id, items.accepted.item_id
    )
    before = Mock(return_value=("complete scoped owner rows", "programme events"))
    if fault == "write":
        before.side_effect = [("before",), ("after",)]
    owner = Mock(return_value=2)
    responses = []

    def submit(**kwargs):
        responses.append(kwargs)
        assert kwargs["form"]["csrfmiddlewaretoken"] == "a" * 64
        assert kwargs["form"]["expected_version"] == "2"
        assert kwargs["item_id"] in {row.item_id for row in objects}
        status = 503 if kwargs["edition_id"] == setup.edition_id else 404
        if fault == "csrf_denied":
            status = 403
        elif fault == "unexpected_success":
            status = 302
        return ProgrammeHttpResponse(
            status,
            {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            b"Private successful scope-owner edit"
            if fault == "private"
            else b"Unavailable",
        )

    session.submit_working_item.side_effect = submit
    monkeypatch.setattr(isolation, "require_programme_rehearsal_request", Mock())
    monkeypatch.setattr(
        isolation, "prepare_isolated_objects", Mock(return_value=objects)
    )
    monkeypatch.setattr(isolation, "ProgrammeHttpSession", Mock(return_value=session))
    monkeypatch.setattr(isolation, "_owner_control", owner)
    monkeypatch.setattr(isolation, "_read", Mock(return_value=_form_html(original)))
    monkeypatch.setattr(isolation, "_snapshot", before)
    if fault:
        with pytest.raises(ProgrammeHttpsError):
            isolation.verify_object_mutation_isolation(fixture, scopes, review, items)
        assert owner.call_count == 2
    else:
        isolation.verify_object_mutation_isolation(fixture, scopes, review, items)
        assert owner.call_count == 4
        assert len(responses) == 4
        assert before.call_count == 5
        assert fixture.verify_excluded_state.call_count == 5
    session.login.assert_called_once_with(review.people[5], destination=original)
    session.logout.assert_called_once()
