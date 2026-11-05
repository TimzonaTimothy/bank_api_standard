from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import F
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from .emails import send_otp_email
from .models import User, OTPChallenge
from .security import enforce_csrf, issue_challenge, verify_challenge


def set_auth_cookies(response, access_token, refresh_token=None):
    for name, token, lifetime in [
        ("access", access_token, settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']),
        ("refresh", refresh_token, settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']),
    ]:
        if token:
            response.set_cookie(name, token, max_age=int(lifetime.total_seconds()),
                                path=settings.COOKIE_PATH, secure=settings.COOKIE_SECURE,
                                httponly=True, samesite=settings.COOKIE_SAMESITE)
    response.set_cookie("logged_in", "true", secure=settings.COOKIE_SECURE,
                        httponly=False, samesite=settings.COOKIE_SAMESITE)


class ChallengeInputSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    otp = serializers.RegexField(r"^\d{6}$")


class LoginInputSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class PublicAuthView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response


class CSRFTokenView(PublicAuthView):
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class CustomTokenCreateView(PublicAuthView):
    def post(self, request):
        enforce_csrf(request)
        serializer = LoginInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].lower()
        user = authenticate(request=request, username=email, password=serializer.validated_data['password'])
        if user is None or user.is_locked_out:
            # Lock counters are serialized to prevent parallel attempts losing updates.
            with transaction.atomic():
                existing = User.objects.select_for_update().filter(email=email).first()
                if existing and not existing.is_locked_out:
                    existing.handle_failed_login_attempts()
            return Response({"error": "Invalid credentials or account unavailable."}, status=400)
        challenge, code = issue_challenge(user, "login")
        send_otp_email(user.email, code)
        return Response({"message": "Verify the code sent to your email.", "challenge_id": str(challenge.pk)})


class OTPVerifyView(PublicAuthView):
    def post(self, request):
        enforce_csrf(request)
        serializer = ChallengeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not verify_challenge(data['challenge_id'], data['otp'], "login"):
            return Response({"error": "Invalid or expired challenge."}, status=400)
        with transaction.atomic():
            owner_id = OTPChallenge.objects.values_list('user_id', flat=True).get(pk=data['challenge_id'])
            user = User.objects.select_for_update().get(pk=owner_id)
            challenge = OTPChallenge.objects.select_for_update().get(pk=data['challenge_id'])
            if (challenge.consumed_at or challenge.expires_at <= timezone.now()
                    or not user.is_active or user.is_locked_out or challenge.auth_version != user.auth_version):
                return Response({"error": "Invalid or expired challenge."}, status=400)
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
            user.reset_failed_login_attempts()
            refresh = RefreshToken.for_user(user)
            refresh['auth_version'] = user.auth_version
            response = Response({"message": "Login successful."})
            set_auth_cookies(response, str(refresh.access_token), str(refresh))
            return response


class CustomTokenRefreshView(PublicAuthView):
    def post(self, request):
        enforce_csrf(request)
        raw = request.COOKIES.get("refresh") or request.data.get("refresh")
        try:
            with transaction.atomic():
                refresh = RefreshToken(raw)
                user = User.objects.select_for_update().get(pk=refresh['user_id'])
                if (not user.is_active or user.is_locked_out
                        or refresh.get('auth_version') != user.auth_version
                        or refresh.get('hash_password') != get_md5_hash_password(user.password)):
                    raise TokenError("Revoked token")
                serializer = TokenRefreshSerializer(data={"refresh": raw})
                serializer.is_valid(raise_exception=True)
        except (TokenError, User.DoesNotExist, KeyError, TypeError, ValueError):
            return Response({"error": "Invalid refresh token."}, status=401)
        response = Response({"message": "Tokens refreshed successfully."})
        set_auth_cookies(response, serializer.validated_data['access'], serializer.validated_data.get('refresh'))
        return response


class LogoutAPIView(APIView):
    def post(self, request):
        enforce_csrf(request)
        # Invalidate all tokens for this user, including already-issued access tokens.
        User.objects.filter(pk=request.user.pk).update(auth_version=F('auth_version') + 1)
        raw = request.COOKIES.get('refresh')
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        for name in ["access", "refresh", "logged_in"]:
            response.delete_cookie(name, path=settings.COOKIE_PATH, samesite=settings.COOKIE_SAMESITE)
        return response
