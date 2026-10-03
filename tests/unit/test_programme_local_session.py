"""Private handoff and explicitly labelled preparation, without native resources."""

import base64
import io
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tests.rehearsals import programme_local_session as session
from tests.rehearsals import programme_runner as runner


def _continuity_fixture():
    organization_id = UUID("10000000-0000-4000-8000-000000000001")
    edition_id = UUID("20000000-0000-4000-8000-000000000002")
    run_id = "a" * 32
    policy = {
        "contract": "scheduling.programme-continuity-trust@1",
        "keys": [
            {
                "organization_id": str(organization_id),
                "edition_id": str(edition_id),
                "key_id": "fixture-" + run_id,
                "public_key_b64": base64.b64encode(b"p" * 32).decode(),
                "not_before": "2026-10-02T08:00:00+00:00",
                "not_after": "2026-10-02T09:00:00+00:00",
            }
        ],
    }
    fixture = SimpleNamespace(
        run_id=run_id,
        scenario=SimpleNamespace(
            organization_id=organization_id, edition_id=edition_id
        ),
        continuity_trust_policy=json.dumps(
            policy, sort_keys=True, separators=(",", ":")
        ).encode(),
    )
    return fixture, policy


def test_published_handoff_uses_only_independently_prepared_public_trust():
    fixture, policy = _continuity_fixture()
    result = session.continuity_handoff(fixture, "published")
    assert json.loads(result["continuity_trust_policy"]) == policy
    assert result["continuity_trust_policy"].encode() == fixture.continuity_trust_policy
    assert "private_key" not in json.dumps(result)


@pytest.mark.parametrize("stage", ["team", "items"])
def test_other_stages_do_not_read_or_hand_off_continuity_material(stage):
    assert session.continuity_handoff(object(), stage) == {}


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "malformed",
        "private",
        "foreign",
        "other-edition",
        "other-run",
        "two-keys",
    ],
)
def test_handoff_refuses_missing_secret_or_cross_fixture_trust(change):
    fixture, policy = _continuity_fixture()
    key = policy["keys"][0]
    if change == "private":
        key["private_key_b64"] = "must-not-be-handed-off"
    elif change == "foreign":
        key["organization_id"] = "30000000-0000-4000-8000-000000000003"
    elif change == "other-edition":
        key["edition_id"] = "30000000-0000-4000-8000-000000000003"
    elif change == "other-run":
        key["key_id"] = "fixture-" + "b" * 32
    elif change == "two-keys":
        policy["keys"].append(dict(key))
    fixture.continuity_trust_policy = json.dumps(
        policy, sort_keys=True, separators=(",", ":")
    ).encode()
    if change == "missing":
        fixture.continuity_trust_policy = None
    elif change == "malformed":
        fixture.continuity_trust_policy = b"not JSON"
    with pytest.raises(ValueError, match="invalid_continuity_handoff"):
        session.continuity_handoff(fixture, "published")


def test_handoff_is_encrypted_and_round_trips_only_for_recipient():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()
    recipient = session.load_recipient(public)
    document = {"email": "fictional@example.invalid", "password": "private-test-value"}
    envelope = session.seal_handoff(document, recipient)
    encoded = json.dumps(envelope)
    assert "fictional@example.invalid" not in encoded
    assert "private-test-value" not in encoded
    aes_key = key.decrypt(
        base64.b64decode(envelope["sealed_key"]),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    plaintext = AESGCM(aes_key).decrypt(
        base64.b64decode(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        session._AAD,
    )
    assert json.loads(plaintext) == document
    assert envelope != session.seal_handoff(document, recipient)


@pytest.mark.parametrize(
    "value", [None, "", "invalid!", "x" * 1025, "/private/key.pem"]
)
def test_recipient_is_not_a_path_or_unbounded_input(value):
    with pytest.raises((ValueError, TypeError)):
        session.load_recipient(value)


def test_other_key_types_cannot_receive_credentials():
    key = ec.generate_private_key(ec.SECP256R1())
    encoded = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()
    with pytest.raises(ValueError, match="invalid_handoff_key"):
        session.load_recipient(encoded)


def test_team_does_not_precomplete_later_human_tasks():
    person = SimpleNamespace(
        account_id="fictional-id", email="fictional@example.invalid", password="private"
    )
    fixture = Mock(
        scenario=SimpleNamespace(controllers=(person, person), intake_person=person)
    )
    people = session.prepare_stage(fixture, "team")
    assert [person["role"] for person in people] == [
        "organizer",
        "independent-approver",
        "intake-organizer",
    ]
    fixture.prepare_proposal.assert_not_called()
    fixture.prepare_items.assert_not_called()
    fixture.prepare_release.assert_not_called()


def test_invalid_stage_does_not_start_later_prerequisites():
    person = SimpleNamespace(
        account_id="fictional-id", email="fictional@example.invalid", password="private"
    )
    fixture = Mock(
        scenario=SimpleNamespace(controllers=(person, person), intake_person=person)
    )
    with pytest.raises(ValueError, match="invalid_session_stage"):
        session.prepare_stage(fixture, "production")
    fixture.prepare_proposal.assert_not_called()


@pytest.mark.parametrize("stage", ["items", "published"])
def test_handoff_contains_exact_existing_personas_for_prepared_stages(stage):
    def person(label):
        return SimpleNamespace(
            account_id=label,
            email=f"{label}@example.invalid",
            password=f"synthetic-{label}",
        )

    review_labels = (
        "review-coordinator",
        "recusing-reviewer",
        "reviewer",
        "moderator",
        "decider",
        "converter",
    )
    labels = [
        "organizer",
        "independent-approver",
        "intake-organizer",
        *review_labels,
        "proposal-lead",
        "collaborator",
        "public-copy-reviewer",
        "ceremony-host",
        "planner",
        "catalog-organizer",
        "physical-reviewer",
        "volunteer",
        "release-reviewer",
    ]
    people = {label: person(label) for label in labels}
    fixture = Mock(
        scenario=SimpleNamespace(
            controllers=(people["organizer"], people["independent-approver"]),
            intake_person=people["intake-organizer"],
        )
    )
    proposal = SimpleNamespace(
        lead=people["proposal-lead"], collaborator=people["collaborator"]
    )
    review = SimpleNamespace(people=tuple(people[label] for label in review_labels))
    items = SimpleNamespace(
        public_reviewer=people["public-copy-reviewer"],
        ceremony_host=people["ceremony-host"],
    )
    planning = SimpleNamespace(
        planner=people["planner"], catalog_person=people["catalog-organizer"]
    )
    physical = SimpleNamespace(reviewer=people["physical-reviewer"])
    staffing = SimpleNamespace(volunteer=people["volunteer"])
    release = SimpleNamespace(reviewer=people["release-reviewer"])
    stages = (
        "proposal",
        "review",
        "items",
        "planning",
        "physical",
        "staffing",
        "release",
    )
    results = (proposal, review, items, planning, physical, staffing, release)
    for name, result in zip(stages, results, strict=True):
        getattr(fixture, f"prepare_{name}").return_value = result

    actual = session.prepare_stage(fixture, stage)

    expected_labels = labels if stage == "published" else labels[:13]
    assert actual == [
        session._person(label, people[label]) for label in expected_labels
    ]
    assert len({item["account_id"] for item in actual}) == len(actual)
    fixture.prepare_proposal.assert_called_once_with()
    fixture.prepare_review.assert_called_once_with(proposal)
    fixture.prepare_items.assert_called_once_with(proposal, review)
    if stage == "published":
        fixture.prepare_planning.assert_called_once_with(proposal, review, items)
        fixture.prepare_physical.assert_called_once_with(
            proposal, review, items, planning
        )
        fixture.prepare_staffing.assert_called_once_with(
            proposal, review, items, planning, physical
        )
        fixture.prepare_release.assert_called_once_with(
            proposal, review, items, planning, physical, staffing
        )
    else:
        fixture.prepare_planning.assert_not_called()
        fixture.prepare_physical.assert_not_called()
        fixture.prepare_staffing.assert_not_called()
        fixture.prepare_release.assert_not_called()
    fixture.verify_excluded_state.assert_called_once_with()


@pytest.mark.parametrize(
    "input_text", ["", "stop\n", "unknown\n", "refresh\n", "diagnostics\n"]
)
@pytest.mark.parametrize("stage", ["team", "items", "published"])
def test_interactive_input_keeps_original_lease_and_disposes_owned_contexts(
    monkeypatch, input_text, stage
):
    events = []
    provisioned, _ = _continuity_fixture()
    fixture = Mock(
        deadline=3600.0,
        run_id=provisioned.run_id,
        scenario=provisioned.scenario,
        continuity_trust_policy=provisioned.continuity_trust_policy,
    )

    @contextmanager
    def application(**options):
        assert options == {
            "setup_mode": "new_foundation",
            "with_scanner": stage != "team",
            "with_continuity": stage == "published",
            "with_isolation": True,
        }
        try:
            yield fixture
        finally:
            events.append("application disposed")

    @contextmanager
    def browser(actual):
        assert actual is fixture
        try:
            yield SimpleNamespace(
                url="http://127.0.0.1:50001",
                diagnostics=lambda: [{"method": "POST", "state": "200", "count": 2}],
            )
        finally:
            events.append("browser disposed")

    monkeypatch.setattr(session, "require_programme_rehearsal_request", Mock())
    monkeypatch.setenv(session.OPT_IN, "synthetic-loopback-only")
    monkeypatch.setattr(session.sys, "stdin", io.StringIO(input_text))
    monkeypatch.setattr(
        session.threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(start=target, daemon=daemon),
    )
    monkeypatch.setattr(session.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(runner, "isolated_programme_application", application)
    monkeypatch.setattr(session, "local_programme_browser", browser)
    monkeypatch.setattr(session, "prepare_stage", Mock(return_value=[]))
    handoff = Mock(return_value={"state": "ready", "ciphertext": "encrypted"})
    monkeypatch.setattr(session, "seal_handoff", handoff)
    emitted = []
    monkeypatch.setattr(session, "_emit", emitted.append)

    session.run_session(recipient="public key", stage=stage)

    assert events == ["browser disposed", "application disposed"]
    assert [item["state"] for item in emitted] == [
        "preparing",
        "ready",
        *(["diagnostics"] if input_text == "diagnostics\n" else []),
        "disposed",
    ]
    if input_text == "diagnostics\n":
        assert emitted[2] == {
            "state": "diagnostics",
            "counts": [{"method": "POST", "state": "200", "count": 2}],
        }
    assert fixture.deadline == 3600.0
    assert handoff.call_args.args[0]["remaining_seconds"] == 3500
    handed_off = handoff.call_args.args[0]
    if stage == "published":
        assert (
            handed_off["continuity_trust_policy"].encode()
            == provisioned.continuity_trust_policy
        )
    else:
        assert "continuity_trust_policy" not in handed_off
    assert fixture.refresh_workers.call_count == (1 if input_text == "refresh\n" else 0)
    assert fixture.verify_excluded_state.call_count == 2
