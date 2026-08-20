"""Browser, scope, and replay contracts for the Page 10 registration builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse
from django.utils.html import strip_tags

from maru.audit.models import AuditEvent
from maru.organizations.models import OrganizationMembership
from maru.participation.models import Participation
from maru.registration.models import (
    MinorRegistrationPolicy,
    Registration,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupOrigin,
)
from maru.registration.setup_content import configuration_content_digest
from maru.workforce.models import PositionAssignment
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationQuestionFactory,
)

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _administrator() -> Account:
    return AccountFactory(
        email=f"page10-registration-{uuid4()}@example.invalid",
        display_name="Synthetic Platform Registration Operator",
        is_staff=True,
        is_superuser=True,
    )


def _client(account: Account, *, csrf: bool = False) -> Client:
    client = Client(enforce_csrf_checks=csrf)
    client.force_login(account)
    return client


def _grant(account: Account, edition: EventEdition) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        capability_code="registration.manage_configuration",
    )


def _url(
    name: str,
    edition: EventEdition,
    configuration: RegistrationConfiguration | UUID | None = None,
    section: RegistrationSection | UUID | None = None,
) -> str:
    args: list[object] = [
        edition.organization.slug,
        edition.series.slug,
        edition.slug,
    ]
    if configuration is not None:
        args.append(
            configuration.id
            if isinstance(configuration, RegistrationConfiguration)
            else configuration
        )
    if section is not None:
        args.append(section.id if isinstance(section, RegistrationSection) else section)
    return reverse(name, args=args)


def _assert_private_no_store(response: Any) -> None:
    directives = {
        directive.strip().casefold()
        for directive in response.headers.get("Cache-Control", "").split(",")
    }
    assert {"private", "no-store"}.issubset(directives)


def _form_value(form: Any, field_name: str) -> str:
    value = form[field_name].value()
    return "" if value is None else str(value)


def _valid_start_data(response: Any, **overrides: str) -> dict[str, str]:
    form = response.context["form"]
    data = {
        "source_kind": RegistrationSetupOrigin.BLANK,
        "source_id": "",
        "name": _form_value(form, "name"),
        "opens_at": _form_value(form, "opens_at"),
        "closes_at": _form_value(form, "closes_at"),
        "capacity": _form_value(form, "capacity"),
        "currency": _form_value(form, "currency"),
        "minimum_age": _form_value(form, "minimum_age"),
        "default_payment_window_minutes": _form_value(
            form,
            "default_payment_window_minutes",
        ),
        "waitlist_enabled": _form_value(form, "waitlist_enabled"),
        "automatic_waitlist_promotion": _form_value(
            form,
            "automatic_waitlist_promotion",
        ),
        "expected_version": _form_value(form, "expected_version"),
        "reason": "Start the synthetic edition registration workspace.",
        "retry_key": _form_value(form, "retry_key"),
    }
    data.update(overrides)
    return data


def _start_blank(
    *,
    client: Client,
    edition: EventEdition,
) -> tuple[RegistrationConfiguration, dict[str, str]]:
    page = client.get(_url("registration-setup-start", edition))
    assert page.status_code == 200
    data = _valid_start_data(page)
    response = client.post(_url("start-registration-setup", edition), data)
    assert response.status_code == 302
    configuration = RegistrationConfiguration.objects.get(edition=edition)
    assert response.headers["Location"] == _url(
        "registration-setup-configuration",
        edition,
        configuration,
    )
    return configuration, data


def _valid_section_create_data(response: Any, **overrides: str) -> dict[str, str]:
    form = response.context["form"]
    data = {
        "key": "profile",
        "title": "Profile",
        "description": "Attendee-facing profile details.",
        "after_section_id": _form_value(form, "after_section_id"),
        "expected_version": _form_value(form, "expected_version"),
        "reason": "Add a reviewed synthetic registration section.",
        "retry_key": _form_value(form, "retry_key"),
    }
    data.update(overrides)
    return data


def _create_section(
    *,
    client: Client,
    edition: EventEdition,
    configuration: RegistrationConfiguration,
    key: str,
    title: str,
    after_section_id: str | None = None,
) -> tuple[RegistrationSection, dict[str, str]]:
    page = client.get(_url("registration-setup-section-create", edition, configuration))
    assert page.status_code == 200
    overrides = {"key": key, "title": title}
    if after_section_id is not None:
        overrides["after_section_id"] = after_section_id
    data = _valid_section_create_data(page, **overrides)
    response = client.post(
        _url("create-registration-setup-section", edition, configuration),
        data,
    )
    assert response.status_code == 302
    assert response.headers["Location"] == _url(
        "registration-setup-configuration",
        edition,
        configuration,
    )
    return RegistrationSection.objects.get(configuration=configuration, key=key), data


def _synchronize_configuration_digest(
    configuration: RegistrationConfiguration,
) -> None:
    sections = tuple(configuration.sections.order_by("position", "key", "id"))
    questions = tuple(configuration.questions.order_by("position", "key", "id"))
    products = tuple(configuration.products.order_by("position", "code", "id"))
    policy = MinorRegistrationPolicy.objects.filter(configuration=configuration).first()
    digest = configuration_content_digest(
        name=configuration.name,
        schema_version=configuration.version,
        opens_at=configuration.opens_at,
        closes_at=configuration.closes_at,
        capacity=configuration.capacity,
        capacity_ceiling=configuration.capacity_ceiling,
        currency=configuration.currency,
        minimum_age=configuration.minimum_age,
        default_payment_window_minutes=configuration.default_payment_window_minutes,
        waitlist_enabled=configuration.waitlist_enabled,
        automatic_waitlist_promotion=configuration.automatic_waitlist_promotion,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=policy,
    )
    RegistrationConfiguration.objects.filter(pk=configuration.pk).update(
        content_digest=digest
    )
    configuration.refresh_from_db()


def test_configuration_detail_mounts_its_minor_policy_link() -> None:
    edition = EventEditionFactory()
    client = _client(_administrator())
    configuration, _start_data = _start_blank(client=client, edition=edition)

    detail_url = _url("registration-setup-configuration", edition, configuration)
    minor_policy_url = _url(
        "registration-setup-minor-policy",
        edition,
        configuration,
    )
    detail = client.get(detail_url)

    assert detail.status_code == 200
    assert minor_policy_url in detail.content.decode()
    assert client.get(minor_policy_url).status_code == 200


def test_registration_workspace_is_canonical_private_same_shell_navigation() -> None:
    edition = EventEditionFactory(name="Synthetic MaruCon Browser Edition")
    path = _url("registration-setup", edition)

    anonymous = Client().get(path)
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"] == f"{reverse('staff-login')}?next={path}"

    administrator = _administrator()
    response = _client(administrator).get(path)
    content = response.content.decode()

    assert response.status_code == 200
    _assert_private_no_store(response)
    assert 'data-page="registration-setup"' in content
    assert content.count('aria-current="page"') == 1
    assert "Convention work" in content
    assert "Specialist records" in content
    assert "Quick start" not in content
    assert "Not configured" in content
    assert "Choose a starting point" in content
    assert "Configuration does not create a registrant" in content
    assert "Registration" in content


def test_exact_methods_query_contract_and_name_free_fail_closed_states() -> None:
    edition = EventEditionFactory(name="Never Disclose Query Edition")
    administrator = _administrator()
    client = _client(administrator)
    audit_count = AuditEvent.objects.count()

    invalid = client.get(f"{_url('registration-setup', edition)}?preview=true")
    invalid_content = invalid.content.decode()
    assert invalid.status_code == 400
    _assert_private_no_store(invalid)
    assert "Invalid registration setup request" in invalid_content
    assert edition.name not in invalid_content
    assert edition.organization.name not in invalid_content
    assert AuditEvent.objects.count() == audit_count

    assert client.post(_url("registration-setup", edition), {}).status_code == 405
    assert client.get(_url("start-registration-setup", edition)).status_code == 405

    with patch(
        "maru.registration.setup_views.get_registration_setup_workspace",
        side_effect=DatabaseError("synthetic bounded projection failure"),
    ):
        unavailable = client.get(_url("registration-setup", edition))
    unavailable_content = unavailable.content.decode()
    assert unavailable.status_code == 503
    _assert_private_no_store(unavailable)
    assert "Registration setup unavailable" in unavailable_content
    assert edition.name not in unavailable_content
    assert edition.organization.name not in unavailable_content


def test_authorization_and_tenant_scope_precede_form_body_parsing() -> None:
    protected_edition = EventEditionFactory(name="Protected Registration Edition")
    foreign_edition = EventEditionFactory(name="Foreign Registration Edition")
    actor = AccountFactory(display_name="Exact Edition Registration Manager")
    _grant(actor, protected_edition)
    client = _client(actor)

    assert client.get(_url("registration-setup", protected_edition)).status_code == 200
    denied = client.get(_url("registration-setup", foreign_edition))
    assert denied.status_code == 403
    assert foreign_edition.name not in denied.content.decode()

    with patch(
        "maru.registration.setup_views.RegistrationSetupStartForm",
        side_effect=AssertionError("a denied request must not parse its body"),
    ) as form_class:
        denied_post = client.post(
            _url("start-registration-setup", foreign_edition),
            {"private-field": "never parse this"},
        )
    assert denied_post.status_code == 403
    form_class.assert_not_called()
    assert foreign_edition.name not in denied_post.content.decode()


def test_start_form_is_closed_accessible_csrf_protected_and_non_participating() -> None:
    edition = EventEditionFactory()
    administrator = _administrator()
    csrf_client = _client(administrator, csrf=True)
    path = _url("registration-setup-start", edition)
    page = csrf_client.get(path)
    form = page.context["form"]
    content = page.content.decode()

    assert page.status_code == 200
    _assert_private_no_store(page)
    for field_name in (
        "source_kind",
        "source_id",
        "name",
        "opens_at",
        "closes_at",
        "capacity",
        "currency",
        "minimum_age",
        "default_payment_window_minutes",
        "waitlist_enabled",
        "automatic_waitlist_promotion",
        "reason",
    ):
        bound = form[field_name]
        assert f'for="{bound.id_for_label}"' in content
        assert f'id="{bound.id_for_label}"' in content
        if bound.help_text:
            assert f'id="{bound.id_for_label}_helptext"' in content
            assert f'aria-describedby="{bound.id_for_label}_helptext"' in content

    data = _valid_start_data(page)
    missing_csrf = csrf_client.post(_url("start-registration-setup", edition), data)
    assert missing_csrf.status_code == 403
    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()

    data["csrfmiddlewaretoken"] = csrf_client.cookies["csrftoken"].value
    created = csrf_client.post(_url("start-registration-setup", edition), data)
    assert created.status_code == 302
    _assert_private_no_store(created)
    configuration = RegistrationConfiguration.objects.get(edition=edition)
    assert configuration.origin == RegistrationSetupOrigin.BLANK
    assert not OrganizationMembership.objects.filter(account=administrator).exists()
    assert not Participation.objects.filter(account=administrator).exists()
    assert not Registration.objects.filter(account=administrator).exists()
    assert not PositionAssignment.objects.filter(account=administrator).exists()


def test_start_rejects_unknown_or_unprojected_values_then_replays_exactly() -> None:
    edition = EventEditionFactory()
    administrator = _administrator()
    client = _client(administrator)
    page = client.get(_url("registration-setup-start", edition))
    data = _valid_start_data(page)

    unknown = client.post(
        _url("start-registration-setup", edition),
        {**data, "surprise_private_field": "must fail closed"},
    )
    assert unknown.status_code == 400
    _assert_private_no_store(unknown)
    assert unknown.context["form"]["retry_key"].value() == data["retry_key"]
    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()

    forged = client.post(
        _url("start-registration-setup", edition),
        {
            **data,
            "source_kind": RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
            "source_id": str(uuid4()),
        },
    )
    assert forged.status_code == 400
    assert not RegistrationConfiguration.objects.filter(edition=edition).exists()

    created = client.post(_url("start-registration-setup", edition), data)
    assert created.status_code == 302
    configuration = RegistrationConfiguration.objects.get(edition=edition)
    receipt_count = RegistrationSetupCommandReceipt.objects.filter(
        edition=edition
    ).count()

    replayed = client.post(_url("start-registration-setup", edition), data)
    assert replayed.status_code == 302
    assert replayed.headers["Location"] == _url(
        "registration-setup-configuration",
        edition,
        configuration,
    )
    assert RegistrationConfiguration.objects.filter(edition=edition).count() == 1
    assert (
        RegistrationSetupCommandReceipt.objects.filter(edition=edition).count()
        == receipt_count
    )

    changed_retry = client.post(
        _url("start-registration-setup", edition),
        {**data, "name": "A different payload under the same retry key"},
    )
    assert changed_retry.status_code == 409
    _assert_private_no_store(changed_retry)
    assert changed_retry.context["form"]["retry_key"].value() == data["retry_key"]
    assert changed_retry.context["form"]["expected_version"].value() == "0"
    assert "disabled" in changed_retry.content.decode()


def test_section_write_is_csrf_protected_and_rejects_unknown_fields() -> None:
    edition = EventEditionFactory()
    administrator = _administrator()
    configuration, _start_data = _start_blank(
        client=_client(administrator),
        edition=edition,
    )
    client = _client(administrator, csrf=True)
    page = client.get(_url("registration-setup-section-create", edition, configuration))
    data = _valid_section_create_data(page)
    path = _url("create-registration-setup-section", edition, configuration)

    missing_csrf = client.post(path, data)
    assert missing_csrf.status_code == 403
    assert not RegistrationSection.objects.filter(configuration=configuration).exists()

    csrf_token = client.cookies["csrftoken"].value
    unknown = client.post(
        path,
        {
            **data,
            "csrfmiddlewaretoken": csrf_token,
            "unreviewed_internal_value": "must fail closed",
        },
    )
    assert unknown.status_code == 400
    _assert_private_no_store(unknown)
    assert unknown.context["form"]["retry_key"].value() == data["retry_key"]
    assert not RegistrationSection.objects.filter(configuration=configuration).exists()

    created = client.post(path, {**data, "csrfmiddlewaretoken": csrf_token})
    assert created.status_code == 302
    _assert_private_no_store(created)
    assert RegistrationSection.objects.filter(
        configuration=configuration,
        key="profile",
    ).exists()


def test_builder_section_create_update_move_delete_and_exact_replay() -> None:
    edition = EventEditionFactory()
    administrator = _administrator()
    client = _client(administrator)
    configuration, _start_data = _start_blank(client=client, edition=edition)

    profile, profile_data = _create_section(
        client=client,
        edition=edition,
        configuration=configuration,
        key="profile",
        title="Profile",
    )
    replay = client.post(
        _url("create-registration-setup-section", edition, configuration),
        profile_data,
    )
    assert replay.status_code == 302
    assert RegistrationSection.objects.filter(configuration=configuration).count() == 1

    logistics, _logistics_data = _create_section(
        client=client,
        edition=edition,
        configuration=configuration,
        key="logistics",
        title="Logistics",
    )
    builder = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    assert builder.status_code == 200
    _assert_private_no_store(builder)
    editors = builder.context["section_editors"]
    assert [editor.section.key for editor in editors] == ["profile", "logistics"]
    visible = strip_tags(builder.content.decode())
    assert str(configuration.id) not in visible
    assert str(profile.id) not in visible
    assert str(logistics.id) not in visible

    profile_editor = next(
        editor for editor in editors if editor.section.id == profile.id
    )
    update_form = profile_editor.update_form
    updated = client.post(
        _url(
            "update-registration-setup-section",
            edition,
            configuration,
            profile,
        ),
        {
            "key": _form_value(update_form, "key"),
            "title": "Attendee profile",
            "description": _form_value(update_form, "description"),
            "expected_version": _form_value(update_form, "expected_version"),
            "reason": "Clarify the attendee-facing section title.",
            "retry_key": _form_value(update_form, "retry_key"),
        },
    )
    assert updated.status_code == 302
    profile.refresh_from_db()
    assert profile.title == "Attendee profile"

    builder = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    logistics_editor = next(
        editor
        for editor in builder.context["section_editors"]
        if editor.section.id == logistics.id
    )
    move_form = logistics_editor.move_form
    moved = client.post(
        _url(
            "move-registration-setup-section",
            edition,
            configuration,
            logistics,
        ),
        {
            "after_section_id": "",
            "expected_version": _form_value(move_form, "expected_version"),
            "reason": "Place logistics first for the synthetic workflow.",
            "retry_key": _form_value(move_form, "retry_key"),
        },
    )
    assert moved.status_code == 302
    assert list(
        RegistrationSection.objects.filter(configuration=configuration)
        .order_by("position", "id")
        .values_list("key", flat=True)
    ) == ["logistics", "profile"]

    builder = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    profile_editor = next(
        editor
        for editor in builder.context["section_editors"]
        if editor.section.id == profile.id
    )
    delete_form = profile_editor.delete_form
    removed = client.post(
        _url(
            "remove-registration-setup-section",
            edition,
            configuration,
            profile,
        ),
        {
            "expected_version": _form_value(delete_form, "expected_version"),
            "reason": "Remove the now-unused synthetic profile section.",
            "retry_key": _form_value(delete_form, "retry_key"),
        },
    )
    assert removed.status_code == 302
    assert not RegistrationSection.objects.filter(pk=profile.pk).exists()

    builder = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    remaining = builder.context["section_editors"][0]
    final_delete = remaining.delete_form
    final = client.post(
        _url(
            "remove-registration-setup-section",
            edition,
            configuration,
            logistics,
        ),
        {
            "expected_version": _form_value(final_delete, "expected_version"),
            "reason": "Confirm that zero custom sections remains valid.",
            "retry_key": _form_value(final_delete, "retry_key"),
        },
    )
    assert final.status_code == 302
    empty = client.get(_url("registration-setup-configuration", edition, configuration))
    assert empty.status_code == 200
    assert "Zero custom sections is valid" in empty.content.decode()


def test_stale_section_form_preserves_safe_values_and_requires_reload() -> None:
    edition = EventEditionFactory()
    client = _client(_administrator())
    configuration, _start_data = _start_blank(client=client, edition=edition)
    profile, _profile_data = _create_section(
        client=client,
        edition=edition,
        configuration=configuration,
        key="profile",
        title="Profile",
    )
    stale_page = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    stale_form = stale_page.context["section_editors"][0].update_form
    stale_data = {
        "key": _form_value(stale_form, "key"),
        "title": "Preserve this safe stale title",
        "description": _form_value(stale_form, "description"),
        "expected_version": _form_value(stale_form, "expected_version"),
        "reason": "Exercise optimistic concurrency in the browser.",
        "retry_key": _form_value(stale_form, "retry_key"),
    }
    _create_section(
        client=client,
        edition=edition,
        configuration=configuration,
        key="preferences",
        title="Preferences",
    )

    stale = client.post(
        _url(
            "update-registration-setup-section",
            edition,
            configuration,
            profile,
        ),
        stale_data,
    )
    assert stale.status_code == 409
    _assert_private_no_store(stale)
    content = stale.content.decode()
    assert "reload the latest builder" in content.casefold()
    assert "Preserve this safe stale title" in content
    assert 'disabled aria-disabled="true"' in content
    active = next(
        editor
        for editor in stale.context["section_editors"]
        if editor.section.id == profile.id
    )
    assert active.update_form["retry_key"].value() == stale_data["retry_key"]
    assert (
        active.update_form["expected_version"].value() == stale_data["expected_version"]
    )
    profile.refresh_from_db()
    assert profile.title == "Profile"


def test_foreign_configuration_and_referenced_section_fail_without_disclosure() -> None:
    administrator = _administrator()
    client = _client(administrator)
    edition = EventEditionFactory(name="Visible Exact Edition")
    foreign_edition = EventEditionFactory(name="Hidden Foreign Edition")
    configuration, _start_data = _start_blank(client=client, edition=edition)
    foreign_configuration, _foreign_data = _start_blank(
        client=client,
        edition=foreign_edition,
    )

    mismatch = client.get(
        _url(
            "registration-setup-configuration",
            edition,
            foreign_configuration,
        )
    )
    assert mismatch.status_code == 404
    mismatch_content = mismatch.content.decode()
    assert foreign_edition.name not in mismatch_content
    assert foreign_configuration.name not in mismatch_content

    section, _section_data = _create_section(
        client=client,
        edition=edition,
        configuration=configuration,
        key="profile",
        title="Protected profile section",
    )
    RegistrationQuestionFactory(
        configuration=configuration,
        section=section,
        created_in_setup_version=2,
        last_changed_in_setup_version=2,
    )
    _synchronize_configuration_digest(configuration)
    builder = client.get(
        _url("registration-setup-configuration", edition, configuration)
    )
    editor = builder.context["section_editors"][0]
    delete_form = editor.delete_form
    protected = client.post(
        _url(
            "remove-registration-setup-section",
            edition,
            configuration,
            section,
        ),
        {
            "expected_version": _form_value(delete_form, "expected_version"),
            "reason": "Attempt a non-cascading protected removal.",
            "retry_key": _form_value(delete_form, "retry_key"),
        },
    )
    assert protected.status_code == 409
    protected_content = protected.content.decode()
    assert "still referenced by a registration question" in protected_content
    assert RegistrationSection.objects.filter(pk=section.pk).exists()
    assert RegistrationQuestion.objects.filter(section=section).exists()
