"""Literal owner metadata inventories exclude private content and shared scope."""

import pytest
from django.apps import apps

from maru.applications import models
from maru.applications.programme_stop_queries import STOP_METADATA_SOURCES
from maru.effects import models as effects_models
from maru.effects.programme_stop_queries import STOP_METADATA_SOURCES as EFFECTS_SOURCES
from maru.programme import models as programme_models
from maru.programme.programme_stop_queries import (
    STOP_METADATA_SOURCES as CONTENT_SOURCES,
)
from maru.scheduling import models as scheduling_models
from maru.scheduling.programme_stop_queries import (
    STOP_METADATA_SOURCES as SCHEDULING_SOURCES,
)
from maru.venues import models as venue_models
from maru.venues.programme_stop_queries import STOP_METADATA_SOURCES as VENUE_SOURCES
from maru.workforce import models as workforce_models
from maru.workforce.programme_stop_queries import (
    STOP_METADATA_SOURCES as WORKFORCE_SOURCES,
)


@pytest.mark.parametrize(
    ("owner", "sources", "count", "excluded"),
    [
        ("applications", STOP_METADATA_SOURCES, 43, set()),
        ("programme", CONTENT_SOURCES, 22, set()),
        ("scheduling", SCHEDULING_SOURCES, 27, set()),
        ("workforce", WORKFORCE_SOURCES, 22, {"PositionTemplate"}),
        (
            "venues",
            VENUE_SOURCES,
            9,
            {
                "VenueProperty",
                "VenuePropertyMedia",
                "VenueSite",
                "VenueBuilding",
                "VenueSpace",
                "VenueSpaceConfiguration",
                "VenueSpaceCombination",
                "VenueSpaceCombinationMember",
                "VenueLayoutVersion",
                "AccommodationRoomType",
                "AccommodationNightInventory",
            },
        ),
        ("effects", EFFECTS_SOURCES, 4, set()),
    ],
)
def test_stop_inventory_covers_every_owned_operational_model_without_discovery(
    owner, sources, count, excluded
):
    assert {row[0] for row in sources} == {
        model.__name__ for model in apps.get_app_config(owner).get_models()
    } - excluded
    assert len(sources) == count


@pytest.mark.parametrize(
    ("module", "sources"),
    [
        (models, STOP_METADATA_SOURCES),
        (programme_models, CONTENT_SOURCES),
        (scheduling_models, SCHEDULING_SOURCES),
        (venue_models, VENUE_SOURCES),
        (workforce_models, WORKFORCE_SOURCES),
        (effects_models, EFFECTS_SOURCES),
    ],
)
def test_each_metadata_projection_and_tenant_parent_is_real_and_minimized(
    module, sources
):
    forbidden = {
        "name",
        "description",
        "purpose",
        "payload",
        "canonical_payload",
        "value",
        "reason",
        "message",
        "email",
        "public_name",
        "biography",
        "pronouns",
        "options",
        "label",
        "help_text",
        "account_id",
        "actor_id",
        "storage_key",
        "scanner_receipt",
        "stages",
        "templates",
        "internal_title",
        "working_summary",
        "technical_requirements",
        "briefing",
        "public_title",
        "public_summary",
        "review_reason",
        "body",
    }
    for name, path, state, versions in sources:
        model = getattr(module, name)
        fields = {"id", "updated_at", *versions, *((state,) if state else ())}
        assert not fields & forbidden
        assert fields <= {field.attname for field in model._meta.fields}
        parent = model
        for part in path.strip("_").split("__") if path else ():
            parent = parent._meta.get_field(part).related_model
        assert {
            "organization_id",
            "event_edition_id" if module is effects_models else "edition_id",
        } <= {field.attname for field in parent._meta.fields}
