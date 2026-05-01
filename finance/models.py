from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from administration.models import Term
from users.models import Accountant, CustomUser as User
from academic.models import Teacher, Student


class PaymentStatus(models.TextChoices):
    PENDING = "Pending", "Pending"
    COMPLETED = "Completed", "Completed"
    CANCELLED = "Cancelled", "Cancelled"


class PaymentThrough(models.TextChoices):
    CRDB = "CRDB", "CRDB"
    NMB = "NMB", "NMB"
    NBC = "NBC", "NBC"
    HATI_MALIPO = "HATI MALIPO", "HATI MALIPO"
    CASH = "CASH", "CASH"
    UNKNOWN = "Unknown", "Unknown"


class DebtRecord(models.Model):
    student = models.ForeignKey(
        Student, related_name="debt_records", on_delete=models.CASCADE,
        verbose_name=_("student"),
    )
    term = models.ForeignKey(Term, on_delete=models.CASCADE, verbose_name=_("term"))
    amount_added = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        verbose_name=_("amount added"),
    )
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        verbose_name=_("amount paid"),
    )
    note = models.TextField(blank=True, null=True, verbose_name=_("note"))
    date_updated = models.DateTimeField(auto_now_add=True, verbose_name=_("date updated"))
    is_reversed = models.BooleanField(default=False, verbose_name=_("is reversed"))
    reversed_on = models.DateTimeField(null=True, blank=True, verbose_name=_("reversed on"))

    class Meta:
        verbose_name = _("Debt Record")
        verbose_name_plural = _("Debt Records")
        unique_together = ("student", "term")
        ordering = ["-date_updated"]

    def __str__(self):
        return f"{self.student.full_name} - {self.term.name} - {self.amount_added}"

    @property
    def balance(self):
        return max(Decimal("0.00"), self.amount_added - self.amount_paid)

    def apply_payment(self, amount):
        """
        Applies a payment to this debt record and prevents overpayment.
        """
        amount = Decimal(amount)
        if amount <= 0:
            raise ValueError(_("Payment must be positive."))
        if self.balance < amount:
            raise ValueError(_("Cannot pay more than the remaining balance."))
        self.amount_paid += amount
        self.save()

    def reverse(self):
        self.is_reversed = True
        self.reversed_on = timezone.now()
        self.save()


class ReceiptAllocation(models.Model):
    name = models.CharField(max_length=255, null=True, verbose_name=_("name"))
    abbr = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("abbreviation"))

    class Meta:
        verbose_name = _("Receipt Allocation")
        verbose_name_plural = _("Receipt Allocations")

    def __str__(self):
        return self.name


class PaymentAllocation(models.Model):
    name = models.CharField(max_length=255, null=True, verbose_name=_("name"))
    abbr = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("abbreviation"))

    class Meta:
        verbose_name = _("Payment Allocation")
        verbose_name_plural = _("Payment Allocations")

    def __str__(self):
        return self.name


class Receipt(models.Model):
    receipt_number = models.IntegerField(unique=True, blank=True, null=True, verbose_name=_("receipt number"))
    date = models.DateField(auto_now_add=True, verbose_name=_("date"))
    payer = models.CharField(max_length=255, default="Unknown", verbose_name=_("payer"))
    paid_for = models.ForeignKey(
        "ReceiptAllocation", on_delete=models.SET_NULL, null=True,
        verbose_name=_("paid for"),
    )
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("student"),
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("amount"))
    paid_through = models.CharField(
        max_length=20, choices=PaymentThrough.choices, default=PaymentThrough.UNKNOWN,
        verbose_name=_("paid through"),
    )
    term = models.ForeignKey(Term, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("term"))
    payment_date = models.DateField(default=timezone.now, verbose_name=_("payment date"))
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
        verbose_name=_("status"),
    )
    received_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True, verbose_name=_("received by"))

    class Meta:
        verbose_name = _("Receipt")
        verbose_name_plural = _("Receipts")

    def __str__(self):
        return f"Receipt {self.receipt_number} | {self.date} | {self.paid_for} | {self.payer}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError(_("Amount must be a positive value."))

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            with transaction.atomic():
                last_receipt = (
                    Receipt.objects.select_for_update()
                    .order_by("-receipt_number")
                    .first()
                )
                self.receipt_number = (
                    (last_receipt.receipt_number + 1) if last_receipt else 1
                )
        super().save(*args, **kwargs)

        # Don't apply debt reduction here — move logic to PaymentRecord for full control


class Payment(models.Model):
    payment_number = models.IntegerField(
        unique=True, blank=True, null=True, db_index=True, verbose_name=_("payment number"),
    )
    date = models.DateField(auto_now_add=True, verbose_name=_("date"))
    paid_to = models.CharField(max_length=255, null=True, verbose_name=_("paid to"))
    user = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.SET_NULL, related_name="payments",
        verbose_name=_("user"),
    )
    paid_for = models.ForeignKey(
        PaymentAllocation, on_delete=models.SET_NULL, null=True, verbose_name=_("paid for"),
    )
    paid_through = models.CharField(
        max_length=20, choices=PaymentThrough.choices, default=PaymentThrough.CASH,
        verbose_name=_("paid through"),
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("amount"))
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
        verbose_name=_("status"),
    )
    paid_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True, verbose_name=_("paid by"))

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")

    def __str__(self):
        return f"Payment {self.payment_number} | {self.date} | {self.paid_for} | {self.paid_to}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError(_("Amount must be a positive value."))

    def save(self, *args, **kwargs):
        if not self.payment_number:
            last_payment = Payment.objects.order_by("-payment_number").first()
            self.payment_number = (
                (last_payment.payment_number + 1) if last_payment else 1
            )

        super().save(*args, **kwargs)

    def handle_salary_payment(self):
        if self.paid_for.name.lower() == "salary":
            if isinstance(self.paid_to, Teacher) or isinstance(
                self.paid_to, Accountant
            ):
                self.paid_to.unpaid_salary -= self.amount
                self.paid_to.save()
        self.save()


class PaymentRecord(models.Model):
    student = models.ForeignKey(
        Student, related_name="payments", on_delete=models.CASCADE, verbose_name=_("student"),
    )
    debt_record = models.ForeignKey(
        "DebtRecord", related_name="payments", on_delete=models.CASCADE, verbose_name=_("debt record"),
    )
    receipt = models.ForeignKey(
        "Receipt", related_name="payment_records", on_delete=models.CASCADE, verbose_name=_("receipt"),
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("amount"))
    method = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("method"))
    reference = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("reference"))
    paid_on = models.DateTimeField(auto_now_add=True, verbose_name=_("paid on"))
    note = models.TextField(blank=True, null=True, verbose_name=_("note"))
    processed_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True, verbose_name=_("processed by"))

    class Meta:
        verbose_name = _("Payment Record")
        verbose_name_plural = _("Payment Records")

    def save(self, *args, **kwargs):
        if self.amount <= 0:
            raise ValidationError(_("Payment amount must be positive."))
        if self.debt_record.balance < self.amount:
            raise ValidationError(_("Payment exceeds remaining balance for this debt."))

        # Apply payment to debt
        self.debt_record.apply_payment(self.amount)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.full_name} paid {self.amount} toward {self.debt_record.term.name}"
