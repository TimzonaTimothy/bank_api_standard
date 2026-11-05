import random
from io import BytesIO
from textwrap import wrap
from typing import Any

from django.utils import timezone
from django.db.models import Q
from django.http import FileResponse
from reportlab.pdfgen import canvas
from rest_framework import generics, status, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from core_apps.common.permissions import IsAccountExecutive, IsTeller
from core_apps.common.renderers import GenericJSONRenderer
from core_apps.user_profile.views import StandardResultsSetPagination
from .emails import send_full_activation_email, send_deposit_email
from .models import BankAccount, Transaction
from .serializers import AccountVerificationSerializer, CustomerInfoSerializer, DepositSerializer, OTPVerificationSerializer, SecurityQuestionSerializer, TransactionSerializer, UsernameVerificationSerializer
from django.db import transaction
from decimal import Decimal 
from .emails import send_full_activation_email, send_deposit_email, send_withdrawal_email, send_transfer_email, send_transfer_otp_email
from loguru import logger

# Create your views here.


class AccountVerificationView(generics.UpdateAPIView):
    queryset = BankAccount.objects.all()
    serializer_class = AccountVerificationSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "Verification"
    permission_classes = [IsAccountExecutive]

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
                instance.verification_notes = serializer.validated_data.get(
                    "verification_notes",""
                )
                instance.verified_by = request.user
                instance.fully_activated = True 
                instance.account_status = BankAccount.AccountStatus.ACTIVE 
                instance.save()
                
                send_full_activation_email(instance) 
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
    object_label = 'deposit'
    permission_classes = [IsTeller]
    
    def get(self, request:Request, *args:Any, **kwarga:Any) -> Response:
        account_number = request.query_params.get("account_number")
        if not account_number:
            return Response(
                {"error":"Account number is required"}, 
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            account = BankAccount.objects.get(account_number=account_number)
            serializer = CustomerInfoSerializer(account)
            return Response(serializer.data) 
        except BankAccount.DoesNotExist:
            return Response(
                {'error':"Account number does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
    @transaction.atomic 
    def create(self, request:Request, *args:Any, **kwargs:Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        account = serializer.context['account']
        amount = serializer.context['amount']
        
        try:
            account.account_balance += amount 
            account.full_clean()
            account.save()
            
            logger.info(f"Deposit of {amount} made to account {account.account_number} by teller {request.user.email}")
            
            send_deposit_email(
                user=account.user,
                user_email=account.user.email,
                amount=amount, 
                currency=account.currency, 
                new_balance=account.account_balance,
                account_number=account.account_number,
            )
            return Response(
                {
                    "message":f"Successfully deposited {amount} to account {account.account_number}", 
                    "new_balance": str(account.account_balance), 
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f"Error during deposit: {str(e)}") 
            return Response(
                {"error":"An error occurred during the deposit"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
class InitiateWithdrawalView(generics.CreateAPIView):
    serializer_class = TransactionSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "initiate_withdrawal"
    
    def create(self, request:Request, *args:Any, **kwargs:Any) -> Response:
        account_number = request.data.get("account_number")
        amount = request.data.get("amount")
        
        if not account_number:
            return Response(
                {"error":"Account number is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            account = BankAccount.objects.get(account_number=account_number, user=request.user)
            if not (account.fully_activated and account.kyc_verified):
                return Response(
                    {"error":"Your account is not fully verified. Please complete the verification process"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        except BankAccount.DoesNotExist:
            return Response(
                {"error":"You are not authorized to withdraw from this account"},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = self.get_serializer(
            data = {
                "amount":amount,
                "description":f"Withdrawal from account {account_number}", 
                "transaction_type":Transaction.TransactionType.WITHDRAWAL,
                "sender_account":account_number,
                "receiver_account":account_number
            }
        )
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError as e:
            return Response({"error":str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        amount = serializer.validated_data['amount']
        
        if account.account_balance < amount:
            return Response(
                {"error":"Insufficient funds for withdrawal"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        request.session['withdrawal_data'] = {
            "account_number":account_number,
            "amount":str(amount),
        }
        logger.info("Withdrawal data stored in session")
        
        return Response(
            {
                "message": "Withdrawal Initiated. Please verify your username to complete the withdrawal",
                "next_step": "Verify your username to complete",
            },
            status=status.HTTP_200_OK,
        )
        
class VerifyUsernameAndWithdrawAPIView(generics.CreateAPIView):
    serializer_class = UsernameVerificationSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "verify_username_and_withdraw"
    
    @transaction.atomic 
    def create(self, request:Request, *args:Any, **kwargs:Any) -> Response:
        serializer = self.get_serializer(
            data=request.data, context={"request":request}
        )    
        serializer.is_valid(raise_exception=True)
        withdrawal_data = request.session.get("withdrawal_data")
        if not withdrawal_data:
            return Response(
                {"error":"No pending withdrawal found. Please initiate a withdrawal first"},
                status = status.HTTP_400_BAD_REQUEST
            )
        account_number = withdrawal_data["account_number"]
        amount = Decimal(withdrawal_data["amount"])
        
        try:
            account = BankAccount.objects.get(account_number=account_number, user=request.user)
        except BankAccount.DoesNotExist:
            return Response(
                {"error":f"Account number {account_number} does not exists"},
                status=status.HTTP_404_NOT_FOUND,
            )
        if account.account_balance < amount:
            return Response(
                {"error":"Insufficient funds for withdrawal"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        account.account_balance -= amount
        account.save()
        
        withdraw_transaction = Transaction.objects.create(
            user=request.user,
            sender=request.user,
            sender_account=account, 
            amount=amount,
            description=f"Withdrawal from account {account_number}",
            transaction_type=Transaction.TransactionType.WITHDRAWAL,
            status=Transaction.TransactionStatus.COMPLETED,
        )
        logger.info(f"Withdrawal of {amount} made from account {account_number}")
        
        send_withdrawal_email(
            user=account.user,
            user_email=account.user.email, 
            amount=amount, 
            currency=account.currency, 
            new_balance=account.account_balance,
            account_number=account.account_number
        )
        
        del request.session["withdrawal_data"]
        
        return Response(
            {
                "message":"Withdrawal Completed Successfully", 
                "transaction":TransactionSerializer(withdraw_transaction).data
            }, 
            status=status.HTTP_200_OK
        )
        

class InitiateTransferView(generics.CreateAPIView):
    serializer_class = TransactionSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "initiate_transfer"
    
    def create(self, request:Request, *args:Any, **kwargs:Any) -> Response:
        data = request.data.copy()
        data['transaction_type'] = Transaction.TransactionType.TRANSFER
        
        
        sender_account = data.get('sender_account')
        receiver_account = data.get('receiver_account')
        
        try:
            sender_account = BankAccount.objects.get(account_number=sender_account, user=request.user)
            if not(sender_account.fully_activated and sender_account.kyc_verified):
                return Response(
                    {"error":"Your account is not fully verified. Please complete the verification process"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            receiver_account = BankAccount.objects.get(account_number=receiver_account)
        except BankAccount.DoesNotExist:
            return Response(
                {"error":"Sender or receiver account does not exist or you're not authorized to use this account"},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(data=data)
        
        if serializer.is_valid():
            request.session['transfer_data'] = {
                "sender_account_number":sender_account.account_number,
                "receiver_account_number":receiver_account.account_number,
                "amount":str(serializer.validated_data['amount']),
                "description":serializer.validated_data.get('description', ''),
            }
            return Response(
                {
                "message":"Please answer the security question to proceed with the transfer",
                "next_step":"verify security question",
                }, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    
class VerifySecurityQuestionView(generics.CreateAPIView):
    serializer_class = SecurityQuestionSerializer 
    renderer_classes = [GenericJSONRenderer]
    object_label = "verification_answer"
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request":request})
        if serializer.is_valid():
            otp = "".join([str(random.randint(0, 9)) for _ in range(6)])  # Generate a random 6-digit OTP
            request.user.set_otp(otp)   
            send_transfer_otp_email(request.user.email, otp)
            return Response( 
                {
                    "message":"Security question verified. An OTP has been sent to your email. Please verify the OTP to complete the transfer",
                    "next_step":"verify OTP"
                },
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class VerifyOTPView(generics.CreateAPIView):
    serializer_class = OTPVerificationSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "verify_otp"
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request":request})
        if serializer.is_valid(): 
            return self.process_transfer(request)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def process_transfer(self, request) -> Response: 
        transfer_data = request.session.get("transfer_data") 
        if not transfer_data:
            return Response(
                {"error":"No pending transfer found. Please initiate a transfer first"},
                status=status.HTTP_400_BAD_REQUEST
            )
        try: 
            sender_account = BankAccount.objects.get(account_number=transfer_data["sender_account_number"], user=request.user)
            receiver_account = BankAccount.objects.get(account_number=transfer_data["receiver_account_number"])
        except BankAccount.DoesNotExist:
            return Response(
                {"error":"Sender or receiver account does not exist or you're not authorized to use this account"},
                status=status.HTTP_404_NOT_FOUND
            )
        amount = Decimal(transfer_data["amount"])
        if sender_account.account_balance < amount:
            return Response(
                {"error":"Insufficient funds for transfer"},
                status=status.HTTP_400_BAD_REQUEST
            )
        sender_account.account_balance -= amount
        receiver_account.account_balance += amount
        sender_account.save()
        receiver_account.save()
        
        transfer_transaction = Transaction.objects.create(
            user=request.user,
            sender=request.user,
            sender_account=sender_account,
            receiver_account=receiver_account,
            amount=amount,
            description=transfer_data.get("description", ""),
            transaction_type=Transaction.TransactionType.TRANSFER,
            status=Transaction.TransactionStatus.COMPLETED,
        )
        del request.session["transfer_data"]
        
        send_transfer_email(
            user=sender_account.user,
            user_email=sender_account.user.email,
            amount=amount,
            currency=sender_account.currency,
            new_balance=sender_account.account_balance,
            account_number=sender_account.account_number,
            receiver_account_number=receiver_account.account_number
        )
        
        logger.info(f"Transfer of {amount} from account {sender_account.account_number} to account {receiver_account.account_number} completed successfully")
        return Response(
           TransactionSerializer(transfer_transaction).data,
           status=status.HTTP_201_CREATED
        )


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
