"""DB-free acceptance for the dormant Applications Programme boundary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import override_settings

from maru.applications import programme_authorization, programme_commands
from maru.applications.models import (
    ApplicationCommandReceipt,
    ApplicationTargetKind,
    ApplicationTargetRecord,
    ProgrammeCommandReceipt,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
    ApplicationsProgrammeAuthorizer,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
)
from maru.applications.programme_events import (
    APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
)
from maru.effects.handlers import (
    ACKNOWLEDGED_DORMANT_EVENTS,
    built_in_handler_registry,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src" / "maru"
_APPLICATIONS_ROOT = _SOURCE_ROOT / "applications"
_PYTHON_SURFACE_NAMES = frozenset(
    {
        "admin.py",
        "admin_context.py",
        "api.py",
        "apps.py",
        "forms.py",
        "navigation.py",
        "openapi.py",
        "scheduler.py",
        "schedules.py",
        "schema.py",
        "serializers.py",
        "supervisor.py",
        "tasks.py",
        "urls.py",
        "views.py",
        "worker.py",
    }
)
_FORBIDDEN_SURFACE_MARKERS = (
    "applications.edit_programme_",
    "applications.manage_programme_",
    "applications.programme_",
    "applications.respond_programme_",
    "applications.self.programme_",
    "applications.submit_programme_",
    "applications.target.programme_",
    "applications.view_programme_",
    "applicationsprogramme",
    "maru.applications.programme",
    "programme-call",
    "programme-proposal",
    "programme_adoption",
    "programme_authorization",
    "programme_call",
    "programme_commands",
    "programme_events",
    "programme_inputs",
    "programme_item",
    "programme_proposal",
    "programme_queries",
    "programme_writer_boundary",
    "programmecall",
    "programmecommandreceipt",
    "programmeproposal",
)


def _execution_surface_paths() -> tuple[Path, ...]:
    """Return every checked route, UI, adapter, worker, and schedule surface."""
    paths = {
        path
        for path in _SOURCE_ROOT.rglob("*.py")
        if path.name in _PYTHON_SURFACE_NAMES
        or "management/commands" in path.as_posix()
        or "settings" in path.relative_to(_SOURCE_ROOT).parts
    }
    paths.add(_APPLICATIONS_ROOT / "__init__.py")
    paths.update(_SOURCE_ROOT.rglob("*.html"))
    paths.add(_REPOSITORY_ROOT / "openapi.yaml")
    paths.add(_REPOSITORY_ROOT / "pyproject.toml")
    for pattern in (
        ".github/workflows/*.yaml",
        ".github/workflows/*.yml",
        "compose*.yaml",
        "compose*.yml",
        "docker-compose*.yaml",
        "docker-compose*.yml",
    ):
        paths.update(_REPOSITORY_ROOT.glob(pattern))
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def _locked_manager(*, first: object | None = None, exists: bool = False) -> MagicMock:
    """Return a queryset manager double for one locked replay lookup."""
    manager = MagicMock()
    filtered = manager.select_for_update.return_value.filter.return_value
    filtered.first.return_value = first
    filtered.exists.return_value = exists
    return manager


def test_programme_kernel_has_no_mounted_or_scheduled_surface() -> None:
    """Keep the dormant kernel out of routes, schemas, UI, workers, and jobs."""
    violations: dict[str, tuple[str, ...]] = {}
    surface_paths = _execution_surface_paths()
    for path in surface_paths:
        content = path.read_text(encoding="utf-8").lower()
        matched = tuple(
            marker for marker in _FORBIDDEN_SURFACE_MARKERS if marker in content
        )
        if matched:
            violations[path.relative_to(_REPOSITORY_ROOT).as_posix()] = matched

    assert violations == {}
    assert tuple(
        path.relative_to(_REPOSITORY_ROOT).as_posix()
        for path in surface_paths
        if "programme_checks" in path.read_text(encoding="utf-8")
    ) == (
        "src/maru/applications/apps.py",
        "src/maru/programme/apps.py",
    )


def test_programme_models_have_no_django_admin_registration() -> None:
    """Keep every Applications-owned Programme relation out of Django admin."""
    admin.autodiscover()
    programme_models = tuple(
        model
        for model in apps.get_app_config("applications").get_models()
        if model.__name__.startswith("Programme")
    )

    assert programme_models
    assert not tuple(
        model for model in programme_models if admin.site.is_registered(model)
    )


def test_programme_events_have_no_built_in_handler() -> None:
    """Keep registered Programme facts dormant at every built-in destination."""
    event_names = frozenset(
        {
            APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
            APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
        }
    )
    handlers = built_in_handler_registry()

    assert event_names <= ACKNOWLEDGED_DORMANT_EVENTS
    assert all(
        handlers.resolve(event_name=event_name, destination=destination) is None
        for event_name in event_names
        for destination in ("internal", "notifications")
    )


@pytest.mark.parametrize(
    ("allow_test_authorizer", "database_name"),
    [(False, "test_maru"), (True, "maru")],
    ids=("flag-disabled", "non-test-database"),
)
def test_injected_authorizer_is_rejected_before_scope_reads(
    allow_test_authorizer: bool,
    database_name: str,
) -> None:
    """Require both test gates before any injected authorizer or scope read."""
    authorizer = MagicMock(spec=ApplicationsProgrammeAuthorizer)
    with (
        override_settings(
            MARU_ALLOW_APPLICATIONS_PROGRAMME_TEST_AUTHORIZER=(allow_test_authorizer)
        ),
        patch.dict(
            connection.settings_dict,
            {"NAME": database_name},
        ),
        patch.object(
            programme_authorization,
            "resolve_active_verified_person_reference",
        ) as resolve_actor,
        pytest.raises(ApplicationsProgrammeAuthorizationDeniedError),
    ):
        programme_authorization.authorize_programme_call_scope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            department_id=uuid4(),
            authorizer=authorizer,
        )

    resolve_actor.assert_not_called()
    assert authorizer.mock_calls == []


def test_programme_replay_rejects_a_generic_receipt_collision() -> None:
    """Enforce the generic-to-Programme half of the shared retry namespace."""
    actor_id = uuid4()
    organization_id = uuid4()
    edition_id = uuid4()
    retry_key = uuid4()
    authorizer = MagicMock(spec=ApplicationsProgrammeAuthorizer)
    programme_receipts = _locked_manager()
    generic_receipts = _locked_manager(exists=True)

    with (
        patch.object(
            programme_commands,
            "authorize_programme_retry_scope",
        ) as authorize_retry,
        patch.object(
            programme_commands,
            "lock_applications_retry_namespace",
        ) as retry_lock,
        patch.object(
            ProgrammeCommandReceipt,
            "objects",
            programme_receipts,
        ),
        patch.object(
            ApplicationCommandReceipt,
            "objects",
            generic_receipts,
        ),
        pytest.raises(ApplicationsProgrammeIdempotencyConflictError),
    ):
        programme_commands._replay(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            retry_key=retry_key,
            request_digest="a" * 64,
            authorizer=authorizer,
        )

    authorize_retry.assert_called_once_with(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    retry_lock.assert_called_once_with(
        edition_id=edition_id,
        actor_id=actor_id,
        retry_key=retry_key,
    )
    programme_receipts.select_for_update.return_value.filter.assert_called_once_with(
        edition_id=edition_id,
        actor_id=actor_id,
        retry_key=retry_key,
    )
    generic_receipts.select_for_update.return_value.filter.assert_called_once_with(
        edition_id=edition_id,
        actor_id=actor_id,
        retry_key=retry_key,
    )


def test_programme_target_record_fails_before_loading_its_submission() -> None:
    """Reject the reserved target kind at the ORM boundary without a relation read."""
    target = ApplicationTargetRecord(
        submission_id=uuid4(),
        adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
        created_by_id=uuid4(),
    )

    with pytest.raises(ValidationError) as caught:
        target.clean()

    assert caught.value.code == "application_target_adapter_unavailable"
