"""Database-free joined startup preparation, never native fixture acceptance."""

import ast
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import MagicMock, Mock

import django
import pytest
from django.core import wsgi
from django.core.checks import Error
from django.core.checks import Warning as CheckWarning
from django.db import connection

from maru.authorization import programme_role_readiness
from maru.core import views
from maru.events import adoption, programme_setup_readiness
from maru.events.checks import current_adoption_catalog_snapshot
from maru.workforce import programme_starter_readiness
from tests.rehearsals import programme_compatibility as compatibility
from tests.rehearsals import programme_effects as effects
from tests.rehearsals import programme_function_acl as helper_acl
from tests.rehearsals import programme_runtime as runtime
from tests.rehearsals import programme_runtime_privileges as privileges
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE as PROFILE
from tests.rehearsals.programme_registration import IsolatedAdoptionProfileCode
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


def _strict_settings():
    return SimpleNamespace(
        SETTINGS_MODULE="tests.rehearsals.programme_runtime_settings",
        DEBUG=False,
        ALLOWED_HOSTS=["127.0.0.1"],
        ROOT_URLCONF="tests.rehearsals.programme_urls",
        MIGRATION_MODULES={"events": "tests.rehearsals.programme_event_migrations"},
        REQUIRE_EXACT_AUTHORITY_PROVENANCE=True,
        REQUIRE_PRIVILEGED_STEP_UP=True,
        ENFORCE_EDITION_CLOSURE_GATES=True,
        IDENTITY_INVITATION_ENCRYPTION_REQUIRED=True,
        IDENTITY_EXPOSE_TEST_TOKENS=False,
        MARU_EXPOSE_TEST_CREDENTIAL_TOKENS=False,
        DEMO_PAYMENT_ADAPTER_ENABLED=False,
        SILENCED_SYSTEM_CHECKS=[],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_SSL_REDIRECT=True,
    )


@pytest.fixture
def candidate_registry(monkeypatch):
    profiles = {**adoption.ADOPTION_PROFILES, PROFILE.key: PROFILE}
    choices = tuple((key[0], value.label) for key, value in profiles.items())
    double = SimpleNamespace(
        ADOPTION_PROFILES=MappingProxyType(profiles),
        AdoptionProfileCode=IsolatedAdoptionProfileCode,
        SELECTABLE_ADOPTION_PROFILE_KEYS=MappingProxyType(
            {IsolatedAdoptionProfileCode(key[0]): key for key in profiles}
        ),
        PERSISTED_ADOPTION_PROFILE_CHOICES=choices,
        SELECTABLE_ADOPTION_PROFILE_CHOICES=choices,
    )
    monkeypatch.setattr(compatibility, "adoption", double)
    monkeypatch.setattr(
        compatibility,
        "adoption_persistence",
        SimpleNamespace(
            PERSISTED_ADOPTION_PROFILE_KEYS=tuple(profiles),
        ),
    )
    catalog = replace(
        current_adoption_catalog_snapshot(), persisted_profile_keys=frozenset(profiles)
    )
    monkeypatch.setattr(
        compatibility, "current_adoption_catalog_snapshot", lambda: catalog
    )
    return double


def test_independent_candidate_catalog_and_original_profile_dormancy(
    candidate_registry,
):
    compatibility.validate_installed_candidate()
    assert adoption.adoption_profile("programme_operations", 1) is None


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "replaced", "selector", "choices", "persisted"]
)
def test_baseline_or_candidate_registry_drift_fails(mutation, candidate_registry):
    profiles = dict(candidate_registry.ADOPTION_PROFILES)
    if mutation == "missing":
        profiles.pop(PROFILE.key)
    elif mutation == "extra":
        profiles["unexpected", 1] = PROFILE
    elif mutation == "replaced":
        key = ("workforce_only", 1)
        profiles[key] = replace(
            profiles[key], modules=profiles[key].modules | {"programme"}
        )
    elif mutation == "selector":
        candidate_registry.SELECTABLE_ADOPTION_PROFILE_KEYS = {}
    elif mutation == "choices":
        candidate_registry.SELECTABLE_ADOPTION_PROFILE_CHOICES = ()
    else:
        compatibility.adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS = ()
    candidate_registry.ADOPTION_PROFILES = profiles
    with pytest.raises(compatibility.ProgrammeCompatibilityError):
        compatibility.validate_installed_candidate()


def test_catalog_failure_is_not_hidden_by_expected_dormancy(
    candidate_registry, monkeypatch
):
    catalog = compatibility.current_adoption_catalog_snapshot()
    monkeypatch.setattr(
        compatibility,
        "current_adoption_catalog_snapshot",
        lambda: replace(catalog, registry_problem_codes=("unknown-catalog-error",)),
    )
    with pytest.raises(
        compatibility.ProgrammeCompatibilityError, match="catalog_incomplete"
    ):
        compatibility.validate_installed_candidate()


def test_original_profile_dormancy_is_independently_checked(
    candidate_registry, monkeypatch
):
    monkeypatch.setattr(
        compatibility,
        "scheduling_dormancy_problem_codes",
        lambda **_kwargs: ("dormancy.module-adopted",),
    )
    with pytest.raises(
        compatibility.ProgrammeCompatibilityError, match="baseline_not_dormant"
    ):
        compatibility.validate_installed_candidate()


@pytest.fixture
def candidate_checks(candidate_registry, monkeypatch):
    fence = Mock()
    monkeypatch.setattr(compatibility, "require_programme_runtime_environment", fence)
    checks = []
    owner_contracts = {}
    for (
        identifier,
        _problem_function,
        expected,
    ) in compatibility._OWNER_PROBLEMS.values():
        check = Mock(return_value=[Error("Expected isolated adoption", id=identifier)])
        problems = Mock(return_value=tuple(expected))
        checks.append(check)
        owner_contracts[check] = (identifier, problems, expected)
    normal = Mock(return_value=[])
    checks.append(normal)
    monkeypatch.setattr(compatibility, "_OWNER_PROBLEMS", owner_contracts)
    monkeypatch.setattr(
        compatibility, "registry", SimpleNamespace(get_checks=Mock(return_value=checks))
    )
    return SimpleNamespace(
        checks=checks, normal=normal, fence=fence, owners=owner_contracts
    )


def test_all_checks_run_and_adapted_owner_results_are_explicit(candidate_checks):
    assert compatibility.check_isolated_candidate() == (
        "applications.E002",
        "programme.E001",
        "scheduling.E001",
    )
    for check in candidate_checks.checks:
        check.assert_called_once_with(app_configs=None, databases=["default"])


@pytest.mark.parametrize(
    "message",
    [
        Error("private", id="unknown.E001"),
        Error("collision", id="programme.E001"),
        CheckWarning("private", id="unknown.W001"),
        "not a check message",
    ],
)
def test_unknown_checks_and_id_collisions_are_never_ignored(message, candidate_checks):
    candidate_checks.normal.return_value = [message]
    with pytest.raises(compatibility.ProgrammeCompatibilityError):
        compatibility.check_isolated_candidate()


@pytest.mark.parametrize(
    "defect", ["missing", "extra-problem", "extra-message", "wrong-level", "empty"]
)
def test_owner_adaptation_cannot_hide_a_changed_contract(defect, candidate_checks):
    check = candidate_checks.checks[0]
    identifier, problems, expected = candidate_checks.owners[check]
    if defect == "missing":
        candidate_checks.checks.remove(check)
    elif defect == "extra-problem":
        problems.return_value = (*expected, "catalog.event-missing")
    elif defect == "extra-message":
        check.return_value.append(Error("additional error", id=identifier))
    elif defect == "wrong-level":
        check.return_value = [CheckWarning("not expected", id=identifier)]
    else:
        check.return_value = []
    with pytest.raises(compatibility.ProgrammeCompatibilityError):
        compatibility.check_isolated_candidate()


def test_policy_fails_before_check_registry_access(candidate_checks):
    candidate_checks.fence.side_effect = ProgrammeRehearsalEnvironmentError("deferred")
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        compatibility.check_isolated_candidate()
    compatibility.registry.get_checks.assert_not_called()


def test_real_joined_handlers_keep_all_existing_handlers_and_only_add_candidate_facts():
    original = effects._BASELINE_FACTORY()
    joined = effects.joined_handler_registry()
    for profile in adoption.ADOPTION_PROFILES.values():
        for route in profile.effect_routes:
            assert joined.resolve(
                event_name=route.event_name, destination=route.destination
            ) is original.resolve(
                event_name=route.event_name, destination=route.destination
            )
    for route in PROFILE.effect_routes:
        assert (
            joined.resolve(event_name=route.event_name, destination=route.destination)
            is effects.acknowledge_internal_fact
        )
    assert (
        joined.resolve(
            event_name="programme.item.changed.v1", destination="notifications"
        )
        is None
    )
    assert effects.owner_handlers.built_in_handler_registry is effects._BASELINE_FACTORY


def test_conflicting_candidate_handler_cannot_be_overwritten(monkeypatch):
    registry = SimpleNamespace(resolve=Mock(return_value=object()), register=Mock())
    monkeypatch.setattr(effects, "_BASELINE_FACTORY", lambda: registry)
    with pytest.raises(ValueError, match="Unexpected candidate effect owner"):
        effects.joined_handler_registry()
    registry.register.assert_not_called()


def test_handler_installation_checks_policy_before_factory_mutation(monkeypatch):
    monkeypatch.setattr(
        effects,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    before = effects.owner_handlers.built_in_handler_registry
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        effects.install_isolated_candidate_handlers()
    assert effects.owner_handlers.built_in_handler_registry is before


@pytest.fixture
def native_readiness(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        ("synthetic", "maru_runtime", "maru_runtime"),
        (True,),
        (True,),
    ]
    cursor.fetchall.return_value = [(runtime._PROFILE_CHECK, True, True, 0, False)]
    manager = MagicMock()
    manager.__enter__.return_value = cursor
    monkeypatch.setattr(connection, "cursor", Mock(return_value=manager))
    health = Mock(
        return_value=SimpleNamespace(
            status_code=200,
            data={"status": "ok", "dependencies": {"authority_provenance": "ok"}},
        )
    )
    setup = Mock(return_value=True)
    roles = Mock(return_value=True)
    starter = Mock(return_value=True)
    helpers = Mock()
    monkeypatch.setattr(helper_acl, "require_helper_catalog", helpers)
    monkeypatch.setattr(views, "readiness", health)
    monkeypatch.setattr(
        programme_setup_readiness, "programme_setup_database_integrity_is_ready", setup
    )
    monkeypatch.setattr(
        programme_role_readiness, "programme_role_database_integrity_is_ready", roles
    )
    monkeypatch.setattr(
        programme_starter_readiness,
        "programme_starter_database_integrity_is_ready",
        starter,
    )
    return SimpleNamespace(
        cursor=cursor,
        health=health,
        setup=setup,
        roles=roles,
        helpers=helpers,
        starter=starter,
    )


def test_native_readiness_uses_real_owner_entrypoints_in_sequence(native_readiness):
    runtime._require_native_readiness(SimpleNamespace(database_name="synthetic"))
    native_readiness.health.assert_called_once()
    native_readiness.setup.assert_called_once()
    native_readiness.roles.assert_called_once()
    native_readiness.starter.assert_called_once()
    native_readiness.helpers.assert_called_once_with(
        connection.connection, runtime_granted=True
    )


def test_native_helper_failure_prevents_health_and_application_acceptance(
    native_readiness,
):
    native_readiness.helpers.side_effect = helper_acl.ProgrammeFunctionError("private")
    with pytest.raises(
        runtime.ProgrammeStartupError, match="native_helper_unavailable"
    ):
        runtime._require_native_readiness(SimpleNamespace(database_name="synthetic"))
    native_readiness.health.assert_not_called()
    native_readiness.setup.assert_not_called()
    native_readiness.roles.assert_not_called()


@pytest.mark.parametrize(
    "defect",
    [
        "identity",
        "migration",
        "constraint",
        "health",
        "dependency",
        "setup",
        "roles",
        "starter",
    ],
)
def test_native_readiness_fails_closed_on_any_unavailable_boundary(
    defect, native_readiness
):
    if defect == "identity":
        native_readiness.cursor.fetchone.side_effect = [
            ("foreign", "postgres", "postgres")
        ]
    elif defect == "migration":
        native_readiness.cursor.fetchone.side_effect = [
            ("synthetic", "maru_runtime", "maru_runtime"),
            (False,),
        ]
    elif defect == "constraint":
        native_readiness.cursor.fetchall.return_value = [
            ("CHECK (true)", True, True, 0, False)
        ]
    elif defect == "health":
        native_readiness.health.return_value.status_code = 503
    elif defect == "dependency":
        native_readiness.health.return_value.data["dependencies"][
            "authority_provenance"
        ] = "unavailable"
    elif defect == "setup":
        native_readiness.setup.return_value = False
    elif defect == "roles":
        native_readiness.roles.return_value = False
    else:
        native_readiness.starter.return_value = False
    with pytest.raises(runtime.ProgrammeStartupError):
        runtime._require_native_readiness(SimpleNamespace(database_name="synthetic"))


def test_builder_refuses_deferred_policy_before_django(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        runtime.build_candidate_application()


@pytest.mark.parametrize(
    "secret",
    [
        "MARU_IDENTITY_INVITATION_PRIVATE_KEYS_JSON",
        "MARU_PROGRAMME_REHEARSAL_ADMIN_PASSWORD",
        "MARU_PROGRAMME_REHEARSAL_BOOTSTRAP",
    ],
)
def test_web_builder_refuses_owner_or_worker_secret_even_when_empty(
    monkeypatch, secret
):
    monkeypatch.setattr(runtime, "require_programme_runtime_environment", Mock())
    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE", "tests.rehearsals.programme_runtime_settings"
    )
    monkeypatch.setenv(secret, "")
    setup = Mock()
    monkeypatch.setattr(django, "setup", setup)
    with pytest.raises(runtime.ProgrammeStartupError, match="secret_contamination"):
        runtime.build_candidate_application()
    setup.assert_not_called()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DEBUG", True),
        ("ALLOWED_HOSTS", ["*"]),
        ("ROOT_URLCONF", "maru.urls"),
        ("MIGRATION_MODULES", {}),
        ("REQUIRE_EXACT_AUTHORITY_PROVENANCE", False),
        ("REQUIRE_PRIVILEGED_STEP_UP", False),
        ("ENFORCE_EDITION_CLOSURE_GATES", False),
        ("IDENTITY_INVITATION_ENCRYPTION_REQUIRED", False),
        ("IDENTITY_EXPOSE_TEST_TOKENS", True),
        ("MARU_EXPOSE_TEST_CREDENTIAL_TOKENS", True),
        ("DEMO_PAYMENT_ADAPTER_ENABLED", True),
        ("SILENCED_SYSTEM_CHECKS", ["programme.E001"]),
        ("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"),
        ("SESSION_COOKIE_SECURE", False),
        ("CSRF_COOKIE_SECURE", False),
        ("SECURE_SSL_REDIRECT", False),
        ("SETTINGS_MODULE", "maru.settings.test"),
    ],
)
def test_serving_settings_cannot_weaken_any_required_boundary(name, value):
    settings = _strict_settings()
    assert runtime._runtime_configuration_is_strict(settings)
    setattr(settings, name, value)
    assert not runtime._runtime_configuration_is_strict(settings)


def test_candidate_settings_register_before_base_without_test_settings():
    source = (
        Path(runtime.__file__)
        .with_name("programme_runtime_settings.py")
        .read_text(encoding="utf-8")
    )
    tree = ast.parse(source)
    imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert "maru.settings.base" in imports
    assert "maru.settings.test" not in imports
    assert source.index("register_isolated_programme_candidate()") < source.index(
        "from maru.settings.base"
    )
    assert "SILENCED_SYSTEM_CHECKS" not in source


@pytest.mark.parametrize("fail_native", [False, True])
def test_builder_does_not_construct_wsgi_until_all_checks_succeed(
    fail_native, monkeypatch
):
    steps = []
    monkeypatch.setattr(
        runtime,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(database_name="synthetic"),
    )
    monkeypatch.setattr(
        runtime,
        "os",
        SimpleNamespace(
            environ={
                "DJANGO_SETTINGS_MODULE": "tests.rehearsals.programme_runtime_settings"
            }
        ),
    )
    monkeypatch.setattr(django, "setup", lambda: steps.append("django"))
    monkeypatch.setattr(django.conf, "settings", _strict_settings())
    monkeypatch.setattr(
        privileges,
        "install_isolated_candidate_privilege_contract",
        lambda: steps.append("privileges"),
    )
    monkeypatch.setattr(
        effects, "install_isolated_candidate_handlers", lambda: steps.append("handlers")
    )

    def checks():
        steps.append("checks")
        return ("explicit isolated adoption",)

    def native(_environment):
        steps.append("native")
        if fail_native:
            raise runtime.ProgrammeStartupError("not_ready")

    monkeypatch.setattr(compatibility, "check_isolated_candidate", checks)
    monkeypatch.setattr(runtime, "_require_native_readiness", native)
    application = object()
    factory = Mock(side_effect=lambda: (steps.append("wsgi"), application)[1])
    monkeypatch.setattr(wsgi, "get_wsgi_application", factory)
    if fail_native:
        with pytest.raises(runtime.ProgrammeStartupError, match="not_ready"):
            runtime.build_candidate_application()
        factory.assert_not_called()
        assert steps == ["django", "privileges", "handlers", "checks", "native"]
    else:
        assert runtime.build_candidate_application() == (
            application,
            ("explicit isolated adoption",),
        )
        assert steps == ["django", "privileges", "handlers", "checks", "native", "wsgi"]
