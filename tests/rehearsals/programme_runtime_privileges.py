"""Closed candidate table privileges, never production ACLs or a probe substitute.

The actual native role-safety query remains unchanged. An explicit isolated child
installs these declared relation classes before calling that real query. The
fixture provisioner grants the same reviewed table privileges, thirteen literal
invoker helpers and one reviewed advisory-lock helper in its owned empty database;
never ownership, DDL,
unlisted execution or grant options. Native owner readiness still checks every
source/metadata boundary against an explicitly validated baseline contract.
"""

from types import MappingProxyType

from maru.authorization import database_role_safety as owner
from maru.events import adoption
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.rehearsals.programme_function_contract import (
    HELPERS,
    candidate_function_contracts,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)


def _tables(groups):
    return frozenset(
        f"public.{module}_{name}" for module, names in groups.items() for name in names
    )


# Retained evidence never updated or locked by the mounted owner commands.
INSERT = _tables(
    {
        "events": ("programmeadoptionsetupreceipt",),
        "authorization": ("programmeroledecisionrecord",),
        "applications": (
            "programmeproposalselectionrevision",
            "programmeproposalcollaboratortransition",
            "programmeproposalrevisionanswer",
            "programmeproposalrevisionresponse",
            "programmecommandreceipt",
            "programmereviewpolicy",
            "programmereviewentry",
            "programmereviewdecision",
            "programmedecisionacknowledgement",
            "programmereviewreceipt",
            "programmeacceptedtransition",
            "programmefileintake",
            "programmefilecontent",
        ),
        "programme": (
            "programmeitemsourcebinding",
            "programmepublicrendition",
            "programmepublicrenditionwithdrawal",
            "programmehostinvitation",
            "programmehostrevision",
            "programmestaffingrevision",
            "programmeplacementdecision",
        ),
        "workforce": ("programmeshiftbindingrevision",),
        "venues": ("venueschedulingbinding",),
        "scheduling": (
            "schedulingservicedayrevision",
            "schedulingoccurrencerevision",
            "schedulingcandidaterevision",
            "schedulingplacementrevision",
            "schedulingcandidatemember",
            "schedulingplacementhostpresence",
            "schedulingevaluation",
            "schedulingconflict",
            "schedulingwarningacknowledgement",
            "schedulingreservationintent",
            "schedulingcommandreceipt",
            "schedulingreleasewarningacknowledgement",
            "schedulingreleaseapproval",
            "schedulingreleaseapprovalplacement",
            "schedulingreleaseapprovaldependency",
            "schedulingrelease",
            "schedulingreleaseartifact",
            "schedulingreleasewithdrawal",
            "schedulingchangenotice",
            "schedulingchangenoticeevidence",
        ),
    }
)
# UPDATE also permits SELECT FOR UPDATE on retained sources. Their native
# immutable-history guards remain mandatory and reject actual history edits.
INSERT_UPDATE = _tables(
    {
        "authorization": ("programmerolerequest",),
        "applications": (
            "programmecall",
            "programmeproposal",
            "programmeproposalcollaborator",
            "programmeproposalrevision",
            "programmeproposalrevisioncontributor",
            # The contributor-response command locks this joined revision too.
            "programmeproposalcontributorprofilerevision",
            "programmeimportbatch",
            "programmeimportitem",
            "programmeimportpreviewrevision",
            "programmeimportpreviewitemresult",
            "programmeimportsourcebinding",
            "programmeimportappliedcommand",
            "programmeimportcommandreceipt",
            "programmereviewcase",
            "programmereviewassignment",
        ),
        "programme": (
            "programmeeditioncontrol",
            "programmeitem",
            "programmeworkingrevision",
            "programmedeliveryrevision",
            "programmedepartmentdiscussionentry",
            "programmereadinessrequirement",
            "programmereadinessrequirementrevision",
            "programmereadinessevidence",
            "programmecommandreceipt",
            "programmehostrelationship",
            "programmestaffingrequirement",
        ),
        "workforce": ("programmeshiftbinding",),
        "scheduling": (
            "schedulingeditioncontrol",
            "schedulingserviceday",
            "schedulingoccurrence",
            "schedulingcandidate",
            "schedulingreleasedependencykey",
            "schedulingreleasepointer",
        ),
    }
)
INSERT_DELETE = _tables(
    {
        "applications": ("programmecallcontributorfield",),
        "programme": ("programmehostavailabilitywindow",),
    }
)
# Draft replacement deletes track/format rows; proposal admission locks them.
INSERT_UPDATE_DELETE = _tables(
    {"applications": ("programmecalltrack", "programmecallformat")}
)
PRIVILEGES = MappingProxyType(
    {
        **dict.fromkeys(INSERT, ("INSERT",)),
        **dict.fromkeys(INSERT_UPDATE, ("INSERT", "UPDATE")),
        **dict.fromkeys(INSERT_DELETE, ("INSERT", "DELETE")),
        **dict.fromkeys(INSERT_UPDATE_DELETE, ("INSERT", "UPDATE", "DELETE")),
    }
)
_NAMES = (
    "RUNTIME_DATABASE_SELECT_ONLY_RELATIONS",
    "RUNTIME_DATABASE_SELECT_INSERT_RELATIONS",
    "RUNTIME_DATABASE_SELECT_UPDATE_RELATIONS",
    "RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS",
    "RUNTIME_DATABASE_SELECT_INSERT_DELETE_RELATIONS",
)
_BASELINE = tuple(getattr(owner, name) for name in _NAMES)
_QUERY = owner._RUNTIME_DATABASE_ROLE_SAFETY_QUERY
_FUNCTIONS = owner.RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4


class ProgrammePrivilegeError(RuntimeError):
    """Expose a stable contract error, never role, credential or database contents."""


def candidate_relation_classes():
    """Project literal candidate classes while preserving every unrelated limit.

    Returns
    -------
    tuple
        The same five native-probe input classes; only named dormant tables move.
        CRUD tables use the existing ordinary-table class. Their REFERENCES
        privilege remains denied and is checked separately at candidate startup.
    """
    targets = set(PRIVILEGES)
    if (
        sum(map(len, (INSERT, INSERT_UPDATE, INSERT_DELETE, INSERT_UPDATE_DELETE)))
        != len(targets)
        or not targets <= set(_BASELINE[0])
        or any(targets & set(group) for group in _BASELINE[1:])
    ):
        raise ProgrammePrivilegeError("candidate_privilege_contract_changed")
    return (
        tuple(table for table in _BASELINE[0] if table not in targets),
        (*_BASELINE[1], *sorted(INSERT)),
        _BASELINE[2],
        (*_BASELINE[3], *sorted(INSERT_UPDATE)),
        (*_BASELINE[4], *sorted(INSERT_DELETE)),
    )


def install_isolated_candidate_privilege_contract():
    """Install explicit native expectations only in the opted-in candidate child."""
    require_programme_runtime_environment()
    if (
        adoption.ADOPTION_PROFILES.get(PROGRAMME_REHEARSAL_PROFILE.key)
        is not PROGRAMME_REHEARSAL_PROFILE
        or tuple(getattr(owner, name) for name in _NAMES) != _BASELINE
        or owner._RUNTIME_DATABASE_ROLE_SAFETY_QUERY != _QUERY
        or owner.RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4 != _FUNCTIONS
    ):
        raise ProgrammePrivilegeError("candidate_privilege_baseline_changed")
    classes = candidate_relation_classes()
    function_contracts = candidate_function_contracts()
    functions = (*_FUNCTIONS, *("public." + identity for identity in sorted(HELPERS)))
    for name, relations in zip(_NAMES, classes, strict=True):
        setattr(owner, name, relations)
    owner.RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V4 = functions
    for module, attribute, _original, projected in function_contracts:
        setattr(module, attribute, projected)


def require_candidate_reference_boundary(cursor):
    """Keep table and column REFERENCES denied on every reclassified relation."""
    cursor.execute(
        "SELECT count(*) = %s AND bool_and(NOT EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_roles AS reachable WHERE "
        "(reachable.rolname = current_user OR "
        "pg_catalog.pg_has_role(current_user, reachable.oid, 'SET')) AND ("
        "pg_catalog.has_table_privilege(reachable.oid, relation.oid, 'REFERENCES') "
        "OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS attribute "
        "WHERE attribute.attrelid = relation.oid AND attribute.attnum > 0 "
        "AND NOT attribute.attisdropped AND pg_catalog.has_column_privilege("
        "reachable.oid, relation.oid, attribute.attnum, 'REFERENCES'))))) "
        "FROM pg_catalog.pg_class AS relation "
        "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relnamespace "
        "WHERE namespace.nspname = 'public' "
        "AND ('public.' || relation.relname) = ANY(%s)",
        [len(PRIVILEGES), sorted(PRIVILEGES)],
    )
    if cursor.fetchone() != (True,):
        raise ProgrammePrivilegeError("candidate_reference_privilege_changed")
