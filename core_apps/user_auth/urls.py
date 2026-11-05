from django.urls import path 


from .views import (
    CustomTokenCreateView,CustomTokenRefreshView, LogoutAPIView,OTPVerifyView, CSRFTokenView
)

urlpatterns =[
    path('csrf/', CSRFTokenView.as_view(), name="csrf_token"),
    path('login/', CustomTokenCreateView.as_view(), name="login"),
    path('very-otp/', OTPVerifyView.as_view(), name="verify_login_otp"),
    path('verify-otp/', OTPVerifyView.as_view(), name="verify_login_challenge"),
    path("refresh/", CustomTokenRefreshView.as_view(), name="refresh"),
    path('logout/', LogoutAPIView.as_view(), name="logout"),
]
