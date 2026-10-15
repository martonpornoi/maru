"""Routes mounted only by the explicit local convention preview setting."""

from django.urls import path

from maru.demo.views import convention_demo
from maru.urls import urlpatterns as application_urls

urlpatterns = [
    path("demo/", convention_demo, name="convention-demo"),
    *application_urls,
]
