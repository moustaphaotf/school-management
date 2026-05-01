from datetime import date
from decimal import Decimal

from django.test import TestCase

from academic.models import (
    AllocatedSubject,
    ClassLevel,
    ClassRoom,
    GradeLevel,
    Stream,
    Student,
    StudentClassEnrollment,
    Subject,
    Teacher,
)
from administration.models import AcademicYear, Term
from examination.models import (
    ExaminationListHandler,
    GradeScale,
    MarksManagement,
    Result,
)
from examination.services import (
    assign_mention,
    compute_class_ranking,
    compute_subject_average,
    compute_term_average,
    generate_term_results,
    get_grade_scale,
)


def _create_classroom(class_level, name_suffix="A"):
    """Create a Stream + ClassRoom for a given ClassLevel.
    Teacher.save() auto-creates a CustomUser, which needs first/last name + email."""
    stream = Stream.objects.create(name=f"STR-{name_suffix}")
    teacher = Teacher.objects.create(
        username=f"teacher-{name_suffix}",
        first_name=f"First{name_suffix}",
        last_name=f"Last{name_suffix}",
        email=f"teacher-{name_suffix}@example.com",
        empId=f"E{name_suffix}",
        short_name=f"T{name_suffix[:2]}",
    )
    return ClassRoom.objects.create(
        name=class_level, stream=stream, class_teacher=teacher
    )


def _make_exam(name, classroom, term, out_of):
    exam = ExaminationListHandler.objects.create(
        name=name,
        start_date=term.start_date,
        ends_date=term.end_date,
        out_of=out_of,
        term=term,
    )
    exam.classrooms.add(classroom)
    return exam


def _enroll(classroom, year, first_name):
    """Student.save() requires parent_contact and auto-creates a Parent.
    admission_number is unique=True (blank='' collides on second insert)."""
    h = abs(hash(first_name)) % 100000
    student = Student.objects.create(
        first_name=first_name,
        last_name="Test",
        admission_number=f"ADM-{first_name}-{h:05d}",
        parent_contact=f"+224000{h:05d}",
    )
    return StudentClassEnrollment.objects.create(
        classroom=classroom, academic_year=year, student=student
    )


class GradeScaleResolutionTests(TestCase):
    """Verify the chain enrollment > classroom > class_level > grade_level >
    grade_scale resolves correctly for both /10 and /20 setups."""

    def test_resolves_20_scale_for_college(self):
        scale_20 = GradeScale.objects.get(name="/20")
        grade_level = GradeLevel.objects.create(
            id=1, name="Collège", grade_scale=scale_20
        )
        class_level = ClassLevel.objects.create(
            id=10, name="6eme", grade_level=grade_level
        )
        classroom = _create_classroom(class_level, "A")
        year = AcademicYear.objects.create(
            name="2025-2026", start_date=date(2025, 9, 1), active_year=True
        )
        enrollment = _enroll(classroom, year, "Aissatou")

        self.assertEqual(get_grade_scale(enrollment), scale_20)

    def test_resolves_10_scale_for_primary(self):
        scale_10 = GradeScale.objects.get(name="/10")
        grade_level = GradeLevel.objects.create(
            id=2, name="Primaire", grade_scale=scale_10
        )
        class_level = ClassLevel.objects.create(
            id=20, name="CM2", grade_level=grade_level
        )
        classroom = _create_classroom(class_level, "B")
        year = AcademicYear.objects.create(
            name="2025-2026", start_date=date(2025, 9, 1), active_year=True
        )
        enrollment = _enroll(classroom, year, "Mamadou")

        self.assertEqual(get_grade_scale(enrollment), scale_10)

    def test_returns_none_when_grade_scale_missing(self):
        grade_level = GradeLevel.objects.create(id=3, name="Sans échelle")
        class_level = ClassLevel.objects.create(
            id=30, name="X", grade_level=grade_level
        )
        classroom = _create_classroom(class_level, "C")
        year = AcademicYear.objects.create(
            name="2025-2026", start_date=date(2025, 9, 1), active_year=True
        )
        enrollment = _enroll(classroom, year, "Sans")

        self.assertIsNone(get_grade_scale(enrollment))


class AverageOn20Tests(TestCase):
    """Compute averages on the /20 scale for a college class with 2 subjects
    and 3 students."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=100, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=101, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "X20")
        cls.year = AcademicYear.objects.create(
            name="2025-26", start_date=date(2025, 9, 1), active_year=True
        )
        cls.term = Term.objects.create(
            name="T1",
            academic_year=cls.year,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )

        cls.math = Subject.objects.create(name="Math")
        cls.francais = Subject.objects.create(name="Francais")

        teacher = cls.classroom.class_teacher
        AllocatedSubject.objects.create(
            teacher_name=teacher,
            subject=cls.math,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("4"),
            weekly_periods=4,
        )
        AllocatedSubject.objects.create(
            teacher_name=teacher,
            subject=cls.francais,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("2"),
            weekly_periods=4,
        )

        cls.exam = _make_exam("DS1 T1", cls.classroom, cls.term, out_of=20)
        cls.alice = _enroll(cls.classroom, cls.year, "Alice")
        cls.bob = _enroll(cls.classroom, cls.year, "Bob")
        cls.cleo = _enroll(cls.classroom, cls.year, "Cleo")

        # Alice: math 16, francais 14
        # Bob:   math 12, francais 18
        # Cleo:  math 16, francais 14  (same as Alice -> tied rank)
        for enr, math_pts, fr_pts in [
            (cls.alice, 16, 14),
            (cls.bob, 12, 18),
            (cls.cleo, 16, 14),
        ]:
            MarksManagement.objects.create(
                exam_name=cls.exam,
                points_scored=math_pts,
                subject=cls.math,
                student=enr,
                created_by=teacher,
            )
            MarksManagement.objects.create(
                exam_name=cls.exam,
                points_scored=fr_pts,
                subject=cls.francais,
                student=enr,
                created_by=teacher,
            )

    def test_subject_average_one_exam(self):
        self.assertEqual(
            compute_subject_average(self.alice, self.math, self.term),
            Decimal("16.00"),
        )

    def test_term_average_weighted_by_coefficients(self):
        # Alice: (16*4 + 14*2) / 6 = (64+28)/6 = 15.333... -> 15.33
        self.assertEqual(
            compute_term_average(self.alice, self.term), Decimal("15.33")
        )
        # Bob: (12*4 + 18*2) / 6 = (48+36)/6 = 14.00
        self.assertEqual(
            compute_term_average(self.bob, self.term), Decimal("14.00")
        )

    def test_mention_assignment(self):
        avg = compute_term_average(self.alice, self.term)
        self.assertEqual(assign_mention(avg, self.scale), "Bien")  # 15.33 -> [14,16)
        bob_avg = compute_term_average(self.bob, self.term)
        self.assertEqual(assign_mention(bob_avg, self.scale), "Bien")

    def test_class_ranking_handles_ties(self):
        ranking = compute_class_ranking(self.classroom, self.term)
        # Student.save() lowercases first_name on insert
        rows_by_student = {r["enrollment"].student.first_name: r for r in ranking}

        # Alice and Cleo tied at 15.33 -> rank 1, Bob at 14.00 -> rank 3
        self.assertEqual(rows_by_student["alice"]["rank"], 1)
        self.assertEqual(rows_by_student["cleo"]["rank"], 1)
        self.assertEqual(rows_by_student["bob"]["rank"], 3)


class AverageOn10Tests(TestCase):
    """Same logic, /10 scale (primary). Verifies scale-awareness."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/10")
        gl = GradeLevel.objects.create(id=200, name="Primaire", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=201, name="CM2", grade_level=gl)
        cls.classroom = _create_classroom(cl, "X10")
        cls.year = AcademicYear.objects.create(
            name="2025-26", start_date=date(2025, 9, 1), active_year=True
        )
        cls.term = Term.objects.create(
            name="T1",
            academic_year=cls.year,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )

        cls.math = Subject.objects.create(name="Math")
        teacher = cls.classroom.class_teacher
        AllocatedSubject.objects.create(
            teacher_name=teacher,
            subject=cls.math,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )

        # Exam is on /10 scale (out_of=10)
        cls.exam = _make_exam("DS1 T1", cls.classroom, cls.term, out_of=10)
        cls.kid = _enroll(cls.classroom, cls.year, "Fanta")
        MarksManagement.objects.create(
            exam_name=cls.exam,
            points_scored=8,
            subject=cls.math,
            student=cls.kid,
            created_by=teacher,
        )

    def test_subject_average_in_10_scale(self):
        # 8/10 rescaled to /10 max (10) = 8.00
        self.assertEqual(
            compute_subject_average(self.kid, self.math, self.term),
            Decimal("8.00"),
        )

    def test_mention_uses_10_thresholds(self):
        avg = compute_term_average(self.kid, self.term)
        # 8.00 on /10 -> Très Bien (>= 8)
        self.assertEqual(assign_mention(avg, self.scale), "Très Bien")


class GenerateResultsTests(TestCase):
    """End-to-end: persist Result rows from a class ranking."""

    def test_generate_term_results_creates_rows(self):
        scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=300, name="Collège", grade_scale=scale)
        cl = ClassLevel.objects.create(id=301, name="6eme", grade_level=gl)
        classroom = _create_classroom(cl, "X")
        year = AcademicYear.objects.create(
            name="2025-26", start_date=date(2025, 9, 1), active_year=True
        )
        term = Term.objects.create(
            name="T1",
            academic_year=year,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )
        subject = Subject.objects.create(name="Math")
        AllocatedSubject.objects.create(
            teacher_name=classroom.class_teacher,
            subject=subject,
            academic_year=year,
            term=term,
            class_room=classroom,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )
        exam = _make_exam("DS1 T1", classroom, term, out_of=20)
        enr = _enroll(classroom, year, "Pupil")
        MarksManagement.objects.create(
            exam_name=exam,
            points_scored=18,
            subject=subject,
            student=enr,
            created_by=classroom.class_teacher,
        )

        results = generate_term_results(classroom, term)
        self.assertEqual(len(results), 1)
        r = Result.objects.get(student=enr.student, term=term)
        self.assertEqual(r.average, Decimal("18.00"))
        self.assertEqual(r.rank, 1)
        self.assertEqual(r.mention, "Très Bien")
