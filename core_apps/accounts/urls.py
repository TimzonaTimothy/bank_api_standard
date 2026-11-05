from django.urls import path 
from .views import (
    AccountVerificationView, DepositView, InitiateWithdrawalView,
    VerifyUsernameAndWithdrawAPIView, InitiateTransferView,
    VerifySecurityQuestionView, VerifyOTPView, TransactionListAPIView,
    TransactionPDFView,
)

urlpatterns = [
    path("verify/<uuid:pk>/", AccountVerificationView.as_view(), name="account_verification"),
    path("deposit/", DepositView.as_view(), name="account_deposit"),
    path("initiate-withdrawal/", InitiateWithdrawalView.as_view(), name="initiate_withdrawal"),
    path("verify-username-and-wthdraw/", VerifyUsernameAndWithdrawAPIView.as_view(), name="verify_username_and_withdraw"),
    path("initiate-transfer/", InitiateTransferView.as_view(), name="initiate_transfer"),
    path("verify-security-question/", VerifySecurityQuestionView.as_view(), name="verify_security_question"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify_otp"),
    path("transactions/", TransactionListAPIView.as_view(), name="transaction_list"),
    path("transactions/<uuid:pk>/pdf/", TransactionPDFView.as_view(), name="transaction_pdf"),
]
