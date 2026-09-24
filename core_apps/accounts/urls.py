from django.urls import path 
from .views import AccountVerificationSerializer, DepositView, InitiateWithdrawalView,VerifyUsernameAndWithdrawAPIView

urlpatterns = [
    path("verify/<uuid:pk>/", AccountVerificationSerializer.as_view(), name="account_verification"),
    path("deposit/", DepositView.as_view(), name="account_deposit"),
    path("initiate-withdrawal/", InitiateWithdrawalView.as_view(), name="initiate_withdrawal"),
    path("verify-username-and-wthdraw/", VerifyUsernameAndWithdrawAPIView.as_view(), name="verify_username_and_withdraw"),
]
