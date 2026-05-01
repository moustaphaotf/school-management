from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from datetime import date, datetime
from django.utils.translation import gettext_lazy as _
from user_agents import parse

from .common_objs import *
from users.models import CustomUser


class Article(models.Model):
    title = models.CharField(max_length=150, blank=True, null=True, verbose_name=_("title"))
    content = models.TextField(blank=True, null=True, verbose_name=_("content"))
    picture = models.ImageField(upload_to="articles", blank=True, null=True, verbose_name=_("picture"))
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.DO_NOTHING, blank=True, null=True,
        verbose_name=_("created by"),
    )
    created_at = models.DateTimeField(auto_now=True, verbose_name=_("created at"))

    class Meta:
        verbose_name = _("Article")
        verbose_name_plural = _("Articles")

    def __str__(self):
        return self.title


class CarouselImage(models.Model):
    title = models.CharField(max_length=150, blank=True, null=True, verbose_name=_("title"))
    description = models.TextField(blank=True, null=True, verbose_name=_("description"))
    picture = models.ImageField(upload_to="carousel", verbose_name=_("picture"))

    class Meta:
        verbose_name = _("Carousel Image")
        verbose_name_plural = _("Carousel Images")

    def __str__(self):
        return self.title


class AccessLog(models.Model):
    login = models.ForeignKey(CustomUser, null=True, on_delete=models.SET_NULL, verbose_name=_("user"))
    ua = models.CharField(
        max_length=2000,
        verbose_name=_("user agent"),
        help_text=_("User agent. We can use this to determine operating system and browser in use."),
    )
    date = models.DateTimeField(
        auto_now_add=True, verbose_name=_("date"),
    )  # Set this to add the timestamp on creation only
    ip = models.GenericIPAddressField(verbose_name=_("IP address"))
    usage = models.CharField(max_length=255, verbose_name=_("usage"))

    class Meta:
        verbose_name = _("Access Log")
        verbose_name_plural = _("Access Logs")
        indexes = [
            models.Index(fields=["login"]),
            models.Index(fields=["date"]),
        ]


    def __str__(self):
        return f"{self.login} - {self.usage} on {self.date}"

    def os(self):
        """
        Extract the operating system from the user agent string.
        Returns 'Unknown' if it cannot be detected.
        """
        try:
            user_agent = parse(self.ua)
            return user_agent.os.family
        except Exception as e:
            print(f"Error extracting OS from UA: {e}")
            return "Unknown"

    def browser(self):
        """
        Extract the browser from the user agent string.
        Returns 'Unknown' if it cannot be detected.
        """
        try:
            user_agent = parse(self.ua)
            return user_agent.browser.family
        except Exception as e:
            print(f"Error extracting Browser from UA: {e}")
            return "Unknown"


class School(models.Model):
    active = models.BooleanField(
        default=False,
        verbose_name=_("active"),
        help_text=_("DANGER..!!!! If marked, this will be the default School Information System Wide..."),
    )
    name = models.CharField(max_length=100, verbose_name=_("name"))
    address = models.CharField(max_length=250, verbose_name=_("address"))
    school_type = models.CharField(
        max_length=25, choices=SCHOOL_TYPE_CHOICE, blank=True, null=True,
        verbose_name=_("school type"),
    )
    students_gender = models.CharField(
        max_length=25, choices=SCHOOL_STUDENTS_GENDER, blank=True, null=True,
        verbose_name=_("students gender"),
    )
    ownership = models.CharField(
        max_length=25, choices=SCHOOL_OWNERSHIP, blank=True, null=True,
        verbose_name=_("ownership"),
    )
    mission = models.TextField(blank=True, null=True, verbose_name=_("mission"))
    vision = models.TextField(blank=True, null=True, verbose_name=_("vision"))
    telephone = models.CharField(max_length=20, blank=True, verbose_name=_("telephone"))
    school_email = models.EmailField(blank=True, null=True, verbose_name=_("school email"))
    school_logo = models.ImageField(blank=True, null=True, upload_to="school_info", verbose_name=_("school logo"))

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("School")
        verbose_name_plural = _("Schools")
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["active"]),
        ]
        ordering = ["name"]


class Day(models.Model):
    DAY_CHOICES = (
        (1, _("Monday")),
        (2, _("Tuesday")),
        (3, _("Wednesday")),
        (4, _("Thursday")),
        (5, _("Friday")),
        (6, _("Saturday")),
        (7, _("Sunday")),
    )
    day = models.IntegerField(choices=DAY_CHOICES, unique=True, verbose_name=_("day"))

    def __str__(self):
        return (
            self.get_day_display()
        )

    class Meta:
        verbose_name = _("Day")
        verbose_name_plural = _("Days")
        ordering = ("day",)


class AcademicYear(models.Model):
    """
    A database table row that maps to every academic year.
    """

    name = models.CharField(max_length=255, unique=True, verbose_name=_("name"))
    start_date = models.DateField(verbose_name=_("start date"))
    end_date = models.DateField(blank=True, null=True, verbose_name=_("end date"))
    active_year = models.BooleanField(
        verbose_name=_("active year"),
        help_text=_(
            "DANGER!! This is the current school year. "
            "There can only be one and setting this will remove it from other years. "
            "If you want to change the active year, click Admin, Change School Year."
        )
    )

    class Meta:
        verbose_name = _("Academic Year")
        verbose_name_plural = _("Academic Years")
        ordering = ("-start_date",)

    def __str__(self):
        return self.name

    @property
    def status(self):
        now_ = date.today()
        if self.active_year:
            return "active"
        elif self.start_date <= now_ <= self.end_date:
            return "pending"
        elif self.start_date > now_ > self.end_date:
            return "ended"
        return "unknown"  # Fallback in case status doesn't match any condition

    def save(self, *args, **kwargs):
        # Ensure only one active year at a time
        if self.active_year:
            AcademicYear.objects.exclude(pk=self.pk).update(active_year=False)
        super(AcademicYear, self).save(*args, **kwargs)

    def clean(self):
        """
        Add custom validation to ensure the end_date is after start_date if both are provided.
        """
        if self.end_date and self.start_date > self.end_date:
            raise ValidationError(_("End date must be after start date."))


class Term(models.Model):
    name = models.CharField(
        max_length=50, verbose_name=_("name"),
        help_text=_("e.g., Term 1, Term 2"),
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="terms",
        verbose_name=_("academic year"),
    )
    default_term_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=312500,
        verbose_name=_("default term fee"),
    )
    start_date = models.DateField(verbose_name=_("start date"))
    end_date = models.DateField(verbose_name=_("end date"))

    class Meta:
        verbose_name = _("Term")
        verbose_name_plural = _("Terms")

    def __str__(self):
        return f"{self.name} - {self.academic_year.name}"


class SchoolEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ("exam", _("Examination Period")),
        ("graduation", _("Graduation Day")),
        ("holiday", _("Holiday")),
        ("leave", _("Student Leave")),
        ("other", _("Other Event")),
    ]

    term = models.ForeignKey(
        "Term",
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("term"),
        help_text=_("The term this event belongs to"),
    )
    name = models.CharField(
        max_length=255, verbose_name=_("name"),
        help_text=_("Name of the event (e.g., Midterm Exams, Eid Holiday)"),
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, verbose_name=_("event type"))
    start_date = models.DateField(verbose_name=_("start date"))
    end_date = models.DateField(blank=True, null=True, verbose_name=_("end date"))
    description = models.TextField(
        blank=True, help_text=_("Optional details about the event"), verbose_name=_("description"),
    )

    class Meta:
        verbose_name = _("School Event")
        verbose_name_plural = _("School Events")
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.name} ({self.term.name} - {self.term.academic_year.name})"

    def clean(self):
        if not self.start_date or not self.term_id:
            return
        if self.end_date and self.start_date > self.end_date:
            raise ValidationError(_("End date must be after start date."))
        if self.term.start_date and self.term.end_date:
            if not (self.term.start_date <= self.start_date <= self.term.end_date):
                raise ValidationError(
                    _("Start date must be within the term's duration.")
                )
            if self.end_date and not (
                self.term.start_date <= self.end_date <= self.term.end_date
            ):
                raise ValidationError(
                    _("End date must be within the term's duration.")
                )
