from django.db import models
from django.utils.translation import gettext_lazy as _

from academic.models import ClassRoom, Teacher, AllocatedSubject


class Period(models.Model):
    DAY_CHOICES = [
        ("Monday", _("Monday")),
        ("Tuesday", _("Tuesday")),
        ("Wednesday", _("Wednesday")),
        ("Thursday", _("Thursday")),
        ("Friday", _("Friday")),
    ]

    day_of_week = models.CharField(
        max_length=10,
        choices=DAY_CHOICES,
        verbose_name=_("day of week"),
    )
    start_time = models.TimeField(verbose_name=_("start time"))
    end_time = models.TimeField(verbose_name=_("end time"))
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name=_("classroom"))
    subject = models.ForeignKey(AllocatedSubject, on_delete=models.CASCADE, verbose_name=_("subject"))
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name=_("teacher"))

    class Meta:
        verbose_name = _("Period")
        verbose_name_plural = _("Periods")
        unique_together = ("day_of_week", "start_time", "classroom")

    def __str__(self):
        return f"{self.classroom} - {self.subject} ({self.day_of_week} {self.start_time}-{self.end_time})"
