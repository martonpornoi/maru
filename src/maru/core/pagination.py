"""Bounded API pagination shared by list projections."""

from rest_framework.pagination import PageNumberPagination


class StandardPageNumberPagination(PageNumberPagination):
    """Describe standard page number pagination."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100
