from decimal import Decimal
from io import BytesIO
from textwrap import wrap
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.http import FileResponse
from rest_framework import generics, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from reportlab.pdfgen import canvas

from core_apps.common.permissions import IsAccountExecutive, IsTeller
from core_apps.common.renderers import GenericJSONRenderer
from core_apps.user_profile.views import StandardResultsSetPagination
from core_apps.user_auth.security import issue_challenge
from core_apps.user_auth.views import ChallengeInputSerializer
from .emails import send_full_activation_email, send_deposit_email, send_transfer_otp_email
from .models import BankAccount, Transaction, StaffAuditLog
from .serializers import AccountVerificationSerializer, CustomerInfoSerializer, DepositSerializer, TransactionSerializer
from .services import validate_account, execute_idempotently, complete_transaction

class AccountVerificationView(generics.UpdateAPIView):
    queryset = BankAccount.objects.select_for_update()
    serializer_class = AccountVerificationSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "Verification"
    permission_classes = [IsAccountExecutive]

    @transaction.atomic
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        if instance.kyc_verified and instance.fully_activated:
            return Response(
                {
                    "message": "This Account has already been verified and fully activated"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid(raise_exception=True):
            kyc_submitted = serializer.validated_data.get(
                "kyc_submitted", instance.kyc_submitted
            )
            kyc_verified = serializer.validated_data.get(
                "kyc_verified", instance.kyc_verified
            )

            if kyc_verified and not kyc_submitted:
                return Response(
                    {
                        "error":'KYC must be submitted before it can be verified'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            instance.kyc_submitted = kyc_submitted
            instance.save()

            if kyc_submitted and kyc_verified:
                instance.kyc_verified = kyc_verified
                instance.verification_date = serializer.validated_data.get(
                    "verification_date", timezone.now()
                )
                instance.verfication_notes = serializer.validated_data.get(
                    "verfication_notes",""
                )
                instance.verified_by = request.user
                instance.fully_activated = True
                instance.account_status = BankAccount.AccountStatus.ACTIVE
                instance.save()

                StaffAuditLog.objects.create(actor=request.user, action="account_verification", object_id=instance.pk,
                                             details={"kyc_verified": True})
                transaction.on_commit(lambda: send_full_activation_email(instance))
            return Response(
                {
                    "message":"Account Verification status updated successfully",
                    "data": self.get_serializer(instance).data
                }
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DepositView(generics.CreateAPIView):
    serializer_class = DepositSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "deposit"
    permission_classes = [IsTeller]

    def get(self, request, *args, **kwargs):
        account_number = request.query_params.get("account_number")
        if not account_number:
            return Response({"error": "Account number is required"}, status=400)
        account = generics.get_object_or_404(BankAccount, account_number=account_number)
        return Response(CustomerInfoSerializer(account).data)

    def create(self, request, *args, **kwargs):
        return execute_idempotently(request, 'deposit', lambda: self.deposit(request))

    def deposit(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = BankAccount.objects.select_for_update().get(account_number=serializer.validated_data['account_number'])
        validate_account(account)
        amount = serializer.validated_data['amount']
        if account.account_balance + amount > Decimal('9999999999.99'):
            raise serializers.ValidationError({"amount": "Account balance limit exceeded."})
        account.account_balance += amount
        BankAccount.objects.filter(pk=account.pk).update(account_balance=account.account_balance, updated_at=timezone.now())
        record = Transaction.objects.create(
            user=account.user, performed_by=request.user, receiver=account.user,
            receiver_account=account, amount=amount, transaction_type='deposit', status='completed',
        )
        StaffAuditLog.objects.create(actor=request.user, action='deposit', object_id=record.pk,
                                     details={"account_id": str(account.pk), "amount": str(amount)})
        transaction.on_commit(lambda: send_deposit_email(
            account.user, account.user.email, amount, account.currency,
            account.account_balance, account.account_number,
        ))
        return Response({"message": "Deposit completed", "transaction": TransactionSerializer(record).data,
                         "new_balance": str(account.account_balance)})


class TransactionAuthView(generics.GenericAPIView):
    renderer_classes = [GenericJSONRenderer]
    object_label = "transaction"
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "transaction_auth"


class InitiateWithdrawalView(TransactionAuthView):
    serializer_class = TransactionSerializer

    def post(self, request):
        account = generics.get_object_or_404(BankAccount, account_number=request.data.get('account_number'), user=request.user)
        validate_account(account)
        serializer = self.get_serializer(data={
            'sender_account': account.account_number, 'transaction_type': 'withdrawal',
            'amount': request.data.get('amount'),
        })
        serializer.is_valid(raise_exception=True)
        payload = {'sender_account': account.account_number, 'amount': str(serializer.validated_data['amount'])}
        challenge, code = issue_challenge(request.user, 'withdrawal', payload)
        send_transfer_otp_email(request.user.email, code, payload)
        return Response({'message': 'Verify the emailed OTP to withdraw.', 'challenge_id': str(challenge.pk)})


class VerifyUsernameAndWithdrawAPIView(TransactionAuthView):
    # Legacy URL retained; username confirmation has been replaced with an OTP challenge.
    serializer_class = ChallengeInputSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = complete_transaction(request.user, serializer.validated_data['challenge_id'],
                                      serializer.validated_data['otp'], 'withdrawal')
        return Response({'message': 'Withdrawal completed', 'transaction': TransactionSerializer(record).data})


class InitiateTransferView(TransactionAuthView):
    serializer_class = TransactionSerializer

    def post(self, request):
        data = request.data.copy()
        data['transaction_type'] = 'transfer'
        sender = generics.get_object_or_404(BankAccount, account_number=data.get('sender_account'), user=request.user)
        validate_account(sender)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        receiver = serializer.validated_data['receiver_account']
        validate_account(receiver)
        payload = {'sender_account': sender.account_number, 'receiver_account': receiver.account_number,
                   'amount': str(serializer.validated_data['amount']),
                   'description': serializer.validated_data.get('description', '')}
        challenge, code = issue_challenge(request.user, 'transfer', payload)
        send_transfer_otp_email(request.user.email, code, payload)
        return Response({'message': 'Verify the emailed OTP to transfer.', 'challenge_id': str(challenge.pk)})


class VerifySecurityQuestionView(TransactionAuthView):
    serializer_class = ChallengeInputSerializer

    def post(self, request):
        return Response({'error': 'Security questions are retired. Initiate a transfer and verify its OTP.'}, status=410)


class VerifyOTPView(TransactionAuthView):
    serializer_class = ChallengeInputSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = complete_transaction(request.user, serializer.validated_data['challenge_id'],
                                      serializer.validated_data['otp'], 'transfer')
        return Response(TransactionSerializer(record).data, status=status.HTTP_201_CREATED)


class TransactionQuerysetMixin:
    def get_queryset(self):
        user = self.request.user
        return Transaction.objects.filter(
            Q(user=user) | Q(sender=user) | Q(receiver=user)
            | Q(sender_account__user=user) | Q(receiver_account__user=user)
        ).select_related(
            "sender", "receiver", "sender_account", "receiver_account"
        ).order_by("-created_at", "-id")


class TransactionListAPIView(TransactionQuerysetMixin, generics.ListAPIView):
    serializer_class = TransactionSerializer
    renderer_classes = [GenericJSONRenderer]
    pagination_class = StandardResultsSetPagination
    object_label = "transactions"


class TransactionPDFView(TransactionQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = TransactionSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "transaction"

    def retrieve(self, request:Request, *args:Any, **kwargs:Any) -> FileResponse:
        instance = self.get_object()
        buffer = BytesIO()
        document = canvas.Canvas(buffer)
        document.setTitle(f"Transaction receipt - {instance.id}")
        document.setFont("Helvetica-Bold", 16)
        document.drawString(50, 800, "FLOW BANK - Transaction Receipt")
        document.setFont("Helvetica", 11)
        details = [
            f"Reference: {instance.id}",
            f"Date: {instance.created_at:%Y-%m-%d %H:%M:%S %Z}",
            f"Type: {instance.get_transaction_type_display()}",
            f"Status: {instance.get_status_display()}",
            f"Amount: {instance.amount}",
            f"Sender: {instance.sender.full_name if instance.sender else '-'}",
            f"Receiver: {instance.receiver.full_name if instance.receiver else '-'}",
            f"Sender account: {instance.sender_account.account_number if instance.sender_account else '-'}",
            f"Receiver account: {instance.receiver_account.account_number if instance.receiver_account else '-'}",
        ]
        account = instance.sender_account or instance.receiver_account
        if account:
            details.append(f"Currency: {account.get_currency_display()}")
        # Wrap the description so a long value stays within the receipt margins.
        details.extend(wrap(f"Description: {instance.description or '-'}", width=80))
        for index, line in enumerate(details):
            document.drawString(50, 765 - index * 22, line)
        document.showPage()
        document.save()
        buffer.seek(0)
        return FileResponse(
            buffer, as_attachment=True,
            filename=f"transaction-{instance.id}.pdf", content_type="application/pdf",
        )
