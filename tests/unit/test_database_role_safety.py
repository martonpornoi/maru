from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps

from maru.authorization import provenance_readiness
from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1,
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2,
    RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3,
    RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
    RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
    RuntimeDatabaseRoleProbeError,
    RuntimeDatabaseRoleSafety,
    probe_runtime_database_role_safety,
)

_BOUNDED_DOMAIN_APP_LABELS = ("applications", "charities", "catalog", "venues")
_APPLICATION_DRAFT_CHILD_RELATIONS = {
    "public.applications_applicationownerdepartment",
    "public.applications_applicationreviewerrole",
    "public.applications_applicationreviewerperson",
    "public.applications_applicationsection",
    "public.applications_applicationquestion",
}


def test_runtime_relation_privilege_profiles_are_exact_and_disjoint() -> None:
    assert RUNTIME_DATABASE_SELECT_ONLY_RELATIONS == (
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
    assert RUNTIME_DATABASE_SELECT_INSERT_RELATIONS == (
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
    assert RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS == (
        "public.identity_platformaccountinventorycontrol",
    )
    assert RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS == (
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
    assert RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS == (
        "public.workforce_personavailabilitywindow",
    )
    profiles = (
        set(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_INSERT_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS),
        set(RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS),
    )
    assert all(
        not left & right
        for index, left in enumerate(profiles)
        for right in profiles[index + 1 :]
    )
    assert "public.workforce_department" not in set().union(*profiles)


def test_dormant_programme_relations_are_completely_select_only() -> None:
    programme_relations = {
        f"public.{model._meta.db_table}"
        for model in apps.get_app_config("programme").get_models()
    }
    select_only_programme_relations = {
        identity
        for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
        if identity.startswith("public.programme_")
    }
    runtime_dml_relations = set().union(
        RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
        RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
        RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
        RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS,
    )

    assert programme_relations == select_only_programme_relations
    assert not programme_relations & runtime_dml_relations


def test_applications_programme_relations_are_completely_select_only() -> None:
    programme_relations = {
        f"public.{model._meta.db_table}"
        for model in apps.get_app_config("applications").get_models()
        if model.__name__.startswith("Programme")
    }
    select_only_relations = set(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS)
    runtime_dml_relations = set().union(
        RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
        RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
        RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
        RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS,
    )

    assert len(programme_relations) == 21
    assert programme_relations <= select_only_relations
    assert not programme_relations & runtime_dml_relations


def test_bounded_domain_relation_lifecycles_are_completely_classified() -> None:
    bounded_relations = {
        f"public.{model._meta.db_table}"
        for app_label in _BOUNDED_DOMAIN_APP_LABELS
        for model in apps.get_app_config(app_label).get_models()
    }
    append_only_relations = {
        identity
        for identity in RUNTIME_DATABASE_SELECT_INSERT_RELATIONS
        if identity.split(".", 1)[1].startswith(_BOUNDED_DOMAIN_APP_LABELS)
    }
    retained_aggregate_relations = {
        identity
        for identity in RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS
        if identity.split(".", 1)[1].startswith(_BOUNDED_DOMAIN_APP_LABELS)
    }
    select_only_bounded_relations = {
        identity
        for identity in RUNTIME_DATABASE_SELECT_ONLY_RELATIONS
        if identity.split(".", 1)[1].startswith(_BOUNDED_DOMAIN_APP_LABELS)
    }

    assert len(append_only_relations) == 18
    assert len(retained_aggregate_relations) == 24
    assert not append_only_relations & retained_aggregate_relations
    assert bounded_relations == (
        append_only_relations
        | retained_aggregate_relations
        | _APPLICATION_DRAFT_CHILD_RELATIONS
        | select_only_bounded_relations
    )
    assert (
        not (append_only_relations | retained_aggregate_relations)
        & _APPLICATION_DRAFT_CHILD_RELATIONS
    )
    assert len(select_only_bounded_relations) == 21
    assert not select_only_bounded_relations & (
        append_only_relations
        | retained_aggregate_relations
        | _APPLICATION_DRAFT_CHILD_RELATIONS
    )


def test_v2_function_allowlist_preserves_frozen_v1_and_adds_latch_helper() -> None:
    assert len(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1) == 18
    assert RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2[:-1] == (
        RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V1
    )


def test_v3_function_allowlist_preserves_v2_and_adds_operator_helpers() -> None:
    assert RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3[:-2] == (
        RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2
    )
    assert RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3[-2:] == (
        "public.maru_assert_active_maru_operators(uuid)",
        "public.maru_assert_active_maru_operators_v0009(uuid)",
    )


def test_every_v3_runtime_function_has_a_readiness_definition_fingerprint() -> None:
    def normalize(identity: str) -> str:
        return identity.removeprefix("public.").replace(
            "timestamp with time zone",
            "timestamptz",
        )

    allowlisted = {
        normalize(identity)
        for identity in RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3
    }

    assert allowlisted <= set(provenance_readiness._CORE_FUNCTIONS)
    assert allowlisted <= set(provenance_readiness._FUNCTION_DEFINITION_SHA256)
    assert len(allowlisted) == len(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3)


def _result(**overrides: bool) -> RuntimeDatabaseRoleSafety:
    values = {
        "role_exists": True,
        "can_login": True,
        "attributes_safe": True,
        "memberships_safe": True,
        "database_ownership_safe": True,
        "user_schema_ownership_safe": True,
        "user_relation_ownership_safe": True,
        "user_function_ownership_safe": True,
        "database_privileges_safe": True,
        "user_schema_privileges_safe": True,
        "table_privileges_safe": True,
        "parameter_privileges_safe": True,
        "role_settings_safe": True,
        "session_replication_role_is_origin": True,
        "database_connect_available": True,
        "user_schema_usage_available": True,
        "required_relation_privileges_available": True,
        "sequence_privileges_safe": True,
        "required_sequence_privileges_available": True,
        "grant_options_safe": True,
        "function_execute_boundary_safe": True,
        "required_function_execute_available": True,
        "current_user_matches": True,
        "session_user_matches": True,
        "authenticated_user_matches": True,
    }
    values.update(overrides)
    return RuntimeDatabaseRoleSafety(**values)


def test_result_separates_future_role_proof_from_current_session_match() -> None:
    future_role = _result(current_user_matches=False)

    assert future_role.target_role_is_safe
    assert not future_role.current_session_is_safe

    for field in (
        "role_exists",
        "can_login",
        "attributes_safe",
        "memberships_safe",
        "database_ownership_safe",
        "user_schema_ownership_safe",
        "user_relation_ownership_safe",
        "user_function_ownership_safe",
        "database_privileges_safe",
        "user_schema_privileges_safe",
        "table_privileges_safe",
        "parameter_privileges_safe",
        "role_settings_safe",
        "session_replication_role_is_origin",
        "database_connect_available",
        "user_schema_usage_available",
        "required_relation_privileges_available",
        "sequence_privileges_safe",
        "required_sequence_privileges_available",
        "grant_options_safe",
        "function_execute_boundary_safe",
        "required_function_execute_available",
    ):
        assert not _result(**{field: False}).target_role_is_safe

    for field in (
        "current_user_matches",
        "session_user_matches",
        "authenticated_user_matches",
    ):
        assert _result(**{field: False}).target_role_is_safe
        assert not _result(**{field: False}).current_session_is_safe


@patch("maru.authorization.database_role_safety.connections")
def test_probe_binds_the_role_and_required_function_identities(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True,) * 25
    injected_name = "role' OR TRUE --"

    result = probe_runtime_database_role_safety(
        role_name=injected_name,
        using="security",
    )

    query, parameters = cursor.__enter__.return_value.execute.call_args.args
    assert injected_name not in query
    assert parameters == [
        injected_name,
        list(RUNTIME_DATABASE_SELECT_ONLY_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_INSERT_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS),
        list(RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS),
        list(RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3),
    ]
    configured_connections.__getitem__.assert_called_once_with("security")
    assert result.current_session_is_safe


@patch("maru.authorization.database_role_safety.connections")
def test_probe_query_covers_identity_integrity_and_nondelegation_boundaries(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True,) * 25

    probe_runtime_database_role_safety(role_name="maru_runtime")

    query = cursor.__enter__.return_value.execute.call_args.args[0]
    assert "SESSION_USER" in query
    assert "pg_stat_activity" in query
    assert "pg_backend_pid()" in query
    assert "lower(target.rolname) LIKE 'pg\\_%%'" in query
    assert "pg_parameter_acl" in query
    assert "pg_db_role_setting" in query
    assert "current_setting('session_replication_role'" in query
    assert "membership.admin_option" in query
    assert "privilege.is_grantable" in query
    assert "has_sequence_privilege" in query
    assert "'UPDATE'" in query
    assert "'REFERENCES'" in query
    assert "FALSE,\n        FALSE,\n        FALSE,\n        TRUE" in query
    for identity in (
        *RUNTIME_DATABASE_SELECT_ONLY_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
        *RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
        *RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS,
    ):
        assert identity not in query


@patch("maru.authorization.database_role_safety.connections")
def test_probe_rejects_an_unexpected_catalog_shape(
    configured_connections: MagicMock,
) -> None:
    cursor = configured_connections.__getitem__.return_value.cursor.return_value
    cursor.__enter__.return_value.fetchone.return_value = (True, False)

    with pytest.raises(RuntimeDatabaseRoleProbeError, match="invalid"):
        probe_runtime_database_role_safety(role_name="maru_runtime")
