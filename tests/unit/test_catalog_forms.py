"""Closed browser-boundary checks for catalog definition forms."""

from uuid import uuid4

from maru.catalog.forms import CatalogProductAddForm, CatalogVariantAddForm
from maru.catalog.models import CatalogProduct
from maru.charities.models import CharitySelection


def _product_data(**overrides: str) -> dict[str, str]:
    data = {
        "expected_version": "1",
        "idempotency_key": str(uuid4()),
        "reason": "Configure one reviewed convention product.",
        "code": "con-shirt",
        "kind": CatalogProduct.Kind.MERCHANDISE,
        "name": "Convention shirt",
        "description": "",
        "beneficiary": CatalogProduct.Beneficiary.CONVENTION,
        "charity_selection_id": "",
        "sale_opens_at": "",
        "sale_closes_at": "",
        "fulfilment_mode": CatalogProduct.Fulfilment.PICKUP,
        "per_order_limit": "10",
    }
    data.update(overrides)
    return data


def test_catalog_sale_window_rejects_whitespace_and_ambiguous_local_time() -> None:
    selections = CharitySelection.objects.none()
    whitespace = CatalogProductAddForm(
        _product_data(sale_opens_at=" 2027-01-15T10:00"),
        edition_time_zone="Europe/Budapest",
        charity_selections=selections,
    )
    assert whitespace.is_valid() is False
    assert "sale_opens_at" in whitespace.errors

    ambiguous = CatalogProductAddForm(
        _product_data(sale_opens_at="2026-10-25T02:30"),
        edition_time_zone="Europe/Budapest",
        charity_selections=selections,
    )
    assert ambiguous.is_valid() is False
    assert "sale_opens_at" in ambiguous.errors


def test_catalog_product_and_variant_policy_shapes_fail_closed() -> None:
    donation = CatalogProductAddForm(
        _product_data(
            kind=CatalogProduct.Kind.DONATION,
            fulfilment_mode=CatalogProduct.Fulfilment.PICKUP,
        ),
        edition_time_zone="UTC",
        charity_selections=CharitySelection.objects.none(),
    )
    assert donation.is_valid() is False
    assert "kind" in donation.errors

    supporter_variant = CatalogVariantAddForm(
        {
            "expected_version": "1",
            "idempotency_key": str(uuid4()),
            "reason": "Configure a genuinely finite early supporter offer.",
            "sku": "supporter-one",
            "name": "First supporter",
            "price_minor": "10000",
            "initial_stock": "",
            "stock_ceiling": "",
        },
        product_kind=CatalogProduct.Kind.SUPPORTER,
    )
    assert supporter_variant.is_valid() is False
    assert "initial_stock" in supporter_variant.errors

    bounded_supporter = CatalogVariantAddForm(
        {
            "expected_version": "1",
            "idempotency_key": str(uuid4()),
            "reason": "Configure a genuinely finite early supporter offer.",
            "sku": "supporter-one",
            "name": "First supporter",
            "price_minor": "10000",
            "initial_stock": "10",
            "stock_ceiling": "9",
        },
        product_kind=CatalogProduct.Kind.SUPPORTER,
    )
    assert bounded_supporter.is_valid() is False
    assert "stock_ceiling" in bounded_supporter.errors
