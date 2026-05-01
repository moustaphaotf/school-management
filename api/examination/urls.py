from django.urls import path
from examination.views import (
    BulletinPDFView,
    BulletinView,
    ClassMarksView,
    ClassRankingView,
    ExamDetailView,
    ExamListView,
    GenerateClassResultsView,
    GradeScaleDetailView,
    GradeScaleListView,
    GradeScaleRuleDetailView,
    GradeScaleRuleListView,
    MarksBulkEntryView,
    MarksDetailView,
    MarksListView,
    ResultDetailView,
    ResultListView,
)


urlpatterns = [
    # Grade scales
    path("grade-scales/", GradeScaleListView.as_view(), name="grade-scale-list"),
    path(
        "grade-scales/<int:pk>/",
        GradeScaleDetailView.as_view(),
        name="grade-scale-detail",
    ),
    path(
        "grade-scale-rules/",
        GradeScaleRuleListView.as_view(),
        name="grade-scale-rule-list",
    ),
    path(
        "grade-scale-rules/<int:pk>/",
        GradeScaleRuleDetailView.as_view(),
        name="grade-scale-rule-detail",
    ),
    # Exams
    path("exams/", ExamListView.as_view(), name="exam-list"),
    path("exams/<int:pk>/", ExamDetailView.as_view(), name="exam-detail"),
    # Marks (individual + bulk)
    path("marks/", MarksListView.as_view(), name="mark-list"),
    path("marks/<int:pk>/", MarksDetailView.as_view(), name="mark-detail"),
    path("marks/bulk/", MarksBulkEntryView.as_view(), name="mark-bulk-entry"),
    # Class marks grid
    path(
        "classrooms/<int:classroom_id>/exams/<int:exam_id>/marks/",
        ClassMarksView.as_view(),
        name="class-marks",
    ),
    # Bulletin (one student, one term)
    path(
        "enrollments/<int:enrollment_id>/terms/<int:term_id>/bulletin/",
        BulletinView.as_view(),
        name="bulletin-json",
    ),
    path(
        "enrollments/<int:enrollment_id>/terms/<int:term_id>/bulletin/pdf/",
        BulletinPDFView.as_view(),
        name="bulletin-pdf",
    ),
    # Class ranking
    path(
        "classrooms/<int:classroom_id>/terms/<int:term_id>/ranking/",
        ClassRankingView.as_view(),
        name="class-ranking",
    ),
    # Generate persisted Results for a class+term
    path(
        "classrooms/<int:classroom_id>/terms/<int:term_id>/generate-results/",
        GenerateClassResultsView.as_view(),
        name="generate-class-results",
    ),
    # Results CRUD
    path("results/", ResultListView.as_view(), name="result-list"),
    path("results/<int:pk>/", ResultDetailView.as_view(), name="result-detail"),
]
