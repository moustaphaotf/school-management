from rest_framework import serializers

from academic.models import (
    AllocatedSubject,
    ClassRoom,
    StudentClassEnrollment,
    Subject,
    Teacher,
)
from administration.models import Term
from administration.serializers import TermSerializer
from .models import (
    ExaminationListHandler,
    GradeScale,
    GradeScaleRule,
    MarksManagement,
    Result,
)


class GradeScaleRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeScaleRule
        fields = ["id", "min_grade", "max_grade", "letter_grade", "numeric_scale"]


class GradeScaleSerializer(serializers.ModelSerializer):
    rules = GradeScaleRuleSerializer(
        many=True, read_only=True, source="gradescalerule_set"
    )

    class Meta:
        model = GradeScale
        fields = ["id", "name", "rules"]


class SubjectMiniSerializer(serializers.ModelSerializer):
    """Lightweight subject representation embedded in marks/bulletins."""

    class Meta:
        model = Subject
        fields = ["id", "name", "subject_code"]


class ClassRoomMiniSerializer(serializers.ModelSerializer):
    class_level = serializers.CharField(source="name.name", read_only=True)
    stream = serializers.CharField(source="stream.name", read_only=True)

    class Meta:
        model = ClassRoom
        fields = ["id", "class_level", "stream"]


class ExamSerializer(serializers.ModelSerializer):
    """CRUD on ExaminationListHandler (an exam definition)."""

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(), allow_null=True, required=False
    )
    classrooms = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ClassRoom.objects.all()
    )
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=Teacher.objects.all(), allow_null=True, required=False
    )

    term_details = TermSerializer(read_only=True, source="term")
    classrooms_details = ClassRoomMiniSerializer(
        many=True, read_only=True, source="classrooms"
    )
    status = serializers.CharField(read_only=True)

    class Meta:
        model = ExaminationListHandler
        fields = [
            "id",
            "name",
            "start_date",
            "ends_date",
            "out_of",
            "term",
            "term_details",
            "classrooms",
            "classrooms_details",
            "comments",
            "created_by",
            "created_on",
            "status",
        ]
        read_only_fields = ["created_on"]

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("ends_date")
        if start and end and start > end:
            raise serializers.ValidationError(
                {"ends_date": "ends_date must be on or after start_date."}
            )
        out_of = attrs.get("out_of")
        if out_of is not None and out_of <= 0:
            raise serializers.ValidationError(
                {"out_of": "out_of must be a positive integer."}
            )
        return attrs


class MarkSerializer(serializers.ModelSerializer):
    """CRUD on a single MarksManagement entry."""

    exam_name = serializers.PrimaryKeyRelatedField(
        queryset=ExaminationListHandler.objects.all()
    )
    subject = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    student = serializers.PrimaryKeyRelatedField(
        queryset=StudentClassEnrollment.objects.all()
    )
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=Teacher.objects.all(), required=False
    )

    subject_details = SubjectMiniSerializer(read_only=True, source="subject")
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = MarksManagement
        fields = [
            "id",
            "exam_name",
            "points_scored",
            "subject",
            "subject_details",
            "student",
            "student_name",
            "created_by",
            "date_time",
        ]
        read_only_fields = ["date_time"]

    def get_student_name(self, obj):
        s = obj.student.student
        return f"{s.first_name} {s.last_name}".strip()

    def validate(self, attrs):
        exam = attrs.get("exam_name") or getattr(self.instance, "exam_name", None)
        points = attrs.get("points_scored")
        if exam and points is not None:
            if points < 0 or points > exam.out_of:
                raise serializers.ValidationError(
                    {
                        "points_scored": (
                            f"points_scored must be between 0 and {exam.out_of}."
                        )
                    }
                )
        return attrs


class BulkMarkItemSerializer(serializers.Serializer):
    """One row in a bulk-marks payload."""

    student = serializers.PrimaryKeyRelatedField(
        queryset=StudentClassEnrollment.objects.all()
    )
    points_scored = serializers.FloatField(min_value=0)


class BulkMarksSerializer(serializers.Serializer):
    """Bulk POST: enter many marks for one (exam, subject) at once."""

    exam_name = serializers.PrimaryKeyRelatedField(
        queryset=ExaminationListHandler.objects.all()
    )
    subject = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    marks = BulkMarkItemSerializer(many=True)

    def validate(self, attrs):
        exam = attrs["exam_name"]
        for item in attrs["marks"]:
            if item["points_scored"] > exam.out_of:
                raise serializers.ValidationError(
                    f"points_scored {item['points_scored']} exceeds out_of {exam.out_of}"
                )
        return attrs


class ResultSerializer(serializers.ModelSerializer):
    """CRUD on a persisted Result row (term aggregate)."""

    term_details = TermSerializer(read_only=True, source="term")
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Result
        fields = [
            "id",
            "student",
            "student_name",
            "academic_year",
            "term",
            "term_details",
            "average",
            "rank",
            "mention",
            "gpa",
            "cat_gpa",
        ]

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}".strip()


class BulletinSubjectLineSerializer(serializers.Serializer):
    """One line on a bulletin: subject + coefficient + average."""

    subject = serializers.CharField()
    coefficient = serializers.DecimalField(max_digits=4, decimal_places=2)
    average = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True
    )
    weighted = serializers.DecimalField(
        max_digits=7, decimal_places=2, allow_null=True
    )


class BulletinSerializer(serializers.Serializer):
    """Read-only bulletin payload for one student in one term."""

    student_id = serializers.IntegerField()
    student_name = serializers.CharField()
    classroom = serializers.CharField()
    academic_year = serializers.CharField()
    term = serializers.CharField()
    scale = serializers.CharField()
    subjects = BulletinSubjectLineSerializer(many=True)
    average = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True
    )
    rank = serializers.IntegerField(allow_null=True)
    class_size = serializers.IntegerField()
    mention = serializers.CharField(allow_blank=True)


class ClassRankingRowSerializer(serializers.Serializer):
    """One row of the class ranking endpoint."""

    student_id = serializers.IntegerField()
    student_name = serializers.CharField()
    average = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True
    )
    rank = serializers.IntegerField(allow_null=True)
    mention = serializers.CharField(allow_blank=True)


class AllocatedSubjectMiniSerializer(serializers.ModelSerializer):
    """Used to expose coefficients in bulletins."""

    subject = SubjectMiniSerializer(read_only=True)
    teacher_name = serializers.CharField(source="teacher_name.short_name", default="")

    class Meta:
        model = AllocatedSubject
        fields = ["id", "subject", "coefficient", "teacher_name"]
