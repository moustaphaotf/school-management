from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.http import JsonResponse


def custom_404_handler(request, exception):
    return JsonResponse(
        {
            "error": "Page Not Found",
            "detail": f"The requested URL {request.path} was not found on this server.",
        },
        status=404,
    )


def custom_500_handler(request):
    return JsonResponse(
        {
            "error": "Server Error",
            "detail": "An unexpected error occurred on the server. Please try again later.",
        },
        status=500,
    )


def custom_403_handler(request, exception):
    return JsonResponse(
        {
            "error": "Permission Denied",
            "detail": "You do not have permission to perform this action.",
        },
        status=403,
    )


def custom_400_handler(request, exception):
    return JsonResponse(
        {
            "error": "Bad Request",
            "detail": "The request could not be understood or was missing required parameters.",
        },
        status=400,
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="index.html")),
    path("api/academic/", include("api.academic.urls")),
    path("api/administration/", include("api.administration.urls")),
    path("api/attendance/", include("api.attendance.urls")),
    path("api/assignments/", include("api.assignments.urls")),
    path("api/blog/", include("api.blog.urls")),
    path("api/examination/", include("api.examination.urls")),
    path("api/finance/", include("api.finance.urls")),
    # path('api/journals/', include('api.journals.urls')),
    # path("api/notes/", include("api.notes.urls")),
    path("api/users/", include("api.users.urls")),
    path("api/timetable/", include("api.schedule.urls")),
    path("api/sis/", include("api.sis.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

handler404 = custom_404_handler
handler500 = custom_500_handler
handler403 = custom_403_handler
handler400 = custom_400_handler
