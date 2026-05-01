from django.utils.translation import gettext_lazy as _

A = "A"
B = "B"
C = "C"
D = "D"
F = "F"
PASS = "PASS"
FAIL = "FAIL"

GRADE = (
    (A, "A"),
    (B, "B"),
    (C, "C"),
    (D, "D"),
    (F, "F"),
)

COMMENT = (
    (PASS, "PASS"),
    (FAIL, "FAIL"),
)

ACADEMIC_TERM = (
    ("One", _("One")),
    ("Two", _("Two")),
    ("Three", _("Three")),
    ("Four", _("Four")),
)

GENDER_CHOICE = (
    ("Male", _("Male")),
    ("Female", _("Female")),
    ("Other", _("Other")),
)
RELIGION_CHOICE = (
    ("Islam", _("Islam")),
    ("Christian", _("Christian")),
    ("Other", _("Other")),
)

PARENT_CHOICE = (
    ("Father", _("Father")),
    ("Mother", _("Mother")),
    ("Guardian", _("Guardian")),
)

SCHOOL_TYPE_CHOICE = (
    ("boarding school", _("boarding school")),
    ("day school", _("day school")),
    ("boarding-day school", _("boarding-day school")),
)

SCHOOL_STUDENTS_GENDER = (
    ("Boys School", _("Boys School")),
    ("Girl School", _("Girl School")),
    ("Mixed", _("Mixed")),
)

SCHOOL_OWNERSHIP = (
    ("Government", _("Government")),
    ("Private", _("Private")),
)


ATTENDANCE_CHOICES = (
    ("Present", _("Present")),
    ("Absent", _("Absent")),
    ("Holiday", _("Holiday")),
    ("Sick", _("Sick")),
)
