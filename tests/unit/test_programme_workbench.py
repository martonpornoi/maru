"""Database-free real forms and HTML with independently stubbed owner boundaries."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import resolve

from maru.programme import workbench_views as views
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import (
    ProgrammeIdempotencyConflictError,
    ProgrammeLifecycleConflictError,
    ProgrammeLimitConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
)
from maru.programme.queries import (
    ProgrammeDeliveryProjection,
    ProgrammeItemProjection,
    ProgrammePrivateItemProjection,
    ProgrammePublicCopyProjection,
    ProgrammeQueryUnavailableError,
    ProgrammeReadinessConcernProjection,
    ProgrammeTimetableInventoryLimitError,
    ProgrammeTimetableItemProjection,
    ProgrammeWorkingProjection,
)
from maru.programme.workbench_forms import (
    ProgrammeCoreForm,
    ProgrammeDeliveryForm,
    ProgrammePublicCopyForm,
    ProgrammeReadinessForm,
    ProgrammeWorkingForm,
)
from maru.programme.workbench_queries import (
    ProgrammeWorkbenchInventory,
    ProgrammeWorkbenchItem,
)


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", side_effect=lambda _request: {}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.fixture
def page(monkeypatch):
    actor, organization, edition, item_id, source_id = (
        UUID(int=i) for i in range(1, 6)
    )
    item = ProgrammeItemProjection(item_id, "ceremony", "organizer_core", "active", 7)
    working = ProgrammeWorkingProjection("Opening ceremony", "Private working brief", 6)
    selected = ProgrammeWorkbenchItem(
        ProgrammePrivateItemProjection(item, working), source_id
    )
    inventory = ProgrammeWorkbenchInventory(
        3, (ProgrammeTimetableItemProjection(item, working.internal_title, 6),)
    )
    private = Mock(return_value=selected)
    listing = Mock(return_value=inventory)
    auth = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    monkeypatch.setattr(views, "authorize_programme_scope", auth)
    monkeypatch.setattr(views, "load_programme_workbench_item", private)
    monkeypatch.setattr(views, "load_programme_workbench_inventory", listing)
    monkeypatch.setattr(
        views,
        "resolve_scheduling_edition_reference",
        Mock(return_value=SimpleNamespace(accepts_scheduling_writes=True)),
    )
    readers = {}
    for name, result in {
        "load_programme_delivery": ProgrammeDeliveryProjection(
            "Secret technical cue", "Access instruction", "Media note", 7
        ),
        "load_programme_readiness": (
            ProgrammeReadinessConcernProjection(
                "public_copy", "stale", 1, 2, 1, 1, "source", 1
            ),
        ),
        "load_programme_public_copy": ProgrammePublicCopyProjection(
            2, "Public ceremony", "Public summary", "Public note"
        ),
        "list_programme_working_history": (),
        "list_programme_delivery_history": (),
        "list_programme_readiness_history": (),
        "list_programme_public_copy_review_history": (),
    }.items():
        readers[name] = Mock(return_value=result)
        monkeypatch.setattr(views.queries, name, readers[name])
    writers = {}
    for task, name in {
        "create": "create_organizer_core_item",
        "working": "revise_programme_working",
        "delivery": "revise_programme_delivery",
        "readiness": "configure_programme_readiness",
        "public-copy": "approve_programme_public_rendition",
    }.items():
        writers[task] = Mock(return_value=SimpleNamespace(item_id=item_id))
        monkeypatch.setattr(views.commands, name, writers[task])
    return SimpleNamespace(
        actor=actor,
        organization=organization,
        edition=edition,
        item_id=item_id,
        source_id=source_id,
        selected=selected,
        private=private,
        listing=listing,
        auth=auth,
        readers=readers,
        writers=writers,
    )


def call(
    page, task=None, data=None, *, query="", anonymous=False, csrf=False, method=None
):
    url = f"/admin/programme/items/{page.organization}/{page.edition}/"
    if task:
        url += f"{page.item_id}/{task}/"
    url += query
    if data is not None:
        encoded = data if isinstance(data, QueryDict) else QueryDict("", mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = RequestFactory().post(
            url,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    else:
        request = RequestFactory().generic(method or "GET", url)
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=page.actor,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    kwargs = {"organization_id": page.organization, "edition_id": page.edition}
    if task:
        return views.programme_item(request, **kwargs, item_id=page.item_id, task=task)
    return views.programme_items(request, **kwargs)


def submitted(page, task):
    common = {
        "expected_version": "7",
        "idempotency_key": str(UUID(int=90)),
        "reason": "Synthetic retained reason",
    }
    fields = {
        "create": {
            "kind": "ceremony",
            "internal_title": "New ceremony",
            "working_summary": "Working summary",
        },
        "working": {
            "internal_title": "Revised ceremony",
            "working_summary": "Working summary",
        },
        "delivery": {
            "technical_requirements": "New cue",
            "accessibility_delivery": "Step-free",
            "media_consent_notes": "No recording",
        },
        "readiness": {"concern": "technical_needs", "disposition": "required"},
        "public-copy": {
            "source_working_revision_id": str(page.source_id),
            "public_title": "Reviewed ceremony",
            "public_summary": "Reviewed summary",
            "public_content_note": "Quiet opening",
        },
    }
    return {**common, **fields[task]}


def parsed(response):
    return BeautifulSoup(response.content, "html.parser")


def test_inventory_is_labelled_shared_shell_and_private_layer_minimized(page):
    response = call(page)
    doc = parsed(response)
    assert response.status_code == 200
    assert len(doc.select("h1")) == len(doc.select("main")) == 1
    assert doc.find("a", string="Opening ceremony")
    assert doc.select_one('input[name="expected_version"]')["value"] == "3"
    assert not doc.select('input:not([type="hidden"])[name$="_id"]')
    assert "Private working brief" not in doc.get_text()
    assert "Secret technical cue" not in doc.get_text()
    for reader in page.readers.values():
        reader.assert_not_called()
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_empty_inventory_is_not_readiness_or_acceptance(page):
    page.listing.return_value = ProgrammeWorkbenchInventory(0, ())
    response = call(page)
    assert response.status_code == 200
    assert "No Programme items yet" in parsed(response).get_text()
    assert parsed(response).select_one('input[name="expected_version"]')["value"] == "0"


@pytest.mark.parametrize(
    "task", ["create", "working", "delivery", "readiness", "public-copy"]
)
def test_real_forms_forward_only_closed_exact_scope_and_original_intent(page, task):
    data = submitted(page, task)
    response = call(page, None if task == "create" else task, data)
    assert response.status_code == 302
    kwargs = page.writers[task].call_args.kwargs
    assert kwargs["actor_id"] == page.actor
    assert kwargs["organization_id"] == page.organization
    assert kwargs["edition_id"] == page.edition
    assert kwargs["expected_version"] == 7
    assert kwargs["idempotency_key"] == UUID(int=90)
    assert kwargs["reason"] == data["reason"]
    assert kwargs["source_channel"] == "programme-workbench"
    assert isinstance(kwargs["correlation_id"], UUID)
    if task != "create":
        assert kwargs["item_id"] == page.item_id
    assert response["Location"].endswith(
        f"/{page.item_id}/{'working' if task == 'create' else task}/"
    )
    for other, writer in page.writers.items():
        if other != task:
            writer.assert_not_called()


@pytest.mark.parametrize(
    ("task", "reader", "visible"),
    [
        ("delivery", "load_programme_delivery", "Secret technical cue"),
        ("readiness", "load_programme_readiness", "stale"),
        ("public-copy", "load_programme_public_copy", "Public ceremony"),
        ("working-history", "list_programme_working_history", "No entries"),
        ("delivery-history", "list_programme_delivery_history", "No entries"),
        ("readiness-history", "list_programme_readiness_history", "No entries"),
        (
            "public-copy-history",
            "list_programme_public_copy_review_history",
            "No entries",
        ),
    ],
)
def test_only_selected_authorized_layer_is_loaded(page, task, reader, visible):
    response = call(page, task)
    assert response.status_code == 200
    assert visible in parsed(response).get_text()
    kwargs = page.readers[reader].call_args.kwargs
    assert kwargs["item_id"] == page.item_id
    assert kwargs["organization_id"] == page.organization
    assert kwargs["edition_id"] == page.edition
    assert kwargs["actor_id"] == page.actor
    for name, other in page.readers.items():
        if name != reader:
            other.assert_not_called()
    if task.endswith("history"):
        assert kwargs["limit"] == 200
        assert not parsed(response).select(".programme-workbench form[method=post]")


def test_public_form_never_copies_private_or_previous_public_values(page):
    doc = parsed(call(page, "public-copy"))
    assert doc.select_one('input[name="public_title"]').get("value", "") == ""
    assert doc.select_one('textarea[name="public_summary"]').text.strip() == ""
    assert doc.select_one('input[name="source_working_revision_id"]')["value"] == str(
        page.source_id
    )
    assert "Draft self-curation is not release approval" in doc.get_text()


def test_absent_or_withdrawn_copy_has_no_old_fallback(page):
    page.readers["load_programme_public_copy"].return_value = None
    doc = parsed(call(page, "public-copy"))
    assert "No available reviewed public copy" in doc.get_text()
    assert "Public ceremony" not in doc.get_text()
    page.readers["list_programme_public_copy_review_history"].assert_not_called()


@pytest.mark.parametrize("task", [None, *views._READS])
def test_base_denial_precedes_private_lookup_and_input_echo(page, task):
    page.auth.side_effect = ProgrammeAuthorizationDeniedError
    response = call(page, task)
    assert response.status_code == 404
    assert "Opening ceremony" not in response.content.decode()
    page.private.assert_not_called()
    page.listing.assert_not_called()
    for reader in page.readers.values():
        reader.assert_not_called()


@pytest.mark.parametrize(
    "task",
    [
        "delivery",
        "readiness",
        "public-copy",
        "working-history",
        "delivery-history",
        "readiness-history",
        "public-copy-history",
    ],
)
def test_independent_field_denial_hides_link_and_selected_page(page, task):
    denied_capability, denied_fields = views._READS[task]

    def authorize(**kwargs):
        if (
            kwargs["capability_code"] == denied_capability
            and kwargs["requested_fields"] == denied_fields
        ):
            raise ProgrammeAuthorizationDeniedError
        return SimpleNamespace(accepts_private_planning_writes=True)

    page.auth.side_effect = authorize
    doc = parsed(call(page, "working"))
    assert not doc.find("a", string=views._LABELS[task])
    page.private.reset_mock()
    assert call(page, task).status_code == 404
    page.private.assert_not_called()


@pytest.mark.parametrize(
    "task", ["create", "working", "delivery", "readiness", "public-copy"]
)
def test_read_only_authority_hides_form_and_rejects_forged_post(page, task):
    def authorize(**kwargs):
        if (
            kwargs["capability_code"] == views._WRITES[task]
            and kwargs["requested_fields"] is None
        ):
            raise ProgrammeAuthorizationDeniedError
        return SimpleNamespace(accepts_private_planning_writes=True)

    page.auth.side_effect = authorize
    selected_task = None if task == "create" else task
    assert not parsed(call(page, selected_task)).select(
        ".programme-workbench form[method=post]"
    )
    response = call(page, selected_task, submitted(page, task))
    assert response.status_code == 404
    assert "Synthetic retained reason" not in response.content.decode()
    page.writers[task].assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        ProgrammeVersionConflictError,
        ProgrammeIdempotencyConflictError,
        ProgrammeLifecycleConflictError,
        ProgrammeLimitConflictError,
    ],
)
def test_conflict_retains_original_input_and_tokens_not_fresh_version(page, failure):
    page.writers["working"].side_effect = failure
    page.private.return_value = replace(
        page.selected,
        private=replace(
            page.selected.private,
            item=replace(page.selected.private.item, aggregate_version=99),
        ),
    )
    data = submitted(page, "working")
    response = call(page, "working", data)
    assert response.status_code == 409
    doc = parsed(response)
    assert doc.select_one('input[name="expected_version"]')["value"] == "7"
    assert (
        doc.select_one('input[name="idempotency_key"]')["value"]
        == data["idempotency_key"]
    )
    assert (
        doc.select_one('input[name="internal_title"]')["value"]
        == data["internal_title"]
    )
    assert "Version 99" in doc.get_text()
    assert "original version" in doc.get_text()
    assert doc.select_one('[role="alert"][autofocus]')


def test_validation_is_actionable_without_resetting_retry(page):
    page.writers["working"].side_effect = ValidationError(
        {"working_summary": "Control characters are not allowed."}
    )
    response = call(page, "working", submitted(page, "working"))
    assert response.status_code == 400
    assert "Control characters" in parsed(response).get_text()
    assert parsed(response).select_one('input[name="expected_version"]')["value"] == "7"


def test_revocation_after_refused_command_does_not_echo_private_input(page):
    def command(**_kwargs):
        page.auth.side_effect = ProgrammeAuthorizationDeniedError
        raise ProgrammeVersionConflictError

    page.writers["working"].side_effect = command
    response = call(page, "working", submitted(page, "working"))
    assert response.status_code == 404
    assert "Working summary" not in response.content.decode()


@pytest.mark.parametrize(
    "failure",
    [
        DatabaseError,
        ProgrammeQueryUnavailableError,
        ProgrammeTimetableInventoryLimitError,
    ],
)
def test_query_failure_is_unavailable_not_empty_or_partial(page, failure):
    page.listing.side_effect = failure
    response = call(page)
    assert response.status_code == 503
    assert "No Programme items yet" not in response.content.decode()
    assert "Opening ceremony" not in response.content.decode()


@pytest.mark.parametrize("failure", [DatabaseError, ProgrammeUnavailableError])
def test_command_unavailable_never_claims_success_or_returns_private_content(
    page, failure
):
    page.writers["working"].side_effect = failure
    response = call(page, "working", submitted(page, "working"))
    assert response.status_code == 503
    assert "Revised ceremony" not in response.content.decode()
    assert "Retry the same request" in response.content.decode()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "item_id", "authorizer", "unexpected"]
)
def test_unknown_fields_rejected_before_command(page, field):
    data = {**submitted(page, "working"), field: str(UUID(int=40))}
    assert call(page, "working", data).status_code == 400
    page.writers["working"].assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "expected_version",
        "idempotency_key",
        "reason",
        "internal_title",
        "csrfmiddlewaretoken",
    ],
)
def test_duplicate_values_rejected_before_command(page, field):
    data = QueryDict("", mutable=True)
    data.update(submitted(page, "working"))
    data.setlist(field, ["one", "two"])
    assert call(page, "working", data).status_code == 400
    page.writers["working"].assert_not_called()


def test_csrf_anonymous_methods_and_unsupported_selection(page):
    assert (
        call(page, "working", submitted(page, "working"), csrf=True).status_code == 403
    )
    assert call(page, anonymous=True).status_code == 302
    assert call(page, method="DELETE").status_code == 405
    assert call(page, "unknown").status_code == 400
    assert call(page, "working-history", submitted(page, "working")).status_code == 400
    assert call(page, query="?actor=other").status_code == 400
    for writer in page.writers.values():
        writer.assert_not_called()


def test_retired_and_closed_state_omit_private_edit_controls(page):
    page.private.return_value = replace(
        page.selected,
        private=replace(
            page.selected.private,
            item=replace(page.selected.private.item, lifecycle="retired"),
        ),
    )
    assert not parsed(call(page, "working")).select(
        ".programme-workbench form[method=post]"
    )
    page.auth.return_value = SimpleNamespace(accepts_private_planning_writes=False)
    assert not parsed(call(page)).select(".programme-workbench form[method=post]")


def test_text_escaping_and_single_labels_unique_ids(page):
    evil = '<script>alert("private")</script>'
    page.private.return_value = replace(
        page.selected,
        private=replace(
            page.selected.private, working=ProgrammeWorkingProjection(evil, evil, 7)
        ),
    )
    doc = parsed(call(page, "working"))
    assert not doc.find("script", string='alert("private")')
    assert evil in doc.get_text()
    ids = [element["id"] for element in doc.select("[id]")]
    assert len(ids) == len(set(ids))
    for control in doc.select(
        'form[method="post"] input:not([type="hidden"]), '
        'form[method="post"] textarea, form[method="post"] select'
    ):
        assert doc.find("label", attrs={"for": control["id"]})


@pytest.mark.parametrize(
    ("form_type", "extra"),
    [
        (
            ProgrammeCoreForm,
            {"kind": "accepted_proposal", "internal_title": "Invalid conversion"},
        ),
        (ProgrammeWorkingForm, {"internal_title": "x" * 241}),
        (ProgrammeDeliveryForm, {"technical_requirements": "x" * 5001}),
        (ProgrammeReadinessForm, {"concern": "attendance", "disposition": "satisfied"}),
        (
            ProgrammePublicCopyForm,
            {"source_working_revision_id": "not-a-uuid", "public_title": "Public"},
        ),
    ],
)
def test_closed_form_bounds_and_no_source_fabrication(form_type, extra):
    form = form_type(
        {
            "expected_version": "0",
            "idempotency_key": str(UUID(int=90)),
            "reason": "Reason",
            **extra,
        }
    )
    assert not form.is_valid()


def test_reserved_routes_resolve_only_in_dormant_urlconf(page):
    url = (
        f"/admin/programme/items/{page.organization}/{page.edition}/"
        f"{page.item_id}/working/"
    )
    assert (
        resolve(url, urlconf="maru.programme.workbench_urls").func
        is views.programme_item
    )
    assert resolve(url).func is not views.programme_item
    assert resolve(url).url_name != "programme-item"


@pytest.mark.parametrize(
    ("task", "reader", "specific"),
    [
        ("working-history", "list_programme_working_history", "Retained working title"),
        (
            "delivery-history",
            "list_programme_delivery_history",
            "Retained technical cue",
        ),
        (
            "readiness-history",
            "list_programme_readiness_history",
            "Retained evidence note",
        ),
        (
            "public-copy-history",
            "list_programme_public_copy_review_history",
            "Retained public title",
        ),
    ],
)
def test_history_renders_only_its_explicit_retained_fields(
    page, task, reader, specific
):
    entry = SimpleNamespace(
        internal_title="Retained working title",
        working_summary="Retained working prose",
        technical_requirements="Retained technical cue",
        accessibility_delivery="Retained access cue",
        media_consent_notes="Retained media cue",
        concern="public_copy",
        kind="evidence",
        disposition=None,
        state="blocked",
        note="Retained evidence note",
        requirement_version=2,
        dependency_version=3,
        rendition_number=1,
        public_title="Retained public title",
        public_summary="Retained public prose",
        public_content_note="Retained content note",
        withdrawn_at="Synthetic withdrawal time",
        withdrawal_reason="Retained withdrawal rationale",
        reason="Retained decision reason",
        actor_id=UUID(int=40),
        occurred_at="Synthetic source time",
        private_unknown_field="Never render unknown fields",
    )
    page.readers[reader].return_value = (entry,)
    response = call(page, task)
    text = parsed(response).get_text()
    assert response.status_code == 200
    assert specific in text
    assert "Retained decision reason" in text
    assert "Never render unknown fields" not in text
    if task != "public-copy-history":
        assert "Retained public title" not in text
    else:
        assert "Withdrawn" in text
        assert "Retained withdrawal rationale" in text
    if task != "delivery-history":
        assert "Retained technical cue" not in text


def test_final_core_form_order_leads_with_work_not_rationale(page):
    form = parsed(call(page)).select_one(".programme-workbench form")
    labels = [label.get_text() for label in form.select("label")]
    assert labels == ["Item type:", "Working title:", "Working summary:", "Reason:"]
