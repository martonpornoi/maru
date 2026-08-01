"""Privacy and deployment-readiness evidence for ADR 0044 provenance."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from itertools import pairwise
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.utils import timezone

from maru.authorization import provenance_readiness
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.issuance import (
    create_delegated_grant_issuance,
    create_persistent_dual_control_issuance,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.provenance_readiness import BLOCKER_KEYS, REVIEW_KEYS
from maru.identity.models import Account
from tests.factories import AccountFactory, EventEditionFactory, OrganizationFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _run_readiness(*, no_fail: bool = True) -> tuple[str, dict[str, Any]]:
    output = StringIO()
    arguments = ("--no-fail",) if no_fail else ()
    call_command(
        "check_authority_provenance_readiness",
        *arguments,
        stdout=output,
    )
    rendered = output.getvalue()
    return rendered, json.loads(rendered)


def _empty_report() -> dict[str, object]:
    return {
        "status": "ready",
        "production_status": "blocked",
        "blocker_counts": dict.fromkeys(BLOCKER_KEYS, 0),
        "blocker_total": 0,
        "review_counts": dict.fromkeys(REVIEW_KEYS, 0),
        "known_production_gates": {
            "exact_lineage_policy_cutover": "unresolved",
            "database_completeness_guards": "unresolved",
            "provenance_write_downgrade_fence": "unresolved",
        },
    }


def _board() -> tuple[object, Account, Account]:
    organization = OrganizationFactory()
    actor, approver = activate_synthetic_board(organization)
    return organization, actor, approver


def _board_source(controller: Account) -> AuthorityIssuance:
    return AuthorityIssuance.objects.get(
        role_assignment__principal=controller,
        role_assignment__role_bundle__code="executive-board",
    )


def test_clean_executive_board_graph_is_data_ready_but_activation_blocked() -> None:
    _organization, _actor, _approver = _board()

    first_rendered, first = _run_readiness()
    second_rendered, second = _run_readiness()

    assert first == _empty_report()
    assert second == first
    assert second_rendered == first_rendered
    assert "@" not in first_rendered
    assert "principal" not in first_rendered
    assert "capability_code" not in first_rendered


def test_unproven_open_authority_blocks_but_dead_unused_legacy_is_review_only() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    private_capability = "events.view_basic"
    private_reason = "Readiness must never print this entered reason."

    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=private_capability,
        effective_from=now + timedelta(days=2),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=private_capability,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    old_bundle = RoleBundle.objects.create(
        organization=organization,
        code="private-readiness-role",
        name="Private readiness old role",
        version=1,
        capability_codes=[private_capability],
        created_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    RoleBundle.objects.create(
        organization=organization,
        code="private-readiness-role",
        name="Private readiness current role",
        version=2,
        capability_codes=[private_capability],
        created_by=actor,
        approved_by=approver,
        reason=private_reason,
    )
    RoleAssignment.objects.create(
        organization=organization,
        principal=recipient,
        role_bundle=old_bundle,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        granted_by=actor,
        approved_by=approver,
        reason=private_reason,
    )

    rendered, report = _run_readiness()

    assert report["status"] == "blocked"
    assert report["production_status"] == "blocked"
    assert (
        report["blocker_counts"]["effective_or_future_root_grant_missing_issuance"] == 1
    )
    assert (
        report["blocker_counts"][
            "referenced_or_assignable_role_bundle_missing_issuance"
        ]
        == 1
    )
    assert (
        report["review_counts"]["expired_or_revoked_root_grant_missing_issuance"] == 1
    )
    assert (
        report["review_counts"]["expired_or_revoked_role_assignment_missing_issuance"]
        == 1
    )
    assert report["review_counts"]["unused_role_bundle_missing_issuance"] == 1
    assert recipient.email not in rendered
    assert str(recipient.id) not in rendered
    assert organization.name not in rendered
    assert private_capability not in rendered
    assert private_reason not in rendered

    failing_output = StringIO()
    with pytest.raises(CommandError, match="Authority provenance blockers detected"):
        call_command("check_authority_provenance_readiness", stdout=failing_output)
    assert json.loads(failing_output.getvalue()) == report


def test_delegated_gaps_and_preserved_broad_bootstrap_are_counted() -> None:
    organization = OrganizationFactory()
    platform = AccountFactory(is_staff=True, is_superuser=True)
    chair = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=chair,
        capability_code="events.view_basic",
        effective_from=now,
        granted_by=platform,
        approved_by=chair,
        reason="Synthetic preserved parent.",
    )
    CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=parent.capability_code,
        effective_from=now,
        granted_by=chair,
        delegated_from=parent,
        reason="Synthetic delegated gap.",
    )
    broad_bundle = RoleBundle.objects.create(
        organization=organization,
        code="authority-controller",
        name="Synthetic preserved broad bootstrap",
        version=1,
        capability_codes=["authorization.manage_roles"],
        created_by=platform,
        approved_by=chair,
        reason="Synthetic preserved broad bootstrap.",
    )
    RoleAssignment.objects.create(
        organization=organization,
        principal=chair,
        role_bundle=broad_bundle,
        effective_from=now,
        granted_by=platform,
        approved_by=platform,
        reason="Synthetic preserved broad assignment.",
    )

    _rendered, report = _run_readiness()

    assert (
        report["blocker_counts"]["effective_or_future_delegated_grant_missing_issuance"]
        == 1
    )
    assert report["blocker_counts"]["delegated_grant_parent_missing_issuance"] == 1
    assert report["review_counts"]["preserved_broad_workforce_bootstrap_signature"] == 1


def test_incomplete_and_raw_identity_mismatch_are_classified_without_values() -> None:
    organization, actor, approver = _board()
    recipient = AccountFactory()
    evaluated_at = timezone.now()
    incomplete = CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Private incomplete evidence.",
    )
    AuthorityIssuance.objects.create(
        capability_grant=incomplete,
        policy_version=POLICY_VERSION,
        evaluated_at=evaluated_at,
    )

    complete = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code="organizations.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Private raw mismatch evidence.",
    )
    complete_issuance = create_persistent_dual_control_issuance(
        target=complete,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=evaluated_at,
    )
    actor_control = AuthorityControl.objects.get(
        issuance=complete_issuance,
        role=AuthorityControl.Role.ACTOR,
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_immutable"
            )
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_insert_guard"
            )
            cursor.execute(
                "UPDATE authorization_authoritycontrol SET principal_id = %s "
                "WHERE id = %s",
                [recipient.id, actor_control.id],
            )
        rendered, report = _run_readiness()
        assert report["blocker_counts"]["incomplete_control_set"] == 1
        assert report["blocker_counts"]["control_identity_mismatch"] == 1
        assert recipient.email not in rendered
        assert str(recipient.id) not in rendered
        assert complete.capability_code not in rendered
        transaction.set_rollback(True)


def test_raw_non_earlier_delegated_parent_is_a_data_blocker() -> None:
    organization = OrganizationFactory()
    delegator = AccountFactory()
    recipient = AccountFactory()
    controller = AccountFactory()
    evaluated_at = timezone.now()
    parent = CapabilityGrant.objects.create(
        organization=organization,
        principal=delegator,
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        granted_by=controller,
        approved_by=AccountFactory(),
        reason="Synthetic malformed parent order.",
    )
    child = CapabilityGrant.objects.create(
        organization=organization,
        principal=recipient,
        capability_code=parent.capability_code,
        effective_from=evaluated_at,
        granted_by=delegator,
        delegated_from=parent,
        reason="Synthetic malformed child order.",
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authorityissuance DISABLE TRIGGER "
                "authorization_authority_issuance_insert_guard"
            )
            cursor.execute(
                "INSERT INTO authorization_authorityissuance "
                "(public_id, policy_version, evaluated_at, capability_grant_id, "
                "role_bundle_id, role_assignment_id, created_at) "
                "VALUES (%s, %s, %s, %s, NULL, NULL, %s) RETURNING ordinal",
                [uuid4(), POLICY_VERSION, evaluated_at, child.id, evaluated_at],
            )
            child_ordinal = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO authorization_authorityissuance "
                "(public_id, policy_version, evaluated_at, capability_grant_id, "
                "role_bundle_id, role_assignment_id, created_at) "
                "VALUES (%s, %s, %s, %s, NULL, NULL, %s) RETURNING ordinal",
                [uuid4(), POLICY_VERSION, evaluated_at, parent.id, evaluated_at],
            )
            parent_ordinal = cursor.fetchone()[0]

        _rendered, report = _run_readiness()

        assert parent_ordinal > child_ordinal
        assert report["status"] == "blocked"
        assert report["blocker_counts"]["control_source_not_earlier"] == 1
        assert report["blocker_counts"]["malformed_lineage"] >= 1
        transaction.set_rollback(True)


def test_raw_control_metadata_mismatch_is_classified() -> None:
    organization, actor, approver = _board()
    target = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by=actor,
        approved_by=approver,
        reason="Synthetic metadata mismatch.",
    )
    issuance = create_persistent_dual_control_issuance(
        target=target,
        actor_source=_board_source(actor),
        approver_source=_board_source(approver),
        evaluated_at=target.effective_from,
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_immutable"
            )
            cursor.execute(
                "ALTER TABLE authorization_authoritycontrol DISABLE TRIGGER "
                "authorization_authority_control_insert_guard"
            )
            cursor.execute(
                "UPDATE authorization_authoritycontrol "
                "SET policy_version = %s WHERE issuance_id = %s AND role = %s",
                [
                    "synthetic-mismatched-policy",
                    issuance.ordinal,
                    AuthorityControl.Role.ACTOR,
                ],
            )

        _rendered, report = _run_readiness()

        assert report["status"] == "blocked"
        assert report["blocker_counts"]["control_metadata_mismatch"] == 1
        transaction.set_rollback(True)


def test_corrupt_legacy_snapshots_are_classified_without_mutating_evidence() -> None:  # noqa: PLR0915
    organization, actor, approver = _board()
    evaluated_at = timezone.now()
    actor_board = _board_source(actor)
    approver_board = _board_source(approver)

    def issue(
        *,
        principal: Account,
        capability_code: str,
        granted_by: Account,
        approved_by: Account,
        actor_source: AuthorityIssuance,
        approver_source: AuthorityIssuance,
        edition=None,  # type: ignore[no-untyped-def]
        expires_at=None,  # type: ignore[no-untyped-def]
    ) -> tuple[CapabilityGrant, AuthorityIssuance]:
        grant = CapabilityGrant.objects.create(
            organization=organization,
            edition=edition,
            principal=principal,
            capability_code=capability_code,
            effective_from=evaluated_at,
            expires_at=expires_at,
            granted_by=granted_by,
            approved_by=approved_by,
            reason="Synthetic readiness graph evidence.",
        )
        issuance = create_persistent_dual_control_issuance(
            target=grant,
            actor_source=actor_source,
            approver_source=approver_source,
            evaluated_at=evaluated_at,
        )
        return grant, issuance

    actor_root, actor_root_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
    )
    _approver_root, approver_root_issuance = issue(
        principal=approver,
        capability_code="authorization.grant_direct",
        granted_by=approver,
        approved_by=actor,
        actor_source=approver_board,
        approver_source=actor_board,
    )
    _wrong_capability, wrong_capability_issuance = issue(
        principal=actor,
        capability_code="events.view_basic",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
    )
    edition = EventEditionFactory(series__organization=organization)
    _edition_source, edition_source_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
        edition=edition,
    )
    _bounded_source, bounded_source_issuance = issue(
        principal=actor,
        capability_code="authorization.grant_direct",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_board,
        approver_source=approver_board,
        expires_at=evaluated_at + timedelta(days=1),
    )
    target, target_issuance = issue(
        principal=AccountFactory(),
        capability_code="events.view_basic",
        granted_by=actor,
        approved_by=approver,
        actor_source=actor_root_issuance,
        approver_source=approver_root_issuance,
    )
    delegated = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=target.capability_code,
        effective_from=evaluated_at,
        granted_by=target.principal,
        delegated_from=target,
        reason="Synthetic delegated readiness evidence.",
    )
    delegated_issuance = create_delegated_grant_issuance(
        grant=delegated,
        evaluated_at=evaluated_at,
    )

    base = provenance_readiness._AuthorityGraph(
        at=evaluated_at + timedelta(microseconds=1)
    )
    assert not {
        key: value for key, value in base.structural_blocker_counts().items() if value
    }

    target_ordinal = target_issuance.ordinal

    def target_actor_control(candidate):  # type: ignore[no-untyped-def]
        return next(
            control
            for control in candidate.controls_by_issuance[target_ordinal]
            if control["role"] == AuthorityControl.Role.ACTOR
        )

    cases: list[tuple[str, provenance_readiness._AuthorityGraph, dict[str, int]]] = []

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        approver_root_issuance.ordinal
    )
    cases.append(("foreign source", candidate, {"control_source_foreign": 1}))

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        wrong_capability_issuance.ordinal
    )
    cases.append(
        (
            "wrong capability",
            candidate,
            {"control_source_capability_mismatch": 1},
        )
    )

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        edition_source_issuance.ordinal
    )
    cases.append(("narrow scope", candidate, {"control_source_scope_mismatch": 1}))

    candidate = deepcopy(base)
    candidate.grants[target.id]["resource_binding_id"] = uuid4()
    cases.append(
        (
            "resource without department",
            candidate,
            {"control_source_not_current": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    candidate.grants[target.id]["department_id"] = uuid4()
    cases.append(
        (
            "department without edition",
            candidate,
            {"control_source_not_current": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    target_actor_control(candidate)["source_issuance_id"] = (
        bounded_source_issuance.ordinal
    )
    cases.append(("short horizon", candidate, {"control_source_horizon_mismatch": 1}))

    candidate = deepcopy(base)
    target_actor_control(candidate)["policy_version"] = "synthetic-mismatch"
    cases.append(("control metadata", candidate, {"control_metadata_mismatch": 1}))

    candidate = deepcopy(base)
    candidate.issuances[target_ordinal]["policy_version"] = ""
    cases.append(
        (
            "issuance metadata",
            candidate,
            {"control_metadata_mismatch": 1, "malformed_lineage": 1},
        )
    )

    candidate = deepcopy(base)
    board_actor_control = next(
        control
        for control in candidate.controls_by_issuance[actor_board.ordinal]
        if control["role"] == AuthorityControl.Role.ACTOR
    )
    board_actor_control["representation_id"] = uuid4()
    cases.append(
        (
            "Board ceremony",
            candidate,
            {"invalid_board_ceremony_basis": 1},
        )
    )

    candidate = deepcopy(base)
    excess_control = deepcopy(target_actor_control(candidate))
    excess_control.update(id=uuid4(), issuance_id=delegated_issuance.ordinal)
    candidate.controls_by_issuance[delegated_issuance.ordinal].append(excess_control)
    cases.append(
        (
            "delegated excess controls",
            candidate,
            {"delegated_grant_excess_controls": 1},
        )
    )

    candidate = deepcopy(base)
    candidate.issuance_by_grant.pop(target.id)
    cases.append(
        (
            "delegated parent missing",
            candidate,
            {
                "delegated_grant_parent_missing_issuance": 1,
                "malformed_lineage": 1,
            },
        )
    )

    candidate = deepcopy(base)
    duplicate_ordinal = max(int(value) for value in candidate.issuances) + 1
    duplicate_issuance = deepcopy(candidate.issuances[target_ordinal])
    duplicate_issuance["ordinal"] = duplicate_ordinal
    candidate.issuances[duplicate_ordinal] = duplicate_issuance
    candidate.duplicate_target_issuance_ordinals.update(
        {target_ordinal, duplicate_ordinal}
    )
    cases.append(
        (
            "duplicate target issuance",
            candidate,
            {"target_issuance_shape_mismatch": 2},
        )
    )

    candidate = deepcopy(base)
    duplicate_control = deepcopy(target_actor_control(candidate))
    duplicate_control["id"] = uuid4()
    candidate.controls_by_issuance[target_ordinal].append(duplicate_control)
    cases.append(
        (
            "duplicate control role",
            candidate,
            {"incomplete_control_set": 1, "duplicate_control_role": 1},
        )
    )

    target_scope = (organization.id, None, None, None)
    assert not provenance_readiness._scope_contains(
        source=(uuid4(), None, None, None),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, uuid4(), uuid4()),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, uuid4(), None),
        target=target_scope,
    )
    assert not provenance_readiness._scope_contains(
        source=(organization.id, edition.id, None, None),
        target=target_scope,
    )

    for label, candidate, expected in cases:
        observed = {
            key: value
            for key, value in candidate.structural_blocker_counts().items()
            if value
        }
        assert observed == expected, label

    assert (
        AuthorityIssuance.objects.get(pk=target_ordinal).policy_version
        == POLICY_VERSION
    )
    assert not AuthorityControl.objects.filter(
        issuance_id=delegated_issuance.ordinal
    ).exists()
    assert actor_root.capability_code == "authorization.grant_direct"


def test_readiness_graph_closure_and_integrity_fail_closed() -> None:
    graph = provenance_readiness._AuthorityGraph(at=timezone.now())
    child_id = uuid4()
    parent_id = uuid4()
    source_bundle_id = uuid4()
    child_ordinal = 10
    parent_ordinal = 9
    source_ordinal = 8
    graph.grants = {
        child_id: {"id": child_id, "delegated_from_id": parent_id},
        parent_id: {"id": parent_id, "delegated_from_id": None},
    }
    graph.bundles = {source_bundle_id: {"id": source_bundle_id}}
    graph.assignments = {}
    graph.issuances = {
        child_ordinal: {
            "ordinal": child_ordinal,
            "capability_grant_id": child_id,
            "role_bundle_id": None,
            "role_assignment_id": None,
        },
        parent_ordinal: {
            "ordinal": parent_ordinal,
            "capability_grant_id": parent_id,
            "role_bundle_id": None,
            "role_assignment_id": None,
        },
        source_ordinal: {
            "ordinal": source_ordinal,
            "capability_grant_id": None,
            "role_bundle_id": source_bundle_id,
            "role_assignment_id": None,
        },
    }
    graph.controls_by_issuance = {
        child_ordinal: [{"source_issuance_id": source_ordinal}]
    }
    graph.open_grant_ids = {child_id}
    graph.open_assignment_ids = set()
    graph.reachable_bundle_ids = set()
    graph.issuance_by_grant = {
        child_id: child_ordinal,
        parent_id: parent_ordinal,
    }
    graph.issuance_by_assignment = {}
    graph.issuance_by_bundle = {source_bundle_id: source_ordinal}

    assert graph._reachable_issuance_ordinals() == {
        source_ordinal,
        parent_ordinal,
        child_ordinal,
    }

    cycle_start = 1
    cycle_peer = 2
    depth_start = 100
    missing_start = 200
    missing_node = 999
    depth_nodes = tuple(
        range(
            depth_start,
            depth_start + provenance_readiness.MAX_AUTHORITY_LINEAGE_DEPTH + 1,
        )
    )
    graph.reachable_issuances = {cycle_start, depth_start, missing_start}
    graph.issuances = {
        ordinal: {}
        for ordinal in (cycle_start, cycle_peer, missing_start, *depth_nodes)
    }
    edges = {
        cycle_start: {cycle_peer},
        cycle_peer: {cycle_start},
        missing_start: {missing_node},
        **{current: {following} for current, following in pairwise(depth_nodes)},
    }

    cycles, too_deep, malformed = graph._recursive_graph_issues(edges)

    assert cycles == {cycle_start}
    assert too_deep == {depth_start}
    assert malformed == {missing_start}
