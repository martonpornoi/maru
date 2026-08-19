import importlib

from django.conf import settings
from django.core import validators
from django.db import migrations, models
import django.db.models.deletion
import uuid


PRE_COMMERCE_REGISTRATION_GUARD_SQL = importlib.import_module(
    "maru.registration.migrations.0016_guardian_lifecycle_guard"
).FORWARD_SQL


COMMERCE_GUARDS_SQL = r"""
CREATE FUNCTION maru_guard_registration_commerce_control()
RETURNS trigger AS $$
DECLARE
    configuration_organization uuid;
    configuration_edition uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registration commerce controls require recovery'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id
      INTO configuration_organization, configuration_edition
      FROM registration_registrationconfiguration
     WHERE id = NEW.configuration_id;
    IF configuration_organization IS NULL
       OR configuration_organization != NEW.organization_id
       OR configuration_edition != NEW.edition_id
    THEN
        RAISE EXCEPTION 'registration commerce control scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'registration commerce controls start at version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW) - ARRAY['aggregate_version', 'updated_at']
           = to_jsonb(OLD) - ARRAY['aggregate_version', 'updated_at']
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid registration commerce control transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_commerce_control_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationcommercecontrol
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_commerce_control();

CREATE FUNCTION maru_guard_registration_commerce_append()
RETURNS trigger AS $$
BEGIN
    IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'registration commerce evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_commerce_receipt_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationcommercecommandreceipt
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_commerce_append();

CREATE TRIGGER registration_capacity_adjustment_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_registrationcapacityadjustment
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_commerce_append();

CREATE TRIGGER registration_waitlist_batch_append_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_waitlistbatchoffer
FOR EACH ROW EXECUTE FUNCTION maru_guard_registration_commerce_append();

CREATE FUNCTION maru_guard_admission_tier_replacement()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
    registration_configuration uuid;
    source_configuration uuid;
    target_configuration uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admission tier replacements require retention'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, configuration_id
      INTO registration_organization, registration_edition, registration_configuration
      FROM registration_registration
     WHERE id = NEW.registration_id;
    SELECT configuration_id INTO source_configuration
      FROM registration_admissionproduct WHERE id = NEW.source_product_id;
    SELECT configuration_id INTO target_configuration
      FROM registration_admissionproduct WHERE id = NEW.target_product_id;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR source_configuration != registration_configuration
       OR target_configuration != registration_configuration
       OR NEW.source_product_id = NEW.target_product_id
    THEN
        RAISE EXCEPTION 'admission tier replacement scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status != 'payment_pending'
           OR NEW.aggregate_version != 1
           OR NEW.completed_at IS NOT NULL
           OR NEW.expired_at IS NOT NULL
           OR NEW.cancelled_at IS NOT NULL
           OR NEW.resulting_registration_version IS NOT NULL
        THEN
            RAISE EXCEPTION 'invalid initial admission tier replacement'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'payment_pending'
       AND NEW.status IN ('completed', 'expired', 'cancelled')
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW) - ARRAY[
               'status', 'aggregate_version', 'resulting_registration_version',
               'completed_at', 'expired_at', 'cancelled_at', 'updated_at'
           ]
           = to_jsonb(OLD) - ARRAY[
               'status', 'aggregate_version', 'resulting_registration_version',
               'completed_at', 'expired_at', 'cancelled_at', 'updated_at'
           ]
       )
       AND (
           (NEW.status = 'completed'
            AND NEW.completed_at IS NOT NULL
            AND NEW.resulting_registration_version IS NOT NULL
            AND NEW.expired_at IS NULL
            AND NEW.cancelled_at IS NULL)
           OR
           (NEW.status = 'expired'
            AND NEW.expired_at IS NOT NULL
            AND NEW.resulting_registration_version IS NULL
            AND NEW.completed_at IS NULL
            AND NEW.cancelled_at IS NULL)
           OR
           (NEW.status = 'cancelled'
            AND NEW.cancelled_at IS NOT NULL
            AND NEW.resulting_registration_version IS NULL
            AND NEW.completed_at IS NULL
            AND NEW.expired_at IS NULL)
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid admission tier replacement transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_tier_replacement_guard
BEFORE INSERT OR UPDATE OR DELETE
ON registration_admissiontierreplacement
FOR EACH ROW EXECUTE FUNCTION maru_guard_admission_tier_replacement();
"""


COMMERCE_GUARDS_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS registration_tier_replacement_guard
    ON registration_admissiontierreplacement;
DROP FUNCTION IF EXISTS maru_guard_admission_tier_replacement();
DROP TRIGGER IF EXISTS registration_waitlist_batch_append_guard
    ON registration_waitlistbatchoffer;
DROP TRIGGER IF EXISTS registration_capacity_adjustment_append_guard
    ON registration_registrationcapacityadjustment;
DROP TRIGGER IF EXISTS registration_commerce_receipt_append_guard
    ON registration_registrationcommercecommandreceipt;
DROP FUNCTION IF EXISTS maru_guard_registration_commerce_append();
DROP TRIGGER IF EXISTS registration_commerce_control_guard
    ON registration_registrationcommercecontrol;
DROP FUNCTION IF EXISTS maru_guard_registration_commerce_control();
"""


REGISTRATION_GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION maru_guard_registration_record()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
    participation_organization uuid;
    participation_edition uuid;
    participation_account uuid;
    configuration_organization uuid;
    configuration_edition uuid;
    configuration_status varchar;
    product_configuration uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registrations require cancellation and retention'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM events_eventedition WHERE id = NEW.edition_id;
    SELECT organization_id, edition_id, account_id
      INTO participation_organization, participation_edition, participation_account
      FROM participation_participation WHERE id = NEW.participation_id;
    SELECT organization_id, edition_id, status
      INTO configuration_organization, configuration_edition, configuration_status
      FROM registration_registrationconfiguration WHERE id = NEW.configuration_id;
    SELECT configuration_id INTO product_configuration
      FROM registration_admissionproduct WHERE id = NEW.product_id;

    IF edition_organization IS NULL
       OR edition_organization != NEW.organization_id
       OR participation_organization != NEW.organization_id
       OR participation_edition != NEW.edition_id
       OR participation_account != NEW.account_id
       OR configuration_organization != NEW.organization_id
       OR configuration_edition != NEW.edition_id
       OR product_configuration != NEW.configuration_id
    THEN
        RAISE EXCEPTION 'registration scope relationships do not match'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle IN ('archived', 'cancelled') THEN
        RAISE EXCEPTION 'registration records are closed for this edition'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 OR configuration_status != 'active' THEN
            RAISE EXCEPTION 'new registration requires active version one'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'waitlisted' AND NEW.waitlisted_at IS NULL THEN
            RAISE EXCEPTION 'waitlisted registration requires queue time'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'payment_pending' AND NEW.payment_due_at IS NULL THEN
            RAISE EXCEPTION 'payment pending registration requires deadline'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'confirmed'
           AND (NEW.confirmed_at IS NULL OR NEW.confirmation_basis = '')
        THEN
            RAISE EXCEPTION 'confirmed registration requires evidence basis'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.state = 'payment_pending'
       AND NEW.state = 'payment_pending'
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND NEW.payment_due_at IS NOT NULL
       AND (
           to_jsonb(NEW) - ARRAY['aggregate_version', 'payment_due_at', 'updated_at']
           = to_jsonb(OLD) - ARRAY['aggregate_version', 'payment_due_at', 'updated_at']
       )
    THEN
        RETURN NEW;
    END IF;

    IF OLD.state IN ('confirmed', 'checked_in')
       AND NEW.state = OLD.state
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND NEW.product_id != OLD.product_id
       AND EXISTS (
           SELECT 1
             FROM registration_admissiontierreplacement replacement
            WHERE replacement.registration_id = OLD.id
              AND replacement.status = 'payment_pending'
              AND replacement.source_product_id = OLD.product_id
              AND replacement.target_product_id = NEW.product_id
              AND replacement.target_product_name_snapshot = NEW.product_name_snapshot
              AND replacement.target_price_minor_snapshot = NEW.price_minor_snapshot
              AND replacement.payment_due_at > CURRENT_TIMESTAMP
       )
       AND (
           to_jsonb(NEW) - ARRAY[
               'product_id', 'product_name_snapshot', 'price_minor_snapshot',
               'aggregate_version', 'updated_at'
           ]
           = to_jsonb(OLD) - ARRAY[
               'product_id', 'product_name_snapshot', 'price_minor_snapshot',
               'aggregate_version', 'updated_at'
           ]
       )
    THEN
        RETURN NEW;
    END IF;

    IF (
        (OLD.state = 'guardian_pending'
            AND NEW.state IN ('waitlisted', 'payment_pending', 'confirmed', 'cancelled'))
        OR (OLD.state = 'waitlisted'
            AND NEW.state IN ('payment_pending', 'confirmed', 'cancelled'))
        OR (OLD.state = 'payment_pending'
            AND NEW.state IN ('confirmed', 'expired', 'cancelled'))
        OR (OLD.state = 'confirmed' AND NEW.state IN ('checked_in', 'cancelled'))
       )
       AND NEW.aggregate_version = OLD.aggregate_version + 1
       AND (
           to_jsonb(NEW) - ARRAY[
               'state', 'aggregate_version', 'waitlisted_at', 'offered_at',
               'payment_due_at', 'confirmed_at', 'checked_in_at', 'expired_at',
               'cancelled_at', 'confirmation_basis', 'updated_at'
           ]
           = to_jsonb(OLD) - ARRAY[
               'state', 'aggregate_version', 'waitlisted_at', 'offered_at',
               'payment_due_at', 'confirmed_at', 'checked_in_at', 'expired_at',
               'cancelled_at', 'confirmation_basis', 'updated_at'
           ]
       )
    THEN
        IF NEW.state = 'waitlisted' AND NEW.waitlisted_at IS NULL THEN
            RAISE EXCEPTION 'waitlisted registration requires queue time'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'payment_pending' AND NEW.payment_due_at IS NULL THEN
            RAISE EXCEPTION 'payment pending registration requires deadline'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'confirmed'
           AND (NEW.confirmed_at IS NULL OR NEW.confirmation_basis = '')
        THEN
            RAISE EXCEPTION 'confirmed registration requires evidence basis'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'expired' AND NEW.expired_at IS NULL THEN
            RAISE EXCEPTION 'expired registration requires expiry time'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state = 'cancelled' AND NEW.cancelled_at IS NULL THEN
            RAISE EXCEPTION 'cancelled registration requires cancellation time'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid registration lifecycle transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0037_template_catalog_and_activation_evidence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionproduct",
            name="capacity_ceiling",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Optional hard ceiling for governed live capacity adjustments. "
                    "When omitted, the configured capacity is the ceiling."
                ),
            ),
        ),
        migrations.AddField(
            model_name="registrationconfiguration",
            name="capacity_ceiling",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Optional hard ceiling for reasoned live capacity adjustments. "
                    "When omitted, the initial capacity is the ceiling."
                ),
            ),
        ),
        migrations.AddField(
            model_name="registrationlifecyclerun",
            name="tier_replacements_expired",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="registrationtemplateproduct",
            name="capacity_ceiling",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Optional hard ceiling for governed live capacity adjustments. "
                    "When omitted, the configured capacity is the ceiling."
                ),
            ),
        ),
        migrations.CreateModel(
            name="AdmissionTierReplacement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization_id", models.UUIDField()),
                ("edition_id", models.UUIDField()),
                ("source_product_name_snapshot", models.CharField(max_length=160)),
                ("target_product_name_snapshot", models.CharField(max_length=160)),
                ("source_price_minor_snapshot", models.PositiveBigIntegerField()),
                ("target_price_minor_snapshot", models.PositiveBigIntegerField()),
                ("amount_due_minor", models.PositiveBigIntegerField()),
                ("currency", models.CharField(max_length=3)),
                ("source_entitlement_code", models.SlugField(max_length=80)),
                ("target_entitlement_code", models.SlugField(max_length=80)),
                ("target_entitlement_name_snapshot", models.CharField(max_length=160)),
                ("status", models.CharField(choices=[("payment_pending", "Payment pending"), ("completed", "Completed"), ("expired", "Expired"), ("cancelled", "Cancelled")], default="payment_pending", max_length=24)),
                ("aggregate_version", models.PositiveIntegerField(default=1)),
                ("expected_registration_version", models.PositiveIntegerField()),
                ("resulting_registration_version", models.PositiveIntegerField(blank=True, null=True)),
                ("reserved_at", models.DateTimeField()),
                ("payment_due_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("expired_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="admission_tier_replacements", to=settings.AUTH_USER_MODEL)),
                ("registration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tier_replacements", to="registration.registration")),
                ("source_product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tier_replacements_from", to="registration.admissionproduct")),
                ("target_product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tier_replacements_to", to="registration.admissionproduct")),
            ],
            options={"ordering": ("-reserved_at", "id")},
        ),
        migrations.AddField(
            model_name="paymentintent",
            name="tier_replacement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payment_intents", to="registration.admissiontierreplacement"),
        ),
        migrations.CreateModel(
            name="RegistrationCommerceControl",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization_id", models.UUIDField()),
                ("edition_id", models.UUIDField()),
                ("aggregate_version", models.PositiveBigIntegerField(default=1)),
                ("configuration", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="commerce_control", to="registration.registrationconfiguration")),
            ],
            options={"ordering": ("organization_id", "edition_id", "id")},
        ),
        migrations.CreateModel(
            name="RegistrationCommerceCommandReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("operation", models.CharField(choices=[("tier_replacement_reserved", "Admission tier replacement reserved"), ("overall_capacity_adjusted", "Overall capacity adjusted"), ("product_capacity_adjusted", "Product capacity adjusted"), ("waitlist_batch_offered", "Waitlist batch offered")], max_length=48)),
                ("idempotency_key", models.UUIDField()),
                ("request_digest", models.CharField(max_length=64, validators=[validators.RegexValidator(code="invalid_registration_setup_digest", message="Use a lowercase SHA-256 digest.", regex="^[0-9a-f]{64}$")])),
                ("expected_version", models.PositiveBigIntegerField()),
                ("resulting_version", models.PositiveBigIntegerField()),
                ("result_id", models.UUIDField()),
                ("result_count", models.PositiveIntegerField(default=1)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_commerce_command_receipts", to=settings.AUTH_USER_MODEL)),
                ("registration", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="commerce_command_receipts", to="registration.registration")),
                ("control", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="command_receipts", to="registration.registrationcommercecontrol")),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.CreateModel(
            name="RegistrationCapacityAdjustment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization_id", models.UUIDField()),
                ("edition_id", models.UUIDField()),
                ("scope", models.CharField(choices=[("overall", "Overall registration"), ("product", "Admission product")], max_length=16)),
                ("previous_capacity", models.PositiveIntegerField()),
                ("new_capacity", models.PositiveIntegerField()),
                ("hard_ceiling", models.PositiveIntegerField()),
                ("control_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=500)),
                ("occurred_at", models.DateTimeField()),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_capacity_adjustments", to=settings.AUTH_USER_MODEL)),
                ("configuration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="capacity_adjustments", to="registration.registrationconfiguration")),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="capacity_adjustments", to="registration.admissionproduct")),
                ("control", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="capacity_adjustments", to="registration.registrationcommercecontrol")),
            ],
            options={"ordering": ("control_version", "id")},
        ),
        migrations.CreateModel(
            name="WaitlistBatchOffer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization_id", models.UUIDField()),
                ("edition_id", models.UUIDField()),
                ("requested_size", models.PositiveIntegerField()),
                ("offered_count", models.PositiveIntegerField()),
                ("control_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=500)),
                ("occurred_at", models.DateTimeField()),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_waitlist_batches", to=settings.AUTH_USER_MODEL)),
                ("configuration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waitlist_batches", to="registration.registrationconfiguration")),
                ("control", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waitlist_batches", to="registration.registrationcommercecontrol")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waitlist_batches", to="registration.admissionproduct")),
            ],
            options={"ordering": ("-occurred_at", "id")},
        ),
        migrations.AddIndex(model_name="admissiontierreplacement", index=models.Index(fields=["organization_id", "edition_id", "status", "payment_due_at"], name="tier_replacement_expiry_idx")),
        migrations.AddIndex(model_name="admissiontierreplacement", index=models.Index(fields=["target_product", "status", "reserved_at"], name="tier_replacement_capacity_idx")),
        migrations.AddConstraint(model_name="admissiontierreplacement", constraint=models.UniqueConstraint(condition=models.Q(status="payment_pending"), fields=("registration",), name="one_pending_tier_replacement_per_registration")),
        migrations.AddConstraint(model_name="admissiontierreplacement", constraint=models.CheckConstraint(condition=models.Q(amount_due_minor__gt=0), name="tier_replacement_amount_positive")),
        migrations.AddConstraint(model_name="admissiontierreplacement", constraint=models.CheckConstraint(condition=models.Q(target_price_minor_snapshot__gt=models.F("source_price_minor_snapshot")), name="tier_replacement_price_increases")),
        migrations.AddConstraint(model_name="admissiontierreplacement", constraint=models.CheckConstraint(condition=models.Q(payment_due_at__gt=models.F("reserved_at")), name="tier_replacement_deadline_after_reservation")),
        migrations.AddConstraint(model_name="registrationcommercecontrol", constraint=models.CheckConstraint(condition=models.Q(aggregate_version__gt=0), name="reg_commerce_control_version_positive")),
        migrations.AddConstraint(model_name="registrationcommercecommandreceipt", constraint=models.UniqueConstraint(fields=("control", "actor", "idempotency_key"), name="reg_commerce_command_retry_unique")),
        migrations.AddConstraint(model_name="registrationcommercecommandreceipt", constraint=models.CheckConstraint(condition=models.Q(expected_version__gt=0), name="reg_commerce_receipt_expected_positive")),
        migrations.AddConstraint(model_name="registrationcommercecommandreceipt", constraint=models.CheckConstraint(condition=models.Q(resulting_version__gt=models.F("expected_version")), name="reg_commerce_receipt_version_advanced")),
        migrations.AddIndex(model_name="registrationcapacityadjustment", index=models.Index(fields=["organization_id", "edition_id", "scope", "occurred_at"], name="reg_capacity_scope_idx")),
        migrations.AddConstraint(model_name="registrationcapacityadjustment", constraint=models.UniqueConstraint(fields=("control", "control_version"), name="reg_capacity_adjustment_version_unique")),
        migrations.AddConstraint(model_name="registrationcapacityadjustment", constraint=models.CheckConstraint(condition=models.Q(previous_capacity__gt=0, new_capacity__gt=0), name="reg_capacity_adjustment_values_positive")),
        migrations.AddConstraint(model_name="registrationcapacityadjustment", constraint=models.CheckConstraint(condition=models.Q(new_capacity__lte=models.F("hard_ceiling")), name="reg_capacity_adjustment_below_ceiling")),
        migrations.AddConstraint(model_name="registrationcapacityadjustment", constraint=models.CheckConstraint(condition=(models.Q(scope="overall", product__isnull=True) | models.Q(scope="product", product__isnull=False)), name="reg_capacity_adjustment_scope_shape")),
        migrations.AddIndex(model_name="waitlistbatchoffer", index=models.Index(fields=["organization_id", "edition_id", "occurred_at"], name="reg_waitlist_batch_scope_idx")),
        migrations.AddConstraint(model_name="waitlistbatchoffer", constraint=models.UniqueConstraint(fields=("control", "control_version"), name="reg_waitlist_batch_version_unique")),
        migrations.AddConstraint(model_name="waitlistbatchoffer", constraint=models.CheckConstraint(condition=models.Q(offered_count__lte=models.F("requested_size")), name="reg_waitlist_batch_within_requested")),
        migrations.RunSQL(COMMERCE_GUARDS_SQL, reverse_sql=COMMERCE_GUARDS_REVERSE_SQL),
        migrations.RunSQL(
            REGISTRATION_GUARD_SQL,
            reverse_sql=PRE_COMMERCE_REGISTRATION_GUARD_SQL,
        ),
    ]
