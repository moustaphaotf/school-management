from rest_framework import serializers
from django.utils.translation import gettext as _

from academic.models import (
    StudentsMedicalHistory,
    Student,
    Parent,
    ReasonLeft,
    ClassLevel,
    ClassYear,
)
from academic.serializers import ClassLevelSerializer, ClassYearSerializer


class ReasonLeftSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReasonLeft
        fields = "__all__"


class StudentHealthRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentsMedicalHistory
        fields = "__all__"


class ParentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parent
        fields = "__all__"


class SiblingSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    class_level = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "full_name",
            "admission_number",
            "gender",
            "class_level",
            "class_of_year",
        ]

    def get_full_name(self, obj):
        return obj.full_name

    def get_class_level(self, obj):
        return obj.class_level.name if obj.class_level else None


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    class_level_display = serializers.SerializerMethodField()
    class_of_year_display = serializers.SerializerMethodField()
    parent_guardian_display = serializers.SerializerMethodField()
    siblings = SiblingSerializer(many=True, read_only=True)

    class_level = serializers.CharField(write_only=True, required=True)
    class_of_year = serializers.CharField(
        write_only=False, required=False, allow_null=True
    )

    class Meta:
        model = Student
        fields = [
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "admission_number",
            "parent_contact",
            "region",
            "city",
            "street",
            "gender",
            "religion",
            "date_of_birth",
            "std_vii_number",
            "prems_number",
            "full_name",
            "class_level_display",
            "class_of_year_display",
            "parent_guardian_display",
            "class_level",  # write-only
            "class_of_year",  # write-only
            "siblings",
        ]

    def get_full_name(self, obj):
        return obj.full_name

    def get_class_level_display(self, obj):
        return obj.class_level.name if obj.class_level else None

    def get_class_of_year_display(self, obj):
        return obj.class_of_year.full_name if obj.class_of_year else None

    def get_parent_guardian_display(self, obj):
        return obj.parent_guardian.email if obj.parent_guardian else None

    def validate_and_create_student(self, data):
        print("validated_data:", data)
        class_level_name = data.pop("class_level", None)
        if not class_level_name:
            raise serializers.ValidationError(_("Missing 'class_level' field."))

        try:
            class_level = ClassLevel.objects.get(name__iexact=class_level_name)
        except ClassLevel.DoesNotExist:
            raise serializers.ValidationError(
                _("Class level '%(level)s' does not exist.") % {"level": class_level_name}
            )
        data["class_level"] = class_level
        date_of_birth = (data.get("date_of_birth", "2000-01-01"),)
        religion = data.get("religion", None)

        class_of_year_name = data.pop("class_of_year", None)
        if class_of_year_name:
            try:
                class_year = ClassYear.objects.get(year=class_of_year_name)
                data["class_of_year"] = class_year
            except ClassYear.DoesNotExist:
                raise serializers.ValidationError(
                    _("Class year '%(year)s' does not exist.") % {"year": class_of_year_name}
                )

        # Normalize names
        data["first_name"] = data["first_name"].title()
        data["middle_name"] = data.get("middle_name", "").title()
        data["last_name"] = data["last_name"].title()

        parent = None
        contact = data.get("parent_contact")
        if contact:
            parent, _ = Parent.objects.get_or_create(
                phone_number=contact,
                defaults={
                    "first_name": data["middle_name"] or "Unknown",
                    "last_name": data["last_name"],
                    "email": f"parent_of_{data['first_name']}_{data['last_name']}@hayatul.com",
                },
            )
        data["parent_guardian"] = parent

        return Student.objects.create(**data)

    def create(self, validated_data):
        return self.validate_and_create_student(validated_data)

    def update(self, instance, validated_data):
        class_level_name = validated_data.pop("class_level", None)
        if class_level_name:
            try:
                class_level = ClassLevel.objects.get(name__iexact=class_level_name)
                instance.class_level = class_level
            except ClassLevel.DoesNotExist:
                raise serializers.ValidationError(
                    _("Class level '%(level)s' does not exist.") % {"level": class_level_name}
                )

        class_year_name = validated_data.pop("class_of_year", None)
        if class_year_name:
            try:
                class_year = ClassYear.objects.get(year=class_year_name)
                instance.class_of_year = class_year
            except ClassYear.DoesNotExist:
                raise serializers.ValidationError(
                    _("Class year '%(year)s' does not exist.") % {"year": class_year_name}
                )

        instance.first_name = validated_data.get(
            "first_name", instance.first_name
        ).title()
        instance.middle_name = validated_data.get(
            "middle_name", instance.middle_name
        ).title()
        instance.last_name = validated_data.get("last_name", instance.last_name).title()

        for field in [
            "admission_number",
            "parent_contact",
            "region",
            "city",
            "street",
            "gender",
            "religion",
            "date_of_birth",
            "std_vii_number",
            "prems_number",
        ]:
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        # Update parent if needed
        contact = validated_data.get("parent_contact", instance.parent_contact)
        if contact:
            parent, _ = Parent.objects.get_or_create(
                phone_number=contact,
                defaults={
                    "first_name": instance.middle_name or "Unknown",
                    "last_name": instance.last_name,
                    "email": f"parent_of_{instance.first_name}_{instance.last_name}@hayatul.com",
                },
            )
            instance.parent_guardian = parent

        instance.save()
        return instance

    def bulk_create(self, student_data_list):
        created_students = []
        errors = []

        for data in student_data_list:
            try:
                student = self.validate_and_create_student(data)
                created_students.append(student)
            except serializers.ValidationError as e:
                data["error"] = str(e)
                errors.append(data)

        return created_students, errors
