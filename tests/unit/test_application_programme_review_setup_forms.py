"""Bounded explicit review composition without persistence or policy defaults."""

import json
from dataclasses import asdict, replace
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.http import QueryDict

from maru.applications.programme_review_documents import decode_review_policy
from maru.applications.programme_review_setup_forms import (
    MAX_REVIEW_STATE,
    ReviewPolicySaveForm,
    ReviewStageForm,
    ReviewTemplatesForm,
    decode_proposed_review,
)
from maru.applications.programme_review_setup_queries import ReviewSetupQuestion
from tests.unit.test_application_programme_review_inputs import review_policy


def proposed():
    return json.dumps(asdict(review_policy()))


def proof(**changes):
    return {
        "proposed": proposed(),
        "expected_version": "4",
        "retry_key": str(UUID(int=90)),
    } | changes


def stage_data(**changes):
    return (
        proof(
            stage_index="0",
            code="content",
            required_reviews="2",
            anonymous="yes",
            discussion="no",
            question_keys=["session-title"],
            criterion_0_code="fit",
            criterion_0_label="Programme fit",
            criterion_0_minimum="0",
            criterion_0_maximum="5",
        )
        | changes
    )


def stage_form(**changes):
    return ReviewStageForm(
        stage_data(**changes),
        questions=(
            ReviewSetupQuestion("session-title", "Session title", "short_text", "C2"),
        ),
    )


def test_complete_document_round_trip_matches_canonical_policy_digest():
    decoded = decode_review_policy(json.loads(proposed()))
    assert decoded == review_policy().normalized()
    assert decoded.digest == review_policy().digest
    assert decode_review_policy(decode_proposed_review(proposed())) == decoded
    assert decode_proposed_review('{"stages":[],"templates":[]}') == {
        "stages": [],
        "templates": [],
    }


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        "{}",
        '{"stages":[],"templates":[],"extra":1}',
        '{"stages":[],"stages":[],"templates":[]}',
        '{"stages":{},"templates":[]}',
        '{"stages":[],"templates":[{}]}',
        "[" * 2000,
        " " * (MAX_REVIEW_STATE + 1),
    ],
    ids=[
        "null",
        "array",
        "empty",
        "unknown",
        "duplicate",
        "wrong-list",
        "partial-template",
        "deep",
        "oversized",
    ],
)
def test_untrusted_proposed_state_rejects_malformed_duplicate_or_oversized_input(raw):
    with pytest.raises(ValidationError):
        decode_proposed_review(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"anonymous": ""},
        {"discussion": ""},
        {"anonymous": "true"},
        {"required_reviews": ""},
        {"required_reviews": "02"},
        {"required_reviews": "17"},
        {"criterion_0_minimum": ""},
        {"criterion_0_maximum": "-1"},
        {"criterion_0_minimum": "6"},
        {"criterion_0_maximum": "10001"},
        {"criterion_1_label": "Partially supplied"},
        {"question_keys": []},
        {"question_keys": ["foreign"]},
        {"question_keys": ["session-title"] * 2},
        {"organization_id": str(UUID(int=22))},
        {"criterion_16_code": "overflow"},
    ],
)
def test_stage_rejects_defaults_partials_unknown_questions_or_extra_scope(change):
    assert not stage_form(**change).is_valid()


def test_stage_allows_inclusive_zero_and_requires_at_least_one_complete_criterion():
    form = stage_form(criterion_0_maximum="0")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["stage"].criteria[0].minimum == 0
    assert form.cleaned_data["stage"].criteria[0].maximum == 0
    assert not stage_form(
        **{f"criterion_0_{key}": "" for key in ("code", "label", "minimum", "maximum")}
    ).is_valid()


def test_largest_single_stage_stays_below_framework_field_count_limit():
    questions = tuple(
        ReviewSetupQuestion(f"key-{index}", f"Question {index}", "short_text", "C2")
        for index in range(500)
    )
    values = stage_data(
        question_keys=[row.key for row in questions], required_reviews="16"
    )
    for index in range(16):
        values.update(
            {
                f"criterion_{index}_code": f"fit-{index}",
                f"criterion_{index}_label": f"Fit {index}",
                f"criterion_{index}_minimum": "0",
                f"criterion_{index}_maximum": "10000",
            }
        )
    form = ReviewStageForm(values, questions=questions)
    assert form.is_valid(), form.errors
    assert len(form.fields) - 1 + len(questions) + 2 < 1000


def test_duplicate_single_value_field_is_not_silently_selected():
    values = QueryDict(mutable=True)
    for key, value in stage_data().items():
        values.setlist(key, value if isinstance(value, list) else [value])
    values.setlist("required_reviews", ["1", "2"])
    assert not ReviewStageForm(
        values,
        questions=(ReviewSetupQuestion("session-title", "Title", "short_text", "C2"),),
    ).is_valid()


def test_final_save_requires_all_stages_templates_confirmation_and_reason():
    values = proof(reason="Explicit policy", confirm="on")
    form = ReviewPolicySaveForm(values)
    assert form.is_valid(), form.errors
    assert form.policy() == review_policy().normalized()
    for field in ("reason", "confirm", "expected_version", "retry_key"):
        assert not ReviewPolicySaveForm(values | {field: ""}).is_valid()
    form = ReviewPolicySaveForm(values | {"proposed": '{"stages":[],"templates":[]}'})
    assert form.is_valid()
    with pytest.raises(ValidationError):
        form.policy()


def test_templates_have_no_implicit_recipient_text_or_receipt_policy():
    form = ReviewTemplatesForm(proof())
    assert not form.is_valid()
    assert len(form.errors) == 8


def test_policy_and_nested_documents_reject_unknown_keys_and_duplicate_codes():
    document = json.loads(proposed())
    document["stages"][0]["private_answers"] = "smuggled"
    with pytest.raises(ValidationError):
        decode_review_policy(document)
    repeated = replace(review_policy(), stages=review_policy().stages * 2)
    with pytest.raises(ValidationError):
        decode_proposed_review(json.dumps(asdict(repeated)))
