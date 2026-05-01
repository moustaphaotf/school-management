from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status
import traceback


def custom_exception_handler(exc, context):
    # Translate Django model ValidationError (e.g. from full_clean()) into a
    # 400 response so callers get a clean field-level error instead of a 500.
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        else:
            detail = {"detail": list(exc.messages)}
        return Response(
            {"error": status.HTTP_400_BAD_REQUEST, "detail": detail},
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = drf_exception_handler(exc, context)

    if response is not None:
        return Response(
            {"error": response.status_code, "detail": response.data},
            status=response.status_code,
        )

    # Handle non-DRF errors (500 errors)
    return Response(
        {"error": "Server Error", "detail": str(exc)},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
