"""Pagination classes for examination list endpoints.

Default 50 rows per page is enough for an admin/teacher inspecting a
classroom; clients can override with ?page_size= up to 200."""

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
