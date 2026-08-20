"""Closed staff forms for logistics catalog and operational commands."""

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictBase10IntegerField

from .forms import (
    CanonicalLocalDateTimeField,
    CanonicalUUIDChoiceField,
    LogisticsStrictForm,
)
from .models import (
    MAX_LOGISTICS_REASON_LENGTH,
    Asset,
    AssetAgreement,
    EquipmentOffer,
    LogisticsEvent,
    LogisticsManifest,
    LogisticsNode,
    LogisticsParty,
    RestrictedLogisticsAddress,
)


def _datetime_field(*, required: bool = True) -> CanonicalLocalDateTimeField:
    return CanonicalLocalDateTimeField(required=required)


class CommandForm(LogisticsStrictForm):
    """Collect and validate command input."""

    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class OfferReviewForm(CommandForm):
    """Collect and validate offer review input."""

    offer_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    outcome = forms.ChoiceField(
        choices=(
            (
                EquipmentOffer.Status.ACCEPTED.value,
                EquipmentOffer.Status.ACCEPTED.label,
            ),
            (
                EquipmentOffer.Status.REJECTED.value,
                EquipmentOffer.Status.REJECTED.label,
            ),
        ),
        widget=forms.HiddenInput,
    )
    responsible_department_id = CanonicalUUIDChoiceField(required=False)


class PartyCreateForm(CommandForm):
    """Collect and validate party create input."""

    kind = forms.ChoiceField(choices=LogisticsParty.Kind.choices)
    role = forms.ChoiceField(choices=LogisticsParty.Role.choices)
    code = forms.SlugField(max_length=96)
    legal_name = forms.CharField(max_length=240)
    public_name = forms.CharField(max_length=200)
    provider_reference = forms.CharField(max_length=240, required=False)
    website_url = forms.URLField(
        max_length=2_000,
        required=False,
        assume_scheme="https",
    )


class RestrictedAddressCreateForm(CommandForm):
    """Collect and validate restricted address create input."""

    purpose = forms.ChoiceField(choices=RestrictedLogisticsAddress.Purpose.choices)
    subject_account_id = CanonicalUUIDChoiceField(required=False)
    party_id = CanonicalUUIDChoiceField(required=False)
    label = forms.CharField(max_length=200)
    recipient_name = forms.CharField(max_length=240, required=False)
    contact_email = forms.EmailField(required=False)
    contact_phone = forms.CharField(max_length=16, required=False)
    postal_address = forms.CharField(
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    access_instructions = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    retention_until = _datetime_field(required=False)


class NodeCreateForm(CommandForm):
    """Collect and validate node create input."""

    kind = forms.ChoiceField(choices=LogisticsNode.Kind.choices)
    code = forms.SlugField(max_length=96)
    name = forms.CharField(max_length=200)
    description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    edition_specific = forms.BooleanField(required=False, initial=True)
    storage_address_id = CanonicalUUIDChoiceField(required=False)
    external_owner_id = CanonicalUUIDChoiceField(required=False)
    provider_id = CanonicalUUIDChoiceField(required=False)
    vehicle_registration = forms.CharField(max_length=40, required=False)
    venue_space_selection_id = CanonicalUUIDChoiceField(required=False)
    capacity_note = forms.CharField(max_length=500, required=False)


class OwnedItemForm(CommandForm):
    """Collect and validate owned item input."""

    edition_specific = forms.BooleanField(required=False, initial=True)
    owner_kind = forms.ChoiceField(choices=Asset.OwnerKind.choices)
    owner_account_id = CanonicalUUIDChoiceField(required=False)
    owner_party_id = CanonicalUUIDChoiceField(required=False)
    catalog_code = forms.SlugField(max_length=96)
    name = forms.CharField(max_length=200)
    value_class = forms.CharField(max_length=32, required=False)


class AssetCreateForm(OwnedItemForm):
    """Collect and validate asset create input."""

    asset_type = forms.CharField(max_length=120)
    manufacturer = forms.CharField(max_length=160, required=False)
    model_name = forms.CharField(max_length=160, required=False)
    serial_number = forms.CharField(max_length=200, required=False)
    acquisition = forms.ChoiceField(choices=Asset.Acquisition.choices)


class StockLotCreateForm(OwnedItemForm):
    """Collect and validate stock lot create input."""

    stock_type = forms.CharField(max_length=120)
    unit = forms.CharField(max_length=40)
    initial_quantity = StrictBase10IntegerField(
        min_value=1,
        max_value=1_000_000_000,
    )


class PhysicalKeyCreateForm(CommandForm):
    """Collect and validate physical key create input."""

    edition_specific = forms.BooleanField(required=False, initial=True)
    code = forms.SlugField(max_length=96)
    label = forms.CharField(max_length=200)
    opens_node_id = CanonicalUUIDChoiceField()
    provider_id = CanonicalUUIDChoiceField(required=False)


class KeyholderAssignForm(CommandForm):
    """Collect and validate keyholder assign input."""

    key_id = CanonicalUUIDChoiceField()
    responsible_account_id = CanonicalUUIDChoiceField()
    starts_at = _datetime_field()
    ends_at = _datetime_field(required=False)
    expected_version = StrictBase10IntegerField(min_value=1)


class LabelCreateForm(CommandForm):
    """Collect and validate label create input."""

    subject_kind = forms.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    subject_id = CanonicalUUIDChoiceField()
    label_code = forms.CharField(max_length=96)
    qr_identifier = forms.CharField(
        min_length=24,
        max_length=512,
        widget=forms.PasswordInput(render_value=True),
    )


class AgreementCreateForm(CommandForm):
    """Collect and validate agreement create input."""

    kind = forms.ChoiceField(choices=AssetAgreement.Kind.choices)
    subject_kind = forms.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    subject_id = CanonicalUUIDChoiceField()
    provider_account_id = CanonicalUUIDChoiceField(required=False)
    provider_party_id = CanonicalUUIDChoiceField(required=False)
    borrower_account_id = CanonicalUUIDChoiceField(required=False)
    borrower_party_id = CanonicalUUIDChoiceField(required=False)
    starts_at = _datetime_field()
    ends_at = _datetime_field()
    return_due_at = _datetime_field()
    return_address_id = CanonicalUUIDChoiceField(required=False)
    provider_reference = forms.CharField(max_length=240, required=False)
    terms_reference = forms.CharField(max_length=1_000, required=False)


class KitCreateForm(CommandForm):
    """Collect and validate kit create input."""

    code = forms.SlugField(max_length=96)
    name = forms.CharField(max_length=200)
    description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    subject_kind = forms.ChoiceField(
        choices=(
            (
                LogisticsEvent.SubjectKind.ASSET.value,
                LogisticsEvent.SubjectKind.ASSET.label,
            ),
            (
                LogisticsEvent.SubjectKind.STOCK_LOT.value,
                LogisticsEvent.SubjectKind.STOCK_LOT.label,
            ),
            (
                LogisticsEvent.SubjectKind.KEY.value,
                LogisticsEvent.SubjectKind.KEY.label,
            ),
        )
    )
    subject_id = CanonicalUUIDChoiceField()
    quantity = StrictBase10IntegerField(min_value=1, max_value=1_000_000_000)
    notes = forms.CharField(max_length=500, required=False)


class ManifestCreateForm(CommandForm):
    """Collect and validate manifest create input."""

    responsible_department_id = CanonicalUUIDChoiceField()
    manifest_number = forms.CharField(max_length=96)
    kind = forms.ChoiceField(choices=LogisticsManifest.Kind.choices)
    title = forms.CharField(max_length=200)
    source_node_id = CanonicalUUIDChoiceField(required=False)
    destination_node_id = CanonicalUUIDChoiceField(required=False)
    vehicle_id = CanonicalUUIDChoiceField(required=False)
    provider_id = CanonicalUUIDChoiceField(required=False)
    loading_starts_at = _datetime_field(required=False)
    loading_ends_at = _datetime_field(required=False)
    line_subject_kind = forms.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    line_subject_id = CanonicalUUIDChoiceField()
    line_quantity = StrictBase10IntegerField(
        min_value=1,
        max_value=1_000_000_000,
    )
    line_packed_in_node_id = CanonicalUUIDChoiceField(required=False)
    line_notes = forms.CharField(max_length=500, required=False)


class ManifestStateForm(CommandForm):
    """Collect and validate manifest state input."""

    manifest_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    action = forms.ChoiceField(
        choices=(
            ("seal", "Seal"),
            ("complete", "Complete"),
            ("cancel_draft", "Cancel draft"),
            ("cancel_sealed", "Cancel sealed"),
        ),
        widget=forms.HiddenInput,
    )


class ManifestLineAddForm(CommandForm):
    """Collect and validate manifest line add input."""

    manifest_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    line_subject_kind = forms.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    line_subject_id = CanonicalUUIDChoiceField()
    line_quantity = StrictBase10IntegerField(
        min_value=1,
        max_value=1_000_000_000,
    )
    line_packed_in_node_id = CanonicalUUIDChoiceField(required=False)
    line_notes = forms.CharField(max_length=500, required=False)


class ManifestReceiptForm(CommandForm):
    """Collect and validate manifest receipt input."""

    expected_sequence = StrictBase10IntegerField(
        min_value=0,
        widget=forms.HiddenInput,
    )
    occurred_at = _datetime_field()
    condition_after = forms.CharField(max_length=120)


class MovementEventForm(CommandForm):
    """Collect and validate movement event input."""

    event_type = forms.ChoiceField(choices=LogisticsEvent.EventType.choices)
    subject_kind = forms.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    subject_id = CanonicalUUIDChoiceField()
    expected_sequence = StrictBase10IntegerField(min_value=0)
    occurred_at = _datetime_field()
    source_node_id = CanonicalUUIDChoiceField(required=False)
    destination_node_id = CanonicalUUIDChoiceField(required=False)
    to_custodian_account_id = CanonicalUUIDChoiceField(required=False)
    to_custodian_party_id = CanonicalUUIDChoiceField(required=False)
    quantity = StrictBase10IntegerField(
        min_value=0,
        max_value=1_000_000_000,
        required=False,
    )
    condition_before = forms.CharField(max_length=120, required=False)
    condition_after = forms.CharField(max_length=120, required=False)
    manifest_id = CanonicalUUIDChoiceField(required=False)
    evidence_reference = forms.CharField(max_length=1_000, required=False)


class OfflineBatchForm(CommandForm):
    """Collect and validate offline batch input."""

    device_code = forms.CharField(max_length=96)
    snapshot_version = StrictBase10IntegerField(min_value=0)
    policy_version = forms.CharField(max_length=64)
    expires_at = _datetime_field()
    operation_idempotency_key = CanonicalUUIDField()
    expected_subject_sequence = StrictBase10IntegerField(min_value=0)
    action = forms.ChoiceField(choices=LogisticsEvent.EventType.choices)
    label_code = forms.ChoiceField(choices=())
    source_label_code = forms.ChoiceField(choices=(), required=False)
    destination_label_code = forms.ChoiceField(choices=(), required=False)
    quantity = StrictBase10IntegerField(
        min_value=0,
        max_value=1_000_000_000,
        required=False,
    )
    observed_condition = forms.CharField(max_length=120, required=False)
    occurred_at = _datetime_field()


class RestrictedContactReadForm(LogisticsStrictForm):
    """Collect and validate restricted contact read input."""

    address_id = CanonicalUUIDChoiceField(widget=forms.HiddenInput)
    purpose = forms.ChoiceField(choices=RestrictedLogisticsAddress.Purpose.choices)
    access_purpose = forms.ChoiceField(
        choices=(
            ("pickup_coordination", "Pickup coordination"),
            ("provider_contact", "Provider contact"),
            ("return_coordination", "Return coordination"),
            ("inventory_verification", "Inventory verification"),
            ("incident_response", "Incident response"),
        )
    )
