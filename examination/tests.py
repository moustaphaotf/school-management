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
import io
import zipfile

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from users.models import CustomUser

from examination.services import (
    assign_mention,
    build_bulletin_payload,
    compute_class_ranking,
    compute_subject_average,
    compute_term_average,
    generate_term_results,
    get_grade_scale,
    render_bulletin_pdf,
    render_class_bulletins_zip,
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


class BulletinPdfTests(TestCase):
    """Validate the bulletin payload + PDF + ZIP helpers end to end."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=400, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=401, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "PDF")
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
        AllocatedSubject.objects.create(
            teacher_name=cls.classroom.class_teacher,
            subject=cls.math,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )
        cls.exam = _make_exam("DS1 T1", cls.classroom, cls.term, out_of=20)
        cls.alice = _enroll(cls.classroom, cls.year, "Alice")
        cls.bob = _enroll(cls.classroom, cls.year, "Bob")
        for enr, pts in [(cls.alice, 18), (cls.bob, 12)]:
            MarksManagement.objects.create(
                exam_name=cls.exam,
                points_scored=pts,
                subject=cls.math,
                student=enr,
                created_by=cls.classroom.class_teacher,
            )

    def test_payload_contains_average_and_rank(self):
        payload = build_bulletin_payload(self.alice, self.term)
        self.assertEqual(payload["average"], Decimal("18.00"))
        self.assertEqual(payload["rank"], 1)
        self.assertEqual(payload["scale"], "/20")
        self.assertEqual(payload["mention"], "Très Bien")
        self.assertEqual(len(payload["subjects"]), 1)

    def test_pdf_renders_to_valid_bytes(self):
        pdf = render_bulletin_pdf(self.alice, self.term)
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_class_zip_contains_one_pdf_per_student(self):
        zip_bytes, success, failed = render_class_bulletins_zip(
            self.classroom, self.term
        )
        self.assertEqual(success, 2)
        self.assertEqual(failed, [])
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 2)
            for name in names:
                self.assertTrue(name.endswith(".pdf"))
                with zf.open(name) as fp:
                    self.assertTrue(fp.read(4).startswith(b"%PDF"))


class MarksPermissionTests(TestCase):
    """Verify that only the allocated teacher (or admin) can write marks."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=500, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=501, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "PERM")

        # Teacher A teaches Math; Teacher B teaches Français (in another classroom helper)
        cls.teacher_math = Teacher.objects.create(
            username="math-teacher",
            first_name="Math",
            last_name="Teacher",
            email="math@test.gn",
            empId="EMATH",
            short_name="MTH",
        )
        cls.teacher_fr = Teacher.objects.create(
            username="fr-teacher",
            first_name="Fr",
            last_name="Teacher",
            email="fr@test.gn",
            empId="EFR",
            short_name="FR",
        )

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

        # Only Math is allocated to teacher_math in this classroom
        AllocatedSubject.objects.create(
            teacher_name=cls.teacher_math,
            subject=cls.math,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )

        cls.exam = _make_exam("DS1 T1", cls.classroom, cls.term, out_of=20)
        cls.enr = _enroll(cls.classroom, cls.year, "Pupil")

        cls.admin = CustomUser.objects.create_superuser(
            email="admin@test.gn", password="x"
        )

    def test_anonymous_cannot_post_mark(self):
        client = APIClient()
        response = client.post(
            "/api/examination/marks/",
            {
                "exam_name": self.exam.id,
                "points_scored": 15,
                "subject": self.math.id,
                "student": self.enr.id,
            },
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_math_teacher_can_post_math_mark(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_math.user)
        response = client.post(
            "/api/examination/marks/",
            {
                "exam_name": self.exam.id,
                "points_scored": 15,
                "subject": self.math.id,
                "student": self.enr.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_fr_teacher_cannot_post_math_mark(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_fr.user)
        response = client.post(
            "/api/examination/marks/",
            {
                "exam_name": self.exam.id,
                "points_scored": 15,
                "subject": self.math.id,
                "student": self.enr.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_post_anything(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.post(
            "/api/examination/marks/",
            {
                "exam_name": self.exam.id,
                "points_scored": 12,
                "subject": self.francais.id,  # admin not constrained
                "student": self.enr.id,
                "created_by": self.teacher_fr.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_math_teacher_can_read_marks(self):
        """Read access is not restricted; SAFE_METHODS pass."""
        MarksManagement.objects.create(
            exam_name=self.exam,
            points_scored=15,
            subject=self.math,
            student=self.enr,
            created_by=self.teacher_math,
        )
        client = APIClient()
        client.force_authenticate(user=self.teacher_fr.user)  # Fr teacher reads Math
        response = client.get("/api/examination/marks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class MarksXlsxTests(TestCase):
    """Build template + parse roundtrip on the bulk Excel upload."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=600, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=601, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "XL")
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
        for sub, coef in [(cls.math, Decimal("4")), (cls.francais, Decimal("2"))]:
            AllocatedSubject.objects.create(
                teacher_name=teacher,
                subject=sub,
                academic_year=cls.year,
                term=cls.term,
                class_room=cls.classroom,
                coefficient=coef,
                weekly_periods=4,
            )

        cls.exam = _make_exam("DS1 T1", cls.classroom, cls.term, out_of=20)
        cls.alice = _enroll(cls.classroom, cls.year, "Alice")
        cls.bob = _enroll(cls.classroom, cls.year, "Bob")

    def test_template_has_expected_headers_and_rows(self):
        from examination.services import build_marks_template_xlsx
        from openpyxl import load_workbook

        xlsx = build_marks_template_xlsx(self.exam, self.classroom)
        wb = load_workbook(io.BytesIO(xlsx), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        # Header row
        self.assertEqual(rows[0][0], "admission_number")
        self.assertEqual(rows[0][1], "student_name")
        # Subject names are lowercased on save; columns sorted by name
        self.assertIn("math", rows[0])
        self.assertIn("francais", rows[0])
        # 2 student rows + 1 hint row = 3 data rows after header
        self.assertEqual(len(rows), 4)

    def _build_filled_xlsx(self, payload_rows):
        """Helper: create an in-memory xlsx with the given header + rows."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["admission_number", "student_name", "Math", "Francais"])
        for row in payload_rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_upload_creates_and_updates_marks(self):
        from examination.services import parse_marks_xlsx

        f = self._build_filled_xlsx(
            [
                [self.alice.student.admission_number, "alice test", 16, 14],
                [self.bob.student.admission_number, "bob test", 12, 18],
            ]
        )
        result = parse_marks_xlsx(
            f, self.exam, self.classroom, self.classroom.class_teacher
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["created"], 4)
        self.assertEqual(result["updated"], 0)

        # Re-upload with one updated value -> updated, not created
        f2 = self._build_filled_xlsx(
            [
                [self.alice.student.admission_number, "alice test", 18, 14],
            ]
        )
        result2 = parse_marks_xlsx(
            f2, self.exam, self.classroom, self.classroom.class_teacher
        )
        self.assertEqual(result2["errors"], [])
        self.assertEqual(result2["updated"], 2)
        self.assertEqual(
            MarksManagement.objects.get(
                exam_name=self.exam, subject=self.math, student=self.alice
            ).points_scored,
            18,
        )

    def test_upload_with_out_of_range_value_writes_nothing(self):
        from examination.services import parse_marks_xlsx

        f = self._build_filled_xlsx(
            [
                [self.alice.student.admission_number, "alice", 16, 14],
                [self.bob.student.admission_number, "bob", 25, 12],  # 25 > 20
            ]
        )
        result = parse_marks_xlsx(
            f, self.exam, self.classroom, self.classroom.class_teacher
        )
        # One error, all-or-nothing => 0 written
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["created"], 0)
        self.assertEqual(MarksManagement.objects.count(), 0)

    def test_upload_with_unknown_admission_number(self):
        from examination.services import parse_marks_xlsx

        f = self._build_filled_xlsx(
            [
                ["NOPE-999", "ghost", 16, 14],
            ]
        )
        result = parse_marks_xlsx(
            f, self.exam, self.classroom, self.classroom.class_teacher
        )
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("NOPE-999", result["errors"][0]["msg"])

    def test_upload_skips_blank_cells(self):
        from examination.services import parse_marks_xlsx

        f = self._build_filled_xlsx(
            [
                [self.alice.student.admission_number, "alice", 16, None],
                [self.bob.student.admission_number, "bob", None, 18],
            ]
        )
        result = parse_marks_xlsx(
            f, self.exam, self.classroom, self.classroom.class_teacher
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["created"], 2)  # only the non-blank cells


class ReadPermissionTests(TestCase):
    """Verify GET endpoints scope visibility by role:
    admin sees everything; teachers see their allocated classrooms;
    parents see only their children; class-wide endpoints reject parents."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=700, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=701, name="6eme", grade_level=gl)
        cls.classroom_a = _create_classroom(cl, "RA")
        cls.classroom_b = _create_classroom(cl, "RB")

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

        # Teacher allocated to classroom_a only
        cls.teacher_a = cls.classroom_a.class_teacher
        AllocatedSubject.objects.create(
            teacher_name=cls.teacher_a,
            subject=cls.math,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom_a,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )
        # Teacher of classroom_b — not allocated to classroom_a
        cls.teacher_b = cls.classroom_b.class_teacher

        # _enroll auto-creates a Parent via Student.save() linked by parent_contact;
        # we use that auto-created parent as the "logged-in parent" for the tests.
        cls.enr_a = _enroll(cls.classroom_a, cls.year, "Alpha")
        cls.parent = cls.enr_a.student.parent_guardian

        # Unrelated enrollment in classroom_b (different parent_contact -> different Parent)
        cls.enr_b = _enroll(cls.classroom_b, cls.year, "Beta")

        cls.exam = _make_exam("DS1 T1", cls.classroom_a, cls.term, out_of=20)
        MarksManagement.objects.create(
            exam_name=cls.exam,
            points_scored=15,
            subject=cls.math,
            student=cls.enr_a,
            created_by=cls.teacher_a,
        )

        cls.admin = CustomUser.objects.create_superuser(
            email="admin-r@test.gn", password="x"
        )

    # --- Bulletin (per enrollment) ---

    def test_anonymous_cannot_read_bulletin(self):
        client = APIClient()
        url = (
            f"/api/examination/enrollments/{self.enr_a.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertIn(client.get(url).status_code, (401, 403))

    def test_admin_can_read_any_bulletin(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        url = (
            f"/api/examination/enrollments/{self.enr_b.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_200_OK)

    def test_teacher_of_classroom_can_read_bulletin(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_a.user)
        url = (
            f"/api/examination/enrollments/{self.enr_a.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_200_OK)

    def test_other_teacher_cannot_read_bulletin(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_b.user)
        url = (
            f"/api/examination/enrollments/{self.enr_a.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_parent_can_read_own_child_bulletin(self):
        client = APIClient()
        client.force_authenticate(user=self.parent.user)
        url = (
            f"/api/examination/enrollments/{self.enr_a.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_200_OK)

    def test_parent_cannot_read_other_child_bulletin(self):
        client = APIClient()
        client.force_authenticate(user=self.parent.user)
        url = (
            f"/api/examination/enrollments/{self.enr_b.id}"
            f"/terms/{self.term.id}/bulletin/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    # --- Class-wide endpoints (parents must be rejected) ---

    def test_parent_cannot_read_class_ranking(self):
        client = APIClient()
        client.force_authenticate(user=self.parent.user)
        url = (
            f"/api/examination/classrooms/{self.classroom_a.id}"
            f"/terms/{self.term.id}/ranking/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_parent_cannot_read_class_bulletins_zip(self):
        client = APIClient()
        client.force_authenticate(user=self.parent.user)
        url = (
            f"/api/examination/classrooms/{self.classroom_a.id}"
            f"/terms/{self.term.id}/bulletins-pdf/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_can_read_their_class_ranking(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_a.user)
        url = (
            f"/api/examination/classrooms/{self.classroom_a.id}"
            f"/terms/{self.term.id}/ranking/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_200_OK)

    def test_other_teacher_cannot_read_class_ranking(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_b.user)
        url = (
            f"/api/examination/classrooms/{self.classroom_a.id}"
            f"/terms/{self.term.id}/ranking/"
        )
        self.assertEqual(client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    # --- MarksListView queryset filtering ---

    def test_parent_marks_list_only_includes_their_children(self):
        # Add a mark for the unrelated student in classroom_b
        francais = Subject.objects.create(name="Francais")
        AllocatedSubject.objects.create(
            teacher_name=self.teacher_b,
            subject=francais,
            academic_year=self.year,
            term=self.term,
            class_room=self.classroom_b,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )
        exam_b = _make_exam("DS1 B", self.classroom_b, self.term, out_of=20)
        MarksManagement.objects.create(
            exam_name=exam_b,
            points_scored=10,
            subject=francais,
            student=self.enr_b,
            created_by=self.teacher_b,
        )

        client = APIClient()
        client.force_authenticate(user=self.parent.user)
        response = client.get("/api/examination/marks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data["results"] if isinstance(data, dict) else data
        student_ids = {row["student"] for row in results}
        self.assertEqual(student_ids, {self.enr_a.id})

    def test_teacher_marks_list_only_includes_allocated_classrooms(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher_a.user)
        response = client.get("/api/examination/marks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data["results"] if isinstance(data, dict) else data
        # teacher_a is allocated to classroom_a only — sees the one mark there
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["student"], self.enr_a.id)


class PaginationTests(TestCase):
    """Verify MarksListView pages results once page_size is exceeded."""

    @classmethod
    def setUpTestData(cls):
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=900, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=901, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "PG")
        cls.classroom.capacity = 100  # default 40 is too small for 55 enrollments
        cls.classroom.save()
        cls.year = AcademicYear.objects.create(
            name="2025-26", start_date=date(2025, 9, 1), active_year=True
        )
        cls.term = Term.objects.create(
            name="T1",
            academic_year=cls.year,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )
        cls.subject = Subject.objects.create(name="Math")
        cls.exam = _make_exam("DS1", cls.classroom, cls.term, out_of=20)

        # 55 marks (above default page_size=50)
        teacher = cls.classroom.class_teacher
        for i in range(55):
            enr = _enroll(cls.classroom, cls.year, f"S{i}")
            MarksManagement.objects.create(
                exam_name=cls.exam,
                points_scored=10,
                subject=cls.subject,
                student=enr,
                created_by=teacher,
            )

        cls.admin = CustomUser.objects.create_superuser(
            email="admin-pg@test.gn", password="x"
        )

    def test_default_page_size_is_50_with_paginated_envelope(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/examination/marks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("results", data)
        self.assertEqual(data["count"], 55)
        self.assertEqual(len(data["results"]), 50)
        self.assertIsNotNone(data["next"])

    def test_custom_page_size_query_param(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/examination/marks/?page_size=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 10)

    def test_max_page_size_caps_at_200(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/examination/marks/?page_size=500")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # We have 55 rows total; max_page_size=200 caps but doesn't add data
        self.assertEqual(len(response.json()["results"]), 55)


class MarksCleanValidationTests(TestCase):
    """Verify MarksManagement.save() runs full_clean() so out-of-range
    points_scored is rejected on every write path."""

    @classmethod
    def setUpTestData(cls):
        from django.core.exceptions import ValidationError as DjangoValidationError

        cls.DjangoValidationError = DjangoValidationError
        cls.scale = GradeScale.objects.get(name="/20")
        gl = GradeLevel.objects.create(id=1000, name="Collège", grade_scale=cls.scale)
        cl = ClassLevel.objects.create(id=1001, name="6eme", grade_level=gl)
        cls.classroom = _create_classroom(cl, "CV")
        cls.year = AcademicYear.objects.create(
            name="2025-26", start_date=date(2025, 9, 1), active_year=True
        )
        cls.term = Term.objects.create(
            name="T1",
            academic_year=cls.year,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )
        cls.subject = Subject.objects.create(name="Math")
        AllocatedSubject.objects.create(
            teacher_name=cls.classroom.class_teacher,
            subject=cls.subject,
            academic_year=cls.year,
            term=cls.term,
            class_room=cls.classroom,
            coefficient=Decimal("1"),
            weekly_periods=4,
        )
        cls.exam = _make_exam("DS1", cls.classroom, cls.term, out_of=20)
        cls.enr = _enroll(cls.classroom, cls.year, "X")
        cls.admin = CustomUser.objects.create_superuser(
            email="admin-cv@test.gn", password="x"
        )

    def test_direct_orm_write_with_out_of_range_raises(self):
        with self.assertRaises(self.DjangoValidationError):
            MarksManagement.objects.create(
                exam_name=self.exam,
                points_scored=25,  # out_of is 20
                subject=self.subject,
                student=self.enr,
                created_by=self.classroom.class_teacher,
            )

    def test_direct_orm_write_with_negative_raises(self):
        with self.assertRaises(self.DjangoValidationError):
            MarksManagement.objects.create(
                exam_name=self.exam,
                points_scored=-1,
                subject=self.subject,
                student=self.enr,
                created_by=self.classroom.class_teacher,
            )

    def test_drf_post_out_of_range_returns_400(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.post(
            "/api/examination/marks/",
            {
                "exam_name": self.exam.id,
                "points_scored": 99,
                "subject": self.subject.id,
                "student": self.enr.id,
                "created_by": self.classroom.class_teacher.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("points_scored", str(response.json()))

    def test_valid_write_succeeds(self):
        # Sanity: full_clean shouldn't reject a valid write
        mark = MarksManagement.objects.create(
            exam_name=self.exam,
            points_scored=15,
            subject=self.subject,
            student=self.enr,
            created_by=self.classroom.class_teacher,
        )
        self.assertEqual(mark.points_scored, 15)
