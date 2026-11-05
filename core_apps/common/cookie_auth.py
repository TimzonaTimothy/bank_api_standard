from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from core_apps.user_auth.security import enforce_csrf


class CookieAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        cookie_auth = header is None
        raw = request.COOKIES.get('access') if cookie_auth else self.get_raw_token(header)
        if not raw:
            return None
        token = self.get_validated_token(raw)
        user = self.get_user(token)
        if token.get('auth_version') != user.auth_version or user.is_locked_out:
            raise AuthenticationFailed('Session revoked or account locked.')
        if cookie_auth:
            enforce_csrf(request)
        return user, token
