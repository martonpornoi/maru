"""Allow canonical JSON-null clears for optional closed profile value types."""

from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

_FUNCTION_TEMPLATE = r"""
CREATE OR REPLACE FUNCTION public.maru_guard_registration_profile_value_revision_v2()
RETURNS trigger AS $$
DECLARE
    registration_organization uuid;
    registration_edition uuid;
    field_organization uuid;
    field_edition uuid;
    stable_key varchar;
    field_status varchar;
    field_type varchar;
    field_options jsonb;
    field_required boolean;
    next_sequence integer;
    database_now timestamptz;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'profile extension value revisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    database_now := statement_timestamp();
    SELECT organization_id, edition_id
      INTO registration_organization, registration_edition
      FROM public.registration_registration
     WHERE id = NEW.registration_id;
    SELECT field.organization_id, field.edition_id, field.key, field.status,
           field.field_type, field.options, field.required
      INTO field_organization, field_edition, stable_key, field_status,
           field_type, field_options, field_required
      FROM public.registration_registrationprofileextensionfield AS field
     WHERE field.id = NEW.field_id;
    SELECT COALESCE(max(sequence), 0) + 1
      INTO next_sequence
      FROM public.registration_registrationprofileextensionvaluerevision
     WHERE registration_id = NEW.registration_id
       AND field_key = NEW.field_key;
    IF registration_organization IS NULL
       OR registration_organization != NEW.organization_id
       OR registration_edition != NEW.edition_id
       OR field_organization != NEW.organization_id
       OR field_edition != NEW.edition_id
       OR stable_key != NEW.field_key
       OR field_status != 'active'
       OR NEW.sequence != next_sequence
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR length(NEW.reason) > 500
       OR NEW.reason != btrim(
           NEW.reason,
           U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
       )
       OR octet_length(convert_to(NEW.value::text, 'UTF8')) > 16384
       OR (
           CASE
               WHEN jsonb_typeof(NEW.value) = 'null' THEN __NULL_ALLOWED__
               ELSE CASE field_type
                   WHEN 'short_text' THEN
                       jsonb_typeof(NEW.value) = 'string'
                       AND char_length(NEW.value #>> '{}') <= 500
                       AND (NEW.value #>> '{}') = btrim(
                           NEW.value #>> '{}',
                           U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                       )
                       AND (NOT field_required OR (NEW.value #>> '{}') != '')
                   WHEN 'long_text' THEN
                       jsonb_typeof(NEW.value) = 'string'
                       AND char_length(NEW.value #>> '{}') <= 4000
                       AND (NEW.value #>> '{}') = btrim(
                           NEW.value #>> '{}',
                           U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                       )
                       AND (NOT field_required OR (NEW.value #>> '{}') != '')
                   WHEN 'boolean' THEN jsonb_typeof(NEW.value) = 'boolean'
                   WHEN 'integer' THEN
                       CASE
                           WHEN jsonb_typeof(NEW.value) != 'number' THEN FALSE
                           ELSE
                               (NEW.value #>> '{}')::numeric = trunc(
                                   (NEW.value #>> '{}')::numeric
                               )
                               AND (NEW.value #>> '{}')::numeric
                                   BETWEEN -2147483648 AND 2147483647
                       END
                   WHEN 'single_choice' THEN
                       jsonb_typeof(NEW.value) = 'string'
                       AND field_options ? (NEW.value #>> '{}')
                   WHEN 'multiple_choice' THEN
                       CASE
                           WHEN jsonb_typeof(NEW.value) != 'array' THEN FALSE
                           ELSE
                               jsonb_array_length(NEW.value) <= 64
                               AND (
                                   NOT field_required
                                   OR jsonb_array_length(NEW.value) > 0
                               )
                               AND NOT EXISTS (
                                   SELECT 1
                                     FROM jsonb_array_elements(NEW.value)
                                          AS item(value)
                                    WHERE jsonb_typeof(item.value) != 'string'
                                       OR NOT (
                                           field_options ? (item.value #>> '{}')
                                       )
                               )
                               AND (
                                   SELECT count(*) = count(DISTINCT item.value)
                                     FROM jsonb_array_elements_text(NEW.value)
                                          AS item(value)
                               )
                       END
                   ELSE FALSE
               END
           END
       ) IS NOT TRUE
    THEN
        RAISE EXCEPTION 'invalid profile extension value append'
            USING ERRCODE = '23514';
    END IF;
    NEW.created_at := database_now;
    NEW.updated_at := database_now;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_guard_registration_profile_value_revision_v2()
FROM PUBLIC;
"""

FORWARD_SQL = _FUNCTION_TEMPLATE.replace(
    "__NULL_ALLOWED__",
    "(NOT field_required AND field_type IN ('boolean', 'integer', 'single_choice'))",
)

_REVERSE_FENCE = r"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.registration_registrationprofileextensionvaluerevision
         WHERE jsonb_typeof(value) = 'null'
    ) THEN
        RAISE EXCEPTION
            'cannot reverse optional profile-value clear with JSON-null evidence'
            USING ERRCODE = '55000';
    END IF;
END;
$$;
"""

REVERSE_SQL = _REVERSE_FENCE + _FUNCTION_TEMPLATE.replace(
    "__NULL_ALLOWED__",
    "FALSE",
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("registration", "0039_profile_audiences_and_platform_starter")
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            reverse_sql=REVERSE_SQL,
        )
    ]
