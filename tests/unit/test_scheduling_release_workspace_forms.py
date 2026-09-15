"""Closed release transport retains original identity, source and retry evidence."""

import json
from uuid import UUID, uuid4

import pytest
from django.http import QueryDict

from maru.scheduling import release_workspace_forms as forms


def release_post(action="approve"):
    data = {
        "action": action,
        "reason": "Independent synthetic release decision",
        "retry_key": str(uuid4()),
        "confirm": "on",
    }
    if action in {"approve", "acknowledge"}:
        data.update(
            candidate_id=str(uuid4()),
            candidate_revision_id=str(uuid4()),
            expected_candidate_version="3",
            source_snapshot_digest="a" * 64,
        )
        if action == "approve":
            data["acknowledgement_ids"] = json.dumps([str(uuid4())])
        else:
            data["finding_fingerprint"] = "b" * 64
    elif action == "publish":
        data.update(
            approval_id=str(uuid4()),
            source_snapshot_digest="a" * 64,
            expected_active_release_id="",
            expected_release_version="0",
        )
    else:
        data.update(active_release_id=str(uuid4()), expected_release_version="4")
    return data


FORM_TYPES = {
    "acknowledge": forms.ReleaseWarningForm,
    "approve": forms.ReleaseApproveForm,
    "publish": forms.ReleasePublishForm,
    "withdraw": forms.ReleaseWithdrawForm,
}


@pytest.mark.parametrize("action", FORM_TYPES)
def test_closed_command_keeps_original_reason_retry_and_versions(action):
    data = release_post(action)
    form = FORM_TYPES[action](data)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["retry_key"] == UUID(data["retry_key"])
    assert form.cleaned_data["reason"] == data["reason"]
    assert form.data == data
    if action in {"approve", "acknowledge"}:
        assert form.selection().expected_candidate_version == 3
        assert form.selection().candidate_revision_id == UUID(
            data["candidate_revision_id"]
        )
        assert form.selection().source_snapshot_digest == "a" * 64


@pytest.mark.parametrize("action", FORM_TYPES)
@pytest.mark.parametrize(
    "problem", ["confirmation", "reason", "retry", "extra", "duplicate", "version"]
)
def test_invalid_transport_never_becomes_a_command(action, problem):
    data = QueryDict(mutable=True)
    data.update(release_post(action))
    if problem == "confirmation":
        data["confirm"] = ""
    elif problem == "reason":
        data["reason"] = "private\ncontrol"
    elif problem == "retry":
        data["retry_key"] = data["retry_key"].upper()
    elif problem == "extra":
        data["eligible"] = "true"
    elif problem == "duplicate":
        data.appendlist("reason", "hidden second reason")
    else:
        data[
            "expected_candidate_version"
            if action in {"approve", "acknowledge"}
            else "expected_release_version"
        ] = "01"
    assert not FORM_TYPES[action](data).is_valid()


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "{}",
        "true",
        "[null]",
        "[false]",
        '["not-an-id"]',
        "[[]]",
        "[1]",
        "[",
        "[" * 1000,
    ],
)
def test_warning_selection_is_a_closed_bounded_canonical_array(value):
    data = release_post()
    data["acknowledgement_ids"] = value
    assert not forms.ReleaseApproveForm(data).is_valid()


def test_warning_selection_preserves_exact_ids_and_rejects_duplicates(monkeypatch):
    data = release_post()
    identifiers = [str(uuid4()), str(uuid4())]
    data["acknowledgement_ids"] = json.dumps(identifiers)
    form = forms.ReleaseApproveForm(data)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["acknowledgement_ids"] == tuple(map(UUID, identifiers))
    data["acknowledgement_ids"] = json.dumps([identifiers[0]] * 2)
    assert not forms.ReleaseApproveForm(data).is_valid()
    monkeypatch.setattr(forms, "MAX_CONFLICTS", 1)
    data["acknowledgement_ids"] = json.dumps(identifiers)
    assert not forms.ReleaseApproveForm(data).is_valid()
    data["acknowledgement_ids"] = "[]"
    assert forms.ReleaseApproveForm(data).is_valid()


def test_pending_warning_does_not_invent_fresh_source_label():
    form = forms.ReleaseWarningForm(release_post("acknowledge"))
    forms.restore_pending_warning_choice(form)
    assert form.is_valid()
    html = str(form["finding_fingerprint"])
    assert "Original pending warning" in html
    assert "b" * 64 in html
