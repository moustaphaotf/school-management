"""Custom DRF permissions for the examination app.

Design:
- Reads are scoped by role:
    * admin (superuser/staff) sees everything,
    * teachers see data for classrooms where they have an AllocatedSubject,
    * parents see data for their children only (Student.parent_guardian).
- Writes on marks reserved to admin or the teacher allocated to the subject
  for that classroom.
- For exams (ExaminationListHandler), the creator OR a teacher of one of
  the linked classrooms can write.
"""
from rest_framework import permissions

from academic.models import AllocatedSubject, Student, StudentClassEnrollment
from .models import ExaminationListHandler, MarksManagement


def is_admin(user) -> bool:
    return bool(
        user and user.is_authenticated and (user.is_superuser or user.is_staff)
    )


def user_can_view_classroom(user, classroom_id: int) -> bool:
    """True if user is admin, a teacher allocated to this classroom, or
    a parent with at least one child enrolled in this classroom."""
    if not user or not user.is_authenticated:
        return False
    if is_admin(user):
        return True
    teacher = getattr(user, "teacher", None)
    if teacher is not None:
        if AllocatedSubject.objects.filter(
            teacher_name=teacher, class_room_id=classroom_id
        ).exists():
            return True
    parent = getattr(user, "parent", None)
    if parent is not None:
        if StudentClassEnrollment.objects.filter(
            classroom_id=classroom_id, student__parent_guardian=parent
        ).exists():
            return True
    return False


def user_can_view_enrollment(user, enrollment_id: int) -> bool:
    """True if user is admin, a teacher allocated to the enrollment's
    classroom, or the parent of the enrolled student."""
    if not user or not user.is_authenticated:
        return False
    if is_admin(user):
        return True
    enrollment = (
        StudentClassEnrollment.objects.filter(pk=enrollment_id)
        .select_related("student")
        .first()
    )
    if enrollment is None:
        return False
    teacher = getattr(user, "teacher", None)
    if teacher is not None:
        if AllocatedSubject.objects.filter(
            teacher_name=teacher, class_room_id=enrollment.classroom_id
        ).exists():
            return True
    parent = getattr(user, "parent", None)
    if parent is not None:
        if enrollment.student.parent_guardian_id == parent.id:
            return True
    return False


class CanViewExaminationData(permissions.BasePermission):
    """Base gate for read endpoints on examination data: must be admin,
    a teacher, or a parent. Per-row visibility is enforced via queryset
    filtering in the view's get_queryset."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return (
            is_admin(user)
            or getattr(user, "teacher", None) is not None
            or getattr(user, "parent", None) is not None
        )


class IsAdminOrTeacherOfClassroom(permissions.BasePermission):
    """Used by class-wide views (ZIP bulletins, ranking, grid, generate
    results) where parents must NOT see the whole class. The view's
    URL kwarg `classroom_id` is consulted."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if is_admin(user):
            return True
        teacher = getattr(user, "teacher", None)
        if teacher is None:
            return False
        classroom_id = view.kwargs.get("classroom_id")
        if classroom_id is None:
            return False
        return AllocatedSubject.objects.filter(
            teacher_name=teacher, class_room_id=classroom_id
        ).exists()


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
