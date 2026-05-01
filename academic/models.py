from django.db import models, transaction
from django.db.models import F
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from django.utils.crypto import get_random_string
from django.utils import timezone
from users.models import CustomUser
from administration.models import AcademicYear, Term

from .validators import *
from administration.common_objs import *


class Department(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name=_("name"))
    order_rank = models.IntegerField(
        blank=True, null=True, verbose_name=_("order rank"),
        help_text=_("Rank for subject reports"),
    )

    class Meta:
        verbose_name = _("Department")
        verbose_name_plural = _("Departments")
        ordering = ("order_rank", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.lower()

        super().save(*args, **kwargs)


class Subject(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name=_("name"))
    subject_code = models.CharField(max_length=10, blank=True, null=True, unique=True, verbose_name=_("subject code"))
    is_selectable = models.BooleanField(
        default=False, verbose_name=_("is selectable"),
        help_text=_("Select if subject is optional"),
    )
    graded = models.BooleanField(
        default=True, verbose_name=_("graded"),
        help_text=_("Teachers can submit grades"),
    )
    description = models.CharField(max_length=255, blank=True, verbose_name=_("description"))
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("department"),
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["subject_code"]
        verbose_name = _("Subject")
        verbose_name_plural = _("Subjects")

    def save(self, *args, **kwargs):
        # Generate description
        self.name = self.name.lower()
        self.description = f"{self.name.lower()} - {self.subject_code}"

        super().save(*args, **kwargs)


class Teacher(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="teacher",
        null=True,
        blank=True,
        verbose_name=_("user"),
    )
    username = models.CharField(unique=True, max_length=250, blank=True, verbose_name=_("username"))
    first_name = models.CharField(max_length=300, blank=True, verbose_name=_("first name"))
    middle_name = models.CharField(max_length=100, blank=True, verbose_name=_("middle name"))
    last_name = models.CharField(max_length=300, blank=True, verbose_name=_("last name"))
    gender = models.CharField(max_length=10, choices=GENDER_CHOICE, blank=True, verbose_name=_("gender"))
    email = models.EmailField(blank=True, null=True, verbose_name=_("email"))
    empId = models.CharField(max_length=8, unique=True, null=True, blank=True, verbose_name=_("employee ID"))
    tin_number = models.CharField(max_length=9, blank=True, null=True, verbose_name=_("TIN number"))
    nssf_number = models.CharField(max_length=9, blank=True, null=True, verbose_name=_("NSSF number"))
    short_name = models.CharField(max_length=3, blank=True, null=True, unique=True, verbose_name=_("short name"))
    salary = models.IntegerField(blank=True, null=True, verbose_name=_("salary"))
    unpaid_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("unpaid salary"))
    subject_specialization = models.ManyToManyField(Subject, blank=True, verbose_name=_("subject specialization"))
    national_id = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("national ID"))
    address = models.CharField(max_length=255, blank=True, verbose_name=_("address"))
    phone_number = models.CharField(max_length=150, blank=True, verbose_name=_("phone number"))
    alt_email = models.EmailField(blank=True, null=True, verbose_name=_("alternative email"))
    date_of_birth = models.DateField(blank=True, null=True, verbose_name=_("date of birth"))
    designation = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("designation"))
    image = models.ImageField(upload_to="Employee_images", blank=True, null=True, verbose_name=_("image"))
    inactive = models.BooleanField(default=False, verbose_name=_("inactive"))

    class Meta:
        verbose_name = _("Teacher")
        verbose_name_plural = _("Teachers")
        ordering = ("id", "first_name", "last_name")

    def __str__(self):
        return "{} {}".format(self.first_name, self.last_name)

    @property
    def deleted(self):
        return self.inactive

    def save(self, *args, **kwargs):
        """
        When an teacher is created, generate a CustomUser instance for login.
        """
        # Generate unique username
        if not self.username:
            self.username = f"{self.first_name.lower()}{self.last_name.lower()}{get_random_string(4)}"

        if not self.user:
            # Create the user if it doesn't exist
            user = CustomUser.objects.create(
                first_name=self.first_name,
                last_name=self.last_name,
                email=self.email,
                is_teacher=True,
            )

            # Set a default password using empId (if available) or fallback
            default_password = f"Complex.{self.empId[-4:] if self.empId and len(self.empId) >= 4 else '0000'}"
            user.set_password(default_password)
            user.save()

            # Attach the created user to the teacher
            self.user = user

            # Add user to "teacher" group
            group, _ = Group.objects.get_or_create(name="teacher")
            user.groups.add(group)

        super().save(*args, **kwargs)

        # Optionally send email (integrate email backend here)

    def update_unpaid_salary(self):
        # Update unpaid salary at the start of each month
        current_month = timezone.now().month
        if self.unpaid_salary > 0:
            self.unpaid_salary += self.salary  # Add salary amount to unpaid salary
        else:
            self.unpaid_salary = (
                self.salary
            )  # If unpaid salary is 0, set the first month's salary
        self.save()


class GradeLevel(models.Model):
    id = models.IntegerField(unique=True, primary_key=True, verbose_name=_("Grade Level"))
    name = models.CharField(max_length=150, unique=True, verbose_name=_("name"))
    grade_scale = models.ForeignKey(
        "examination.GradeScale",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("grade scale"),
        help_text=_("Grading scale used for this level (e.g., /10 for primary, /20 for college/high-school)."),
    )

    class Meta:
        verbose_name = _("Grade Level")
        verbose_name_plural = _("Grade Levels")
        ordering = ("id",)

    def __str__(self):
        return self.name


class ClassLevel(models.Model):
    id = models.IntegerField(unique=True, primary_key=True, verbose_name=_("Class Level"))
    name = models.CharField(max_length=150, unique=True, verbose_name=_("name"))
    grade_level = models.ForeignKey(
        GradeLevel, blank=True, null=True, on_delete=models.SET_NULL,
        verbose_name=_("grade level"),
    )

    class Meta:
        verbose_name = _("Class Level")
        verbose_name_plural = _("Class Levels")
        ordering = ("id",)

    def __str__(self):
        return self.name


class ClassYear(models.Model):
    year = models.CharField(max_length=100, unique=True, verbose_name=_("year"), help_text=_("Example 2020"))
    full_name = models.CharField(
        max_length=255, verbose_name=_("full name"),
        help_text=_("Example Class of 2020"), blank=True,
    )

    class Meta:
        verbose_name = _("Class Year")
        verbose_name_plural = _("Class Years")

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        if not self.full_name:
            self.full_name = f"Class of {self.year}"
        super().save(*args, **kwargs)


class ReasonLeft(models.Model):
    reason = models.CharField(max_length=255, unique=True, verbose_name=_("reason"))

    class Meta:
        verbose_name = _("Reason Left")
        verbose_name_plural = _("Reasons Left")

    def __str__(self):
        return self.reason


class Stream(models.Model):
    name = models.CharField(max_length=50, validators=[stream_validator], verbose_name=_("name"))

    class Meta:
        verbose_name = _("Stream")
        verbose_name_plural = _("Streams")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super().save(*args, **kwargs)


class ClassRoom(models.Model):
    name = models.ForeignKey(
        ClassLevel, on_delete=models.CASCADE, blank=True, related_name="class_level",
        verbose_name=_("class level"),
    )
    stream = models.ForeignKey(
        Stream, on_delete=models.CASCADE, blank=True, related_name="class_stream",
        verbose_name=_("stream"),
    )
    class_teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, blank=True, verbose_name=_("class teacher"))
    capacity = models.PositiveIntegerField(default=40, blank=True, verbose_name=_("capacity"))
    occupied_sits = models.PositiveIntegerField(default=0, blank=True, verbose_name=_("occupied sits"))

    class Meta:
        verbose_name = _("Classroom")
        verbose_name_plural = _("Classrooms")
        constraints = [
            models.UniqueConstraint(fields=["name", "stream"], name="unique_classroom")
        ]

    def __str__(self):
        return f"{self.name} {self.stream}" if self.stream else str(self.name)

    @property
    def available_sits(self):
        return self.capacity - self.occupied_sits

    @property
    def class_status(self):
        percentage = (self.occupied_sits / self.capacity) * 100
        return f"{percentage:.2f}%"

    def clean(self):
        if (
            self.occupied_sits is not None
            and self.capacity is not None
            and self.occupied_sits > self.capacity
        ):
            raise ValidationError(_("Occupied sits cannot exceed the capacity."))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Topic(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("name"))
    class_level = models.ForeignKey(
        ClassLevel, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("class level"),
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("subject"),
    )

    class Meta:
        verbose_name = _("Topic")
        verbose_name_plural = _("Topics")

    def __str__(self):
        return self.name


class SubTopic(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("name"))
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, blank=True, null=True, verbose_name=_("topic"))

    class Meta:
        verbose_name = _("Sub-Topic")
        verbose_name_plural = _("Sub-Topics")

    def __str__(self):
        return self.name


class AllocatedSubject(models.Model):
    teacher_name = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name=_("teacher"))
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="allocated_subjects",
        verbose_name=_("subject"),
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, verbose_name=_("academic year"))
    term = models.ForeignKey(Term, on_delete=models.SET_NULL, blank=True, null=True, verbose_name=_("term"))
    class_room = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="subjects",
        verbose_name=_("classroom"),
    )
    coefficient = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.0,
        verbose_name=_("coefficient"),
        help_text=_("Coefficient applied to this subject's average when computing the term general average."),
    )
    weekly_periods = models.IntegerField(
        verbose_name=_("weekly periods"),
        help_text=_("Total number of periods per week."),
    )
    max_daily_periods = models.IntegerField(
        default=2,
        verbose_name=_("max daily periods"),
        help_text=_("Maximum number of periods allowed per day for this subject."),
    )

    class Meta:
        verbose_name = _("Allocated Subject")
        verbose_name_plural = _("Allocated Subjects")
        unique_together = (
            "teacher_name",
            "subject",
            "academic_year",
            "term",
            "class_room",
        )

    def __str__(self):
        return f"{self.teacher_name} - {self.subject} ({self.academic_year})"


class Parent(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="parent",
        null=True,
        blank=True,
        verbose_name=_("user"),
    )
    first_name = models.CharField(
        max_length=300, verbose_name=_("First Name"), blank=True, null=True
    )
    middle_name = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Middle Name")
    )
    last_name = models.CharField(
        max_length=300, verbose_name=_("Last Name"), blank=True, null=True
    )
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICE, blank=True, null=True,
        verbose_name=_("gender"),
    )
    email = models.EmailField(blank=True, null=True, unique=True, verbose_name=_("email"))
    date_of_birth = models.DateField(blank=True, null=True, verbose_name=_("date of birth"))
    parent_type = models.CharField(
        choices=PARENT_CHOICE, max_length=10, blank=True, null=True,
        verbose_name=_("parent type"),
    )
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("address"))
    phone_number = models.CharField(
        max_length=150, unique=True, verbose_name=_("phone number"),
        help_text=_("Personal phone number"),
    )
    national_id = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("national ID"))
    occupation = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("occupation"),
        help_text=_("Current occupation"),
    )
    monthly_income = models.FloatField(
        verbose_name=_("monthly income"),
        help_text=_("Parent's average monthly income"), blank=True, null=True,
    )
    single_parent = models.BooleanField(
        default=False, blank=True, verbose_name=_("single parent"),
        help_text=_("Is he/she a single parent"),
    )
    alt_email = models.EmailField(blank=True, null=True, verbose_name=_("alternative email"),
                                  help_text=_("Personal email"))
    date = models.DateTimeField(auto_now_add=True, verbose_name=_("date"))
    image = models.ImageField(upload_to="Parent_images", blank=True, verbose_name=_("image"))
    inactive = models.BooleanField(default=False, verbose_name=_("inactive"))

    class Meta:
        verbose_name = _("Parent")
        verbose_name_plural = _("Parents")
        ordering = ["email", "first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    def save(self, *args, **kwargs):
        """
        When a parent is created, ensure a user exists or is created
        based on phone number. Attach the user to the parent.
        """
        user, created = CustomUser.objects.get_or_create(
            phone_number=self.phone_number,
            defaults={
                "first_name": self.first_name,
                "last_name": self.last_name,
                "email": self.email,
                "is_parent": True,
            },
        )

        if created:
            # Set password only for new users
            user.set_password("Complex.0000")
            user.save()

            # Add user to "parent" group
            group, _ = Group.objects.get_or_create(name="parent")
            user.groups.add(group)
        else:
            # Optionally update user details if needed
            updated = False
            if not user.is_parent:
                user.is_parent = True
                updated = True
            if updated:
                user.save()

        # Link the user to this parent instance
        self.user = user

        super().save(*args, **kwargs)

        # Optionally send email (integrate email backend here)


class Student(models.Model):
    id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=150, null=True, verbose_name=_("First Name"))
    middle_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name=_("Middle Name")
    )
    last_name = models.CharField(max_length=150, null=True, verbose_name=_("Last Name"))
    graduation_date = models.DateField(blank=True, null=True, verbose_name=_("graduation date"))
    class_level = models.ForeignKey(
        "ClassLevel", blank=True, null=True, on_delete=models.SET_NULL,
        verbose_name=_("class level"),
    )
    class_of_year = models.ForeignKey(
        "ClassYear", blank=True, null=True, on_delete=models.SET_NULL,
        verbose_name=_("class of year"),
    )
    date_dismissed = models.DateField(blank=True, null=True, verbose_name=_("date dismissed"))
    reason_left = models.ForeignKey(
        "ReasonLeft", blank=True, null=True, on_delete=models.SET_NULL,
        verbose_name=_("reason left"),
    )
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICE, blank=True, null=True,
        verbose_name=_("gender"),
    )
    religion = models.CharField(
        max_length=50, choices=RELIGION_CHOICE, blank=True, null=True,
        verbose_name=_("religion"),
    )
    region = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("region"))
    city = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("city"))
    street = models.CharField(max_length=255, blank=True, verbose_name=_("street"))
    blood_group = models.CharField(max_length=10, blank=True, null=True, verbose_name=_("blood group"))
    parent_guardian = models.ForeignKey(
        "Parent",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="children",
        verbose_name=_("parent / guardian"),
    )
    parent_contact = models.CharField(max_length=15, blank=True, null=True, verbose_name=_("parent contact"))
    date_of_birth = models.DateField(blank=True, null=True, verbose_name=_("date of birth"))
    admission_date = models.DateTimeField(auto_now_add=True, verbose_name=_("admission date"))
    admission_number = models.CharField(max_length=50, blank=True, unique=True, verbose_name=_("admission number"))
    prems_number = models.CharField(max_length=50, blank=True, verbose_name=_("PREMS number"))
    std_vii_number = models.CharField(max_length=50, blank=True, verbose_name=_("Std VII number"))
    siblings = models.ManyToManyField("self", blank=True, verbose_name=_("siblings"))
    image = models.ImageField(upload_to="Student_images", blank=True, verbose_name=_("image"))
    cache_gpa = models.DecimalField(
        editable=False, max_digits=5, decimal_places=2, blank=True, null=True,
        verbose_name=_("cached GPA"),
    )

    class Meta:
        verbose_name = _("Student")
        verbose_name_plural = _("Students")
        ordering = ["admission_number", "last_name", "first_name"]

    def __str__(self):
        return f"{self.admission_number} - {self.first_name} {self.last_name} - Debt: {self.debt}"

    @property
    def full_name(self):
        parts = filter(None, [self.first_name, self.middle_name, self.last_name])
        return " ".join(part.capitalize() for part in parts)

    @property
    def debt(self):
        """
        Compute total unpaid debt across all terms.
        """
        return sum(
            (record.balance for record in self.debt_records.filter(is_reversed=False)),
            Decimal("0.00"),
        )

    @property
    def total_paid(self):
        """
        Compute total amount paid across all PaymentRecords.
        """
        return self.payments.aggregate(total=models.Sum("amount"))["total"] or Decimal(
            "0.00"
        )

    def unpaid_terms(self):
        """
        Returns queryset of DebtRecords with remaining balances.
        """
        return self.debt_records.filter(is_reversed=False).exclude(
            amount_paid__gte=models.F("amount_added")
        )

    def clean(self):
        super().clean()

    def save(self, *args, **kwargs):
        # Validate parent_contact presence
        if not self.parent_contact:
            raise ValidationError(_("Parent contact is required."))

        # Normalize name fields
        self.first_name = self.first_name.lower() if self.first_name else ""
        self.middle_name = self.middle_name.lower() if self.middle_name else ""
        self.last_name = self.last_name.lower() if self.last_name else ""

        # Ensure parent exists or is created
        parent, created = Parent.objects.get_or_create(
            phone_number=self.parent_contact,
            defaults={
                "first_name": self.middle_name or "Unknown",
                "last_name": self.last_name or "Unknown",
                "email": f"parent_of_{self.first_name}_{self.last_name}@hayatul.com",
                "phone_number": self.parent_contact,
            },
        )
        self.parent_guardian = parent

        # Save first to ensure self.id is set
        super().save(*args, **kwargs)

        # Link siblings
        existing_siblings = Student.objects.filter(
            parent_contact=self.parent_contact
        ).exclude(id=self.id)

        for sibling in existing_siblings:
            self.siblings.add(sibling)
            sibling.siblings.add(self)

    def update_debt_for_term(self, term):
        """
        Create a DebtRecord for the given term if not already created.
        """
        from finance.models import DebtRecord

        if not self.debt_records.filter(term=term, is_reversed=False).exists():
            DebtRecord.objects.create(
                student=self, term=term, amount_added=term.default_term_fee
            )

    def reverse_debt_for_term(self, term):
        """
        Reverse the debt record for a given term.
        """
        from finance.models import DebtRecord

        debt_record = self.debt_records.filter(term=term, is_reversed=False).first()
        if debt_record:
            debt_record.reverse()

    def carry_forward_debt_to_new_academic_year(self):
        """
        Carry forward unpaid debts to the first term of the next academic year.
        """
        current_academic_year = AcademicYear.objects.get(current=True)
        next_year = AcademicYear.objects.filter(
            start_date__gt=current_academic_year.end_date
        ).first()

        if next_year:
            first_term_of_new_year = (
                Term.objects.filter(academic_year=next_year)
                .order_by("start_date")
                .first()
            )

            if first_term_of_new_year:
                self.update_debt_for_term(first_term_of_new_year)


class StudentClassEnrollment(models.Model):
    """
    Bridge table to link a student to a class.
    Updates the selected class capacity when a student is added or removed.
    """

    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="class_students",
        verbose_name=_("classroom"),
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, verbose_name=_("academic year"))
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_classes",
        blank=True,
        null=True,
        verbose_name=_("student"),
    )

    class Meta:
        verbose_name = _("Student Class Enrollment")
        verbose_name_plural = _("Student Class Enrollments")

    @property
    def is_current_class(self):
        return self.academic_year.is_current_session

    def __str__(self):
        return f"Student: {self.student}, Class: {self.classroom}"

    def clean(self):
        """
        Perform custom validations:
        - Ensure the classroom matches the student's class level.
        - Check if the classroom has available seats.
        - Prevent duplicate assignments for the same student and academic year.
        """
        # Skip validation if required FKs are not set yet (form errors elsewhere)
        if not self.classroom_id or not self.student_id or not self.academic_year_id:
            return

        # Validate that the classroom matches the student's class level
        if self.classroom.name != self.student.class_level:
            raise ValidationError(
                _(
                    "The classroom '%(classroom)s' does not match the student's class level '%(level)s'."
                ) % {"classroom": self.classroom.name, "level": self.student.class_level}
            )

        # Validate that the classroom has available seats
        if (
            not self.pk
            and self.classroom.occupied_sits is not None
            and self.classroom.capacity is not None
            and self.classroom.occupied_sits >= self.classroom.capacity
        ):
            raise ValidationError(
                _("The classroom '%(classroom)s' has reached its maximum capacity.")
                % {"classroom": self.classroom}
            )

        # Check for duplicate StudentClass assignments
        if (
            StudentClassEnrollment.objects.filter(
                classroom=self.classroom,
                academic_year=self.academic_year,
                student=self.student,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                _(
                    "The student '%(student)s' is already assigned to this class for the academic year '%(year)s'."
                ) % {"student": self.student, "year": self.academic_year}
            )

    def update_class_table(self, increment=True):
        """
        Updates the `occupied_sits` count in the classroom manually within a transaction.
        """
        # Use a transaction to ensure consistency
        with transaction.atomic():
            selected_class = ClassRoom.objects.select_for_update().get(
                pk=self.classroom.pk
            )

            if increment:
                # Check capacity before incrementing
                if selected_class.occupied_sits >= selected_class.capacity:
                    raise ValidationError(
                        _("This class has reached its maximum capacity.")
                    )
                selected_class.occupied_sits += 1
            else:
                # Ensure occupied_sits doesn't go below zero
                if selected_class.occupied_sits <= 0:
                    raise ValidationError(_("Cannot have negative occupied sits."))
                selected_class.occupied_sits -= 1

            # Save the updated classroom instance
            selected_class.save()

    def save(self, *args, **kwargs):
        """
        Override the save method to:
        - Validate before saving.
        - Update the classroom's capacity on creation.
        """
        if not self.pk:  # Only increment capacity on creation
            self.update_class_table(increment=True)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Override the delete method to:
        - Decrement the classroom's capacity when a record is deleted.
        """
        self.update_class_table(increment=False)
        super().delete(*args, **kwargs)

    def delete_queryset(self, request, queryset):
        """
        Override the bulk delete behavior to update `occupied_sits` correctly.
        """
        with transaction.atomic():  # Ensure the operation is transactional
            for instance in queryset:
                instance.update_class_table(increment=False)  # Decrement capacity
            queryset.delete()  # Perform the actual deletion


class StudentsMedicalHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))
    history = models.TextField(blank=True, null=True, verbose_name=_("history"))
    file = models.FileField(upload_to="students_medical_files", blank=True, null=True, verbose_name=_("file"))

    class Meta:
        verbose_name = _("Student Medical History")
        verbose_name_plural = _("Student Medical Histories")

    def __str__(self):
        return f"Medical History for {self.student}"

    def clean(self):
        # You can add validation if a file is uploaded and ensure it meets the constraints
        if not self.history and not self.file:
            raise ValidationError(
                _("At least one of 'history' or 'file' must be provided.")
            )


class StudentsPreviousAcademicHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))
    former_school = models.CharField(max_length=255, verbose_name=_("former school"),
                                     help_text=_("Former school name"))
    last_gpa = models.FloatField(verbose_name=_("last GPA"))
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("notes"),
        help_text=_("Indicate student's academic performance according to your observation"),
    )
    academic_record = models.FileField(
        upload_to="students_former_academic_files", blank=True,
        verbose_name=_("academic record"),
    )

    class Meta:
        verbose_name = _("Student Previous Academic History")
        verbose_name_plural = _("Student Previous Academic Histories")

    def __str__(self):
        return f"Previous Academic History for {self.student}"

    def clean(self):
        # You can add validation for the file field if needed
        if not self.former_school:
            raise ValidationError(_("Former school name is required."))


class Dormitory(models.Model):
    name = models.CharField(max_length=150, verbose_name=_("name"))
    capacity = models.PositiveIntegerField(blank=True, null=True, verbose_name=_("capacity"))
    occupied_beds = models.IntegerField(blank=True, null=True, verbose_name=_("occupied beds"))
    captain = models.ForeignKey(Student, on_delete=models.CASCADE, blank=True, verbose_name=_("captain"))

    class Meta:
        verbose_name = _("Dormitory")
        verbose_name_plural = _("Dormitories")

    def __str__(self):
        return self.name

    def available_beds(self):
        total = self.capacity - self.occupied_beds
        if total <= 0:
            return 0  # Return 0 to indicate no available beds
        return total

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if (
            self.capacity is not None
            and self.occupied_beds is not None
            and self.capacity <= self.occupied_beds
        ):
            raise ValueError(
                f"All beds in {self.name} are occupied. Please add more beds or allocate to another dormitory."
            )
        super(Dormitory, self).save()


class DormitoryAllocation(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))
    dormitory = models.ForeignKey(Dormitory, on_delete=models.CASCADE, verbose_name=_("dormitory"))
    date_from = models.DateField(auto_now_add=True, verbose_name=_("date from"))
    date_till = models.DateField(blank=True, null=True, verbose_name=_("date till"))

    class Meta:
        verbose_name = _("Dormitory Allocation")
        verbose_name_plural = _("Dormitory Allocations")

    def __str__(self):
        return str(self.student.admission_number)

    @transaction.atomic
    def update_dormitory(self):
        """Update the capacity of the selected dormitory."""
        selected_dorm = Dormitory.objects.select_for_update().get(pk=self.dormitory.pk)
        if selected_dorm.available_beds() <= 0:
            raise ValidationError(
                _("%(dorm)s has no available beds.") % {"dorm": selected_dorm.name}
            )
        selected_dorm.occupied_beds += 1
        selected_dorm.save()

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        self.update_dormitory()
        super(DormitoryAllocation, self).save()


class StudentFile(models.Model):
    file = models.FileField(
        upload_to="students_files/%(student_id)s/",
        verbose_name=_("file"),
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "jpg", "png", "docx"])
        ],
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))

    class Meta:
        verbose_name = _("Student File")
        verbose_name_plural = _("Student Files")

    def __str__(self):
        return str(self.student)

    def clean(self):
        """Override to validate file size or type if necessary."""
        if self.file.size > 10 * 1024 * 1024:  # Limit to 10MB files
            raise ValidationError(_("File size must be under 10MB."))
        super().clean()


class StudentHealthRecord(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))
    record = models.TextField(verbose_name=_("record"))

    class Meta:
        verbose_name = _("Student Health Record")
        verbose_name_plural = _("Student Health Records")

    def __str__(self):
        return str(self.student)

    def clean(self):
        """Ensure that the record contains appropriate information."""
        if len(self.record) < 10:  # Ensure some minimal content in the record
            raise ValidationError(_("Health record must contain more information."))
        super().clean()


class MessageToParent(models.Model):
    """Store a message to be shown to parents for a specific amount of time."""

    message = models.TextField(verbose_name=_("message"), help_text=_("Message to be shown to Parents."))
    start_date = models.DateField(default=timezone.now, verbose_name=_("start date"))
    end_date = models.DateField(default=timezone.now, verbose_name=_("end date"))

    class Meta:
        verbose_name = _("Message to Parent")
        verbose_name_plural = _("Messages to Parents")

    def __str__(self):
        return self.message

    def clean(self):
        """Ensure that end date is not before start date."""
        if self.end_date < self.start_date:
            raise ValidationError(_("End date cannot be before the start date."))
        super().clean()

    @property
    def is_active(self):
        """Check if the message is currently active."""
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


class MessageToTeacher(models.Model):
    """Stores a message to be shown to Teachers for a specific amount of time."""

    message = models.TextField(verbose_name=_("message"), help_text=_("Message to be shown to Teachers."))
    start_date = models.DateField(default=timezone.now, verbose_name=_("start date"))
    end_date = models.DateField(default=timezone.now, verbose_name=_("end date"))

    class Meta:
        verbose_name = _("Message to Teacher")
        verbose_name_plural = _("Messages to Teachers")

    def __str__(self):
        return self.message

    def clean(self):
        """Ensure that end date is not before start date."""
        if self.end_date < self.start_date:
            raise ValidationError(_("End date cannot be before the start date."))
        super().clean()

    @property
    def is_active(self):
        """Check if the message is currently active."""
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


class FamilyAccessUser(CustomUser):
    """A person who can log into the non-admin side and see the same view as a student."""

    class Meta:
        proxy = True

    def save(self, *args, **kwargs):
        """Override save to assign user to 'family' group."""
        super(FamilyAccessUser, self).save(*args, **kwargs)
        group, created = Group.objects.get_or_create(name="family")
        if not self.groups.filter(name="family").exists():
            self.groups.add(group)
