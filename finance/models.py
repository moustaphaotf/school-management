from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
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
        Student, related_name="debt_records", on_delete=models.CASCADE
    )
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    amount_added = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    note = models.TextField(blank=True, null=True)
    date_updated = models.DateTimeField(auto_now_add=True)
    is_reversed = models.BooleanField(default=False)
    reversed_on = models.DateTimeField(null=True, blank=True)

    class Meta:
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
            raise ValueError("Payment must be positive.")
        if self.balance < amount:
            raise ValueError("Cannot pay more than the remaining balance.")
        self.amount_paid += amount
        self.save()

    def reverse(self):
        self.is_reversed = True
        self.reversed_on = timezone.now()
        self.save()


class ReceiptAllocation(models.Model):
    name = models.CharField(max_length=255, null=True)
    abbr = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.name


class PaymentAllocation(models.Model):
    name = models.CharField(max_length=255, null=True)
    abbr = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.name


class Receipt(models.Model):
    receipt_number = models.IntegerField(unique=True, blank=True, null=True)
    date = models.DateField(auto_now_add=True)
    payer = models.CharField(max_length=255, default="Unknown")
    paid_for = models.ForeignKey(
        "ReceiptAllocation", on_delete=models.SET_NULL, null=True
    )
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_through = models.CharField(
        max_length=20, choices=PaymentThrough.choices, default=PaymentThrough.UNKNOWN
    )
    term = models.ForeignKey(Term, on_delete=models.SET_NULL, null=True, blank=True)
    payment_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    received_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Receipt {self.receipt_number} | {self.date} | {self.paid_for} | {self.payer}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError("Amount must be a positive value.")

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
        unique=True, blank=True, null=True, db_index=True
    )
    date = models.DateField(auto_now_add=True)
    paid_to = models.CharField(max_length=255, null=True)
    user = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.SET_NULL, related_name="payments"
    )
    paid_for = models.ForeignKey(
        PaymentAllocation, on_delete=models.SET_NULL, null=True
    )
    paid_through = models.CharField(
        max_length=20, choices=PaymentThrough.choices, default=PaymentThrough.CASH
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    paid_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Payment {self.payment_number} | {self.date} | {self.paid_for} | {self.paid_to}"

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError("Amount must be a positive value.")

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
        Student, related_name="payments", on_delete=models.CASCADE
    )
    debt_record = models.ForeignKey(
        "DebtRecord", related_name="payments", on_delete=models.CASCADE
    )
    receipt = models.ForeignKey(
        "Receipt", related_name="payment_records", on_delete=models.CASCADE
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50, blank=True, null=True)  # e.g. cash, mpesa
    reference = models.CharField(max_length=100, blank=True, null=True)
    paid_on = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)
    processed_by = models.ForeignKey(Accountant, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        if self.amount <= 0:
            raise ValidationError("Payment amount must be positive.")
        if self.debt_record.balance < self.amount:
            raise ValidationError("Payment exceeds remaining balance for this debt.")

        # Apply payment to debt
        self.debt_record.apply_payment(self.amount)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.full_name} paid {self.amount} toward {self.debt_record.term.name}"
