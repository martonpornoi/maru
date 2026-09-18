"""Database-free exact-profile shell composition and narrow context discovery."""

from dataclasses import replace
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import include, path, resolve

from maru.authorization.policy import AuthorizedScopeProjection
from maru.core import navigation as registry
from maru.core import programme_navigation as navigation
from maru.events import admin_context
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink

ORG, EDITION, SERIES, ACTOR, DEPARTMENT = (UUID(int=i) for i in range(1, 6))
PERSON = Account(
    id=ACTOR, is_active=True, email_verified_at=datetime(2026, 9, 18, tzinfo=UTC)
)
PROJECTION = AuthorizedScopeProjection(
    ORG,
    EDITION,
    DEPARTMENT,
    None,
    frozenset({"authorization.manage_roles"}),
    frozenset({"authorization.manage_roles"}),
    (),
    (),
)


def routes():
    module = ModuleType(f"synthetic_shared_programme_{uuid4().hex}")
    module.urlpatterns = [
        path("", include(owner))
        for owner in (
            "maru.applications.programme_call_urls",
            "maru.programme.workbench_urls",
            "maru.scheduling.planning_urls",
            "maru.scheduling.release_workspace_urls",
            "maru.scheduling.output_urls",
            "maru.authorization.programme_role_urls",
            "maru.events.programme_setup_urls",
            "maru.urls",
        )
    ]
    return module


@pytest.fixture
def world(monkeypatch):
    allowed = set(navigation.PROGRAMME_SHELL_KINDS.values())
    manifest = Mock(return_value=object())
    monkeypatch.setattr(navigation, "adoption_profile", manifest)
    monkeypatch.setattr(
        navigation,
        "profile_allows_shell_destination",
        lambda _code, _version, kind: kind in allowed,
    )
    urlconf = routes()

    def links(scope, **kwargs):
        return tuple(
            ProgrammeWorkspaceLink(
                code,
                f"Synthetic {code}",
                navigation.reverse(
                    navigation._HANDLERS[code][0],
                    urlconf=urlconf,
                    kwargs={
                        "organization_id": scope.organization_id,
                        "edition_id": scope.edition_id,
                        **(
                            {"series_id": SERIES}
                            if code in {"timetable", "release"}
                            else {}
                        ),
                    },
                ),
            )
            for code in navigation.PROGRAMME_SHELL_KINDS
            if code in kwargs["allowed_codes"]
        )

    owner = Mock(side_effect=links)
    access = Mock(return_value=True)
    setup = Mock()
    monkeypatch.setattr(navigation, "programme_workspace_links", owner)
    monkeypatch.setattr(navigation, "can_enter_programme_role_scopes", access)
    monkeypatch.setattr(navigation, "require_programme_setup_actor", setup)
    return SimpleNamespace(
        allowed=allowed,
        manifest=manifest,
        urlconf=urlconf,
        owner=owner,
        access=access,
        setup=setup,
    )


def links(world, **changes):
    return navigation.programme_shell_links(
        **{
            "actor": PERSON,
            "organization_id": ORG,
            "edition_id": EDITION,
            "profile_code": "programme_operations",
            "profile_version": 1,
            "urlconf": world.urlconf,
            **changes,
        }
    )


@pytest.mark.parametrize(
    ("code", "version"),
    [
        ("full_convention", 1),
        ("workforce_only", 1),
        ("programme_operations", 2),
        ("unknown", 1),
        ("programme_operations", True),
    ],
)
def test_current_or_unknown_profiles_never_add_discovery(world, code, version):
    assert links(world, profile_code=code, profile_version=version) == ()
    world.owner.assert_not_called()
    world.access.assert_not_called()


def test_absent_candidate_and_inactive_principal_do_no_optional_reads(world):
    world.manifest.return_value = None
    assert links(world) == ()
    assert (
        navigation.programme_setup_navigation_url(actor=PERSON, urlconf=world.urlconf)
        == ""
    )
    world.owner.assert_not_called()
    world.setup.assert_not_called()
    world.manifest.return_value = object()
    assert links(world, actor=Account(id=ACTOR, is_active=False)) == ()
    world.owner.assert_not_called()


def test_all_seven_independent_tasks_have_exact_registered_scopes(world):
    result = links(world)
    assert len(result) == 7
    assert {row.shell_kind for row in result} == world.allowed
    for row in result:
        match = resolve(row.url, urlconf=world.urlconf)
        assert match.kwargs["organization_id"] == ORG
        assert match.kwargs["edition_id"] == EDITION
        assert "?" not in row.url
    assert world.owner.call_args.kwargs["current"] == "navigation"
    assert world.owner.call_args.kwargs["allowed_codes"] == frozenset(
        navigation.PROGRAMME_SHELL_KINDS
    ) - {"access"}
    world.access.assert_called_once_with(
        actor=PERSON, organization_id=ORG, edition_id=EDITION
    )


@pytest.mark.parametrize("code", tuple(navigation.PROGRAMME_SHELL_KINDS))
def test_each_manifest_kind_is_independently_required(world, code):
    world.allowed.remove(navigation.PROGRAMME_SHELL_KINDS[code])
    assert code not in {row.code for row in links(world)}
    assert code not in world.owner.call_args.kwargs["allowed_codes"]
    if code == "access":
        world.access.assert_not_called()


@pytest.mark.parametrize("result", [False, None, 1])
def test_access_entry_requires_exact_true_without_suppressing_other_tasks(
    world, result
):
    world.access.return_value = result
    assert len(links(world)) == 6


@pytest.mark.parametrize(
    "error",
    [
        PermissionDenied(),
        ValidationError("hidden"),
        DatabaseError("hidden"),
        RuntimeError("hidden"),
    ],
)
def test_unavailable_access_task_omits_only_its_optional_link(world, error):
    world.access.side_effect = error
    assert len(links(world)) == 6


def test_unmounted_access_or_setup_does_not_query_its_owner(world):
    assert links(world, urlconf="maru.urls") == ()
    world.access.assert_not_called()
    assert (
        navigation.programme_setup_navigation_url(actor=PERSON, urlconf="maru.urls")
        == ""
    )
    world.setup.assert_not_called()


def test_shadowed_route_does_not_masquerade_as_an_owner_task(world):
    world.urlconf.urlpatterns.insert(
        0,
        path("<path:rest>", lambda _request, **_kwargs: HttpResponse(), name="shadow"),
    )
    assert links(world) == ()
    world.access.assert_not_called()


def test_wrong_handler_with_correct_route_name_cannot_enter(world):
    world.urlconf.urlpatterns.insert(
        0,
        path(
            "admin/programme/access/<uuid:organization_id>/<uuid:edition_id>/",
            lambda _request, **_kwargs: HttpResponse(),
            name="programme-access-scopes",
        ),
    )
    assert all(row.code != "access" for row in links(world))
    world.access.assert_not_called()


def test_platform_setup_uses_actual_owner_admission_and_route(world):
    value = navigation.programme_setup_navigation_url(
        actor=PERSON, urlconf=world.urlconf
    )
    assert resolve(value, urlconf=world.urlconf).url_name == "programme-setup"
    world.setup.assert_called_once_with(PERSON)
    world.setup.side_effect = PermissionDenied
    assert (
        navigation.programme_setup_navigation_url(actor=PERSON, urlconf=world.urlconf)
        == ""
    )


@pytest.fixture
def context_world(monkeypatch):
    request = RequestFactory().get("/admin/")
    request.user = PERSON
    request.session = {}
    request.urlconf = routes()
    manifest = Mock(return_value=object())
    scopes = Mock(return_value=(PROJECTION,))
    admission = Mock(return_value=(object(),))
    manager = Mock()
    rows = Mock()
    rows.__getitem__ = Mock(return_value=[(EDITION, ORG)])
    manager.filter.return_value.order_by.return_value.values_list.return_value = rows
    monkeypatch.setattr(admin_context, "adoption_profile", manifest)
    monkeypatch.setattr(admin_context, "_authorized_admin_scopes", scopes)
    monkeypatch.setattr(admin_context, "programme_shell_links", admission)
    monkeypatch.setattr(EventEdition, "objects", manager)
    return SimpleNamespace(
        request=request,
        manifest=manifest,
        scopes=scopes,
        admission=admission,
        manager=manager,
        rows=rows,
    )


def test_narrow_source_discovers_only_independently_admitted_edition_metadata(
    context_world,
):
    w = context_world
    assert admin_context._programme_admin_edition_ids(w.request) == frozenset({EDITION})
    assert w.manager.filter.call_args.kwargs == {
        "adoption_profile_code": "programme_operations",
        "adoption_profile_version": 1,
    }
    w.manager.filter.return_value.order_by.return_value.values_list.assert_called_once_with(
        "id", "organization_id"
    )
    w.rows.__getitem__.assert_called_once_with(slice(None, 257))
    assert w.admission.call_args.kwargs["edition_id"] == EDITION
    assert w.admission.call_args.kwargs["organization_id"] == ORG


def test_no_programme_profile_or_own_authority_means_no_metadata_query(context_world):
    w = context_world
    w.manifest.return_value = None
    assert not admin_context._programme_admin_edition_ids(w.request)
    w.manager.filter.assert_not_called()
    w.manifest.return_value = object()
    w.scopes.return_value = ()
    assert not admin_context._programme_admin_edition_ids(w.request)
    w.manager.filter.assert_not_called()


@pytest.mark.parametrize("rows", [[(EDITION, uuid4())], [(uuid4(), ORG)]])
def test_metadata_cannot_rebind_a_foreign_context(context_world, rows):
    w = context_world
    w.rows.__getitem__.return_value = rows
    assert not admin_context._programme_admin_edition_ids(w.request)
    w.admission.assert_not_called()


@pytest.mark.parametrize("count", [256, 257])
def test_complete_context_discovery_bound_never_returns_partial_list(
    context_world, count
):
    w = context_world
    w.scopes.return_value = (replace(PROJECTION, edition_id=None, department_id=None),)
    w.rows.__getitem__.return_value = [(UUID(int=100 + i), ORG) for i in range(count)]
    assert len(admin_context._programme_admin_edition_ids(w.request)) == (
        256 if count == 256 else 0
    )
    if count == 257:
        w.admission.assert_not_called()


def test_current_owner_denial_prevents_edition_label_discovery(context_world):
    context_world.admission.return_value = ()
    assert not admin_context._programme_admin_edition_ids(context_world.request)


@pytest.mark.parametrize(
    "error",
    [
        PermissionDenied(),
        ValidationError("unavailable"),
        DatabaseError("failed"),
        RuntimeError("failed"),
    ],
)
def test_optional_context_failure_is_non_disclosing(context_world, error):
    context_world.admission.side_effect = error
    assert not admin_context._programme_admin_edition_ids(context_world.request)


def test_registry_entries_have_stable_codes_search_metadata_and_exact_current_scope(
    world, monkeypatch
):
    request = RequestFactory().get("/admin/")
    request.user = PERSON
    request.urlconf = world.urlconf
    edition = EventEdition(
        id=EDITION,
        organization_id=ORG,
        adoption_profile_code="programme_operations",
        adoption_profile_version=1,
    )
    monkeypatch.setattr(
        registry, "programme_shell_links", lambda **_kwargs: links(world)
    )
    items = registry._programme_destinations(
        request, edition, "Already authorized context"
    )
    assert len(items) == 7
    assert len({item.code for item in items}) == 7
    assert all("programme" in item.search_text for item in items)
    assert all(item.pinnable for item in items)
    request.path = items[-1].url + "edition/new/"
    assert [
        item.code
        for item in registry._programme_destinations(request, edition, "Context")
        if item.current
    ] == [f"edition.{EDITION}.programme-access"]


def test_shared_registry_reauthorizes_pins_and_separates_personal_surface(
    world, monkeypatch
):
    request = RequestFactory().get("/admin/")
    request.user = PERSON
    request.urlconf = world.urlconf
    edition = EventEdition(
        id=EDITION,
        organization_id=ORG,
        adoption_profile_code="programme_operations",
        adoption_profile_version=1,
    )
    personal = registry.NavigationItem("my.home", "My Maru", "/my/", "Personal")
    monkeypatch.setattr(registry, "programme_shell_links", lambda **_kw: links(world))
    monkeypatch.setattr(registry, "_personal_items", lambda *_a, **_kw: [personal])
    monkeypatch.setattr(
        registry,
        "_selected_edition_items",
        lambda r: registry._programme_destinations(
            r, edition, "Synthetic admitted edition"
        ),
    )
    for name in (
        "_management_items",
        "_scoped_organization_items",
        "_page_context_items",
        "_platform_items",
        "_specialist_items",
    ):
        monkeypatch.setattr(registry, name, lambda *_a, **_kw: [])
    monkeypatch.setattr(
        registry, "admin_shell_access", lambda _r: {"workspace_available": False}
    )
    code = f"edition.{EDITION}.programme-access"
    assert registry.destination_code_is_supported(code)
    monkeypatch.setattr(registry, "navigation_pin_codes", lambda **_kw: (code,))

    def project(*, personal_surface=False):
        return registry.project_shell_navigation(
            request, page_context={}, personal_surface=personal_surface
        )

    management = project()
    assert management["count"] == 7
    assert management["groups"][0]["label"] == "Pinned"
    assert management["groups"][0]["items"][0].code == code
    own = project(personal_surface=True)
    assert own["count"] == 1
    assert own["groups"][0]["items"] == (personal,)
    world.access.return_value = False
    revoked = project()
    assert revoked["count"] == 6
    assert all(group["label"] != "Pinned" for group in revoked["groups"])
    assert all(
        item.code != code for group in revoked["groups"] for item in group["items"]
    )


def test_selector_unions_new_admission_with_unchanged_legacy_candidates(
    context_world, monkeypatch
):
    w = context_world
    legacy_id = uuid4()
    legacy = Mock(return_value=frozenset({legacy_id}))
    monkeypatch.setattr(admin_context, "authorized_admin_edition_ids", legacy)
    queryset = w.manager.all.return_value
    assert admin_context._authorized_admin_editions(w.request) is (
        queryset.filter.return_value.select_related.return_value
    )
    queryset.filter.assert_called_once_with(id__in=frozenset({legacy_id, EDITION}))
    assert legacy.call_args.kwargs["capability_codes"] == (
        admin_context._EDITION_WORKSPACE_NAVIGATION_CAPABILITIES
    )
    queryset.filter.return_value.select_related.assert_called_once_with(
        "organization", "series"
    )
