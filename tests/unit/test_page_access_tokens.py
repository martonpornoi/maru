"""Reject malformed signed scope tokens before any persisted-scope lookup."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core import signing

from maru.authorization.bindings import workforce_position_binding_id
from maru.authorization.models import ScopedResourceBinding
from maru.authorization.page_access import (
    MAX_PAGE_ACCESS_TOKEN_LENGTH,
    PAGE_ACCESS_CONTRACT_VERSION,
    PAGE_ACCESS_SIGNING_SALT,
    decode_page_access_target,
)
from maru.charities.bindings import charity_selection_binding_id
from maru.charities.models import CharitySelection
from maru.core.templatetags.page_access import _object_scope_values
from maru.events.models import EventEdition
from maru.organizations.models import ConventionSeries, Organization
from maru.venues.bindings import edition_space_binding_id
from maru.venues.models import EditionSpaceSelection
from maru.workforce.models import Department, Position


@pytest.mark.parametrize(
    "token", ["", "not-a-signature", "x" * (MAX_PAGE_ACCESS_TOKEN_LENGTH + 1)]
)
def test_page_access_rejects_invalid_transport_without_database_access(
    token: str,
) -> None:
    assert decode_page_access_target(token) is None


@pytest.mark.parametrize(
    "payload", [[], "scope", {}, {"organization_id": str(uuid4())}]
)
def test_valid_signature_does_not_make_an_open_payload_trusted(payload: object) -> None:
    token = signing.dumps(payload, salt=PAGE_ACCESS_SIGNING_SALT)
    assert decode_page_access_target(token) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"contract": "unknown"},
        {"extra": "untrusted"},
        {"organization_id": None},
        {"organization_id": 1},
        {"organization_id": "invalid"},
        {"organization_id": "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB"},
        {"edition_id": []},
        {"department_id": "invalid"},
        {"resource_binding_id": "invalid"},
        {"department_id": str(uuid4())},
        {"resource_binding_id": str(uuid4())},
        {"edition_id": str(uuid4()), "resource_binding_id": str(uuid4())},
        {"department_id": str(uuid4()), "resource_binding_id": str(uuid4())},
    ],
)
def test_page_access_rejects_noncanonical_or_incomplete_scope_ancestry(
    changes: dict[str, object],
) -> None:
    payload = {
        "contract": PAGE_ACCESS_CONTRACT_VERSION,
        "organization_id": str(uuid4()),
        "edition_id": None,
        "department_id": None,
        "resource_binding_id": None,
    }
    payload.update(changes)
    token = signing.dumps(payload, salt=PAGE_ACCESS_SIGNING_SALT)
    assert decode_page_access_target(token) is None


def test_context_scope_derivation_keeps_exact_owner_ancestry_for_each_resource() -> (
    None
):
    """Scope hints are typed owner identifiers, not grants or arbitrary object IDs."""
    organization, edition, department, resource = (uuid4() for _ in range(4))
    ancestry = {"organization_id": organization, "edition_id": edition}
    cases = [
        (Organization(id=organization), (organization, None, None, None)),
        (
            ConventionSeries(organization_id=organization),
            (organization, None, None, None),
        ),
        (
            EventEdition(id=edition, organization_id=organization),
            (organization, edition, None, None),
        ),
        (
            Department(id=department, **ancestry),
            (organization, edition, department, None),
        ),
        (
            ScopedResourceBinding(id=resource, department_id=department, **ancestry),
            (organization, edition, department, resource),
        ),
        (
            Position(id=resource, department_id=department, **ancestry),
            (
                organization,
                edition,
                department,
                workforce_position_binding_id(resource),
            ),
        ),
        (
            CharitySelection(
                id=resource, responsible_department_id=department, **ancestry
            ),
            (organization, edition, department, charity_selection_binding_id(resource)),
        ),
        (
            EditionSpaceSelection(
                id=resource, responsible_department_id=department, **ancestry
            ),
            (organization, edition, department, edition_space_binding_id(resource)),
        ),
        (
            SimpleNamespace(
                **ancestry, department_id=department, resource_binding_id=resource
            ),
            (organization, edition, department, resource),
        ),
    ]
    for value, expected in cases:
        assert _object_scope_values(value) == expected


@pytest.mark.parametrize(
    "parent", ["configuration", "registration", "position", "opportunity"]
)
def test_context_scope_derivation_follows_known_parent_links_only(parent: str) -> None:
    organization, edition = uuid4(), uuid4()
    owner = SimpleNamespace(organization_id=organization, edition_id=edition)
    value = SimpleNamespace(**{parent: owner})
    assert _object_scope_values(value) == (organization, edition, None, None)
    assert _object_scope_values(SimpleNamespace(unknown_parent=owner)) == (None,) * 4


def test_context_scope_derivation_ignores_untyped_identifiers_and_self_links() -> None:
    value = SimpleNamespace(organization_id=str(uuid4()), configuration=object())
    value.position = value
    assert _object_scope_values(value) == (None,) * 4
    assert _object_scope_values(None) == (None,) * 4
