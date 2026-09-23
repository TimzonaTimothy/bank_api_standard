from django.urls import path 
from .views import AccountVerificationSerializer, DepositView

urlpatterns = [
    path("verify/<uuid:pk>/", AccountVerificationSerializer.as_view(), name="account_verification"),
    path("deposit/", DepositView.as_view(), name="account_deposit"),
]
