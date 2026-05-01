from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsTeacherOfSubjectOrAdmin, teacher_owns_subject

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
    permission_classes = [IsTeacherOfSubjectOrAdmin]

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
    permission_classes = [IsTeacherOfSubjectOrAdmin]


# --- Marks (individual) ---


class MarksListView(generics.ListCreateAPIView):
    queryset = MarksManagement.objects.all().select_related(
        "exam_name", "subject", "student__student"
    )
    serializer_class = MarkSerializer
    permission_classes = [IsTeacherOfSubjectOrAdmin]

    def perform_create(self, serializer):
        """On create, enforce that the requesting teacher is allocated to
        the (subject, classroom). Admins bypass."""
        user = self.request.user
        if user.is_superuser or user.is_staff:
            serializer.save()
            return
        teacher = getattr(user, "teacher", None)
        subject = serializer.validated_data["subject"]
        enrollment = serializer.validated_data["student"]
        if not teacher_owns_subject(teacher, subject.id, enrollment.classroom_id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You are not allocated to this subject for this classroom."
            )
        if not serializer.validated_data.get("created_by"):
            serializer.save(created_by=teacher)
        else:
            serializer.save()

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
    permission_classes = [IsTeacherOfSubjectOrAdmin]


# --- Bulk marks entry (one exam x one subject, many students) ---


class MarksBulkEntryView(APIView):
    """POST: enter many marks for one (exam, subject) atomically.

    Existing marks for the same (exam, subject, student) are updated.
    Teachers can only post for subjects they are allocated to (per
    classroom). Admins bypass."""

    permission_classes = [IsTeacherOfSubjectOrAdmin]

    def post(self, request):
        serializer = BulkMarksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.validated_data["exam_name"]
        subject = serializer.validated_data["subject"]
        items = serializer.validated_data["marks"]

        teacher = getattr(request.user, "teacher", None)
        is_admin = request.user.is_superuser or request.user.is_staff

        if not is_admin:
            # Verify the requesting teacher is allocated to this subject for
            # every classroom touched by the marks.
            classrooms = {item["student"].classroom_id for item in items}
            for classroom_id in classrooms:
                if not teacher_owns_subject(teacher, subject.id, classroom_id):
                    from rest_framework.exceptions import PermissionDenied

                    raise PermissionDenied(
                        "You are not allocated to this subject for one or "
                        "more of the classrooms in the payload."
                    )

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
        payload = services.build_bulletin_payload(enrollment, term)
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
        pdf_bytes = services.render_bulletin_pdf(enrollment, term)
        if pdf_bytes is None:
            return Response(
                {"detail": "PDF generation failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = (
            f"bulletin_{enrollment.student.last_name}_"
            f"{enrollment.student.first_name}_{term.name}.pdf"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ClassBulletinsZIPView(APIView):
    """GET a ZIP archive of PDF bulletins for every enrolled student in
    a (classroom, term)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, classroom_id, term_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        term = get_object_or_404(Term, pk=term_id)
        zip_bytes, success, failed = services.render_class_bulletins_zip(
            classroom, term
        )
        if success == 0:
            return Response(
                {
                    "detail": "No bulletins generated.",
                    "failed": failed,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        response = HttpResponse(zip_bytes, content_type="application/zip")
        filename = f"bulletins_classroom{classroom.id}_{term.name}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if failed:
            response["X-Failed-Students"] = ", ".join(failed)
        return response


# --- Bulk Excel: template download + upload ---


class MarksTemplateXLSXView(APIView):
    """GET an .xlsx template pre-filled with the students of a classroom
    and a column per subject allocated for the exam's term."""

    permission_classes = [IsAuthenticated]

    def get(self, request, exam_id, classroom_id):
        exam = get_object_or_404(ExaminationListHandler, pk=exam_id)
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        try:
            xlsx_bytes = services.build_marks_template_xlsx(exam, classroom)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(
            xlsx_bytes,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        filename = f"marks_template_exam{exam.id}_classroom{classroom.id}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class MarksBulkUploadView(APIView):
    """POST multipart .xlsx file, parses marks, validates, persists atomically
    if no errors. Permission: same as bulk-entry — allocated teacher or admin."""

    permission_classes = [IsTeacherOfSubjectOrAdmin]

    def post(self, request, exam_id, classroom_id):
        exam = get_object_or_404(ExaminationListHandler, pk=exam_id)
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)

        file_obj = request.FILES.get("file")
        if file_obj is None:
            return Response(
                {"detail": "No 'file' part in the request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        teacher = getattr(request.user, "teacher", None)
        is_admin = request.user.is_superuser or request.user.is_staff
        if not is_admin and teacher is None:
            return Response(
                {"detail": "Authenticated user has no Teacher record."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Permission gate: validate the teacher owns every subject that
        # appears in the file BEFORE applying. We do a dry-run parse first.
        dry = services.parse_marks_xlsx(
            file_obj, exam, classroom, teacher, apply_changes=False
        )
        if dry["errors"]:
            return Response(
                {
                    "detail": "Validation failed; no marks written.",
                    "errors": dry["errors"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Re-open the file (read_only mode advanced the cursor); request
        # files are seekable so we just rewind.
        file_obj.seek(0)
        if not is_admin:
            # Re-parse headers to find subjects referenced, then verify
            # allocation. parse_marks_xlsx already verified allocation,
            # but here we layer the teacher-ownership check.
            from openpyxl import load_workbook
            wb = load_workbook(filename=file_obj, read_only=True, data_only=True)
            ws = wb.active
            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
            headers = [str(h).strip() if h is not None else "" for h in first_row]
            for header in headers[2:]:
                if not header:
                    continue
                subject = Subject.objects.filter(name__iexact=header).first()
                if subject is None:
                    continue
                if not teacher_owns_subject(teacher, subject.id, classroom.id):
                    return Response(
                        {
                            "detail": (
                                f"You are not allocated to subject "
                                f"'{subject.name}' for this classroom."
                            )
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
            file_obj.seek(0)

        result = services.parse_marks_xlsx(
            file_obj, exam, classroom, teacher, apply_changes=True
        )
        return Response(result, status=status.HTTP_200_OK)


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
