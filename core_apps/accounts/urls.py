from django.urls import path 
from .views import AccountVerificationSerializer

urlpatterns = [
    path("verify/<uuid:pk>/", AccountVerificationSerializer.as_view(), name="account_verification"),
]
