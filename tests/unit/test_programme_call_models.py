from __future__ import annotations

import importlib
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import migrations
from django.db import models as django_models

from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationTargetKind,
    ProgrammeCall,
    ProgrammeCallContributorField,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCollaboratorState,
    ProgrammeCommandAggregateKind,
    ProgrammeCommandReceipt,
    ProgrammeCommandResultKind,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalCollaboratorTransition,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalRevisionResponse,
    ProgrammeProposalSelectionRevision,
)
from maru.applications.programme_writer_boundary import (
    programme_application_writer,
)

PROGRAMME_MODELS = (
    ProgrammeCall,
    ProgrammeCallTrack,
    ProgrammeCallFormat,
    ProgrammeCallContributorField,
    ProgrammeProposal,
    ProgrammeProposalSelectionRevision,
    ProgrammeProposalCollaborator,
    ProgrammeProposalCollaboratorTransition,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalRevisionResponse,
    ProgrammeCommandReceipt,
)

APPEND_ONLY_MODELS = (
    ProgrammeProposalSelectionRevision,
    ProgrammeProposalCollaboratorTransition,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalRevisionResponse,
    ProgrammeCommandReceipt,
)


def test_programme_item_target_and_all_tenant_scopes_are_explicit() -> None:
    assert ApplicationTargetKind.PROGRAMME_ITEM == "programme_item"
    for model_type in PROGRAMME_MODELS:
        field_names = {field.name for field in model_type._meta.fields}
        assert {"organization", "edition"} <= field_names
        assert "aggregate_version" not in field_names


def test_programme_foreign_keys_are_protected_and_profile_is_typed() -> None:
    fields = [
        field for model_type in PROGRAMME_MODELS for field in model_type._meta.fields
    ]
    relation_fields = [
        field
        for field in fields
        if isinstance(field, (django_models.ForeignKey, django_models.OneToOneField))
    ]
    assert relation_fields
    assert all(
        field.remote_field.on_delete is django_models.PROTECT
        for field in relation_fields
    )
    assert not any(isinstance(field, django_models.JSONField) for field in fields)

    profile_fields = {
        field.name: field
        for field in ProgrammeProposalContributorProfileRevision._meta.fields
    }
    assert {"public_name", "biography", "pronouns", "website"} <= profile_fields.keys()
    assert isinstance(profile_fields["website"], django_models.URLField)


def test_collaborator_expiry_is_derived_and_transition_keeps_expiry() -> None:
    assert "expired" not in ProgrammeCollaboratorState.values
    assert set(ProgrammeCollaboratorState.values) == {
        "invited",
        "accepted",
        "declined",
        "left",
        "removed",
    }
    transition_expiry = ProgrammeProposalCollaboratorTransition._meta.get_field(
        "invite_expires_at"
    )
    assert transition_expiry.null


def test_answer_versions_preserve_legacy_nulls_and_validate_exact_steps() -> None:
    source = ApplicationAnswerRevision._meta.get_field("source_version")
    result = ApplicationAnswerRevision._meta.get_field("resulting_version")
    assert source.null
    assert result.null

    legacy = ApplicationAnswerRevision()
    legacy.clean()
    current = ApplicationAnswerRevision(source_version=4, resulting_version=5)
    current.clean()

    with pytest.raises(ValidationError, match="both absent or both present"):
        ApplicationAnswerRevision(source_version=4).clean()
    with pytest.raises(ValidationError, match="exactly one"):
        ApplicationAnswerRevision(source_version=4, resulting_version=6).clean()


def test_proposal_revision_pointers_are_private_current_projection_fields() -> None:
    sealed = ProgrammeProposal._meta.get_field("sealed_revision")
    submitted = ProgrammeProposal._meta.get_field("submitted_revision")
    assert sealed.null
    assert submitted.null
    assert not sealed.editable
    assert not submitted.editable
    assert sealed.remote_field.on_delete is django_models.PROTECT
    assert submitted.remote_field.on_delete is django_models.PROTECT

    constraint = next(
        item
        for item in ProgrammeProposal._meta.constraints
        if item.name == "applications_prg_proposal_pointer_shape"
    )
    assert "sealed_revision" in str(constraint.condition)
    assert "submitted_revision" in str(constraint.condition)


def test_requested_duration_must_fit_the_selected_format() -> None:
    call_format = ProgrammeCallFormat(
        min_duration_minutes=30,
        default_duration_minutes=60,
        max_duration_minutes=90,
    )
    selection = ProgrammeProposalSelectionRevision(
        format=call_format,
        requested_duration_minutes=60,
    )
    selection.clean()
    selection.requested_duration_minutes = 120
    with pytest.raises(ValidationError, match="format bounds"):
        selection.clean()


def test_profile_public_values_require_explicit_publication_intent() -> None:
    profile = ProgrammeProposalContributorProfileRevision(
        proposed_for_publication=False,
        public_name="Hidden name",
    )
    with pytest.raises(ValidationError, match="publication intent"):
        profile.clean()

    profile.public_name = ""
    profile.clean()


def test_initial_selection_and_profile_evidence_allow_zero_to_one() -> None:
    for model_type, constraint_name in (
        (
            ProgrammeProposalSelectionRevision,
            "applications_prg_selection_version_step",
        ),
        (
            ProgrammeProposalContributorProfileRevision,
            "applications_prg_profile_version_step",
        ),
    ):
        constraint = next(
            item
            for item in model_type._meta.constraints
            if item.name == constraint_name
        )
        assert "source_version__gte" in str(constraint.condition)


def test_writer_boundary_allows_current_replacement_but_retains_evidence() -> None:
    current = ProgrammeCall()
    with pytest.raises(ValidationError) as outside_save:
        current.save()
    assert outside_save.value.code == "programme_application_writer_required"
    with pytest.raises(ValidationError) as outside_delete:
        current.delete()
    assert outside_delete.value.code == "programme_application_writer_required"

    with (
        programme_application_writer(),
        patch.object(current, "full_clean") as full_clean,
        patch.object(django_models.Model, "save") as model_save,
        patch.object(
            django_models.Model,
            "delete",
            return_value=(1, {}),
        ) as model_delete,
    ):
        current.save()
        assert current.delete() == (1, {})
    full_clean.assert_called_once_with()
    model_save.assert_called_once()
    model_delete.assert_called_once()

    for model_type in APPEND_ONLY_MODELS:
        evidence = model_type()
        evidence._state.adding = False
        with pytest.raises(ValidationError) as immutable:
            evidence.save()
        assert immutable.value.code == "immutable_programme_application_evidence"
        with pytest.raises(ValidationError) as retained:
            evidence.delete()
        assert retained.value.code == "protected_programme_application_evidence"


def test_command_receipts_support_call_and_proposal_creation_zero_to_one() -> None:
    receipt_fields = {field.name for field in ProgrammeCommandReceipt._meta.fields}
    assert "expected_version" in receipt_fields
    assert "source_version" not in receipt_fields

    definition_id = uuid4()
    call_receipt = ProgrammeCommandReceipt(
        aggregate_kind=ProgrammeCommandAggregateKind.CALL,
        definition_id=definition_id,
        expected_version=0,
        resulting_version=1,
    )
    call_receipt.clean()

    proposal_receipt = ProgrammeCommandReceipt(
        aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
        definition_id=definition_id,
        submission_id=uuid4(),
        expected_version=0,
        resulting_version=1,
    )
    proposal_receipt.clean()

    proposal_receipt.resulting_version = 2
    with pytest.raises(ValidationError, match="exactly one"):
        proposal_receipt.clean()
    call_receipt.submission_id = uuid4()
    with pytest.raises(ValidationError, match="references"):
        call_receipt.clean()


def test_programme_answer_receipts_have_a_typed_result_kind() -> None:
    assert ProgrammeCommandResultKind.ANSWER_REVISION == "answer_revision"
    assert "answer_revision" in ProgrammeCommandResultKind.values


def test_closed_catalogs_have_database_constraints_and_names_are_bounded() -> None:
    constraint_names = {
        constraint.name
        for model_type in PROGRAMME_MODELS
        for constraint in model_type._meta.constraints
    }
    assert {
        "applications_prg_contributor_field_closed",
        "applications_prg_proposal_state_closed",
        "applications_prg_collaborator_state_closed",
        "applications_prg_collab_transition_states_closed",
        "applications_prg_revision_answer_catalogs_closed",
        "applications_prg_revision_contributor_role_closed",
        "applications_prg_response_closed",
        "applications_prg_command_catalogs_closed",
    } <= constraint_names
    assert all(len(name) <= 63 for name in constraint_names)
    assert all(
        len(index.name) <= 30
        for model_type in PROGRAMME_MODELS
        for index in model_type._meta.indexes
    )


def test_0004_adds_revision_pointers_late_and_runs_reverse_preflight_first() -> None:
    migration_module = importlib.import_module(
        "maru.applications.migrations.0004_programme_calls_and_proposals"
    )
    operations = migration_module.Migration.operations
    revision_create = next(
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.CreateModel)
        and operation.name == "ProgrammeProposalRevision"
    )
    pointer_adds = [
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.AddField)
        and operation.model_name == "programmeproposal"
        and operation.name in {"sealed_revision", "submitted_revision"}
    ]
    assert len(pointer_adds) == 2
    assert all(index > revision_create for index in pointer_adds)

    reverse_preflight = operations[-1]
    assert isinstance(reverse_preflight, migrations.RunSQL)
    assert "ACCESS EXCLUSIVE" in reverse_preflight.reverse_sql
    assert "source_version IS NOT NULL" in reverse_preflight.reverse_sql
