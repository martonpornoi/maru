"""Focused vertical coverage for edition catalog products and attendee orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import Client, override_settings
from django.urls import include, path, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.catalog import services as catalog_services
from maru.catalog.models import (
    CatalogCommandReceipt,
    CatalogOrder,
    CatalogPaymentEvent,
    CatalogPaymentIntent,
    CatalogProduct,
    CatalogStockAdjustment,
    CatalogVariant,
    EditionCatalog,
)
from maru.catalog.services import (
    OrderLineRequest,
    activate_catalog,
    add_product,
    add_variant,
    adjust_stock,
    authorize_catalog_order_api_scope,
    available_catalogs_for_actor,
    available_stock,
    catalog_activity,
    complete_demo_payment,
    create_catalog,
    place_order,
)
from maru.charities.bindings import ensure_charity_selection_binding
from maru.charities.models import CharityPartner, CharitySelection
from maru.charities.writer_boundary import charity_writer
from maru.effects.models import DomainEvent, OutboxMessage
from maru.registration.models import AdmissionProduct, Entitlement
from maru.urls import urlpatterns as platform_urlpatterns
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

urlpatterns = [path("", include("maru.catalog.urls")), *platform_urlpatterns]

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _CatalogWorld:
    edition: object
    administrator: object
    catalog: EditionCatalog
    product: CatalogProduct
    variant: CatalogVariant


def _active_catalog(
    *,
    stock: int = 5,
    ceiling: int = 10,
    edition=None,  # type: ignore[no-untyped-def]
) -> _CatalogWorld:
    edition = edition or EventEditionFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    create_catalog(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        currency="EUR",
        actor=administrator,
        reason="Open a reviewed edition commerce catalog.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    catalog = EditionCatalog.objects.get(edition=edition)
    product_result = add_product(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="Add convention-support merchandise.",
        code="con-shirt",
        kind=CatalogProduct.Kind.MERCHANDISE,
        name="Convention shirt",
        fulfilment_mode=CatalogProduct.Fulfilment.PICKUP,
        source_channel="test",
    )
    catalog.refresh_from_db()
    variant_result = add_variant(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product_result.target_id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="Publish the reviewed medium size and ceiling.",
        sku="shirt-m",
        name="Medium",
        price_minor=3_000,
        initial_stock=stock,
        stock_ceiling=ceiling,
        source_channel="test",
    )
    catalog.refresh_from_db()
    activate_catalog(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="The catalog and beneficiary policy were reviewed.",
        source_channel="test",
    )
    catalog.refresh_from_db()
    return _CatalogWorld(
        edition=edition,
        administrator=administrator,
        catalog=catalog,
        product=CatalogProduct.objects.get(id=product_result.target_id),
        variant=CatalogVariant.objects.get(id=variant_result.target_id),
    )


def _confirmed_charity(
    *,
    edition,
    actor,
    slug: str = "animal-care",
    legal_name: str = "Animal Care Association",
    public_name: str = "Animal Care",
    department_name: str = "Charity Commerce",
    department_code: str = "charity-commerce",
) -> CharitySelection:
    department = create_department_for_test(
        edition=edition,
        name=department_name,
        expected_code=department_code,
    )
    with charity_writer():
        partner = CharityPartner.objects.create(
            organization=edition.organization,
            slug=slug,
            legal_name=legal_name,
            public_name=public_name,
            lifecycle=CharityPartner.Lifecycle.ACTIVE,
            created_by=actor,
            last_modified_by=actor,
        )
    with transaction.atomic(), charity_writer():
        selection = CharitySelection.objects.create(
            organization=edition.organization,
            edition=edition,
            responsible_department=department,
            partner=partner,
            status=CharitySelection.Status.CONFIRMED,
            proposed_by=actor,
            submitted_at=timezone.now(),
            decided_at=timezone.now(),
        )
        ensure_charity_selection_binding(selection=selection)
    return selection


def test_catalog_order_api_preflight_requires_exact_owner_and_edition() -> None:
    world = _active_catalog()
    attendee = AccountFactory(display_name="Catalog order owner")
    placed = place_order(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        actor=attendee,
        lines=(OrderLineRequest(world.variant.id, 1),),
        expected_version=world.catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    authorize_catalog_order_api_scope(
        actor=attendee,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        order_id=placed.target_id,
    )
    with pytest.raises(AuthorizationDenied):
        authorize_catalog_order_api_scope(
            actor=AccountFactory(display_name="Different attendee"),
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            order_id=placed.target_id,
        )
    foreign_edition = EventEditionFactory()
    with pytest.raises(AuthorizationDenied):
        authorize_catalog_order_api_scope(
            actor=attendee,
            organization_id=foreign_edition.organization_id,
            edition_id=foreign_edition.id,
            order_id=placed.target_id,
        )


def test_charity_donation_order_and_demo_payment_are_distinct_from_admission() -> None:
    edition = EventEditionFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    selection = _confirmed_charity(edition=edition, actor=administrator)
    create_catalog(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        currency="EUR",
        actor=administrator,
        reason="Create the reviewed charity-support catalog.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    catalog = EditionCatalog.objects.get(edition=edition)
    product_result = add_product(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="Link a fixed donation option to the confirmed beneficiary.",
        code="animal-care-donation",
        kind=CatalogProduct.Kind.DONATION,
        name="Support Animal Care",
        beneficiary=CatalogProduct.Beneficiary.CHARITY,
        charity_selection_id=selection.id,
        fulfilment_mode=CatalogProduct.Fulfilment.NONE,
        source_channel="test",
    )
    catalog.refresh_from_db()
    variant_result = add_variant(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product_result.target_id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="Offer the reviewed fixed donation amount.",
        sku="donation-10",
        name="Ten euro donation",
        price_minor=1_000,
        source_channel="test",
    )
    catalog.refresh_from_db()
    activate_catalog(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=administrator,
        expected_version=catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="The beneficiary and donation price were independently reviewed.",
        source_channel="test",
    )
    catalog.refresh_from_db()
    attendee = AccountFactory()
    order_key = uuid4()
    placed = place_order(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        lines=(OrderLineRequest(variant_result.target_id, 2),),
        expected_version=catalog.aggregate_version,
        idempotency_key=order_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    replay = place_order(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor=attendee,
        lines=(OrderLineRequest(variant_result.target_id, 2),),
        expected_version=catalog.aggregate_version,
        idempotency_key=order_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert replay.replayed is True
    assert replay.target_id == placed.target_id
    order = CatalogOrder.objects.get(id=placed.target_id)
    line = order.lines.get()
    assert order.total_minor == 2_000
    assert line.charity_selection_id_snapshot == selection.id
    assert line.beneficiary_snapshot == CatalogProduct.Beneficiary.CHARITY
    assert (
        available_stock(CatalogVariant.objects.get(id=variant_result.target_id)) is None
    )

    demo_key = uuid4()
    paid = complete_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        order_id=order.id,
        actor=attendee,
        expected_catalog_version=placed.resulting_version,
        expected_order_version=order.aggregate_version,
        idempotency_key=demo_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    paid_replay = complete_demo_payment(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        order_id=order.id,
        actor=attendee,
        expected_catalog_version=placed.resulting_version,
        expected_order_version=order.aggregate_version,
        idempotency_key=demo_key,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert paid_replay.replayed is True
    assert paid_replay.target_id == paid.target_id
    order.refresh_from_db()
    assert order.status == CatalogOrder.Status.PAID
    assert CatalogPaymentIntent.objects.get(order=order).amount_minor == 2_000
    assert CatalogPaymentEvent.objects.filter(intent__order=order).count() == 1
    assert not AdmissionProduct.objects.filter(configuration__edition=edition).exists()
    assert not Entitlement.objects.filter(registration__edition=edition).exists()
    assert (
        DomainEvent.objects.filter(
            event_name="catalog.order.changed.v1", aggregate_id=order.id
        ).count()
        == 3
    )
    assert (
        OutboxMessage.objects.filter(
            event__aggregate_id=order.id,
            event__event_name="catalog.order.changed.v1",
        ).count()
        == 3
    )
    assert (
        AuditEvent.objects.filter(
            operation__in=(
                "catalog.order.place",
                "catalog.payment.create",
                "catalog.payment.reconcile",
            ),
            target_id__in=(
                order.id,
                CatalogPaymentIntent.objects.get(order=order).id,
            ),
        ).count()
        == 3
    )


def test_stock_adjustments_are_append_only_ceiling_bounded_and_tenant_scoped() -> None:
    world = _active_catalog(stock=5, ceiling=8)
    first_key = uuid4()
    adjusted = adjust_stock(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        variant_id=world.variant.id,
        new_stock=8,
        actor=world.administrator,
        expected_version=world.catalog.aggregate_version,
        idempotency_key=first_key,
        correlation_id=uuid4(),
        reason="The supplier confirmed three additional reviewed units.",
        source_channel="test",
    )
    replay = adjust_stock(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        variant_id=world.variant.id,
        new_stock=8,
        actor=world.administrator,
        expected_version=world.catalog.aggregate_version,
        idempotency_key=first_key,
        correlation_id=uuid4(),
        reason="The supplier confirmed three additional reviewed units.",
        source_channel="test",
    )
    assert replay.replayed is True
    assert CatalogStockAdjustment.objects.count() == 1
    world.catalog.refresh_from_db()
    with pytest.raises(ValidationError, match="hard ceiling"):
        adjust_stock(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            variant_id=world.variant.id,
            new_stock=9,
            actor=world.administrator,
            expected_version=world.catalog.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            reason="Attempt beyond the configured ceiling.",
            source_channel="test",
        )
    attendee = AccountFactory()
    placed = place_order(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        actor=attendee,
        lines=(OrderLineRequest(world.variant.id, 2),),
        expected_version=world.catalog.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    world.catalog.refresh_from_db()
    with pytest.raises(ValidationError, match="commitments"):
        adjust_stock(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            variant_id=world.variant.id,
            new_stock=1,
            actor=world.administrator,
            expected_version=world.catalog.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            reason="Invalid attempt below reserved commitments.",
            source_channel="test",
        )
    assert available_stock(world.variant) == 6
    with pytest.raises(DatabaseError):
        CatalogStockAdjustment.objects.filter(id=adjusted.target_id).update(new_stock=7)
    with pytest.raises(DatabaseError):
        CatalogProduct.objects.filter(id=world.product.id).update(name="Mutated")
    world.product.refresh_from_db()
    assert world.product.name == "Convention shirt"

    activity = catalog_activity(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        actor=world.administrator,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert any(item.action == "Adjusted governed catalog stock" for item in activity)
    foreign = _active_catalog()
    with pytest.raises(CatalogVariant.DoesNotExist):
        adjust_stock(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            variant_id=foreign.variant.id,
            new_stock=5,
            actor=world.administrator,
            expected_version=world.catalog.aggregate_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            reason="Foreign-scope attempt.",
            source_channel="test",
        )
    assert CatalogOrder.objects.filter(id=placed.target_id).exists()


@override_settings(ROOT_URLCONF=__name__)
def test_attendee_and_staff_catalog_pages_are_owned_and_closed() -> None:  # noqa: PLR0915
    world = _active_catalog(stock=6, ceiling=8)
    attendee = AccountFactory()
    client = Client()
    client.force_login(attendee)
    index = client.get(reverse("my-catalog-index"))
    assert index.status_code == 200
    assert b"Shop &amp; orders" in index.content
    assert world.edition.name.encode() in index.content
    assert index.content.count(b'id="nav-sidebar"') == 1
    assert index.content.count(b'id="nav-filter"') == 1
    assert index.content.count(b'value="my.registrations"') == 1
    assert b"Catalog commerce" not in index.content
    assert "no-store" in index.headers["Cache-Control"]
    catalog_url = reverse("my-catalog", args=(world.edition.id,))
    page = client.get(catalog_url)
    assert page.status_code == 200
    assert "no-store" in page.headers["Cache-Control"]
    assert b"Merchandise, donations, and supporter products" in page.content
    assert b"Convention shirt" in page.content
    item = page.context["product_cards"][0]["variants"][0]
    form = item["form"]
    command = {
        "variant_id": form["variant_id"].value(),
        "quantity": "2",
        "expected_version": form["expected_version"].value(),
        "idempotency_key": form["idempotency_key"].value(),
    }
    order_url = reverse("my-catalog-order", args=(world.edition.id,))
    rejected = client.post(order_url, {**command, "admission_product_id": uuid4()})
    assert rejected.status_code == 302
    assert not CatalogOrder.objects.filter(account=attendee).exists()
    accepted = client.post(order_url, command)
    assert accepted.status_code == 302
    order = CatalogOrder.objects.get(account=attendee)
    assert accepted.url == reverse(
        "my-catalog-checkout", args=(world.edition.id, order.id)
    )
    checkout = client.get(accepted.url)
    assert checkout.status_code == 200
    assert "no-store" in checkout.headers["Cache-Control"]
    assert order.reference.encode() in checkout.content
    payment_form = checkout.context["payment_form"]
    demo_command = {
        "expected_catalog_version": payment_form["expected_catalog_version"].value(),
        "expected_order_version": payment_form["expected_order_version"].value(),
        "idempotency_key": payment_form["idempotency_key"].value(),
    }
    demo_url = reverse("my-catalog-demo-payment", args=(world.edition.id, order.id))
    assert client.post(demo_url, demo_command).status_code == 302
    order.refresh_from_db()
    assert order.status == CatalogOrder.Status.PAID
    history = client.get(reverse("my-catalog-orders", args=(world.edition.id,)))
    assert history.status_code == 200
    assert "no-store" in history.headers["Cache-Control"]
    assert order.reference.encode() in history.content

    outsider = AccountFactory()
    client.force_login(outsider)
    assert (
        client.get(
            reverse("my-catalog-checkout", args=(world.edition.id, order.id))
        ).status_code
        == 404
    )
    staff_location = reverse(
        "catalog-staff-workspace",
        args=(
            world.edition.organization.slug,
            world.edition.series.slug,
            world.edition.slug,
        ),
    )
    assert client.get(staff_location).status_code in {302, 404}
    client.force_login(world.administrator)
    staff_page = client.get(staff_location)
    assert staff_page.status_code == 200
    assert "no-store" in staff_page.headers["Cache-Control"]
    assert b"Purpose-scoped activity" in staff_page.content
    assert staff_page.content.count(b'id="nav-sidebar"') == 1
    assert staff_page.content.count(b'id="nav-filter"') == 1
    stock_item = staff_page.context["variants"][0]
    stock_form = stock_item["form"]
    stock_command = {
        "variant_id": stock_form["variant_id"].value(),
        "expected_version": stock_form["expected_version"].value(),
        "new_stock": "7",
        "reason": "The supplier delivered one additional checked unit.",
        "idempotency_key": stock_form["idempotency_key"].value(),
    }
    stock_url = reverse(
        "catalog-stock-adjust-page",
        args=(
            world.edition.organization.slug,
            world.edition.series.slug,
            world.edition.slug,
            world.variant.id,
        ),
    )
    assert (
        client.post(
            stock_url, {**stock_command, "selected_person_id": uuid4()}
        ).status_code
        == 302
    )
    assert not CatalogStockAdjustment.objects.exists()
    assert client.post(stock_url, stock_command).status_code == 302
    assert CatalogStockAdjustment.objects.get().new_stock == 7

    api = APIClient()
    api.force_authenticate(user=attendee)
    api_url = reverse(
        "catalog-api-orders",
        args=(world.edition.organization_id, world.edition.id),
    )
    world.catalog.refresh_from_db()
    api_response = api.post(
        api_url,
        {
            "expected_version": world.catalog.aggregate_version,
            "lines": [{"variant_id": world.variant.id, "quantity": 1}],
            "admission_tier": "forbidden",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert api_response.status_code == 400
    assert CatalogOrder.objects.filter(account=attendee).count() == 1


@override_settings(ROOT_URLCONF=__name__)
def test_retained_checkout_routes_require_exact_catalog_profile() -> None:
    """Deny retained checkout reads and payments before loading the order."""
    edition = EventEditionFactory(
        name="Hidden Catalog Edition",
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    creator = AccountFactory(display_name="Retained catalog creator")
    owner = AccountFactory(display_name="Retained catalog owner")
    catalog = EditionCatalog.objects.create(
        organization=edition.organization,
        edition=edition,
        status=EditionCatalog.Status.ACTIVE,
        currency="EUR",
        created_by=creator,
    )
    order = CatalogOrder.objects.create(
        catalog=catalog,
        organization=edition.organization,
        edition=edition,
        account=owner,
        reference="HIDDEN-CATALOG-ORDER",
        status=CatalogOrder.Status.PAYMENT_PENDING,
        currency="EUR",
        total_minor=3_000,
        payment_due_at=timezone.now() + timedelta(days=1),
    )
    client = Client()
    client.force_login(owner)
    checkout_url = reverse("my-catalog-checkout", args=(edition.id, order.id))
    before = {
        "receipts": CatalogCommandReceipt.objects.count(),
        "intents": CatalogPaymentIntent.objects.count(),
        "events": CatalogPaymentEvent.objects.count(),
        "audits": AuditEvent.objects.count(),
        "domain_events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    }

    index = client.get(reverse("my-catalog-index"))
    responses = (
        client.get(reverse("my-catalog", args=(edition.id,))),
        client.post(reverse("my-catalog-order", args=(edition.id,)), {}),
        client.get(reverse("my-catalog-orders", args=(edition.id,))),
        client.get(checkout_url),
        client.post(
            reverse("my-catalog-hosted-payment", args=(edition.id, order.id)),
            {},
        ),
        client.post(
            reverse("my-catalog-demo-payment", args=(edition.id, order.id)),
            {},
        ),
    )

    assert index.status_code == 200
    assert index.context["catalogs"] == ()
    assert {response.status_code for response in responses} == {404}
    rendered = b"".join((index.content, *(response.content for response in responses)))
    assert b"Hidden Catalog Edition" not in rendered
    assert b"HIDDEN-CATALOG-ORDER" not in rendered
    order.refresh_from_db()
    assert order.status == CatalogOrder.Status.PAYMENT_PENDING
    assert order.aggregate_version == 1
    assert {
        "receipts": CatalogCommandReceipt.objects.count(),
        "intents": CatalogPaymentIntent.objects.count(),
        "events": CatalogPaymentEvent.objects.count(),
        "audits": AuditEvent.objects.count(),
        "domain_events": DomainEvent.objects.count(),
        "outbox": OutboxMessage.objects.count(),
    } == before


@override_settings(ROOT_URLCONF=__name__)
def test_staff_can_configure_and_activate_catalog_through_closed_html() -> None:  # noqa: PLR0915
    edition = EventEditionFactory(time_zone="Europe/Budapest")
    foreign_edition = EventEditionFactory(time_zone="Europe/Budapest")
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    selection = _confirmed_charity(edition=edition, actor=administrator)
    foreign_selection = _confirmed_charity(
        edition=foreign_edition,
        actor=administrator,
        slug="foreign-charity",
        legal_name="Foreign Restricted Legal Name",
        public_name="Foreign Public Charity",
        department_name="Foreign Charity Commerce",
        department_code="foreign-charity-commerce",
    )
    client = Client()
    client.force_login(administrator)
    staff_args = (
        edition.organization.slug,
        edition.series.slug,
        edition.slug,
    )
    staff_url = reverse("catalog-staff-workspace", args=staff_args)
    page = client.get(staff_url)
    assert page.status_code == 200
    assert "no-store" in page.headers["Cache-Control"]
    assert page.content.count(b'id="nav-sidebar"') == 1
    create_form = page.context["catalog_create_form"]
    create_command = {
        "currency": "EUR",
        "reason": "Open the reviewed edition commerce catalog.",
        "idempotency_key": create_form["idempotency_key"].value(),
    }
    create_url = reverse("catalog-create-page", args=staff_args)
    rejected_create = client.post(
        create_url,
        {**create_command, "tenant_id": uuid4()},
    )
    assert rejected_create.status_code == 302
    assert not EditionCatalog.objects.filter(edition=edition).exists()
    assert client.post(create_url, create_command).status_code == 302
    assert client.post(create_url, create_command).status_code == 302
    catalog = EditionCatalog.objects.get(edition=edition)
    assert catalog.aggregate_version == 1

    page = client.get(staff_url)
    assert b"Convention merchandise" in page.content
    assert b"Donation" in page.content
    assert b"Limited supporter product" in page.content
    assert b"Animal Care" in page.content
    assert b"Animal Care Association" not in page.content
    assert b"Foreign Public Charity" not in page.content
    product_form = page.context["product_form"]
    product_command = {
        "expected_version": product_form["expected_version"].value(),
        "idempotency_key": product_form["idempotency_key"].value(),
        "reason": "Offer one fixed donation for the confirmed edition charity.",
        "code": "animal-care-donation",
        "kind": CatalogProduct.Kind.DONATION,
        "name": "Support Animal Care",
        "description": "A stockless fixed donation option.",
        "beneficiary": CatalogProduct.Beneficiary.CHARITY,
        "charity_selection_id": str(selection.id),
        "sale_opens_at": "2027-01-15T10:00",
        "sale_closes_at": "2027-01-15T18:00",
        "fulfilment_mode": CatalogProduct.Fulfilment.NONE,
        "per_order_limit": "5",
    }
    product_url = reverse("catalog-product-add-page", args=staff_args)
    assert (
        client.post(
            product_url,
            {**product_command, "charity_selection_id": str(foreign_selection.id)},
        ).status_code
        == 302
    )
    assert not CatalogProduct.objects.filter(catalog=catalog).exists()
    assert client.post(product_url, product_command).status_code == 302
    assert client.post(product_url, product_command).status_code == 302
    product = CatalogProduct.objects.get(catalog=catalog)
    assert product.charity_selection_id == selection.id
    assert product.sale_opens_at.tzinfo is not None
    catalog.refresh_from_db()
    assert catalog.aggregate_version == 2
    assert (
        client.post(
            product_url,
            {
                **product_command,
                "expected_version": str(catalog.aggregate_version),
                "code": "reused-key",
            },
        ).status_code
        == 302
    )
    assert CatalogProduct.objects.filter(catalog=catalog).count() == 1

    page = client.get(staff_url)
    variant_form = page.context["product_cards"][0]["variant_form"]
    variant_command = {
        "expected_version": variant_form["expected_version"].value(),
        "idempotency_key": variant_form["idempotency_key"].value(),
        "reason": "Offer the reviewed fixed donation amount.",
        "sku": "donation-10",
        "name": "Ten euro donation",
        "price_minor": "1000",
        "initial_stock": "",
        "stock_ceiling": "",
    }
    variant_url = reverse("catalog-variant-add-page", args=(*staff_args, product.id))
    stale_variant = client.post(
        variant_url,
        {**variant_command, "expected_version": "1"},
    )
    assert stale_variant.status_code == 302
    assert not CatalogVariant.objects.filter(product=product).exists()
    assert client.post(variant_url, variant_command).status_code == 302
    assert client.post(variant_url, variant_command).status_code == 302
    assert CatalogVariant.objects.filter(product=product).count() == 1
    catalog.refresh_from_db()
    assert catalog.aggregate_version == 3

    page = client.get(staff_url)
    activation_form = page.context["activation_form"]
    activation_command = {
        "expected_version": activation_form["expected_version"].value(),
        "idempotency_key": activation_form["idempotency_key"].value(),
        "reason": "The beneficiary, sale window, and price were reviewed.",
    }
    activation_url = reverse("catalog-activate-page", args=staff_args)
    assert client.post(activation_url, activation_command).status_code == 302
    assert client.post(activation_url, activation_command).status_code == 302
    catalog.refresh_from_db()
    product.refresh_from_db()
    assert catalog.status == EditionCatalog.Status.ACTIVE
    assert product.status == CatalogProduct.Status.ACTIVE
    assert CatalogCommandReceipt.objects.filter(catalog=catalog).count() == 4

    post_activation_product = {
        **product_command,
        "expected_version": str(catalog.aggregate_version),
        "idempotency_key": str(uuid4()),
        "code": "late-product",
        "beneficiary": CatalogProduct.Beneficiary.CONVENTION,
        "charity_selection_id": "",
        "fulfilment_mode": CatalogProduct.Fulfilment.NONE,
    }
    assert client.post(product_url, post_activation_product).status_code == 302
    assert CatalogProduct.objects.filter(catalog=catalog).count() == 1

    foreign_variant_url = reverse(
        "catalog-variant-add-page",
        args=(
            foreign_edition.organization.slug,
            foreign_edition.series.slug,
            foreign_edition.slug,
            product.id,
        ),
    )
    foreign_variant = client.post(
        foreign_variant_url,
        {"unknown": "before-parse"},
    )
    assert foreign_variant.status_code == 404
    attendee = AccountFactory()
    client.force_login(attendee)
    unauthorized = client.post(create_url, {"unknown": "before-authorization"})
    assert unauthorized.status_code == 404


@override_settings(ROOT_URLCONF=__name__)
def test_catalog_index_authorizes_scope_ids_before_bounded_labels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    foreign = _active_catalog(edition=EventEditionFactory(name="AAA Foreign Catalog"))
    allowed = _active_catalog(
        edition=EventEditionFactory(name="ZZZ Authorized Catalog")
    )
    attendee = AccountFactory()

    def authorize_exact_allowed_scope(*, actor, capability_code, target):  # type: ignore[no-untyped-def]
        del actor, capability_code
        if target is not None and target.edition_id == allowed.edition.id:
            return frozenset()
        raise AuthorizationDenied(
            "Foreign catalog unavailable.",
            reason_code="foreign_scope",
        )

    monkeypatch.setattr(catalog_services, "_authorize", authorize_exact_allowed_scope)
    visible = available_catalogs_for_actor(actor=attendee, limit=1)
    assert [catalog.id for catalog in visible] == [allowed.catalog.id]
    client = Client()
    client.force_login(attendee)
    response = client.get(reverse("my-catalog-index"))
    assert response.status_code == 200
    assert allowed.edition.name.encode() in response.content
    assert foreign.edition.name.encode() not in response.content
    assert "no-store" in response.headers["Cache-Control"]


def test_catalog_command_evidence_and_schema_remain_separate() -> None:
    world = _active_catalog()
    assert CatalogCommandReceipt.objects.filter(catalog=world.catalog).count() == 4
    catalog_fields = {field.name for field in CatalogProduct._meta.get_fields()}
    line_fields = {
        field.name for field in world.variant.order_lines.model._meta.get_fields()
    }
    assert "admission_product" not in catalog_fields
    assert "registration" not in line_fields
