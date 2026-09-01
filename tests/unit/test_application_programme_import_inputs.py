"""Unit coverage for strict raw-byte Programme import inputs."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from maru.applications import programme_import_inputs
from maru.applications.programme_import_inputs import (
    MAX_PROGRAMME_IMPORT_BYTES,
    ParsedProgrammeImportDocument,
    ProgrammeImportAddressInput,
    ProgrammeImportCallItemInput,
    ProgrammeImportInputError,
    ProgrammeImportProposalItemInput,
    parse_programme_import_document,
    parse_programme_import_item_payload,
)
from maru.applications.programme_inputs import MAX_PROGRAMME_ANSWER_LENGTH


def _raw(document: object) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _call_item() -> dict[str, object]:
    return {
        "kind": "call",
        "source_key": "call-2027",
        "definition": {
            "code": "programme-call-2027",
            "name": "Programme call 2027",
            "description": "Submit a session for the on-site programme.",
            "purpose": "Collect proposals for Programme review.",
            "classification": "C2",
            "maximum_submissions_per_person": 4,
            "opens_at": "2027-01-01T00:00:00Z",
            "closes_at": "2027-03-01T00:00:00Z",
            "applicant_edit_until": "2027-02-01T00:00:00Z",
            "audience_policy_code": None,
            "retention_policy_code": None,
            "sections": [
                {
                    "key": "proposal",
                    "title": "Proposal",
                    "help_text": "Tell us about the session.",
                    "questions": [
                        {
                            "key": "title",
                            "field_type": "short_text",
                            "label": "Session title",
                            "help_text": "A concise title.",
                            "required": True,
                            "purpose": "Identify the submitted session.",
                            "classification": "C2",
                            "retention_policy_code": None,
                            "condition": None,
                            "constraints": {
                                "minimum_length": 3,
                                "maximum_length": 160,
                            },
                        },
                        {
                            "key": "topics",
                            "field_type": "multiple_choice",
                            "label": "Topics",
                            "help_text": "Choose relevant topics.",
                            "required": False,
                            "purpose": "Support Programme grouping.",
                            "classification": "C1",
                            "retention_policy_code": None,
                            "condition": None,
                            "constraints": {
                                "options": [
                                    {"code": "craft", "label": "Craft"},
                                    {"code": "social", "label": "Social"},
                                ],
                                "maximum_choices": 2,
                            },
                        },
                    ],
                },
            ],
        },
        "configuration": {
            "maximum_collaborators": 3,
            "content_policy_code": "content.v1",
            "contributor_consent_policy_code": "consent.v1",
            "collaboration_retention_policy_code": "collaboration.v1",
            "tracks": [
                {
                    "code": "community",
                    "label": "Community",
                    "description": "Community-created sessions.",
                },
            ],
            "formats": [
                {
                    "code": "talk",
                    "label": "Talk",
                    "description": "A scheduled presentation.",
                    "minimum_duration_minutes": 30,
                    "default_duration_minutes": 45,
                    "maximum_duration_minutes": 60,
                },
            ],
            "contributor_fields": [
                {
                    "field_code": "public_name",
                    "lead_requirement": "required",
                    "collaborator_requirement": "optional",
                },
            ],
        },
    }


def _proposal_item() -> dict[str, object]:
    return {
        "kind": "proposal",
        "source_key": "proposal-42",
        "call_source_key": "call-2027",
        "lead_email": "LEADER@Example.COM",
        "selection": {
            "track_code": "community",
            "format_code": "talk",
            "requested_duration_minutes": 45,
        },
        "answers": [
            {
                "question_key": "topics",
                "field_type": "multiple_choice",
                "value": ["social", "craft"],
            },
            {
                "question_key": "title",
                "field_type": "short_text",
                "value": "  Café meetup  ",
            },
        ],
    }


def _document(*, items: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema": "applications.programme_import",
        "version": 1,
        "items": items or [_proposal_item(), _call_item()],
    }


def test_public_surface_exposes_orchestration_and_reload_contract() -> None:
    """Keep services on the immutable public parser boundary."""
    expected = {
        "ParsedProgrammeImportDocument",
        "ProgrammeImportBatchInput",
        "ProgrammeImportCallItemInput",
        "ProgrammeImportInputError",
        "ProgrammeImportItemInput",
        "ProgrammeImportProposalItemInput",
        "parse_programme_import",
        "parse_programme_import_batch",
        "parse_programme_import_document",
        "parse_programme_import_item_payload",
    }

    assert expected <= set(programme_import_inputs.__all__)
    assert all(hasattr(programme_import_inputs, name) for name in expected)


def test_parse_document_returns_normalized_immutable_typed_items() -> None:
    """Normalize a proposal and call without accepting trusted context in JSON."""
    parsed = parse_programme_import_document(_raw(_document()))

    assert isinstance(parsed, ParsedProgrammeImportDocument)
    assert [item.kind for item in parsed.items] == ["call", "proposal"]
    call = parsed.items[0]
    proposal = parsed.items[1]
    assert isinstance(call, ProgrammeImportCallItemInput)
    assert isinstance(proposal, ProgrammeImportProposalItemInput)
    assert call.item_index == 1
    assert call.definition_input.name == "Programme call 2027"
    configuration = call.configuration_for_owner_department(uuid4())
    assert configuration.maximum_collaborators == 3
    assert proposal.item_index == 0
    assert proposal.lead_email == "leader@example.com"
    assert proposal.track_code == "community"
    assert proposal.format_code == "talk"
    assert proposal.requested_duration_minutes == 45
    assert [answer.question_key for answer in proposal.answers] == ["title", "topics"]
    assert proposal.answers[0].value == "Café meetup"
    assert proposal.answers[1].value == ("craft", "social")
    assert len(parsed.source_digest) == 64
    assert parsed.canonical_payload.startswith(b'{"items":[')

    with pytest.raises(FrozenInstanceError):
        proposal.source_key = "changed"  # type: ignore[misc]


def test_canonical_digest_ignores_nonsemantic_order_and_normalization() -> None:
    """Give semantically equivalent documents identical staged evidence."""
    first_document = _document()
    second_document = deepcopy(first_document)
    second_document["items"].reverse()  # type: ignore[union-attr]
    call = second_document["items"][0]  # type: ignore[index]
    definition = call["definition"]  # type: ignore[index]
    definition["name"] = "  Programme   call 2027  "  # type: ignore[index]
    definition["opens_at"] = "2027-01-01T01:00:00+01:00"  # type: ignore[index]
    proposal = second_document["items"][1]  # type: ignore[index]
    proposal["answers"].reverse()  # type: ignore[index, union-attr]
    proposal["answers"][0]["value"] = "Cafe\u0301 meetup"  # type: ignore[index]
    proposal["answers"][1]["value"].reverse()  # type: ignore[index, union-attr]

    first = parse_programme_import_document(_raw(first_document))
    second = parse_programme_import_document(_raw(second_document))

    assert first.canonical_payload == second.canonical_payload
    assert first.source_digest == second.source_digest
    assert [item.source_digest for item in first.items] == [
        item.source_digest for item in second.items
    ]


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        ("short_text", "  Session  ", "Session"),
        ("long_text", "Line one\r\nLine two", "Line one\nLine two"),
        ("integer", 42, 42),
        ("decimal", "12.3400", "12.34"),
        ("boolean", True, True),
        ("single_choice", "workshop", "workshop"),
        ("multiple_choice", ["social", "craft"], ("craft", "social")),
        ("date", "2028-02-29", "2028-02-29"),
        ("time", "09:30:00.1", "09:30:00.100000"),
        ("instant", "2027-01-01T01:00:00+01:00", "2027-01-01T00:00:00Z"),
        ("email", "speaker@example.test", "speaker@example.test"),
        ("phone", "+36 1 234 5678", "+36 1 234 5678"),
        ("url", "https://example.test/session", "https://example.test/session"),
    ],
)
def test_typed_proposal_answers_have_one_canonical_shape(
    field_type: str,
    value: object,
    expected: object,
) -> None:
    """Bind every scalar/container answer shape before staging and digesting."""

    proposal = _proposal_item()
    proposal["answers"] = [
        {
            "question_key": "typed-answer",
            "field_type": field_type,
            "value": value,
        }
    ]

    parsed = parse_programme_import_document(_raw(_document(items=[proposal])))

    item = parsed.items[0]
    assert isinstance(item, ProgrammeImportProposalItemInput)
    answer = item.answers[0]
    assert answer.field_type.value == field_type
    assert answer.value == expected


@pytest.mark.parametrize(
    ("field_type", "value", "expected_code"),
    [
        ("decimal", 1, "applications_programme_import_field_invalid"),
        ("integer", "1", "applications_programme_import_field_invalid"),
        ("boolean", 1, "applications_programme_import_field_invalid"),
        ("date", "2027-02-29", "applications_programme_import_field_invalid"),
        ("time", "09:30:00+01:00", "applications_programme_import_field_invalid"),
        (
            "instant",
            "2027-01-01T00:00:00",
            "applications_programme_import_field_invalid",
        ),
        ("email", "not-an-email", "applications_programme_import_field_invalid"),
        ("phone", "12", "applications_programme_import_field_invalid"),
        (
            "url",
            "http://example.test/not-https",
            "applications_programme_import_field_invalid",
        ),
        (
            "multiple_choice",
            [f"choice-{index}" for index in range(101)],
            "applications_programme_import_shape_invalid",
        ),
        (
            "person_reference",
            "value",
            "applications_programme_import_question_type_unsupported",
        ),
        (
            "domain_reference",
            "value",
            "applications_programme_import_question_type_unsupported",
        ),
        (
            "safe_file",
            "value",
            "applications_programme_import_question_type_unsupported",
        ),
        ("unknown", "value", "applications_programme_import_field_invalid"),
        ("short_text", None, "applications_programme_import_field_invalid"),
    ],
)
def test_typed_proposal_answers_reject_wrong_or_excluded_shapes(
    field_type: str,
    value: object,
    expected_code: str,
) -> None:
    """Reject ambiguous, null, or excluded typed values with fixed diagnostics."""

    proposal = _proposal_item()
    proposal["answers"] = [
        {
            "question_key": "typed-answer",
            "field_type": field_type,
            "value": value,
        }
    ]

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(_document(items=[proposal])))

    assert failure.value.code == expected_code


def test_answer_value_enforces_the_exact_canonical_byte_boundary() -> None:
    """Count encoded canonical value bytes, including JSON string delimiters."""

    proposal = _proposal_item()
    answer = {
        "question_key": "bounded-answer",
        "field_type": "short_text",
        "value": "x" * (MAX_PROGRAMME_ANSWER_LENGTH - 2),
    }
    proposal["answers"] = [answer]

    parsed = parse_programme_import_document(_raw(_document(items=[proposal])))

    item = parsed.items[0]
    assert isinstance(item, ProgrammeImportProposalItemInput)
    assert len(item.answers[0].value) == MAX_PROGRAMME_ANSWER_LENGTH - 2

    answer["value"] += "x"  # type: ignore[operator]
    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(_document(items=[proposal])))
    assert failure.value.code == "applications_programme_import_field_invalid"


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    [
        ("1.0", "1.0000"),
        ("2027-01-01T01:00:00+01:00", "2027-01-01T00:00:00Z"),
    ],
)
def test_typed_numeric_and_instant_equivalents_share_source_digest(
    first_value: str,
    second_value: str,
) -> None:
    """Digest the canonical typed meaning instead of one equivalent spelling."""

    field_type = "decimal" if first_value.startswith("1.") else "instant"
    documents = []
    for value in (first_value, second_value):
        proposal = _proposal_item()
        proposal["answers"] = [
            {
                "question_key": "canonical-answer",
                "field_type": field_type,
                "value": value,
            }
        ]
        documents.append(
            parse_programme_import_document(_raw(_document(items=[proposal])))
        )

    assert documents[0].canonical_payload == documents[1].canonical_payload
    assert documents[0].source_digest == documents[1].source_digest


@pytest.mark.parametrize(
    "instant",
    [
        "2027-01-01T00:00:00-00:00",
        "2027-01-01T00:00:00+00:60",
        "2027-01-01T00:00:00+14:01",
        "2027-01-01T00:00:00+15:00",
        "2027-01-01T24:00:00Z",
        "2027-01-01T23:59:60Z",
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
    ],
)
def test_instants_reject_ambiguous_or_out_of_range_offsets(instant: str) -> None:
    """Reject lenient ISO spellings before they can change canonical evidence."""

    call = _call_item()
    call["definition"]["opens_at"] = instant  # type: ignore[index]

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(_document(items=[call])))

    assert failure.value.code == "applications_programme_import_field_invalid"
    assert failure.value.field == "opens_at"


@pytest.mark.parametrize(
    "instant",
    [
        "2027-01-01T00:00:00Z",
        "2027-01-01T00:00:00+00:00",
        "2027-01-01T00:00:00+13:59",
        "2027-01-01T00:00:00+14:00",
        "2027-01-01T00:00:00-14:00",
    ],
)
def test_instants_accept_the_closed_civil_offset_boundary(instant: str) -> None:
    """Accept valid explicit civil offsets through exactly fourteen hours."""

    call = _call_item()
    call["definition"]["opens_at"] = instant  # type: ignore[index]

    parsed = parse_programme_import_document(_raw(_document(items=[call])))

    assert isinstance(parsed.items[0], ProgrammeImportCallItemInput)


def test_canonical_item_reload_repeats_validation_and_requires_exact_bytes() -> None:
    """Never rebuild staged typed values through an unchecked JSON decode."""
    parsed = parse_programme_import_document(_raw(_document()))

    reloaded = parse_programme_import_item_payload(parsed.items[1].canonical_payload)

    assert isinstance(reloaded, ProgrammeImportProposalItemInput)
    assert reloaded.item_index == 0
    assert reloaded.source_key == parsed.items[1].source_key
    assert reloaded.source_digest == parsed.items[1].source_digest
    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_item_payload(
            b" " + parsed.items[1].canonical_payload,
        )
    assert failure.value.code == "applications_programme_import_schema_invalid"


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        (b"\xff", "applications_programme_import_encoding_invalid"),
        (b"\xef\xbb\xbf{}", "applications_programme_import_encoding_invalid"),
        ("{}".encode("utf-16-le"), "applications_programme_import_encoding_invalid"),
        (b'{"version":1.0}', "applications_programme_import_json_invalid"),
        (b'{"version":1e0}', "applications_programme_import_json_invalid"),
        (b'{"version":-0}', "applications_programme_import_json_invalid"),
        (b'{"version":NaN}', "applications_programme_import_json_invalid"),
        (b'{"same":1,"same":2}', "applications_programme_import_duplicate_key"),
        (
            '{"\u00e9":1,"e\u0301":2}'.encode(),
            "applications_programme_import_duplicate_key",
        ),
    ],
)
def test_transport_rejects_ambiguous_encoding_numbers_and_keys(
    raw: bytes,
    expected_code: str,
) -> None:
    """Reject transports that could produce ambiguous or unsafe evidence."""
    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(raw)

    assert failure.value.code == expected_code


def test_parser_accepts_only_raw_bytes() -> None:
    """Prevent pre-decoding from bypassing encoding and duplicate-key checks."""
    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document("{}")  # type: ignore[arg-type]

    assert failure.value.code == "applications_programme_import_payload_type_invalid"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(
            b" " * (MAX_PROGRAMME_IMPORT_BYTES + 1),
            id="bytes",
        ),
        pytest.param(
            (b"[" * 17) + b"0" + (b"]" * 17),
            id="depth",
        ),
        pytest.param(
            _raw({str(index): index for index in range(33)}),
            id="object-members",
        ),
        pytest.param(
            _raw(list(range(1_001))),
            id="array-items",
        ),
        pytest.param(
            _raw("x" * 65_537),
            id="string-length",
        ),
    ],
)
def test_parser_enforces_transport_and_graph_complexity(raw: bytes) -> None:
    """Bound bytes, depth, object members, arrays, and strings before staging."""
    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(raw)

    assert failure.value.code in {
        "applications_programme_import_payload_too_large",
        "applications_programme_import_complexity_limit",
    }


def test_parser_enforces_total_json_value_limit() -> None:
    """Reject a shallow bounded-width graph containing too many values."""
    value: object = 0
    for _index in range(4):
        value = [value] * 23

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(value))

    assert failure.value.code == "applications_programme_import_complexity_limit"


@pytest.mark.parametrize(
    "field_type", ["person_reference", "domain_reference", "safe_file"]
)
def test_v1_rejects_deferred_reference_and_file_question_types(field_type: str) -> None:
    """Keep reference resolution and file safety out of the V1 trust boundary."""
    document = _document(items=[_call_item()])
    call = document["items"][0]  # type: ignore[index]
    question = call["definition"]["sections"][0]["questions"][0]  # type: ignore[index]
    question["field_type"] = field_type
    question["constraints"] = {}

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(document))

    assert (
        failure.value.code == "applications_programme_import_question_type_unsupported"
    )
    assert failure.value.field == "field_type"


def test_closed_shapes_reject_unknown_fields_without_echoing_them() -> None:
    """Keep diagnostics fixed even when an attacker supplies a secret key."""
    document = _document(items=[_call_item()])
    call = document["items"][0]  # type: ignore[index]
    call["definition"]["secret-token-should-not-escape"] = "raw-secret"  # type: ignore[index]

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(document))

    diagnostic = failure.value
    rendered = f"{diagnostic!s} {diagnostic.args!r} {diagnostic.__dict__!r}"
    assert diagnostic.code == "applications_programme_import_shape_invalid"
    assert diagnostic.item_index == 0
    assert diagnostic.pointer == "/items/0/definition"
    assert "secret-token-should-not-escape" not in rendered
    assert "raw-secret" not in rendered


def test_duplicate_source_identity_is_rejected_without_disclosure() -> None:
    """Use kind plus exact source key as the document-local source identity."""
    duplicate = deepcopy(_call_item())
    document = _document(items=[_call_item(), duplicate])

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(document))

    assert failure.value.code == "applications_programme_import_source_duplicate"
    assert failure.value.item_index == 1
    assert "call-2027" not in str(failure.value)


def test_invalid_dependency_source_key_reports_its_exact_fixed_field() -> None:
    """Identify the closed dependency field without echoing its supplied value."""

    proposal = _proposal_item()
    proposal["call_source_key"] = " secret value "

    with pytest.raises(ProgrammeImportInputError) as failure:
        parse_programme_import_document(_raw(_document(items=[proposal])))

    assert failure.value.pointer == "/items/0/call_source_key"
    assert failure.value.field == "call_source_key"
    assert "secret value" not in str(failure.value)


def test_address_answer_is_closed_normalized_and_immutable() -> None:
    """Normalize the only admitted object-valued answer without open JSON."""
    proposal = _proposal_item()
    proposal["answers"] = [
        {
            "question_key": "location",
            "field_type": "address",
            "value": {
                "line_1": "  1 Main Street ",
                "line_2": "",
                "locality": "Budapest",
                "region": "Pest",
                "postal_code": "1011",
                "country_code": "hu",
            },
        },
    ]
    parsed = parse_programme_import_document(_raw(_document(items=[proposal])))
    item = parsed.items[0]
    assert isinstance(item, ProgrammeImportProposalItemInput)
    answer = item.answers[0]
    assert answer.field_type.value == "address"
    address = answer.value
    assert isinstance(address, ProgrammeImportAddressInput)
    assert address.country_code == "HU"
    assert address.as_application_value() == {
        "line_1": "1 Main Street",
        "locality": "Budapest",
        "postal_code": "1011",
        "country_code": "HU",
        "region": "Pest",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update({"unexpected": True}),
        lambda document: document.update({"version": 2}),
        lambda document: document.update({"items": []}),
        lambda document: document["items"][0].update({"unknown": "value"}),
    ],
)
def test_root_and_item_shapes_are_exact(mutation: object) -> None:
    """Reject missing, unknown, empty, or unsupported top-level contracts."""
    document = _document(items=[_call_item()])
    mutation(document)  # type: ignore[operator]

    with pytest.raises(ProgrammeImportInputError):
        parse_programme_import_document(_raw(document))
