from django.db import models
from django.utils.translation import gettext_lazy as _


class StudentBulkUpload(models.Model):
    date_uploaded = models.DateTimeField(auto_now=True, verbose_name=_("date uploaded"))
    csv_file = models.FileField(upload_to="api/sis/students/bulkupload", verbose_name=_("CSV file"))

    class Meta:
        verbose_name = _("Student Bulk Upload")
        verbose_name_plural = _("Student Bulk Uploads")
