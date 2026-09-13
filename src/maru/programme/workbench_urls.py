"""Reserved item routes for isolated rehearsal only; absent from production URLs."""

from django.urls import path

from .workbench_views import programme_item, programme_items

urlpatterns = [
    path(
        "admin/programme/items/<uuid:organization_id>/<uuid:edition_id>/",
        programme_items,
        name="programme-items",
    ),
    path(
        "admin/programme/items/<uuid:organization_id>/<uuid:edition_id>/<uuid:item_id>/<slug:task>/",
        programme_item,
        name="programme-item",
    ),
]
