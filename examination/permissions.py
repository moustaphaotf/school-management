"""Custom DRF permissions for the examination app.

Design:
- Any authenticated user can READ marks, exams, results, bulletins.
- Only admins (superuser/staff) and the teacher allocated to the subject
  can CREATE/UPDATE/DELETE marks for a given (subject, classroom).
- For exams (ExaminationListHandler), the creator OR a teacher of one of
  the linked classrooms can write.
"""
from rest_framework import permissions

from academic.models import AllocatedSubject
from .models import ExaminationListHandler, MarksManagement


class IsTeacherOfSubjectOrAdmin(permissions.BasePermission):
    """Authenticated read; write reserved to admin or the responsible teacher."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        return getattr(request.user, "teacher", None) is not None

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        teacher = getattr(request.user, "teacher", None)
        if teacher is None:
            return False
        if isinstance(obj, MarksManagement):
            return AllocatedSubject.objects.filter(
                teacher_name=teacher,
                subject=obj.subject,
                class_room=obj.student.classroom,
            ).exists()
        if isinstance(obj, ExaminationListHandler):
            if obj.created_by_id == teacher.id:
                return True
            return AllocatedSubject.objects.filter(
                teacher_name=teacher,
                class_room__in=obj.classrooms.all(),
            ).exists()
        return True


def teacher_owns_subject(
    teacher, subject_id: int, classroom_id: int, academic_year_id: int = None
) -> bool:
    """Helper used inside views (e.g., bulk-entry) to check a teacher is
    allocated to a (subject, classroom) — optionally for a given academic_year."""
    if teacher is None:
        return False
    qs = AllocatedSubject.objects.filter(
        teacher_name=teacher,
        subject_id=subject_id,
        class_room_id=classroom_id,
    )
    if academic_year_id is not None:
        qs = qs.filter(academic_year_id=academic_year_id)
    return qs.exists()
