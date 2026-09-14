"""Database-free exact-person proof, purpose and uncertain-retry contracts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core import signing
from django.core.exceptions import ValidationError

from maru.applications import programme_reviewer_selection as selections
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_setup_queries import (
    request as setup_request,
)


def request(**changes):
    return setup_request(
        **({"requested_fields": frozenset({"review_context"})} | changes)
    )


@pytest.fixture
def world(monkeypatch):
    scope = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    case = Mock(
        return_value=SimpleNamespace(
            id=UUID(int=20),
            version=3,
            state="open",
            stage=0,
            created_by_id=UUID(int=1),
            proposal=SimpleNamespace(id=UUID(int=30)),
        )
    )
    current = Mock(return_value=True)
    person = Mock(return_value=SimpleNamespace(account_id=UUID(int=40)))
    labels = Mock(return_value={UUID(int=40): "Synthetic reviewer"})
    suitable = Mock(return_value=True)
    audit = Mock()
    for name, mock in (
        ("_scope", scope),
        ("_case", case),
        ("revision_is_current", current),
        ("resolve_active_verified_person_reference_by_email", person),
        ("active_verified_person_account_display_labels", labels),
        ("_suitable", suitable),
        ("_audit", audit),
    ):
        monkeypatch.setattr(selections, name, mock)
    return SimpleNamespace(
        scope=scope,
        case=case,
        current=current,
        person=person,
        labels=labels,
        suitable=suitable,
        audit=audit,
    )


def prepare(**changes):
    return selections.prepare_programme_reviewer_selection.__wrapped__(
        **(
            {
                "request": request(),
                "case_id": UUID(int=20),
                "email": "reviewer@maru.invalid",
                "expected_version": 3,
                "retry_key": UUID(int=50),
            }
            | changes
        )
    )


def read(token, **changes):
    return selections.read_programme_reviewer_selection.__wrapped__(
        **(
            {
                "request": request(),
                "case_id": UUID(int=20),
                "token": token,
                "expected_version": 3,
                "retry_key": UUID(int=50),
            }
            | changes
        )
    )


def test_preview_binds_original_person_scope_and_intent_without_contact_or_name_payload(
    world,
):
    selected = prepare()
    assert selected.account_id == UUID(int=40)
    assert selected.expected_version == 3
    assert selected.retry_key == UUID(int=50)
    value = signing.loads(selected.token, salt=selections._SALT)
    assert value == {
        "actor": str(UUID(int=1)),
        "organization": str(UUID(int=2)),
        "edition": str(UUID(int=3)),
        "department": str(UUID(int=4)),
        "case": str(UUID(int=20)),
        "person": str(UUID(int=40)),
        "version": 3,
        "retry": str(UUID(int=50)),
    }
    assert "reviewer@" not in str(value)
    assert "Synthetic" not in str(value)
    assert world.audit.call_args.args[:3] == (
        request(),
        "reviewer_selection",
        UUID(int=20),
    )


def test_scope_and_source_must_be_admitted_before_identity_lookup(world):
    world.scope.side_effect = Denied
    with pytest.raises(Denied):
        prepare()
    world.case.assert_not_called()
    world.person.assert_not_called()
    world.scope.side_effect = None
    world.case.side_effect = Denied
    with pytest.raises(Denied):
        prepare()
    world.person.assert_not_called()


@pytest.mark.parametrize("reason", ["stale", "closed", "withdrawn", "planning"])
def test_fresh_preview_rejects_ineligible_case_before_identity_lookup(world, reason):
    if reason == "stale":
        world.case.return_value.version = 4
    elif reason == "closed":
        world.case.return_value.state = "accepted"
    elif reason == "withdrawn":
        world.current.return_value = False
    else:
        world.scope.return_value.accepts_private_planning_writes = False
    with pytest.raises(ProgrammeReviewConflictError):
        prepare()
    world.person.assert_not_called()


@pytest.mark.parametrize("reason", ["unknown", "unsuitable", "unusable_label"])
def test_all_unusable_candidates_collapse_to_one_audited_empty_result(world, reason):
    if reason == "unknown":
        world.person.return_value = None
    elif reason == "unsuitable":
        world.suitable.return_value = False
    else:
        world.labels.return_value = {}
    assert prepare() is None
    world.audit.assert_called_once()


def test_audit_failure_never_releases_prospective_identity(world):
    world.audit.side_effect = Denied
    with pytest.raises(Denied):
        prepare()


def test_retained_selection_never_resolves_email_or_revalidates_fresh_assignment(world):
    original = prepare()
    world.person.reset_mock()
    world.suitable.reset_mock()
    world.current.reset_mock()
    world.case.return_value.version = 9
    world.case.return_value.state = "accepted"
    world.scope.return_value.accepts_private_planning_writes = False
    world.labels.return_value = {}
    selected = read(original.token)
    assert selected.account_id == original.account_id
    assert selected.token == original.token
    assert selected.display_label == "Unavailable person"
    assert not selected.person_current
    world.person.assert_not_called()
    world.suitable.assert_not_called()
    world.current.assert_not_called()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "department_id"]
)
def test_signed_selection_cannot_cross_scope_before_identity_label_lookup(world, field):
    original = prepare()
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(original.token, request=replace(request(), **{field: UUID(int=99)}))
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [{"case_id": UUID(int=99)}, {"expected_version": 4}, {"retry_key": UUID(int=99)}],
)
def test_case_version_and_retry_tampering_cannot_rebind_selection(world, changes):
    original = prepare()
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(original.token, **changes)
    world.labels.assert_not_called()


@pytest.mark.parametrize(
    "kind",
    [
        "signature",
        "oversized",
        "nonascii",
        "foreign_salt",
        "compressed",
        "extra",
        "boolean_version",
        "zero_person",
    ],
)
def test_closed_selection_rejects_malformed_or_wrong_purpose_proof(world, kind):
    original = prepare()
    value = signing.loads(original.token, salt=selections._SALT)
    if kind == "signature":
        token = original.token + "x"
    elif kind == "oversized":
        token = "x" * (selections.MAX_REVIEWER_SELECTION_BYTES + 1)
    elif kind == "nonascii":
        token = "界"
    elif kind == "foreign_salt":
        token = signing.dumps(value, salt="different-purpose")
    elif kind == "compressed":
        token = signing.dumps(value, salt=selections._SALT, compress=True)
    else:
        change = {
            "extra": {"extra": "unknown"},
            "boolean_version": {"version": True},
            "zero_person": {"person": str(UUID(int=0))},
        }[kind]
        token = signing.dumps(value | change, salt=selections._SALT)
    world.labels.reset_mock()
    with pytest.raises(Denied):
        read(token)
    world.labels.assert_not_called()


def test_signing_key_rotation_requires_retained_fallback_without_disabling_validation(
    world, settings
):
    settings.SECRET_KEY = "synthetic-original-selection-key"
    selected = prepare()
    settings.SECRET_KEY = "synthetic-replacement-selection-key"
    settings.SECRET_KEY_FALLBACKS = ["synthetic-original-selection-key"]
    assert read(selected.token).account_id == selected.account_id
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(Denied):
        read(selected.token)


@pytest.mark.parametrize("version", [0, True, "3", 2**63])
def test_version_shape_is_closed_before_any_scope_or_identity_query(world, version):
    with pytest.raises(Denied):
        prepare(expected_version=version)
    world.scope.assert_not_called()


def test_untyped_retry_is_rejected_before_scope(world):
    with pytest.raises(ValidationError):
        prepare(retry_key=str(UUID(int=50)))
    world.scope.assert_not_called()
