"""Release inputs cannot smuggle approval flags or ambiguous optimistic state."""

from dataclasses import FrozenInstanceError, fields, replace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.catalogs import MAX_CONFLICTS
from maru.scheduling.release_inputs import (
    ReleaseApprovalIntent,
    ReleaseCandidateSelection,
    ReleasePublicationIntent,
    ReleaseWarningIntent,
    ReleaseWithdrawalIntent,
)


def selection():
    return ReleaseCandidateSelection(uuid4(), uuid4(), 2, "a" * 64)


def publication():
    return ReleasePublicationIntent(uuid4(), None, 0, "a" * 64)


@pytest.mark.parametrize("field", ["candidate_id", "candidate_revision_id"])
@pytest.mark.parametrize("value", [None, "private-marker", 1])
def test_candidate_identifiers_are_exact_and_non_disclosing(field, value):
    with pytest.raises(ValidationError) as caught:
        replace(selection(), **{field: value}).validated()
    assert "private-marker" not in str(caught.value)


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.5, 2**63 - 1])
def test_candidate_version_is_not_coerced(value):
    with pytest.raises(ValidationError):
        replace(selection(), expected_candidate_version=value).validated()


@pytest.mark.parametrize("value", [None, "", "A" * 64, "a" * 63, "a" * 64 + "\n"])
def test_release_fingerprints_use_exact_lowercase_sha256(value):
    with pytest.raises(ValidationError):
        replace(selection(), source_snapshot_digest=value).validated()
    with pytest.raises(ValidationError):
        ReleaseWarningIntent(selection(), value).validated()
    with pytest.raises(ValidationError):
        replace(publication(), source_snapshot_digest=value).validated()


@pytest.mark.parametrize("value", [None, {}, "private-marker"])
def test_warning_and_approval_require_typed_selection(value):
    with pytest.raises(ValidationError):
        ReleaseWarningIntent(value, "a" * 64).validated()
    with pytest.raises(ValidationError):
        ReleaseApprovalIntent(value).validated()


def test_acknowledgements_canonicalize_without_mutating_input():
    ids = (UUID(int=2), UUID(int=1))
    intent = ReleaseApprovalIntent(selection(), ids)
    assert intent.validated().acknowledgement_ids == tuple(reversed(ids))
    assert intent.acknowledgement_ids == ids
    assert intent.validated().validated() == intent.validated()


def test_acknowledgements_reject_duplicates_mutable_collections_and_streams():
    identifier = uuid4()
    for ids in (
        (identifier, identifier),
        [identifier],
        {identifier},
        iter((identifier,)),
    ):
        with pytest.raises(ValidationError):
            ReleaseApprovalIntent(selection(), ids).validated()
    with pytest.raises(ValidationError):
        ReleaseApprovalIntent(selection(), ("private-marker",)).validated()


def test_acknowledgement_collection_bound_is_complete_not_truncated():
    ids = tuple(UUID(int=index + 1) for index in range(MAX_CONFLICTS))
    assert len(
        ReleaseApprovalIntent(selection(), ids).validated().acknowledgement_ids
    ) == (MAX_CONFLICTS)
    with pytest.raises(ValidationError):
        ReleaseApprovalIntent(selection(), (*ids, uuid4())).validated()


def test_initial_and_withdrawn_pointer_absence_are_distinct():
    assert publication().validated().expected_release_version == 0
    assert replace(publication(), expected_release_version=8).validated()
    assert replace(
        publication(), expected_active_release_id=uuid4(), expected_release_version=8
    ).validated()
    with pytest.raises(ValidationError):
        replace(publication(), expected_active_release_id=uuid4()).validated()


@pytest.mark.parametrize("value", [True, -1, "1", 1.5, 2**63 - 1])
def test_pointer_version_is_advanceable_without_coercion(value):
    with pytest.raises(ValidationError):
        replace(publication(), expected_release_version=value).validated()
    with pytest.raises(ValidationError):
        ReleaseWithdrawalIntent(uuid4(), value).validated()


@pytest.mark.parametrize("value", [None, "private-marker", 1])
def test_approval_and_withdrawal_require_retained_identifiers(value):
    with pytest.raises(ValidationError):
        replace(publication(), approval_id=value).validated()
    with pytest.raises(ValidationError):
        ReleaseWithdrawalIntent(value, 1).validated()
    if value is not None:
        with pytest.raises(ValidationError):
            replace(publication(), expected_active_release_id=value).validated()


def test_withdrawal_cannot_mean_a_never_published_empty_candidate():
    with pytest.raises(ValidationError):
        ReleaseWithdrawalIntent(uuid4(), 0).validated()


def test_intents_remain_immutable_and_contain_no_eligibility_or_artifact_flags():
    selected = selection()
    warning = ReleaseWarningIntent(selected, "b" * 64)
    approval = ReleaseApprovalIntent(selected)
    withdrawal = ReleaseWithdrawalIntent(uuid4(), 1)
    for intent in (selected, warning, approval, publication(), withdrawal):
        assert intent.validated() == intent
        first_field = fields(intent)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(intent, first_field, None)
        assert not {"eligible", "approved", "artifact_valid", "authorized"} & {
            field.name for field in fields(intent)
        }
