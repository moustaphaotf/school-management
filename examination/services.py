"""
Pure-Python computations for grading: scale resolution, subject and term
averages, class ranking, mention assignment, and Result persistence.

All averages are returned in the student's native scale (no /4 GPA conversion).
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db import transaction

from academic.models import (
    AllocatedSubject,
    ClassRoom,
    StudentClassEnrollment,
    Subject,
)
from administration.models import Term
from examination.models import (
    ExaminationListHandler,
    GradeScale,
    MarksManagement,
    Result,
)


TWO_PLACES = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def get_grade_scale(enrollment: StudentClassEnrollment) -> Optional[GradeScale]:
    """Resolve the GradeScale for an enrollment via classroom > class_level >
    grade_level > grade_scale. Returns None if any link is missing."""
    classroom = enrollment.classroom
    class_level = classroom.name  # FK is named 'name' in ClassRoom (legacy)
    if class_level is None:
        return None
    grade_level = class_level.grade_level
    if grade_level is None:
        return None
    return grade_level.grade_scale


def compute_subject_average(
    enrollment: StudentClassEnrollment,
    subject: Subject,
    term: Term,
) -> Optional[Decimal]:
    """Mean of all marks for this enrollment x subject x exams-of-this-term.
    Each mark is rescaled to the student's grade_scale max before averaging.

    Returns None if no marks exist."""
    scale = get_grade_scale(enrollment)
    if scale is None:
        return None
    scale_max = _scale_max(scale)
    if scale_max is None:
        return None

    marks = MarksManagement.objects.filter(
        student=enrollment,
        subject=subject,
        exam_name__term=term,
    ).select_related("exam_name")

    if not marks.exists():
        return None

    total = Decimal("0")
    count = 0
    for m in marks:
        out_of = Decimal(str(m.exam_name.out_of or 0))
        if out_of <= 0:
            continue
        scaled = (Decimal(str(m.points_scored)) / out_of) * scale_max
        total += scaled
        count += 1

    if count == 0:
        return None
    return _quantize(total / Decimal(count))


def compute_term_average(
    enrollment: StudentClassEnrollment,
    term: Term,
) -> Optional[Decimal]:
    """Weighted average of subject averages by their AllocatedSubject coefficient.
    Subjects without any marks are excluded (no impact on the result).

    Returns None if there are no subjects with marks at all."""
    allocations = AllocatedSubject.objects.filter(
        class_room=enrollment.classroom,
        academic_year=enrollment.academic_year,
        term=term,
    ).select_related("subject")

    weighted_sum = Decimal("0")
    coef_sum = Decimal("0")
    for alloc in allocations:
        sub_avg = compute_subject_average(enrollment, alloc.subject, term)
        if sub_avg is None:
            continue
        coef = Decimal(str(alloc.coefficient or 1))
        weighted_sum += sub_avg * coef
        coef_sum += coef

    if coef_sum == 0:
        return None
    return _quantize(weighted_sum / coef_sum)


def assign_mention(average: Decimal, scale: GradeScale) -> str:
    """Look up the GradeScaleRule whose [min, max] range contains the average.
    Returns letter_grade or empty string if no rule matches."""
    if average is None or scale is None:
        return ""
    rule = scale.gradescalerule_set.filter(
        min_grade__lte=average, max_grade__gte=average
    ).first()
    return rule.letter_grade if rule and rule.letter_grade else ""


def compute_class_ranking(classroom: ClassRoom, term: Term) -> list[dict]:
    """Compute the ranking for all enrolled students in a classroom for a term.
    Returns a list of dicts ordered by descending average:
        [{"enrollment": ..., "average": Decimal | None, "rank": int | None,
          "mention": str}]

    Tied averages share a rank; the next rank skips accordingly (1, 1, 3 pattern).
    Students with no average are listed last with rank=None."""
    enrollments = list(
        StudentClassEnrollment.objects.filter(classroom=classroom).select_related(
            "student", "academic_year", "classroom"
        )
    )

    rows = []
    for enr in enrollments:
        avg = compute_term_average(enr, term)
        scale = get_grade_scale(enr)
        rows.append(
            {
                "enrollment": enr,
                "average": avg,
                "rank": None,
                "mention": assign_mention(avg, scale) if avg is not None else "",
            }
        )

    ranked = [r for r in rows if r["average"] is not None]
    unranked = [r for r in rows if r["average"] is None]
    ranked.sort(key=lambda r: r["average"], reverse=True)

    last_avg: Optional[Decimal] = None
    last_rank = 0
    for idx, row in enumerate(ranked, start=1):
        if last_avg is not None and row["average"] == last_avg:
            row["rank"] = last_rank
        else:
            row["rank"] = idx
            last_rank = idx
            last_avg = row["average"]

    return ranked + unranked


@transaction.atomic
def generate_term_results(classroom: ClassRoom, term: Term) -> list[Result]:
    """Compute averages, ranks and mentions for every student in a classroom
    and persist them as Result rows. Updates existing Result rows for the same
    (student, academic_year, term) tuple, otherwise creates new ones.

    Returns the list of saved Result instances."""
    ranking = compute_class_ranking(classroom, term)
    saved: list[Result] = []
    for row in ranking:
        enr: StudentClassEnrollment = row["enrollment"]
        result, _ = Result.objects.update_or_create(
            student=enr.student,
            academic_year=enr.academic_year,
            term=term,
            defaults={
                "average": row["average"],
                "rank": row["rank"],
                "mention": row["mention"],
            },
        )
        saved.append(result)
    return saved


def _scale_max(scale: GradeScale) -> Optional[Decimal]:
    """Return the max_grade across all rules of a scale (e.g. 20 for /20)."""
    rule = scale.gradescalerule_set.order_by("-max_grade").first()
    if rule is None:
        return None
    return Decimal(str(rule.max_grade))
