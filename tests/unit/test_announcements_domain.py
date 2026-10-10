"""Closed input validation and publication comparison without database access."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.announcements.contracts import (
    AnnouncementDraftInput,
    AnnouncementSettingsInput,
    AnnouncementVariantInput,
    ManualChannel,
)
from maru.announcements.inputs import (
    digest,
    identifier,
    normalize_draft,
    normalize_settings,
    safe_url,
    version,
)
from maru.announcements.queries import _revision_view


def settings():
    return AnnouncementSettingsInput(
        policy_name="Synthetic rules",
        record_owner="Synthetic records team",
        review_on=date(2035, 1, 1),
        confirmed=True,
        channels=(ManualChannel("website", "Website"),),
        policy_description="Fictional isolated records.",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": False},
        {"policy_description": "", "policy_url": ""},
        {"review_on": "2035-01-01"},
        {"record_owner": ""},
        {"channels": ()},
        {"channels": (ManualChannel("same", "One"), ManualChannel("same", "Two"))},
        {"policy_url": "javascript:alert(1)"},
    ],
)
def test_rules_need_explicit_confirmation_and_closed_readable_values(changes):
    with pytest.raises(ValidationError):
        normalize_settings(replace(settings(), **changes))


@pytest.mark.parametrize("value", [True, 1, "1", None])
def test_scope_ids_do_not_coerce(value):
    with pytest.raises(ValidationError):
        identifier(value)


@pytest.mark.parametrize("value", [True, 0, -1, "1", 2**63])
def test_versions_do_not_coerce_or_wrap(value):
    with pytest.raises(ValidationError):
        version(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test",
        "https://name:password@example.test",
        "javascript:alert(1)",
        "https://example.test\x00/path",
    ],
)
def test_links_are_https_without_credentials_or_hidden_controls(value):
    with pytest.raises(ValidationError):
        safe_url(value)


def test_normalization_preserves_plain_multilingual_copy_and_stable_exact_digest():
    variant = AnnouncementVariantInput(
        "website", "hu", "Nyitás", "  Kezdés: 10:00.\r\nÜdv!  "
    )
    draft = normalize_draft(
        AnnouncementDraftInput(" Nyitás ", " Üdv! ", "hu", (variant,))
    )
    assert draft.variants[0].body == "Kezdés: 10:00.\nÜdv!"
    assert digest({"headline": "Nyitás", "body": "Üdv!"}) == digest(
        {"body": "Üdv!", "headline": "Nyitás"}
    )
    with pytest.raises(ValidationError):
        normalize_draft(replace(draft, variants=(variant, variant)))


def test_correcting_an_older_report_does_not_promote_it_above_a_later_publication():
    actor_id = uuid4()
    old_copy = SimpleNamespace(
        id=uuid4(),
        channel_code="website",
        channel_label="Website",
        channel_url="https://example.test/news",
        language_code="en",
        headline="Time",
        body="10:00",
        copy_digest="old",
    )
    new_copy = SimpleNamespace(
        **{**vars(old_copy), "id": uuid4(), "body": "11:00", "copy_digest": "new"}
    )

    def report(copy, *, supersedes=None, withdrawn=False):
        return SimpleNamespace(
            id=uuid4(),
            variant=copy,
            supersedes_report_id=supersedes,
            withdrawn=withdrawn,
            publication_url="https://example.test/post",
            occurred_at=timezone.now(),
            published_at=None,
            actor_id=actor_id,
        )

    first = report(old_copy)
    second = report(new_copy)
    corrected_first = report(old_copy, supersedes=first.id, withdrawn=True)
    relation = Mock()
    relation.only.return_value.order_by.return_value = [new_copy]
    revision = SimpleNamespace(
        id=uuid4(),
        number=2,
        headline="Time",
        body="11:00",
        language_code="en",
        occurred_at=timezone.now(),
        variants=relation,
    )
    projection = _revision_view(
        revision, (first, second, corrected_first), {actor_id: "Synthetic reporter"}
    )
    assert projection.variants[0].publication_status == "reported"
    assert projection.variants[0].publication_report_id == second.id
    assert projection.variants[0].reported_body == "11:00"
