"""Recognize every installed cross-module Department reference."""

from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION
    public.maru_workforce_department_fk_contract_is_current()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_fk_contract$
    SELECT NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint AS constraint_record
         WHERE constraint_record.contype = 'f'
           AND constraint_record.confrelid =
               'public.workforce_department'::pg_catalog.regclass
           AND NOT (
               constraint_record.confdeltype IN ('a', 'r')
               AND (
                   SELECT pg_catalog.array_agg(
                              attribute.attname::text
                              ORDER BY key_column.ordinality
                          )
                     FROM pg_catalog.unnest(constraint_record.confkey)
                          WITH ORDINALITY
                          AS key_column(attnum, ordinality)
                     JOIN pg_catalog.pg_attribute AS attribute
                       ON attribute.attrelid = constraint_record.confrelid
                      AND attribute.attnum = key_column.attnum
               ) = ARRAY['id']::text[]
               AND EXISTS (
                   SELECT 1
                     FROM (
                         VALUES
                             (
                                 'public.workforce_department'::pg_catalog.regclass,
                                 ARRAY['parent_id']::text[]
                             ),
                             (
                                 'public.workforce_position'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.authorization_scopedresourcebinding'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.authorization_capabilitygrant'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.authorization_roleassignment'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.applications_applicationownerdepartment'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.charities_charityselection'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             ),
                             (
                                 'public.logistics_equipmentoffer'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             ),
                             (
                                 'public.logistics_logisticsmanifest'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             ),
                             (
                                 'public.registration_registrationprofileextensionfield'::pg_catalog.regclass,
                                 ARRAY['audience_department_id']::text[]
                             ),
                             (
                                 'public.venues_editionspaceselection'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             ),
                             (
                                 'public.venues_editionvenueselection'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             ),
                             (
                                 'public.venues_venuebooking'::pg_catalog.regclass,
                                 ARRAY['responsible_department_id']::text[]
                             )
                     ) AS supported(relation_id, local_columns)
                    WHERE supported.relation_id = constraint_record.conrelid
                      AND supported.local_columns = (
                          SELECT pg_catalog.array_agg(
                                     attribute.attname::text
                                     ORDER BY key_column.ordinality
                                 )
                            FROM pg_catalog.unnest(constraint_record.conkey)
                                 WITH ORDINALITY
                                 AS key_column(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_record.conrelid
                             AND attribute.attnum = key_column.attnum
                      )
               )
           )
    );
$page9_fk_contract$;

REVOKE ALL ON FUNCTION
    public.maru_workforce_department_fk_contract_is_current()
FROM PUBLIC;
"""


REVERSE_SQL = (
    r"""
CREATE OR REPLACE FUNCTION
    public.maru_workforce_department_fk_contract_is_current()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_fk_contract$
    SELECT NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint AS constraint_record
         WHERE constraint_record.contype = 'f'
           AND constraint_record.confrelid =
               'public.workforce_department'::pg_catalog.regclass
           AND NOT (
               constraint_record.confdeltype IN ('a', 'r')
               AND (
                   SELECT pg_catalog.array_agg(attribute.attname::text
                                               ORDER BY key_column.ordinality)
                     FROM pg_catalog.unnest(constraint_record.confkey)
                          WITH ORDINALITY
                          AS key_column(attnum, ordinality)
                     JOIN pg_catalog.pg_attribute AS attribute
                       ON attribute.attrelid = constraint_record.confrelid
                      AND attribute.attnum = key_column.attnum
               ) = ARRAY['id']::text[]
               AND CASE constraint_record.conrelid
                   WHEN 'public.workforce_department'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['parent_id']::text[]
                   WHEN 'public.workforce_position'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_"""
    r"""scopedresourcebinding'::pg_catalog.regclass
                       THEN (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_capabilitygrant'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_roleassignment'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   ELSE FALSE
               END
           )
    );
$page9_fk_contract$;

REVOKE ALL ON FUNCTION
    public.maru_workforce_department_fk_contract_is_current()
FROM PUBLIC;
"""
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0001_initial"),
        ("charities", "0001_initial"),
        ("logistics", "0001_initial"),
        ("registration", "0039_profile_audiences_and_platform_starter"),
        ("venues", "0001_initial"),
        ("workforce", "0007_structure_write_integrity"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
