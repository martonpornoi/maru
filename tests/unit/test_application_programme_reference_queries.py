"""Database-free coverage for minimized Programme owner references."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from django.utils import timezone

from maru.applications import programme_queries
from maru.identity.queries import (
    ActiveVerifiedPersonReference,
    active_person_account_display_labels,
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference,
    resolve_active_verified_person_reference_by_email,
)
from maru.workforce.queries import (
    CurrentDepartmentReference,
    resolve_current_department_reference,
)


def _identity_manager(row: object) -> tuple[MagicMock, MagicMock]:
    manager = MagicMock()
    query = manager.all.return_value
    query.filter.return_value.values_list.return_value.first.return_value = row
    return manager, query


def test_identity_resolves_only_current_verified_person_identifier(
    monkeypatch,
) -> None:
    """Require all three Identity state gates without returning account data."""
    account_id = uuid4()
    manager, query = _identity_manager(account_id)
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(
            Kind=SimpleNamespace(PERSON="person"),
            objects=manager,
        ),
    )

    reference = resolve_active_verified_person_reference(account_id=account_id)

    assert reference == ActiveVerifiedPersonReference(account_id=account_id)
    assert tuple(reference.__dataclass_fields__) == ("account_id",)
    query.filter.assert_called_once_with(
        id=account_id,
        is_active=True,
        email_verified_at__isnull=False,
        account_kind="person",
    )
    query.filter.return_value.values_list.assert_called_once_with("id", flat=True)


def test_identity_email_lookup_is_normalized_exact_and_enumeration_safe(
    monkeypatch,
) -> None:
    """Collapse invalid, missing, and unusable invitees to the same result."""
    account_id = uuid4()
    manager, query = _identity_manager(account_id)
    locked = query.select_for_update.return_value
    locked.filter.return_value.values_list.return_value.first.return_value = account_id
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(
            Kind=SimpleNamespace(PERSON="person"),
            objects=manager,
        ),
    )

    reference = resolve_active_verified_person_reference_by_email(
        email="  PERSON@Example.COM  ",
        lock=True,
    )

    assert reference == ActiveVerifiedPersonReference(account_id=account_id)
    query.select_for_update.assert_called_once_with(of=("self",))
    locked.filter.assert_called_once_with(
        email="person@example.com",
        is_active=True,
        email_verified_at__isnull=False,
        account_kind="person",
    )

    assert (
        resolve_active_verified_person_reference_by_email(email="not an address")
        is None
    )


def test_existing_identity_display_labels_keep_unverified_active_people(
    monkeypatch,
) -> None:
    """Preserve the established Workforce-facing active-person semantics."""
    account_id = uuid4()
    manager = MagicMock()
    query = manager.filter.return_value
    query.only.return_value = [
        SimpleNamespace(
            id=account_id,
            display_name="  Unverified Active Person  ",
            email_verified_at=None,
        )
    ]
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(
            Kind=SimpleNamespace(PERSON="person"),
            objects=manager,
        ),
    )

    labels = active_person_account_display_labels([account_id])

    assert labels == {account_id: "Unverified Active Person"}
    manager.filter.assert_called_once_with(
        id__in=[account_id],
        is_active=True,
        account_kind="person",
    )
    query.only.assert_called_once_with("id", "display_name")


def test_identity_verified_display_labels_require_current_verified_person(
    monkeypatch,
) -> None:
    """Give Programme a narrower label seam without changing other callers."""
    account_id = uuid4()
    manager = MagicMock()
    query = manager.filter.return_value
    query.only.return_value = [
        SimpleNamespace(id=account_id, display_name="  Programme Person  ")
    ]
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(
            Kind=SimpleNamespace(PERSON="person"),
            objects=manager,
        ),
    )

    labels = active_verified_person_account_display_labels([account_id])

    assert labels == {account_id: "Programme Person"}
    manager.filter.assert_called_once_with(
        id__in=[account_id],
        is_active=True,
        email_verified_at__isnull=False,
        account_kind="person",
    )
    query.only.assert_called_once_with("id", "display_name")


def test_programme_contributors_use_verified_identity_label_seam(
    monkeypatch,
) -> None:
    """Keep Programme contributor disclosure on the verified-only seam."""
    organization_id = uuid4()
    edition_id = uuid4()
    lead_id = uuid4()
    manager = MagicMock()
    initial = manager.filter.return_value
    initial.order_by.return_value.__getitem__.return_value = []
    verified_labels = MagicMock(return_value={lead_id: "Verified Lead"})
    monkeypatch.setattr(
        programme_queries,
        "ProgrammeProposalCollaborator",
        SimpleNamespace(objects=manager),
    )
    monkeypatch.setattr(
        programme_queries,
        "active_verified_person_account_display_labels",
        verified_labels,
    )
    proposal = SimpleNamespace(
        organization_id=organization_id,
        edition_id=edition_id,
        submission=SimpleNamespace(account_id=lead_id),
    )

    contributors = programme_queries._contributor_projections(
        proposal=proposal,
        scope=SimpleNamespace(relationship="lead", actor_id=lead_id),
        effective_now=timezone.now(),
    )

    verified_labels.assert_called_once_with({lead_id})
    assert len(contributors) == 1
    assert contributors[0].account_id == lead_id
    assert contributors[0].display_label == "Verified Lead"


def test_lead_projection_retains_expired_invitation_for_reinvite(
    monkeypatch,
) -> None:
    """Let only the lead see an expired invitation as actionable history."""
    organization_id = uuid4()
    edition_id = uuid4()
    lead_id = uuid4()
    invitee_id = uuid4()
    collaborator_id = uuid4()
    effective_now = timezone.now()
    manager = MagicMock()
    initial = manager.filter.return_value
    initial.order_by.return_value.__getitem__.return_value = [
        SimpleNamespace(
            id=collaborator_id,
            account_id=invitee_id,
            state=programme_queries.ProgrammeCollaboratorState.INVITED,
            generation=2,
            invite_expires_at=effective_now,
        )
    ]
    monkeypatch.setattr(
        programme_queries,
        "ProgrammeProposalCollaborator",
        SimpleNamespace(objects=manager),
    )
    monkeypatch.setattr(
        programme_queries,
        "active_verified_person_account_display_labels",
        MagicMock(
            return_value={
                lead_id: "Lead",
                invitee_id: "Expired Invitee",
            }
        ),
    )
    proposal = SimpleNamespace(
        organization_id=organization_id,
        edition_id=edition_id,
        submission=SimpleNamespace(account_id=lead_id),
    )

    contributors = programme_queries._contributor_projections(
        proposal=proposal,
        scope=SimpleNamespace(relationship="lead", actor_id=lead_id),
        effective_now=effective_now,
    )

    assert initial.filter.call_count == 0
    assert len(contributors) == 2
    assert contributors[1].account_id == invitee_id
    assert contributors[1].state == programme_queries.ProgrammeCollaboratorState.INVITED
    assert contributors[1].invitation_expired is True


def test_collaborator_projection_hides_every_other_invitation(
    monkeypatch,
) -> None:
    """Restrict a non-lead contributor projection to their accepted row."""
    organization_id = uuid4()
    edition_id = uuid4()
    lead_id = uuid4()
    collaborator_id = uuid4()
    relationship_id = uuid4()
    effective_now = timezone.now()
    manager = MagicMock()
    initial = manager.filter.return_value
    scoped = initial.filter.return_value
    scoped.order_by.return_value.__getitem__.return_value = [
        SimpleNamespace(
            id=relationship_id,
            account_id=collaborator_id,
            state=programme_queries.ProgrammeCollaboratorState.ACCEPTED,
            generation=1,
            invite_expires_at=effective_now,
        )
    ]
    monkeypatch.setattr(
        programme_queries,
        "ProgrammeProposalCollaborator",
        SimpleNamespace(objects=manager),
    )
    monkeypatch.setattr(
        programme_queries,
        "active_verified_person_account_display_labels",
        MagicMock(return_value={lead_id: "Lead", collaborator_id: "Collaborator"}),
    )
    proposal = SimpleNamespace(
        organization_id=organization_id,
        edition_id=edition_id,
        submission=SimpleNamespace(account_id=lead_id),
    )

    contributors = programme_queries._contributor_projections(
        proposal=proposal,
        scope=SimpleNamespace(
            relationship="collaborator",
            actor_id=collaborator_id,
        ),
        effective_now=effective_now,
    )

    initial.filter.assert_called_once_with(
        account_id=collaborator_id,
        state=programme_queries.ProgrammeCollaboratorState.ACCEPTED,
    )
    assert [row.account_id for row in contributors] == [lead_id, collaborator_id]
    assert all(not row.invitation_expired for row in contributors)


def test_workforce_department_reference_is_exact_current_and_label_free(
    monkeypatch,
) -> None:
    """Return only exact scope IDs and reject retired or foreign rows uniformly."""
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()
    manager = MagicMock()
    query = manager.all.return_value
    query.filter.return_value.values.return_value.first.return_value = {
        "id": department_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    monkeypatch.setattr(
        "maru.workforce.queries.Department",
        SimpleNamespace(objects=manager),
    )

    reference = resolve_current_department_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )

    assert reference == CurrentDepartmentReference(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )
    assert tuple(reference.__dataclass_fields__) == (
        "organization_id",
        "edition_id",
        "department_id",
    )
    query.filter.assert_called_once_with(
        id=department_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retired_at__isnull=True,
    )
    query.filter.return_value.values.assert_called_once_with(
        "id",
        "organization_id",
        "edition_id",
    )
