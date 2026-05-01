from django.db import models
from django.utils.translation import gettext_lazy as _

from academic.models import Student, SubTopic
from users.models import CustomUser as User


class Assignment(models.Model):
    title = models.CharField(max_length=50, verbose_name=_("title"))
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name=_("teacher"))

    class Meta:
        verbose_name = _("Assignment")
        verbose_name_plural = _("Assignments")

    def __str__(self):
        return self.title


class GradedAssignment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("student"))
    assignment = models.ForeignKey(
        Assignment, on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name=_("assignment"),
    )
    grade = models.FloatField(verbose_name=_("grade"))

    class Meta:
        verbose_name = _("Graded Assignment")
        verbose_name_plural = _("Graded Assignments")

    def __str__(self):
        return self.student.username


class Choice(models.Model):
    title = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("title"))

    class Meta:
        verbose_name = _("Choice")
        verbose_name_plural = _("Choices")

    def __str__(self):
        return self.title


class Question(models.Model):
    question = models.CharField(max_length=200, verbose_name=_("question"))
    choices = models.ManyToManyField(Choice, verbose_name=_("choices"))
    answer = models.ForeignKey(
        Choice, on_delete=models.CASCADE, related_name="answer", blank=True, null=True,
        verbose_name=_("answer"),
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="questions",
        blank=True,
        null=True,
        verbose_name=_("assignment"),
    )
    order = models.SmallIntegerField(verbose_name=_("order"))

    class Meta:
        verbose_name = _("Question")
        verbose_name_plural = _("Questions")

    def __str__(self):
        return self.question


class SpecificExplanations(models.Model):
    sub_topic = models.ForeignKey(
        SubTopic, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("sub-topic"),
    )
    name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("name"))
    explanation = models.TextField(blank=True, null=True, verbose_name=_("explanation"))
    examples = models.ManyToManyField(Question, blank=True, verbose_name=_("examples"))

    class Meta:
        verbose_name = _("Specific Explanation")
        verbose_name_plural = _("Specific Explanations")

    def __str__(self):
        return f"{self.name} {self.sub_topic}"


class Concept(models.Model):
    sub_topic = models.ForeignKey(
        SubTopic, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("sub-topic"),
    )
    name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("name"))
    explanation = models.TextField(blank=True, null=True, verbose_name=_("explanation"))
    image = models.ImageField(
        verbose_name=_("image"), upload_to="concept images", blank=True, null=True
    )
    list_of_explanations = models.ManyToManyField(SpecificExplanations, blank=True, verbose_name=_("list of explanations"))

    class Meta:
        verbose_name = _("Concept")
        verbose_name_plural = _("Concepts")

    def __str__(self):
        return f"{self.name} {self.sub_topic}"


class Note(models.Model):
    sub_topic = models.ForeignKey(
        SubTopic, on_delete=models.CASCADE, blank=True, null=True,
        verbose_name=_("sub-topic"),
    )
    notes = models.ManyToManyField(Concept, blank=True, verbose_name=_("notes"))

    class Meta:
        verbose_name = _("Note")
        verbose_name_plural = _("Notes")

    def __str__(self):
        return f"{self.sub_topic}"
