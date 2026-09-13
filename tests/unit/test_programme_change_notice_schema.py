"""Dormant notice declarations retain exact owner, lifecycle and event contracts."""

from importlib import import_module
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db.migrations.loader import MigrationLoader

from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
)
from maru.effects.handlers import ACKNOWLEDGED_DORMANT_EVENTS
from maru.effects.registry import event_definition
from maru.events.adoption import ADOPTION_PROFILES
from maru.scheduling.authorization import (
    ACKNOWLEDGE_CHANGE_SELF,
    CHANGE_COMMUNICATION_CAPABILITIES,
    HANDOFF_CHANGE_NOTICES,
    PREPARE_CHANGE_NOTICES,
    REVIEW_CHANGE_NOTICES,
    VIEW_CHANGE_NOTICES,
    VIEW_CHANGE_SELF,
)
from maru.scheduling.catalogs import (
    CHANGE_OPERATION_VALUES,
    PLANNING_OPERATION_VALUES,
    RELEASE_OPERATION_VALUES,
    SchedulingOperation,
)
from maru.scheduling.events import (
    SCHEDULING_NOTICE_CHANGED_EVENT,
    validate_scheduling_changed_payload,
    validate_scheduling_notice_changed_payload,
    validate_scheduling_release_changed_payload,
)
from maru.scheduling.models import (
    SchedulingChangeNotice,
    SchedulingChangeNoticeEvidence,
    _ImmutableSchedulingModel,
)


@pytest.mark.parametrize("operation", CHANGE_OPERATION_VALUES)
def test_notice_events_are_minimized_and_cannot_enter_planning_or_release_streams(
    operation,
):
    event = event_definition(SCHEDULING_NOTICE_CHANGED_EVENT)
    assert event is not None
    assert event.schema_version == 1
    validate_scheduling_notice_changed_payload({"operation": operation})
    for validator in (
        validate_scheduling_changed_payload,
        validate_scheduling_release_changed_payload,
    ):
        with pytest.raises(ValidationError):
            validator({"operation": operation})
    for invalid in (
        {"operation": operation, "recipient_id": "private-marker"},
        {"operation": operation, "message": "private-marker"},
        {"operation": SchedulingOperation(operation)},
    ):
        with pytest.raises(ValidationError) as caught:
            validate_scheduling_notice_changed_payload(invalid)
        assert "private-marker" not in str(caught.value)


@pytest.mark.parametrize(
    "operation",
    [*PLANNING_OPERATION_VALUES, *RELEASE_OPERATION_VALUES, "export", "delivered"],
)
def test_other_operations_cannot_claim_a_notice_fact(operation):
    with pytest.raises(ValidationError):
        validate_scheduling_notice_changed_payload({"operation": operation})


def test_operation_families_partition_the_current_closed_catalog_without_overlap():
    families = [
        set(values)
        for values in (
            CHANGE_OPERATION_VALUES,
            PLANNING_OPERATION_VALUES,
            RELEASE_OPERATION_VALUES,
        )
    ]
    assert set.union(*families) == {
        operation.value for operation in SchedulingOperation
    }
    assert sum(map(len, families)) == len(SchedulingOperation)
    assert SCHEDULING_NOTICE_CHANGED_EVENT in ACKNOWLEDGED_DORMANT_EVENTS
    for profile in ADOPTION_PROFILES.values():
        assert not profile.capability_codes & CHANGE_COMMUNICATION_CAPABILITIES
        assert all(
            route.event_name != SCHEDULING_NOTICE_CHANGED_EVENT
            for route in profile.effect_routes
        )


@pytest.mark.parametrize(
    "capability",
    [
        VIEW_CHANGE_NOTICES,
        PREPARE_CHANGE_NOTICES,
        REVIEW_CHANGE_NOTICES,
        HANDOFF_CHANGE_NOTICES,
    ],
)
def test_organizer_read_and_each_mutation_have_separate_unpinned_authority(capability):
    definition = CAPABILITIES[capability]
    assert definition.maximum_scope is ScopeLevel.EDITION
    assert definition.persistable
    assert definition.delegable
    assert not definition.allow_self
    if capability == VIEW_CHANGE_NOTICES:
        assert definition.field_ceiling == frozenset({"change_notices"})
        assert definition.obligations == frozenset({"audit_sensitive_read"})
    else:
        assert definition.obligations == frozenset({"reason", "audit"})
        assert not definition.field_ceiling


@pytest.mark.parametrize("capability", [VIEW_CHANGE_SELF, ACKNOWLEDGE_CHANGE_SELF])
def test_self_authority_cannot_be_persisted_or_delegated_to_an_operator(capability):
    definition = CAPABILITIES[capability]
    assert definition.maximum_scope is ScopeLevel.RESOURCE
    assert definition.allow_self
    assert not definition.persistable
    assert not definition.delegable
    if capability == ACKNOWLEDGE_CHANGE_SELF:
        assert definition.obligations == frozenset({"audit"})
        assert "reason" not in definition.obligations


@pytest.mark.parametrize(
    "model", [SchedulingChangeNotice, SchedulingChangeNoticeEvidence]
)
def test_notice_models_are_immutable_scoped_and_runtime_select_only(model):
    assert issubclass(model, _ImmutableSchedulingModel)
    assert "public." + model._meta.db_table in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
    for field in ("organization", "edition", "actor", "command_receipt"):
        assert model._meta.get_field(field).remote_field.on_delete is models.PROTECT
    assert not {"body", "message", "contact", "email", "delivered", "attended"} & {
        field.name for field in model._meta.fields
    }
    row = model()
    with pytest.raises(ValidationError, match="registered command"):
        row.save()
    row._state.adding = False
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="history is retained"):
        row.delete()


def test_native_graph_is_additive_and_downgrade_restores_exact_prior_dispatch():
    current = import_module("maru.scheduling.migrations.0022_change_notice_integrity")
    previous = import_module("maru.scheduling.migrations.0017_atomic_release_graph")
    assert previous._graph in current.REVERSE_SQL
    assert "change_prepare" not in previous._graph
    for operation in (*CHANGE_OPERATION_VALUES, *RELEASE_OPERATION_VALUES):
        assert operation in current._graph
    for fragment in (
        "public.audit_auditnativemutationwitness witness",
        "public.maru_audit_current_native_transaction_stamp()",
        "receipt.result_object_id = NEW.id",
        "receipt.resulting_version = expected_version",
        "receipt.actor_id = NEW.actor_id AND receipt.reason = NEW.reason",
        "review.actor_id = notice.actor_id",
        "NEW.actor_id <> notice.recipient_id",
        "last_sequence <> 1 + evidence_count",
        "review.action = 'reject' AND evidence_count <> 1",
        "pointer.version <> notice.pointer_version",
        "public.maru_scheduling_release_artifact_is_exact(publication.id)",
        "chosen.occurrence_id = notice.occurrence_id",
    ):
        assert fragment in current.FORWARD_SQL
    for identity in current.FUNCTIONS:
        assert (
            f"REVOKE ALL ON FUNCTION public.{identity} FROM PUBLIC;"
            in current.FORWARD_SQL
        )
    assert "GRANT " not in current.FORWARD_SQL


@pytest.mark.parametrize("used", ["none", "notice", "evidence", "receipt"])
def test_used_notice_schema_is_fenced_before_any_guard_or_table_removal(used):
    schema = import_module("maru.scheduling.migrations.0021_change_notice_schema")
    guards = import_module("maru.scheduling.migrations.0022_change_notice_integrity")
    apps, editor = Mock(), Mock()
    notice, evidence, receipt = Mock(), Mock(), Mock()
    models_by_name = {
        "SchedulingChangeNotice": notice,
        "SchedulingChangeNoticeEvidence": evidence,
        "SchedulingCommandReceipt": receipt,
    }
    apps.get_model.side_effect = lambda _app, name: models_by_name[name]
    notice.objects.exists.return_value = used == "notice"
    evidence.objects.exists.return_value = used == "evidence"
    receipt.objects.filter.return_value.exists.return_value = used == "receipt"
    if used == "none":
        schema.refuse_used_notice_schema_downgrade(apps, editor)
    else:
        with pytest.raises(RuntimeError, match="fix forward"):
            schema.refuse_used_notice_schema_downgrade(apps, editor)
    assert "ACCESS EXCLUSIVE" in editor.execute.call_args.args[0]
    assert (
        guards.Migration.operations[-1].reverse_code
        is guards.refuse_used_notice_boundary_downgrade
    )
    assert (
        schema.Migration.operations[-1].reverse_code
        is schema.refuse_used_notice_schema_downgrade
    )


def test_django_history_contains_the_exact_notice_fields_and_named_constraints():
    state = MigrationLoader(None).project_state()
    for model in (SchedulingChangeNotice, SchedulingChangeNoticeEvidence):
        historical = state.apps.get_model("scheduling", model.__name__)
        assert {field.name for field in historical._meta.fields} == {
            field.name for field in model._meta.fields
        }
        assert {constraint.name for constraint in historical._meta.constraints} == {
            constraint.name for constraint in model._meta.constraints
        }


def test_prior_used_release_fence_runs_before_a_notice_successor_can_reverse(
    monkeypatch,
):
    guards = import_module("maru.scheduling.migrations.0022_change_notice_integrity")
    calls = []
    notice_guard = Mock(side_effect=lambda *_args: calls.append("notice"))

    def retained_release(*_args):
        calls.append("release")
        raise RuntimeError("Existing release evidence; retain its execution boundary")

    monkeypatch.setattr(
        guards._schema, "refuse_used_notice_schema_downgrade", notice_guard
    )
    monkeypatch.setattr(
        guards._authority_fence,
        "refuse_used_change_capability_downgrade",
        lambda *_args: calls.append("authority"),
    )
    monkeypatch.setattr(
        guards._release_fence,
        "refuse_used_release_boundary_downgrade",
        retained_release,
    )
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        guards.Migration.operations[-1].reverse_code(Mock(), Mock())
    assert calls == ["notice", "authority", "release"]
