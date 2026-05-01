import io
from decimal import Decimal

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from xhtml2pdf import pisa

from academic.models import (
    AllocatedSubject,
    ClassRoom,
    StudentClassEnrollment,
    Subject,
)
from administration.models import Term
from .models import (
    ExaminationListHandler,
    GradeScale,
    GradeScaleRule,
    MarksManagement,
    Result,
)
from .serializers import (
    BulkMarksSerializer,
    BulletinSerializer,
    ClassRankingRowSerializer,
    ExamSerializer,
    GradeScaleSerializer,
    GradeScaleRuleSerializer,
    MarkSerializer,
    ResultSerializer,
)
from . import services


# --- Grade scales (read-only for now) ---


class GradeScaleListView(generics.ListCreateAPIView):
    queryset = GradeScale.objects.all()
    serializer_class = GradeScaleSerializer
    permission_classes = [IsAuthenticated]


class GradeScaleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GradeScale.objects.all()
    serializer_class = GradeScaleSerializer
    permission_classes = [IsAuthenticated]


class GradeScaleRuleListView(generics.ListCreateAPIView):
    queryset = GradeScaleRule.objects.all()
    serializer_class = GradeScaleRuleSerializer
    permission_classes = [IsAuthenticated]


class GradeScaleRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GradeScaleRule.objects.all()
    serializer_class = GradeScaleRuleSerializer
    permission_classes = [IsAuthenticated]


# --- Exams ---


class ExamListView(generics.ListCreateAPIView):
    queryset = ExaminationListHandler.objects.all().select_related("term")
    serializer_class = ExamSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        term_id = self.request.query_params.get("term")
        classroom_id = self.request.query_params.get("classroom")
        if term_id:
            qs = qs.filter(term_id=term_id)
        if classroom_id:
            qs = qs.filter(classrooms__id=classroom_id)
        return qs.distinct()


class ExamDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ExaminationListHandler.objects.all()
    serializer_class = ExamSerializer
    permission_classes = [IsAuthenticated]


# --- Marks (individual) ---


class MarksListView(generics.ListCreateAPIView):
    queryset = MarksManagement.objects.all().select_related(
        "exam_name", "subject", "student__student"
    )
    serializer_class = MarkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        exam_id = self.request.query_params.get("exam")
        subject_id = self.request.query_params.get("subject")
        if exam_id:
            qs = qs.filter(exam_name_id=exam_id)
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        return qs


class MarksDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MarksManagement.objects.all()
    serializer_class = MarkSerializer
    permission_classes = [IsAuthenticated]


# --- Bulk marks entry (one exam x one subject, many students) ---


class MarksBulkEntryView(APIView):
    """POST: enter many marks for one (exam, subject) atomically.

    Existing marks for the same (exam, subject, student) are updated."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BulkMarksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.validated_data["exam_name"]
        subject = serializer.validated_data["subject"]
        items = serializer.validated_data["marks"]

        teacher = getattr(request.user, "teacher", None)

        created, updated = 0, 0
        with transaction.atomic():
            for item in items:
                obj, was_created = MarksManagement.objects.update_or_create(
                    exam_name=exam,
                    subject=subject,
                    student=item["student"],
                    defaults={
                        "points_scored": item["points_scored"],
                        "created_by": teacher,
                    },
                )
                created += 1 if was_created else 0
                updated += 0 if was_created else 1

        return Response(
            {"created": created, "updated": updated, "total": created + updated},
            status=status.HTTP_200_OK,
        )


# --- Class marks grid (read by exam + classroom) ---


class ClassMarksView(APIView):
    """GET marks for one (classroom, exam) as a grid view payload.

    Returns the list of enrollments in the classroom, plus per-subject marks
    for the given exam. Useful for an admin/UI grid."""

    permission_classes = [IsAuthenticated]

    def get(self, request, classroom_id, exam_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        exam = get_object_or_404(ExaminationListHandler, pk=exam_id)

        enrollments = (
            StudentClassEnrollment.objects.filter(classroom=classroom)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )
        subjects = list(
            AllocatedSubject.objects.filter(
                class_room=classroom, term=exam.term
            ).select_related("subject")
        )

        marks_qs = MarksManagement.objects.filter(
            exam_name=exam, student__in=enrollments
        )
        # index by (student_id, subject_id)
        index = {(m.student_id, m.subject_id): m for m in marks_qs}

        rows = []
        for enr in enrollments:
            row = {
                "enrollment_id": enr.id,
                "student_id": enr.student_id,
                "student_name": (
                    f"{enr.student.first_name} {enr.student.last_name}".strip()
                ),
                "marks": [],
            }
            for alloc in subjects:
                m = index.get((enr.id, alloc.subject_id))
                row["marks"].append(
                    {
                        "subject_id": alloc.subject_id,
                        "subject_name": alloc.subject.name,
                        "coefficient": str(alloc.coefficient),
                        "points_scored": m.points_scored if m else None,
                        "mark_id": m.id if m else None,
                    }
                )
            rows.append(row)

        return Response(
            {
                "exam": {
                    "id": exam.id,
                    "name": exam.name,
                    "out_of": exam.out_of,
                    "term_id": exam.term_id,
                },
                "classroom_id": classroom.id,
                "rows": rows,
            }
        )


# --- Bulletin (read-only computed) ---


def _build_bulletin_payload(enrollment: StudentClassEnrollment, term: Term) -> dict:
    scale = services.get_grade_scale(enrollment)
    allocations = AllocatedSubject.objects.filter(
        class_room=enrollment.classroom,
        academic_year=enrollment.academic_year,
        term=term,
    ).select_related("subject")

    subject_lines = []
    for alloc in allocations:
        avg = services.compute_subject_average(enrollment, alloc.subject, term)
        coef = Decimal(str(alloc.coefficient or 1))
        weighted = (avg * coef) if avg is not None else None
        subject_lines.append(
            {
                "subject": alloc.subject.name,
                "coefficient": coef,
                "average": avg,
                "weighted": weighted,
            }
        )

    average = services.compute_term_average(enrollment, term)
    mention = services.assign_mention(average, scale) if average is not None else ""

    ranking = services.compute_class_ranking(enrollment.classroom, term)
    rank = next(
        (r["rank"] for r in ranking if r["enrollment"].id == enrollment.id), None
    )
    class_size = StudentClassEnrollment.objects.filter(
        classroom=enrollment.classroom
    ).count()

    return {
        "student_id": enrollment.student_id,
        "student_name": (
            f"{enrollment.student.first_name} {enrollment.student.last_name}".strip()
        ),
        "classroom": (
            f"{enrollment.classroom.name.name if enrollment.classroom.name else ''}"
            f" {enrollment.classroom.stream.name if enrollment.classroom.stream else ''}"
        ).strip(),
        "academic_year": enrollment.academic_year.name,
        "term": term.name,
        "scale": scale.name if scale else "",
        "subjects": subject_lines,
        "average": average,
        "rank": rank,
        "class_size": class_size,
        "mention": mention,
    }


class BulletinView(APIView):
    """GET bulletin (JSON) for one (student-enrollment, term)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, enrollment_id, term_id):
        enrollment = get_object_or_404(
            StudentClassEnrollment.objects.select_related(
                "student", "classroom", "academic_year"
            ),
            pk=enrollment_id,
        )
        term = get_object_or_404(Term, pk=term_id)
        payload = _build_bulletin_payload(enrollment, term)
        return Response(BulletinSerializer(payload).data)


class BulletinPDFView(APIView):
    """GET PDF bulletin for one (enrollment, term)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, enrollment_id, term_id):
        enrollment = get_object_or_404(
            StudentClassEnrollment.objects.select_related(
                "student", "classroom", "academic_year"
            ),
            pk=enrollment_id,
        )
        term = get_object_or_404(Term, pk=term_id)
        payload = _build_bulletin_payload(enrollment, term)
        html = render_to_string("examination/bulletin.html", {"b": payload})
        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf)
        if result.err:
            return Response(
                {"detail": "PDF generation failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = HttpResponse(buf.getvalue(), content_type="application/pdf")
        filename = (
            f"bulletin_{enrollment.student.last_name}_"
            f"{enrollment.student.first_name}_{term.name}.pdf"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# --- Class ranking ---


class ClassRankingView(APIView):
    """GET ranking for one (classroom, term)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, classroom_id, term_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        term = get_object_or_404(Term, pk=term_id)
        ranking = services.compute_class_ranking(classroom, term)
        rows = [
            {
                "student_id": r["enrollment"].student_id,
                "student_name": (
                    f"{r['enrollment'].student.first_name} "
                    f"{r['enrollment'].student.last_name}".strip()
                ),
                "average": r["average"],
                "rank": r["rank"],
                "mention": r["mention"],
            }
            for r in ranking
        ]
        return Response(ClassRankingRowSerializer(rows, many=True).data)


# --- Generate Results (persist) ---


class GenerateClassResultsView(APIView):
    """POST: persist Result rows for every student in a classroom for a term.

    Idempotent (update_or_create). Returns the count of saved rows."""

    permission_classes = [IsAuthenticated]

    def post(self, request, classroom_id, term_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        term = get_object_or_404(Term, pk=term_id)
        results = services.generate_term_results(classroom, term)
        return Response(
            {"saved": len(results), "term": term.name, "classroom_id": classroom.id},
            status=status.HTTP_200_OK,
        )


# --- Results CRUD ---


class ResultListView(generics.ListCreateAPIView):
    queryset = Result.objects.all().select_related("student", "term", "academic_year")
    serializer_class = ResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get("student")
        term_id = self.request.query_params.get("term")
        if student_id:
            qs = qs.filter(student_id=student_id)
        if term_id:
            qs = qs.filter(term_id=term_id)
        return qs


class ResultDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Result.objects.all()
    serializer_class = ResultSerializer
    permission_classes = [IsAuthenticated]
