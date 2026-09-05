"""PostgreSQL least-privilege proof for Maru's configured runtime role.

The probe accepts a role name as data and never changes role, grants, or
ownership.  Migration and activation sessions may therefore inspect the role
that will run web and worker processes before those processes are started.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from django.db import connections

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper

# Every non-trigger Maru function reachable from a current trigger or direct
# runtime policy call.  Trigger functions themselves are invoked by PostgreSQL;
# their invoker-security helper calls require these explicit EXECUTE grants.
RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1: Final[tuple[str, ...]] = (
    "public.maru_assert_active_board_membership_provenance(uuid)",
    "public.maru_assert_active_executive_board(uuid)",
    "public.maru_assert_active_executive_board_v0009(uuid)",
    "public.maru_assert_authority_issuance_complete(bigint)",
    (
        "public.maru_assert_authority_issuance_complete_internal("
        "bigint,bigint[],integer)"
    ),
    "public.maru_assert_authority_provenance_activation()",
    "public.maru_assert_authority_target_complete(character varying,uuid)",
    "public.maru_audit_test_reset_allowed()",
    (
        "public.maru_authority_bundle_historical_v1("
        "uuid,timestamp with time zone,uuid,bigint[],integer)"
    ),
    (
        "public.maru_authority_issuance_valid_v1(bigint,uuid,character varying,"
        "uuid,uuid,uuid,uuid,timestamp with time zone,timestamp with time zone,"
        "timestamp with time zone,boolean,boolean,bigint[],integer)"
    ),
    "public.maru_authority_provenance_is_active()",
    "public.maru_authority_provenance_test_reset_allowed()",
    (
        "public.maru_authority_scope_contains_v1("
        "uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)"
    ),
    "public.maru_authority_scope_is_current_v1(uuid,uuid,uuid,uuid)",
    "public.maru_authorization_capability_min_scope(text)",
    (
        "public.maru_authorization_scope_contains("
        "uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid)"
    ),
    "public.maru_authorization_scope_rank(uuid,uuid,uuid)",
    (
        "public.maru_workforce_role_evidence_matches_position("
        "uuid,uuid,uuid,uuid,uuid,uuid)"
    ),
)

# ADR 0046 preserves ADR 0044's frozen v1 closure and adds the narrow
# SECURITY DEFINER latch-lock helper needed by select-only runtime relations.
RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2: Final[tuple[str, ...]] = (
    *RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1,
    "public.maru_lock_authority_provenance_latch()",
)

# ADR 0080 preserves the two earlier closures and adds only the two helpers
# reached by the purpose-bounded Maru-operators representation validators.
RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3: Final[tuple[str, ...]] = (
    *RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2,
    "public.maru_assert_active_maru_operators(uuid)",
    "public.maru_assert_active_maru_operators_v0009(uuid)",
)

# These control relations are deliberately readable, but never writable, by
# the application login. Their mutations belong to the controlled
# migration/cutover owner described in ADR-0046. The Programme schema is also
# select-only while issue #61 remains dormant: no current exact profile or
# mounted caller may create or advance Programme state. A later activation
# migration must deliberately reclassify only the relations its writer needs.
RUNTIME_DATABASE_SELECT_ONLY_RELATIONS: Final[tuple[str, ...]] = (
    "public.django_migrations",
    "public.authorization_authorityprovenanceactivation",
    "public.authorization_provenanceactivationlatch",
    "public.identity_platforminvitationretentionpolicycontrol",
    "public.applications_programmecall",
    "public.applications_programmecalltrack",
    "public.applications_programmecallformat",
    "public.applications_programmecallcontributorfield",
    "public.applications_programmeproposal",
    "public.applications_programmeproposalselectionrevision",
    "public.applications_programmeproposalcollaborator",
    "public.applications_programmeproposalcollaboratortransition",
    "public.applications_programmeproposalcontributorprofilerevision",
    "public.applications_programmeproposalrevision",
    "public.applications_programmeproposalrevisionanswer",
    "public.applications_programmeproposalrevisioncontributor",
    "public.applications_programmeproposalrevisionresponse",
    "public.applications_programmecommandreceipt",
    "public.applications_programmeimportbatch",
    "public.applications_programmeimportitem",
    "public.applications_programmeimportpreviewrevision",
    "public.applications_programmeimportpreviewitemresult",
    "public.applications_programmeimportsourcebinding",
    "public.applications_programmeimportappliedcommand",
    "public.applications_programmeimportcommandreceipt",
    "public.applications_programmereviewpolicy",
    "public.applications_programmereviewcase",
    "public.applications_programmereviewassignment",
    "public.applications_programmereviewentry",
    "public.applications_programmereviewdecision",
    "public.applications_programmedecisionacknowledgement",
    "public.applications_programmereviewreceipt",
    "public.programme_programmeeditioncontrol",
    "public.programme_programmeitem",
    "public.programme_programmeitemsourcebinding",
    "public.programme_programmeworkingrevision",
    "public.programme_programmedeliveryrevision",
    "public.programme_programmedepartmentdiscussionentry",
    "public.programme_programmereadinessrequirement",
    "public.programme_programmereadinessrequirementrevision",
    "public.programme_programmereadinessevidence",
    "public.programme_programmepublicrendition",
    "public.programme_programmecommandreceipt",
)

# Effects replay, Workforce adoption, and Organization structure evidence is
# append-only at runtime. The separately credentialed migration/cutover owner
# retains recovery authority. Registration setup and account onboarding's
# transitions, command receipts, and reconciliation receipts use the same
# profile. Delivery attempt/late-outcome provider references and current
# retention assessments have narrowly trigger-guarded v9 updates and become
# terminal when the safe result is disposed.
RUNTIME_DATABASE_SELECT_INSERT_RELATIONS: Final[tuple[str, ...]] = (
    "public.effects_effectreplayreceipt",
    "public.events_workforceadoptionsetupreceipt",
    "public.workforce_editionstructurecommandreceipt",
    "public.workforce_positionassignmentcommandreceipt",
    "public.workforce_personavailabilitycommandreceipt",
    "public.workforce_shiftdemandcommandreceipt",
    "public.workforce_shiftcommitmentcommandreceipt",
    "public.registration_registrationprofileextensionvaluerevision",
    "public.registration_registrationprofileextensionvaluecommandreceipt",
    "public.applications_applicationfilereceipt",
    "public.applications_applicationanswerrevision",
    "public.applications_applicationreviewdecision",
    "public.applications_applicationtargetrecord",
    "public.applications_applicationcommandreceipt",
    "public.charities_charityselectiontimelineentry",
    "public.charities_charitypublicationsnapshot",
    "public.charities_charitycommandreceipt",
    "public.catalog_catalogstockadjustment",
    "public.catalog_catalogcommandreceipt",
    "public.catalog_catalogpaymentevent",
    "public.catalog_catalogordertimelineentry",
    "public.catalog_catalogorderline",
    "public.venues_venuespacecombinationmember",
    "public.venues_editionspacemember",
    "public.venues_editionspaceavailabilitywindow",
    "public.venues_venuebookinghistory",
    "public.venues_venuecommandreceipt",
    "public.identity_platformaccountinvitationtransition",
    "public.identity_platformaccountinvitationcommandreceipt",
    "public.identity_platformidentitydeliveryreconciliationreceipt",
    "public.identity_platforminvitationschedulerrun",
    "public.identity_platforminvitationretentionreceipt",
    "public.logistics_equipmentofferitem",
    "public.logistics_equipmentofferhistory",
    "public.logistics_equipmentofferacceptance",
    "public.logistics_keyholderresponsibility",
    "public.logistics_assetagreement",
    "public.logistics_reusablekitline",
    "public.logistics_logisticsmanifestline",
    "public.logistics_logisticsevent",
    "public.logistics_offlinescanoperation",
    "public.logistics_offlineoperationreceipt",
    "public.logistics_logisticscommandreceipt",
    "public.logistics_logisticsparty",
    "public.logistics_logisticsnode",
    "public.logistics_asset",
    "public.logistics_stocklot",
    "public.logistics_reusablekit",
    "public.logistics_logisticslabel",
    "public.logistics_logisticsdiscrepancy",
)

# Account onboarding seeds its singleton account-inventory control in migration. The
# runtime may only read and advance it; INSERT and DELETE remain owner-only.
RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS: Final[tuple[str, ...]] = (
    "public.identity_platformaccountinventorycontrol",
)

# The Organization structure aggregate, account invitation/delivery
# aggregates, and retained Applications/Charity/Catalog/Venue aggregates may
# be created and advanced, but runtime commands never delete them.
# IdentityChallenge is shared with recovery and verification; every current
# writer creates or advances it and its retention remains controlled.
RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS: Final[tuple[str, ...]] = (
    "public.workforce_editionstructurecontrol",
    "public.workforce_positionassignment",
    "public.workforce_personavailabilityplan",
    "public.workforce_shiftdemand",
    "public.workforce_shiftcommitment",
    "public.registration_registrationprofileextensionvaluecontrol",
    "public.applications_applicationdefinition",
    "public.applications_applicationsubmission",
    "public.charities_charitypartner",
    "public.charities_charitypartnermedia",
    "public.charities_charityselection",
    "public.catalog_editioncatalog",
    "public.catalog_catalogproduct",
    "public.catalog_catalogvariant",
    "public.catalog_catalogorder",
    "public.catalog_catalogpaymentintent",
    "public.identity_identitychallenge",
    "public.identity_platformaccountinvitation",
    "public.identity_platformidentitydelivery",
    "public.identity_platformidentitydeliveryattempt",
    "public.identity_platformidentitydeliverylateoutcome",
    "public.identity_platforminvitationretentionassessment",
    "public.identity_platforminvitationretentionhold",
    "public.venues_venueproperty",
    "public.venues_venuepropertymedia",
    "public.venues_venuesite",
    "public.venues_venuebuilding",
    "public.venues_venuespace",
    "public.venues_venuespaceconfiguration",
    "public.venues_venuespacecombination",
    "public.venues_venuelayoutversion",
    "public.venues_accommodationroomtype",
    "public.venues_accommodationnightinventory",
    "public.venues_editionvenueselection",
    "public.venues_editionspaceselection",
    "public.venues_venuebooking",
    "public.venues_venuebookingoccupancy",
    "public.logistics_restrictedlogisticsaddress",
    "public.logistics_equipmentoffer",
    "public.logistics_physicalkey",
    "public.logistics_logisticsmanifest",
    "public.logistics_logisticscurrentstate",
    "public.logistics_logisticseditioncontrol",
    "public.logistics_offlinescanbatch",
)

# Current Availability periods are full-replacement children. Runtime commands
# may insert a new set and delete the prior set, but never update a period in
# place; exact command evidence and deferred aggregate triggers validate the
# final set at commit.
RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS: Final[tuple[str, ...]] = (
    "public.workforce_personavailabilitywindow",
)

_RUNTIME_DATABASE_ROLE_RESULT_FIELD_COUNT: Final = 25

_RUNTIME_DATABASE_ROLE_SAFETY_QUERY = r"""
WITH RECURSIVE
target_role AS (
    SELECT
        role.oid,
        role.rolname,
        role.rolcanlogin
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = %s
),
reachable_role(role_oid) AS (
    SELECT target.oid
      FROM target_role AS target
    UNION
    SELECT membership.roleid
      FROM pg_catalog.pg_auth_members AS membership
      JOIN reachable_role AS reachable
        ON reachable.role_oid = membership.member
),
current_database_record AS (
    SELECT database.oid, database.datdba, database.datacl
      FROM pg_catalog.pg_database AS database
     WHERE database.datname = pg_catalog.current_database()
),
user_schema AS (
    SELECT namespace.oid, namespace.nspowner, namespace.nspacl
      FROM pg_catalog.pg_namespace AS namespace
     WHERE namespace.nspname <> 'information_schema'
       AND namespace.nspname !~ '^pg_'
),
user_relation AS (
    SELECT
        relation.oid,
        relation.relkind,
        relation.relowner,
        relation.relacl
      FROM pg_catalog.pg_class AS relation
      JOIN user_schema AS namespace
        ON namespace.oid = relation.relnamespace
     WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f')
),
user_sequence AS (
    SELECT relation.oid, relation.relowner, relation.relacl
      FROM pg_catalog.pg_class AS relation
      JOIN user_schema AS namespace
        ON namespace.oid = relation.relnamespace
     WHERE relation.relkind = 'S'
),
user_function AS (
    SELECT procedure.oid, procedure.proowner, procedure.proacl
      FROM pg_catalog.pg_proc AS procedure
      JOIN user_schema AS namespace
        ON namespace.oid = procedure.pronamespace
),
user_column AS (
    SELECT attribute.attrelid, attribute.attnum, attribute.attacl
      FROM pg_catalog.pg_attribute AS attribute
      JOIN user_relation AS relation
        ON relation.oid = attribute.attrelid
     WHERE attribute.attnum > 0
       AND NOT attribute.attisdropped
),
applicable_role_setting(setting) AS (
    SELECT pg_catalog.unnest(role_setting.setconfig)
      FROM pg_catalog.pg_db_role_setting AS role_setting
      CROSS JOIN target_role AS target
      CROSS JOIN current_database_record AS database
     WHERE role_setting.setrole IN (0, target.oid)
       AND role_setting.setdatabase IN (0, database.oid)
),
required_limited_relation(
    identity,
    relation_oid,
    allow_insert,
    allow_update,
    allow_delete,
    forbid_references
) AS (
    SELECT
        required.identity,
        pg_catalog.to_regclass(required.identity),
        FALSE,
        FALSE,
        FALSE,
        TRUE
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
    UNION ALL
    SELECT
        required.identity,
        pg_catalog.to_regclass(required.identity),
        TRUE,
        FALSE,
        FALSE,
        TRUE
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
    UNION ALL
    SELECT
        required.identity,
        pg_catalog.to_regclass(required.identity),
        FALSE,
        TRUE,
        FALSE,
        TRUE
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
    UNION ALL
    SELECT
        required.identity,
        pg_catalog.to_regclass(required.identity),
        TRUE,
        TRUE,
        FALSE,
        TRUE
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
    UNION ALL
    SELECT
        required.identity,
        pg_catalog.to_regclass(required.identity),
        TRUE,
        FALSE,
        TRUE,
        TRUE
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
),
required_runtime_function(identity, procedure_oid) AS (
    SELECT
        required.identity,
        pg_catalog.to_regprocedure(required.identity)
      FROM pg_catalog.unnest(%s::text[]) AS required(identity)
)
SELECT
    EXISTS (SELECT 1 FROM target_role),
    COALESCE((SELECT target.rolcanlogin FROM target_role AS target), FALSE),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          JOIN pg_catalog.pg_roles AS role ON role.oid = reachable.role_oid
         WHERE role.rolsuper
            OR role.rolcreatedb
            OR role.rolcreaterole
            OR role.rolreplication
            OR role.rolbypassrls
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          JOIN pg_catalog.pg_roles AS role ON role.oid = reachable.role_oid
          CROSS JOIN target_role AS target
         WHERE lower(target.rolname) LIKE 'pg\_%%' ESCAPE '\'
            OR (
                role.oid <> target.oid
                AND (
                    role.rolsuper
                    OR role.rolcreatedb
                    OR role.rolcreaterole
                    OR role.rolreplication
                    OR role.rolbypassrls
                    OR lower(role.rolname) LIKE 'pg\_%%' ESCAPE '\'
                )
            )
            OR EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_auth_members AS membership
                  JOIN reachable_role AS member_role
                    ON member_role.role_oid = membership.member
                 WHERE membership.admin_option
            )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          CROSS JOIN current_database_record AS database
         WHERE pg_catalog.pg_has_role(
             reachable.role_oid,
             database.datdba,
             'MEMBER'
         )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          CROSS JOIN user_schema AS namespace
         WHERE pg_catalog.pg_has_role(
             reachable.role_oid,
             namespace.nspowner,
             'MEMBER'
         )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          JOIN pg_catalog.pg_class AS relation
            ON pg_catalog.pg_has_role(
                reachable.role_oid,
                relation.relowner,
                'MEMBER'
            )
          JOIN user_schema AS namespace
            ON namespace.oid = relation.relnamespace
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          JOIN pg_catalog.pg_proc AS procedure
            ON pg_catalog.pg_has_role(
                reachable.role_oid,
                procedure.proowner,
                'MEMBER'
            )
          JOIN user_schema AS namespace
            ON namespace.oid = procedure.pronamespace
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          CROSS JOIN current_database_record AS database
         WHERE pg_catalog.has_database_privilege(
                   reachable.role_oid,
                   database.oid,
                   'CREATE'
               )
            OR pg_catalog.has_database_privilege(
                   reachable.role_oid,
                   database.oid,
                   'TEMPORARY'
               )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          CROSS JOIN user_schema AS namespace
         WHERE pg_catalog.has_schema_privilege(
             reachable.role_oid,
             namespace.oid,
             'CREATE'
         )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          JOIN pg_catalog.pg_class AS relation
            ON relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          JOIN user_schema AS namespace
            ON namespace.oid = relation.relnamespace
         WHERE pg_catalog.has_table_privilege(
                   reachable.role_oid,
                   relation.oid,
                   'TRIGGER'
               )
            OR pg_catalog.has_table_privilege(
                   reachable.role_oid,
                   relation.oid,
                   'TRUNCATE'
               )
            OR pg_catalog.has_table_privilege(
                   reachable.role_oid,
                   relation.oid,
                   'MAINTAIN'
               )
    ),
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_parameter_acl AS parameter
          CROSS JOIN LATERAL pg_catalog.aclexplode(parameter.paracl)
            AS privilege
         WHERE privilege.privilege_type IN ('SET', 'ALTER SYSTEM')
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
    ),
    NOT EXISTS (
        SELECT 1
          FROM applicable_role_setting AS role_setting
         WHERE lower(pg_catalog.split_part(role_setting.setting, '=', 1))
                   = 'session_replication_role'
           AND lower(pg_catalog.split_part(role_setting.setting, '=', 2))
                   <> 'origin'
    ),
    pg_catalog.current_setting('session_replication_role', FALSE) = 'origin',
    EXISTS (SELECT 1 FROM target_role)
    AND EXISTS (
        SELECT 1
          FROM target_role AS target
          CROSS JOIN current_database_record AS database
         WHERE pg_catalog.has_database_privilege(
             target.oid,
             database.oid,
             'CONNECT'
         )
    ),
    EXISTS (SELECT 1 FROM target_role)
    AND NOT EXISTS (
        SELECT 1
          FROM target_role AS target
          CROSS JOIN user_schema AS namespace
         WHERE NOT pg_catalog.has_schema_privilege(
             target.oid,
             namespace.oid,
             'USAGE'
         )
    ),
    EXISTS (SELECT 1 FROM target_role)
    AND NOT EXISTS (
        SELECT 1
          FROM required_limited_relation AS required
          LEFT JOIN user_relation AS relation
            ON relation.oid = required.relation_oid
         WHERE relation.oid IS NULL
    )
    AND NOT EXISTS (
        SELECT 1
          FROM target_role AS target
          CROSS JOIN user_relation AS relation
          LEFT JOIN required_limited_relation AS required
            ON required.relation_oid = relation.oid
         WHERE NOT pg_catalog.has_table_privilege(
                   target.oid,
                   relation.oid,
                   'SELECT'
               )
            OR (
                (
                    relation.relkind = 'm'
                    OR required.relation_oid IS NOT NULL
                )
                AND (
                    (
                        COALESCE(required.allow_insert, FALSE)
                        AND NOT pg_catalog.has_table_privilege(
                            target.oid,
                            relation.oid,
                            'INSERT'
                        )
                    )
                    OR (
                        NOT COALESCE(required.allow_insert, FALSE)
                        AND EXISTS (
                            SELECT 1
                              FROM reachable_role AS reachable
                             WHERE pg_catalog.has_table_privilege(
                                       reachable.role_oid,
                                       relation.oid,
                                       'INSERT'
                                   )
                                OR EXISTS (
                                    SELECT 1
                                      FROM user_column AS attribute
                                     WHERE attribute.attrelid = relation.oid
                                       AND pg_catalog.has_column_privilege(
                                           reachable.role_oid,
                                           attribute.attrelid,
                                           attribute.attnum,
                                           'INSERT'
                                       )
                                )
                        )
                    )
                    OR (
                        COALESCE(required.allow_update, FALSE)
                        AND NOT pg_catalog.has_table_privilege(
                            target.oid,
                            relation.oid,
                            'UPDATE'
                        )
                    )
                    OR (
                        NOT COALESCE(required.allow_update, FALSE)
                        AND EXISTS (
                            SELECT 1
                              FROM reachable_role AS reachable
                             WHERE pg_catalog.has_table_privilege(
                                       reachable.role_oid,
                                       relation.oid,
                                       'UPDATE'
                                   )
                                OR EXISTS (
                                    SELECT 1
                                      FROM user_column AS attribute
                                     WHERE attribute.attrelid = relation.oid
                                       AND pg_catalog.has_column_privilege(
                                           reachable.role_oid,
                                           attribute.attrelid,
                                           attribute.attnum,
                                           'UPDATE'
                                       )
                                )
                        )
                    )
                    OR (
                        COALESCE(required.allow_delete, FALSE)
                        AND NOT pg_catalog.has_table_privilege(
                            target.oid,
                            relation.oid,
                            'DELETE'
                        )
                    )
                    OR (
                        NOT COALESCE(required.allow_delete, FALSE)
                        AND EXISTS (
                            SELECT 1
                              FROM reachable_role AS reachable
                             WHERE pg_catalog.has_table_privilege(
                                 reachable.role_oid,
                                 relation.oid,
                                 'DELETE'
                             )
                        )
                    )
                    OR (
                        COALESCE(required.forbid_references, FALSE)
                        AND EXISTS (
                            SELECT 1
                              FROM reachable_role AS reachable
                             WHERE pg_catalog.has_table_privilege(
                                       reachable.role_oid,
                                       relation.oid,
                                       'REFERENCES'
                                   )
                                OR EXISTS (
                                    SELECT 1
                                      FROM user_column AS attribute
                                     WHERE attribute.attrelid = relation.oid
                                       AND pg_catalog.has_column_privilege(
                                           reachable.role_oid,
                                           attribute.attrelid,
                                           attribute.attnum,
                                           'REFERENCES'
                                       )
                                )
                        )
                    )
                )
            )
            OR (
                relation.relkind <> 'm'
                AND required.relation_oid IS NULL
                AND (
                       NOT pg_catalog.has_table_privilege(
                           target.oid,
                           relation.oid,
                           'INSERT'
                       )
                    OR NOT pg_catalog.has_table_privilege(
                           target.oid,
                           relation.oid,
                           'UPDATE'
                       )
                    OR NOT pg_catalog.has_table_privilege(
                           target.oid,
                           relation.oid,
                           'DELETE'
                       )
                )
            )
    ),
    NOT EXISTS (
        SELECT 1
          FROM reachable_role AS reachable
          CROSS JOIN user_sequence AS sequence
         WHERE pg_catalog.has_sequence_privilege(
             reachable.role_oid,
             sequence.oid,
             'UPDATE'
         )
    ),
    EXISTS (SELECT 1 FROM target_role)
    AND NOT EXISTS (
        SELECT 1
          FROM target_role AS target
          CROSS JOIN user_sequence AS sequence
         WHERE NOT pg_catalog.has_sequence_privilege(
                   target.oid,
                   sequence.oid,
                   'USAGE'
               )
            OR NOT pg_catalog.has_sequence_privilege(
                   target.oid,
                   sequence.oid,
                   'SELECT'
               )
    ),
    NOT EXISTS (
        SELECT 1
          FROM current_database_record AS database
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(
                  database.datacl,
                  pg_catalog.acldefault(
                      'd'::pg_catalog."char",
                      database.datdba
                  )
              )
          ) AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
        UNION ALL
        SELECT 1
          FROM user_schema AS namespace
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(
                  namespace.nspacl,
                  pg_catalog.acldefault(
                      'n'::pg_catalog."char",
                      namespace.nspowner
                  )
              )
          ) AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
        UNION ALL
        SELECT 1
          FROM user_relation AS relation
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(
                  relation.relacl,
                  pg_catalog.acldefault(
                      'r'::pg_catalog."char",
                      relation.relowner
                  )
              )
          ) AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
        UNION ALL
        SELECT 1
          FROM user_column AS attribute
          CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl)
            AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
        UNION ALL
        SELECT 1
          FROM user_sequence AS sequence
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(
                  sequence.relacl,
                  pg_catalog.acldefault(
                      's'::pg_catalog."char",
                      sequence.relowner
                  )
              )
          ) AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
        UNION ALL
        SELECT 1
          FROM user_function AS procedure
          CROSS JOIN LATERAL pg_catalog.aclexplode(
              COALESCE(
                  procedure.proacl,
                  pg_catalog.acldefault(
                      'f'::pg_catalog."char",
                      procedure.proowner
                  )
              )
          ) AS privilege
         WHERE privilege.is_grantable
           AND (
               privilege.grantee = 0
               OR privilege.grantee IN (
                   SELECT reachable.role_oid FROM reachable_role AS reachable
               )
           )
    ),
    EXISTS (SELECT 1 FROM target_role)
    AND NOT EXISTS (
        SELECT 1
          FROM user_function AS procedure
         WHERE EXISTS (
                   SELECT 1
                     FROM pg_catalog.aclexplode(
                         COALESCE(
                             procedure.proacl,
                             pg_catalog.acldefault(
                                'f'::pg_catalog."char",
                                 procedure.proowner
                             )
                         )
                     ) AS privilege
                    WHERE privilege.grantee = 0
                      AND privilege.privilege_type = 'EXECUTE'
               )
            OR (
                EXISTS (
                    SELECT 1
                      FROM reachable_role AS reachable
                     WHERE pg_catalog.has_function_privilege(
                         reachable.role_oid,
                         procedure.oid,
                         'EXECUTE'
                     )
                )
                AND NOT EXISTS (
                    SELECT 1
                      FROM required_runtime_function AS required
                     WHERE required.procedure_oid = procedure.oid
                )
            )
    ),
    EXISTS (SELECT 1 FROM target_role)
    AND NOT EXISTS (
        SELECT 1
          FROM required_runtime_function AS required
          LEFT JOIN pg_catalog.pg_proc AS procedure
            ON procedure.oid = required.procedure_oid
          LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
         WHERE procedure.oid IS NULL
            OR namespace.nspname IS DISTINCT FROM 'public'
            OR NOT EXISTS (
                SELECT 1
                  FROM target_role AS target
                 WHERE pg_catalog.has_function_privilege(
                     target.oid,
                     procedure.oid,
                     'EXECUTE'
                 )
            )
    ),
    COALESCE(
        (SELECT target.rolname = CURRENT_USER FROM target_role AS target),
        FALSE
    ),
    COALESCE(
        (SELECT target.rolname = SESSION_USER FROM target_role AS target),
        FALSE
    ),
    COALESCE(
        (
            SELECT activity.usesysid = target.oid
              FROM target_role AS target
              JOIN pg_catalog.pg_stat_activity AS activity
                ON activity.pid = pg_catalog.pg_backend_pid()
        ),
        FALSE
    )
"""


class RuntimeDatabaseRoleProbeError(RuntimeError):
    """Raised when PostgreSQL does not return the fixed probe contract."""


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseRoleSafety:
    """Identifier-free result for one configured PostgreSQL runtime role.

    Attributes
    ----------
    role_exists
        The role exists retained in this immutable projection.
    can_login
        The can login retained in this immutable projection.
    attributes_safe
        The attributes safe retained in this immutable projection.
    memberships_safe
        The memberships safe retained in this immutable projection.
    database_ownership_safe
        The database ownership safe retained in this immutable projection.
    user_schema_ownership_safe
        The user schema ownership safe retained in this immutable projection.
    user_relation_ownership_safe
        The user relation ownership safe retained in this immutable projection.
    user_function_ownership_safe
        The user function ownership safe retained in this immutable projection.
    database_privileges_safe
        The database privileges safe retained in this immutable projection.
    user_schema_privileges_safe
        The user schema privileges safe retained in this immutable projection.
    table_privileges_safe
        The table privileges safe retained in this immutable projection.
    parameter_privileges_safe
        The parameter privileges safe retained in this immutable projection.
    role_settings_safe
        The role settings safe retained in this immutable projection.
    session_replication_role_is_origin
        The session replication role is origin retained in this immutable projection.
    database_connect_available
        The database connect available retained in this immutable projection.
    user_schema_usage_available
        The user schema usage available retained in this immutable projection.
    required_relation_privileges_available
        Whether every required relation privilege is available.
    sequence_privileges_safe
        The sequence privileges safe retained in this immutable projection.
    required_sequence_privileges_available
        Whether every required sequence privilege is available.
    grant_options_safe
        The grant options safe retained in this immutable projection.
    function_execute_boundary_safe
        The function execute boundary safe retained in this immutable projection.
    required_function_execute_available
        The required function execute available retained in this immutable projection.
    current_user_matches
        The current user matches retained in this immutable projection.
    session_user_matches
        The session user matches retained in this immutable projection.
    authenticated_user_matches
        The authenticated user matches retained in this immutable projection.
    """

    role_exists: bool
    can_login: bool
    attributes_safe: bool
    memberships_safe: bool
    database_ownership_safe: bool
    user_schema_ownership_safe: bool
    user_relation_ownership_safe: bool
    user_function_ownership_safe: bool
    database_privileges_safe: bool
    user_schema_privileges_safe: bool
    table_privileges_safe: bool
    parameter_privileges_safe: bool
    role_settings_safe: bool
    session_replication_role_is_origin: bool
    database_connect_available: bool
    user_schema_usage_available: bool
    required_relation_privileges_available: bool
    sequence_privileges_safe: bool
    required_sequence_privileges_available: bool
    grant_options_safe: bool
    function_execute_boundary_safe: bool
    required_function_execute_available: bool
    current_user_matches: bool
    session_user_matches: bool
    authenticated_user_matches: bool

    @property
    def target_role_is_safe(self) -> bool:
        """Return whether the named role is suitable for runtime use.

        Returns
        -------
        bool
            `True` when the named role is suitable for runtime use; otherwise
            `False`.
        """
        return all(
            (
                self.role_exists,
                self.can_login,
                self.attributes_safe,
                self.memberships_safe,
                self.database_ownership_safe,
                self.user_schema_ownership_safe,
                self.user_relation_ownership_safe,
                self.user_function_ownership_safe,
                self.database_privileges_safe,
                self.user_schema_privileges_safe,
                self.table_privileges_safe,
                self.parameter_privileges_safe,
                self.role_settings_safe,
                self.session_replication_role_is_origin,
                self.database_connect_available,
                self.user_schema_usage_available,
                self.required_relation_privileges_available,
                self.sequence_privileges_safe,
                self.required_sequence_privileges_available,
                self.grant_options_safe,
                self.function_execute_boundary_safe,
                self.required_function_execute_available,
            )
        )

    @property
    def current_session_is_safe(self) -> bool:
        """Return whether this connection is the proved runtime role.

        Returns
        -------
        bool
            `True` when this connection is the proved runtime role; otherwise
            `False`.
        """
        return self.target_role_is_safe and all(
            (
                self.current_user_matches,
                self.session_user_matches,
                self.authenticated_user_matches,
            )
        )


def probe_runtime_database_role_safety(
    *,
    role_name: str,
    using: str = "default",
) -> RuntimeDatabaseRoleSafety:
    """Inspect ``role_name`` without assuming the current session uses it.

    The role name, restricted relation profiles, and required function
    identities are bound query values.  The result intentionally contains no
    role, owner, relation, setting, ACL, or credential name.

    Parameters
    ----------
    role_name : str
        The human-readable role name shown to authorized readers.
    using : str, default='default'
        The Django database alias on which to perform the operation.

    Returns
    -------
    RuntimeDatabaseRoleSafety
        The RuntimeDatabaseRoleSafety produced by probe runtime database role
        safety.

    Raises
    ------
    RuntimeDatabaseRoleProbeError
        If the operation encounters a runtime database role probe condition.
    """
    database: BaseDatabaseWrapper = connections[using]
    with database.cursor() as cursor:
        cursor.execute(
            _RUNTIME_DATABASE_ROLE_SAFETY_QUERY,
            [
                role_name,
                list(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS),
                list(RUNTIME_DATABASE_SELECT_INSERT_RELATIONS),
                list(RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS),
                list(RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS),
                list(RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS),
                list(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3),
            ],
        )
        row = cursor.fetchone()

    if (
        row is None
        or len(row) != _RUNTIME_DATABASE_ROLE_RESULT_FIELD_COUNT
        or any(type(value) is not bool for value in row)
    ):
        raise RuntimeDatabaseRoleProbeError(
            "PostgreSQL returned an invalid runtime-role safety result."
        )
    return RuntimeDatabaseRoleSafety(*cast("tuple[bool, ...]", tuple(row)))
