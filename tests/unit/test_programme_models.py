from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import models as django_models

from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.programme.catalogs import (
    PROGRAMME_ACCEPTED_APPLICATION_SOURCE,
    PROGRAMME_ORGANIZER_CORE_SOURCE,
    ProgrammeCommandOperation,
    ProgrammeItemKind,
    ProgrammeItemLifecycle,
    ProgrammeProvenanceKind,
)
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeDeliveryRevision,
    ProgrammeDepartmentDiscussionEntry,
    ProgrammeEditionControl,
    ProgrammeItem,
    ProgrammeItemSourceBinding,
    ProgrammePublicRendition,
    ProgrammeReadinessEvidence,
    ProgrammeReadinessRequirement,
    ProgrammeReadinessRequirementRevision,
    ProgrammeWorkingRevision,
)
from maru.programme.writer_boundary import programme_writer


def _scope() -> tuple[Organization, EventEdition]:
    organization = Organization(id=uuid4(), name="Synthetic Organizer")
    edition = EventEdition(id=uuid4(), organization=organization)
    return organization, edition


def _item(**overrides: object) -> ProgrammeItem:
    organization, edition = _scope()
    values: dict[str, object] = {
        "id": uuid4(),
        "organization": organization,
        "edition": edition,
        "kind": ProgrammeItemKind.CEREMONY,
        "provenance_kind": ProgrammeProvenanceKind.ORGANIZER_CORE,
        "created_by_id": uuid4(),
        "last_modified_by_id": uuid4(),
    }
    values.update(overrides)
    return ProgrammeItem(**values)


def test_models_keep_scope_on_every_tenant_owned_row() -> None:
    model_types = (
        ProgrammeEditionControl,
        ProgrammeItem,
        ProgrammeItemSourceBinding,
        ProgrammeWorkingRevision,
        ProgrammeDeliveryRevision,
        ProgrammeDepartmentDiscussionEntry,
        ProgrammeReadinessRequirement,
        ProgrammeReadinessRequirementRevision,
        ProgrammeReadinessEvidence,
        ProgrammePublicRendition,
        ProgrammeCommandReceipt,
    )
    for model_type in model_types:
        field_names = {field.name for field in model_type._meta.fields}
        assert {"organization", "edition"} <= field_names


def test_models_have_no_json_url_or_open_external_identity_fields() -> None:
    model_types = (
        ProgrammeEditionControl,
        ProgrammeItem,
        ProgrammeItemSourceBinding,
        ProgrammeWorkingRevision,
        ProgrammeDeliveryRevision,
        ProgrammeDepartmentDiscussionEntry,
        ProgrammeReadinessRequirement,
        ProgrammeReadinessRequirementRevision,
        ProgrammeReadinessEvidence,
        ProgrammePublicRendition,
        ProgrammeCommandReceipt,
    )
    fields = [field for model_type in model_types for field in model_type._meta.fields]
    assert not any(isinstance(field, django_models.JSONField) for field in fields)
    assert not any(isinstance(field, django_models.URLField) for field in fields)
    identity_names = {field.name for field in fields if field.name.endswith("_id")}
    assert identity_names <= {
        "correlation_id",
        "source_object_id",
        "result_object_id",
    }


def test_item_starts_active_and_has_no_content_layer_fields() -> None:
    item = _item()
    assert item.lifecycle == ProgrammeItemLifecycle.ACTIVE
    field_names = {field.name for field in ProgrammeItem._meta.fields}
    assert (
        not {
            "internal_title",
            "working_summary",
            "technical_requirements",
            "public_title",
            "public_summary",
        }
        & field_names
    )


def test_item_and_control_full_clean_does_not_validate_external_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep owner-model existence and scope checks behind public seams."""
    external_validations: list[str] = []

    def record_external_validation(
        field: django_models.ForeignKey,
        value: object,
        model_instance: django_models.Model,
    ) -> None:
        del value, model_instance
        related_model = field.remote_field.model
        if related_model._meta.app_label != "programme":
            external_validations.append(field.name)

    monkeypatch.setattr(
        django_models.ForeignKey,
        "validate",
        record_external_validation,
    )
    organization_id = uuid4()
    edition_id = uuid4()
    control = ProgrammeEditionControl(
        organization_id=organization_id,
        edition_id=edition_id,
        aggregate_version=1,
    )
    item = ProgrammeItem(
        organization_id=organization_id,
        edition_id=edition_id,
        kind=ProgrammeItemKind.CEREMONY,
        provenance_kind=ProgrammeProvenanceKind.ORGANIZER_CORE,
        created_by_id=uuid4(),
        last_modified_by_id=uuid4(),
    )

    control.full_clean(validate_unique=False, validate_constraints=False)
    item.full_clean(validate_unique=False, validate_constraints=False)

    assert external_validations == []


def test_source_binding_is_mandatory_shape_for_both_provenances() -> None:
    item = _item()
    organizer = ProgrammeItemSourceBinding(
        item=item,
        organization=item.organization,
        edition=item.edition,
        binding_code=PROGRAMME_ORGANIZER_CORE_SOURCE,
    )
    organizer.clean()
    organizer.source_object_id = uuid4()
    with pytest.raises(ValidationError):
        organizer.clean()

    accepted_item = _item(
        provenance_kind=ProgrammeProvenanceKind.APPLICATIONS_ACCEPTED,
    )
    accepted = ProgrammeItemSourceBinding(
        item=accepted_item,
        organization=accepted_item.organization,
        edition=accepted_item.edition,
        binding_code=PROGRAMME_ACCEPTED_APPLICATION_SOURCE,
        source_object_id=uuid4(),
        source_version=1,
    )
    accepted.clean()
    accepted.source_version = None
    with pytest.raises(ValidationError):
        accepted.clean()


def test_writer_boundary_and_append_only_history_are_closed() -> None:
    item = _item()
    with pytest.raises(ValidationError) as outside:
        item.save()
    assert outside.value.code == "programme_writer_required"

    with (
        programme_writer(),
        patch.object(item, "full_clean") as full_clean,
        patch.object(django_models.Model, "save") as save,
    ):
        item.save()
    full_clean.assert_called_once_with()
    save.assert_called_once()

    revision = ProgrammeWorkingRevision()
    revision._state.adding = False
    with pytest.raises(ValidationError) as immutable:
        revision.save()
    assert immutable.value.code == "immutable_programme_history"
    with pytest.raises(ValidationError) as retained:
        revision.delete()
    assert retained.value.code == "protected_programme_record"


def test_public_rendition_has_only_reviewed_public_content() -> None:
    fields = {field.name for field in ProgrammePublicRendition._meta.fields}
    assert {
        "public_title",
        "public_summary",
        "public_content_note",
        "reviewed_by",
        "reviewed_at",
        "review_reason",
        "source_working_revision",
        "supersedes",
    } <= fields
    assert (
        not {
            "technical_requirements",
            "accessibility_delivery",
            "media_consent_notes",
            "body",
            "evidence_note",
        }
        & fields
    )
    assert ProgrammePublicRendition._meta.get_field("supersedes").one_to_one


def test_command_receipt_distinguishes_control_and_item_versions() -> None:
    actor_id = uuid4()
    item = _item(created_by_id=actor_id, last_modified_by_id=actor_id)
    control = ProgrammeEditionControl(
        id=uuid4(),
        organization=item.organization,
        edition=item.edition,
        aggregate_version=1,
    )
    common = {
        "control": control,
        "item": item,
        "organization": item.organization,
        "edition": item.edition,
        "actor_id": actor_id,
        "reason": "Create core item",
        "idempotency_key": uuid4(),
        "request_digest": "a" * 64,
        "correlation_id": uuid4(),
        "source_channel": "staff_console",
        "result_object_id": item.id,
    }
    created = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.ITEM_CREATE,
        expected_version=0,
        resulting_control_version=1,
        resulting_item_version=1,
        **common,
    )
    created.clean()
    created.resulting_item_version = 2
    with pytest.raises(ValidationError) as invalid_create:
        created.clean()
    assert invalid_create.value.code == "programme_receipt_create_version_invalid"

    revised = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.WORKING_REVISE,
        expected_version=1,
        resulting_control_version=None,
        resulting_item_version=2,
        **common,
    )
    revised.clean()
    revised.resulting_control_version = 2
    with pytest.raises(ValidationError) as invalid_revision:
        revised.clean()
    assert invalid_revision.value.code == "programme_receipt_item_version_invalid"

    public = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD,
        expected_version=1,
        resulting_control_version=None,
        resulting_item_version=1,
        **(common | {"actor_id": uuid4()}),
    )
    public.clean()
    public.resulting_item_version = 2
    with pytest.raises(ValidationError) as invalid_public:
        public.clean()
    assert invalid_public.value.code == "programme_receipt_public_version_invalid"


def test_command_receipt_binds_item_mutations_to_the_item_actor() -> None:
    """Reject split attribution while leaving public-only approval independent."""
    item_actor_id = uuid4()
    receipt_actor_id = uuid4()
    item = _item(
        created_by_id=item_actor_id,
        last_modified_by_id=item_actor_id,
    )
    control = ProgrammeEditionControl(
        id=uuid4(),
        organization=item.organization,
        edition=item.edition,
        aggregate_version=1,
    )
    common = {
        "control": control,
        "item": item,
        "organization": item.organization,
        "edition": item.edition,
        "actor_id": receipt_actor_id,
        "reason": "Keep actor attribution exact",
        "idempotency_key": uuid4(),
        "request_digest": "a" * 64,
        "correlation_id": uuid4(),
        "source_channel": "staff_console",
        "result_object_id": item.id,
    }

    created = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.ITEM_CREATE,
        expected_version=0,
        resulting_control_version=1,
        resulting_item_version=1,
        **common,
    )
    with pytest.raises(ValidationError) as invalid_create:
        created.clean()
    assert invalid_create.value.code == "programme_receipt_create_actor_mismatch"

    revised = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.WORKING_REVISE,
        expected_version=1,
        resulting_control_version=None,
        resulting_item_version=2,
        **common,
    )
    with pytest.raises(ValidationError) as invalid_revision:
        revised.clean()
    assert invalid_revision.value.code == "programme_receipt_item_actor_mismatch"

    public = ProgrammeCommandReceipt(
        operation=ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD,
        expected_version=1,
        resulting_control_version=None,
        resulting_item_version=1,
        **common,
    )
    public.clean()


def test_layer_fields_are_bounded_and_revision_constraints_are_named() -> None:
    assert ProgrammeWorkingRevision._meta.get_field("internal_title").max_length == 240
    assert (
        ProgrammeDeliveryRevision._meta.get_field("technical_requirements").max_length
        == 5000
    )
    assert (
        ProgrammeReadinessEvidence._meta.get_field("evidence_note").max_length == 2000
    )
    assert ProgrammeCommandReceipt._meta.get_field("expected_version").null is False
    constraint_names = {
        constraint.name
        for model_type in (
            ProgrammeWorkingRevision,
            ProgrammeDeliveryRevision,
            ProgrammeDepartmentDiscussionEntry,
            ProgrammeReadinessRequirement,
            ProgrammeReadinessEvidence,
            ProgrammePublicRendition,
            ProgrammeCommandReceipt,
        )
        for constraint in model_type._meta.constraints
    }
    assert {
        "programme_working_sequence_uq",
        "programme_delivery_sequence_uq",
        "programme_discussion_sequence_uq",
        "programme_readiness_concern_uq",
        "programme_readiness_evidence_sequence_uq",
        "programme_public_rendition_number_uq",
        "programme_command_retry_uq",
    } <= constraint_names


def test_public_chain_requires_immediate_same_item_predecessor() -> None:
    item = _item()
    source = ProgrammeWorkingRevision(
        id=uuid4(),
        item=item,
        organization=item.organization,
        edition=item.edition,
        sequence=1,
        item_version=2,
        internal_title="Opening",
        actor_id=uuid4(),
        reason="Review copy",
        occurred_at=datetime(2031, 1, 1, tzinfo=UTC),
    )
    first = ProgrammePublicRendition(
        id=uuid4(),
        item=item,
        organization=item.organization,
        edition=item.edition,
        rendition_number=1,
        source_item_version=2,
        source_working_revision=source,
        public_title="Opening",
        reviewed_by_id=uuid4(),
        reviewed_at=datetime(2031, 1, 2, tzinfo=UTC),
        review_reason="Approved copy",
    )
    first.clean()
    second = ProgrammePublicRendition(
        item=item,
        organization=item.organization,
        edition=item.edition,
        rendition_number=2,
        source_item_version=2,
        source_working_revision=source,
        supersedes=first,
        public_title="Opening ceremony",
        reviewed_by_id=uuid4(),
        reviewed_at=datetime(2031, 1, 3, tzinfo=UTC),
        review_reason="Updated approved copy",
    )
    second.clean()
    second.rendition_number = 3
    with pytest.raises(ValidationError) as broken:
        second.clean()
    assert broken.value.code == "programme_public_chain_invalid"
