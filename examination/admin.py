from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ExaminationListHandler,
    GradeScale,
    GradeScaleRule,
    MarksManagement,
    Result,
)
from . import services


# --- Grade scales ---


class GradeScaleRuleInline(admin.TabularInline):
    model = GradeScaleRule
    extra = 0
    fields = ("min_grade", "max_grade", "letter_grade", "numeric_scale")


@admin.register(GradeScale)
class GradeScaleAdmin(admin.ModelAdmin):
    list_display = ("name",)
    inlines = [GradeScaleRuleInline]


@admin.register(GradeScaleRule)
class GradeScaleRuleAdmin(admin.ModelAdmin):
    list_display = (
        "grade_scale",
        "min_grade",
        "max_grade",
        "letter_grade",
        "numeric_scale",
    )
    list_filter = ("grade_scale",)


# --- Exams + inline marks ---


class MarksManagementInline(admin.TabularInline):
    """Saisie des notes en grille depuis la page d'un examen.

    Une ligne par note. Pour saisir 30 notes en bloc, on peut ajouter
    30 lignes vides (extra=30) ou utiliser l'endpoint API bulk."""

    model = MarksManagement
    extra = 0
    fields = ("student", "subject", "points_scored", "created_by")
    raw_id_fields = ("student", "subject", "created_by")


@admin.register(ExaminationListHandler)
class ExaminationListHandlerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "term",
        "start_date",
        "ends_date",
        "out_of",
        "status",
        "created_by",
    )
    list_filter = ("term", "term__academic_year", "created_by")
    search_fields = ("name",)
    filter_horizontal = ("classrooms",)
    inlines = [MarksManagementInline]
    actions = ["regenerate_results_for_terms"]

    def save_formset(self, request, form, formset, change):
        """Auto-fill MarksManagement.created_by with the logged-in teacher."""
        if formset.model is MarksManagement:
            instances = formset.save(commit=False)
            teacher = getattr(request.user, "teacher", None)
            for instance in instances:
                if not instance.created_by_id and teacher is not None:
                    instance.created_by = teacher
                instance.save()
            for obj in formset.deleted_objects:
                obj.delete()
            formset.save_m2m()
        else:
            formset.save()

    @admin.action(description="Regenerate Results for the term of selected exams")
    def regenerate_results_for_terms(self, request, queryset):
        """For each unique (classroom, term) of the selected exams, recompute
        and persist Results. Useful after bulk-editing marks."""
        pairs = set()
        for exam in queryset.select_related("term").prefetch_related("classrooms"):
            if exam.term is None:
                continue
            for classroom in exam.classrooms.all():
                pairs.add((classroom.id, exam.term_id))

        from academic.models import ClassRoom
        from administration.models import Term

        total = 0
        for classroom_id, term_id in pairs:
            classroom = ClassRoom.objects.get(pk=classroom_id)
            term = Term.objects.get(pk=term_id)
            saved = services.generate_term_results(classroom, term)
            total += len(saved)

        self.message_user(
            request,
            f"Regenerated {total} Result rows across {len(pairs)} (classroom, term) pairs.",
        )


@admin.register(MarksManagement)
class MarksManagementAdmin(admin.ModelAdmin):
    list_display = (
        "exam_name",
        "subject",
        "student",
        "points_scored",
        "created_by",
        "date_time",
    )
    list_filter = ("exam_name__term", "subject", "created_by")
    search_fields = (
        "student__student__first_name",
        "student__student__last_name",
        "subject__name",
    )
    raw_id_fields = ("student", "subject", "exam_name", "created_by")

    def save_model(self, request, obj, form, change):
        """Auto-fill created_by on first save if the user is a teacher."""
        if not obj.created_by_id:
            teacher = getattr(request.user, "teacher", None)
            if teacher is not None:
                obj.created_by = teacher
        super().save_model(request, obj, form, change)


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "academic_year",
        "term",
        "average",
        "rank",
        "mention",
    )
    list_filter = ("academic_year", "term", "mention")
    search_fields = ("student__first_name", "student__last_name")
    raw_id_fields = ("student", "academic_year", "term")
    readonly_fields = ("gpa", "cat_gpa")
    actions = ["download_bulletins_zip"]

    @admin.action(description="Download bulletins ZIP for selected (one classroom + term only)")
    def download_bulletins_zip(self, request, queryset):
        """Build a ZIP of PDF bulletins for the selected Results.

        Requires the selection to be a single (academic_year, term, classroom)
        triple. The classroom is resolved via the StudentClassEnrollment of
        each student for that academic_year."""
        from academic.models import ClassRoom, StudentClassEnrollment
        from administration.models import Term

        if not queryset.exists():
            self.message_user(request, "No Results selected.", level=messages.ERROR)
            return

        terms = set(queryset.values_list("term_id", flat=True))
        years = set(queryset.values_list("academic_year_id", flat=True))
        if len(terms) != 1 or None in terms:
            self.message_user(
                request,
                "Select Results from a single (non-empty) term only.",
                level=messages.ERROR,
            )
            return
        if len(years) != 1:
            self.message_user(
                request,
                "Select Results from a single academic year only.",
                level=messages.ERROR,
            )
            return

        term_id = terms.pop()
        academic_year_id = years.pop()
        student_ids = list(queryset.values_list("student_id", flat=True))

        classrooms = set(
            StudentClassEnrollment.objects.filter(
                student_id__in=student_ids, academic_year_id=academic_year_id
            ).values_list("classroom_id", flat=True)
        )
        if len(classrooms) != 1:
            self.message_user(
                request,
                "Selected Results span multiple classrooms. "
                "Filter the changelist to one classroom and re-run.",
                level=messages.ERROR,
            )
            return

        classroom = ClassRoom.objects.get(pk=classrooms.pop())
        term = Term.objects.get(pk=term_id)
        zip_bytes, success, failed = services.render_class_bulletins_zip(
            classroom, term
        )
        if success == 0:
            self.message_user(
                request,
                f"No bulletins generated. Failed: {failed or 'none'}",
                level=messages.ERROR,
            )
            return

        response = HttpResponse(zip_bytes, content_type="application/zip")
        filename = f"bulletins_classroom{classroom.id}_{term.name}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if failed:
            self.message_user(
                request,
                f"{success} bulletins generated. Failed: {', '.join(failed)}",
                level=messages.WARNING,
            )
        return response
