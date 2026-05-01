from django.db import models
from django.utils.translation import gettext as _
from rest_framework import serializers
from .models import (
    Receipt,
    Payment,
    ReceiptAllocation,
    PaymentAllocation,
    DebtRecord,
    PaymentRecord,
)
from academic.models import Student
from administration.models import Term
from users.models import CustomUser, Accountant
from administration.serializers import TermSerializer
from sis.serializers import StudentSerializer
from users.serializers import AccountantSerializer, UserSerializer


class ReceiptAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptAllocation
        fields = ["id", "name", "abbr"]


class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = ["id", "name", "abbr"]


class ReceiptSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    paid_for = serializers.PrimaryKeyRelatedField(
        queryset=ReceiptAllocation.objects.all()
    )
    received_by = serializers.PrimaryKeyRelatedField(queryset=Accountant.objects.all())
    term = serializers.PrimaryKeyRelatedField(queryset=Term.objects.all())

    student_details = StudentSerializer(read_only=True, source="student")
    paid_for_details = ReceiptAllocationSerializer(read_only=True, source="paid_for")
    received_by_details = AccountantSerializer(read_only=True, source="received_by")
    term_details = TermSerializer(read_only=True, source="term")

    class Meta:
        model = Receipt
        fields = (
            "id",
            "receipt_number",
            "date",
            "payer",
            "paid_for",
            "paid_for_details",
            "student",
            "student_details",
            "amount",
            "term",
            "term_details",
            "paid_through",
            "payment_date",
            "status",
            "received_by",
            "received_by_details",
        )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_("Amount must be a positive value."))
        return value

    def create(self, validated_data):
        """
        Override create to apply payment to student's DebtRecords.
        """
        receipt = Receipt.objects.create(**validated_data)

        if (
            receipt.student
            and receipt.paid_for
            and receipt.paid_for.name.lower() == "school fees"
        ):
            self.apply_payment_to_debt(receipt.student, receipt.amount, receipt)

        return receipt

    def apply_payment_to_debt(self, student, amount, receipt):
        """
        Distribute payment across unpaid DebtRecords (oldest first).
        Create PaymentRecords linked to each DebtRecord.
        """
        unpaid_debts = student.debt_records.filter(is_reversed=False).order_by(
            "term__start_date"
        )
        remaining = amount

        for debt in unpaid_debts:
            if remaining <= 0:
                break

            debt_balance = debt.balance
            pay_amount = min(remaining, debt_balance)

            if pay_amount > 0:
                # Apply payment to debt
                debt.apply_payment(pay_amount)

                # Create a PaymentRecord
                PaymentRecord.objects.create(
                    student=student,
                    debt_record=debt,
                    amount=pay_amount,
                    method=receipt.paid_through,
                    reference=f"Receipt #{receipt.receipt_number}",
                    note=f"Payment via receipt {receipt.id}",
                    processed_by=receipt.received_by,
                )

                remaining -= pay_amount


class PaymentSerializer(serializers.ModelSerializer):
    paid_for = PaymentAllocationSerializer(read_only=True)
    paid_by = AccountantSerializer(read_only=True)
    user = UserSerializer(read_only=True)
    paid_for_id = serializers.PrimaryKeyRelatedField(
        queryset=PaymentAllocation.objects.all(), source="paid_for", write_only=True
    )
    paid_by_id = serializers.PrimaryKeyRelatedField(
        queryset=Accountant.objects.all(), source="paid_by", write_only=True
    )
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=CustomUser.objects.all(),
        source="user",
        write_only=True,
        required=False,
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_number",
            "date",
            "paid_to",
            "amount",
            "status",
            "paid_for",
            "paid_through",
            "paid_by",
            "user",
            "paid_for_id",
            "paid_by_id",
            "user_id",
        ]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_("Amount must be a positive value."))
        return value


class DebtRecordSerializer(serializers.ModelSerializer):
    term_name = serializers.CharField(source="term.name", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = DebtRecord
        fields = [
            "id",
            "student",
            "student_name",
            "term",
            "term_name",
            "amount_added",
            "amount_paid",
            "balance",
            "note",
            "timestamp",
            "is_reversed",
            "reversed_on",
        ]


class PaymentRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    term_name = serializers.CharField(source="debt_record.term.name", read_only=True)
    processed_by_name = serializers.CharField(
        source="processed_by.full_name", read_only=True
    )

    class Meta:
        model = PaymentRecord
        fields = [
            "id",
            "student",
            "student_name",
            "debt_record",
            "term_name",
            "amount",
            "method",
            "reference",
            "note",
            "paid_on",
            "processed_by",
            "processed_by_name",
        ]


class DebtRecordSummarySerializer(serializers.ModelSerializer):
    term = TermSerializer(read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = DebtRecord
        fields = ["id", "term", "amount_added", "amount_paid", "balance", "is_reversed"]


class PaymentRecordSummarySerializer(serializers.ModelSerializer):
    term_name = serializers.CharField(source="debt_record.term.name", read_only=True)

    class Meta:
        model = PaymentRecord
        fields = ["id", "amount", "method", "reference", "note", "paid_on", "term_name"]


class StudentDebtOverviewSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    debt = serializers.SerializerMethodField()
    unpaid_debts = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "admission_number",
            "full_name",
            "class_level",
            "class_of_year",
            "debt",
            "unpaid_debts",
            "payments",
        ]

    def get_debt(self, obj):
        return obj.debt  # Uses the @property method on Student model

    def get_unpaid_debts(self, obj):
        unpaid = obj.debt_records.filter(is_reversed=False).exclude(
            amount_paid__gte=models.F("amount_added")
        )
        return DebtRecordSummarySerializer(unpaid, many=True).data

    def get_payments(self, obj):
        payments = obj.payments.order_by("-paid_on")[:10]  # Latest 10 payments
        return PaymentRecordSummarySerializer(payments, many=True).data
