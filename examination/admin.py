from django.contrib import admin
from django.http import HttpResponseRedirect
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
