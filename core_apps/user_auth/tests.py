from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.hashers import check_password, make_password
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTPChallenge, User
from .security import issue_challenge


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationSecurityTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            email='secure@example.com', username='secure', id_no=4001,
            password=make_password('Correct-password-123!'), security_answer='blue',
        )

    def login_challenge(self):
        with patch('core_apps.user_auth.security.generate_otp', return_value='123456'):
            response = self.client.post(reverse('login'), {
                'email': self.user.email, 'password': 'Correct-password-123!',
            })
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['challenge_id']

    def verify(self, challenge_id, code='123456'):
        return self.client.post(reverse('verify_login_otp'), {'challenge_id': challenge_id, 'otp': code})

    def authenticated_token(self):
        refresh = RefreshToken.for_user(self.user)
        refresh['auth_version'] = self.user.auth_version
        return refresh

    def test_otp_requires_password_verified_challenge_and_is_hashed(self):
        self.assertEqual(self.verify(uuid4()).status_code, 400)
        challenge_id = self.login_challenge()
        challenge = OTPChallenge.objects.get(pk=challenge_id)
        self.assertNotEqual(challenge.code_hash, '123456')
        self.assertTrue(check_password('123456', challenge.code_hash))
        response = self.verify(challenge_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.cookies)
        self.assertEqual(self.verify(challenge_id).status_code, 400)

    def test_transfer_code_cannot_issue_login_tokens(self):
        with patch('core_apps.user_auth.security.generate_otp', return_value='123456'):
            challenge, _ = issue_challenge(self.user, 'transfer', {'amount': '10'})
        self.assertEqual(self.verify(challenge.pk).status_code, 400)

    def test_five_wrong_attempts_lock_challenge(self):
        challenge_id = self.login_challenge()
        for _ in range(5):
            self.assertEqual(self.verify(challenge_id, '999999').status_code, 400)
        self.assertEqual(self.verify(challenge_id).status_code, 400)
        self.assertEqual(OTPChallenge.objects.get(pk=challenge_id).attempts, 5)

    def test_expired_challenge_and_resend_limit(self):
        challenge_id = self.login_challenge()
        OTPChallenge.objects.filter(pk=challenge_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(challenge_id).status_code, 400)
        response = self.client.post(reverse('login'), {'email': self.user.email, 'password': 'Correct-password-123!'})
        self.assertEqual(response.status_code, 429)

    def test_cookie_requests_require_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('login'), {'email': self.user.email, 'password': 'Correct-password-123!'}).status_code, 403)
        response = client.get(reverse('csrf_token'))
        token = response.data['csrfToken']
        with patch('core_apps.user_auth.views.send_otp_email'):
            response = client.post(reverse('login'), {'email': self.user.email, 'password': 'Correct-password-123!'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        client.cookies['access'] = str(self.authenticated_token().access_token)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
        self.assertEqual(client.post(reverse('logout'), HTTP_X_CSRFTOKEN=token).status_code, 204)

    def test_logout_revokes_access_and_refresh(self):
        refresh = self.authenticated_token()
        access = str(refresh.access_token)
        self.client.cookies['access'] = access
        self.client.cookies['refresh'] = str(refresh)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 204)
        self.client.cookies['access'] = access
        self.assertEqual(self.client.get(reverse('transaction_list')).status_code, 401)
        self.assertEqual(self.client.post(reverse('refresh'), {'refresh': str(refresh)}).status_code, 401)

    def test_password_change_revokes_tokens_and_challenges(self):
        refresh = self.authenticated_token()
        challenge_id = self.login_challenge()
        self.user.set_password('New-password-456!')
        self.user.save(update_fields=['password'])
        self.client.cookies['access'] = str(refresh.access_token)
        self.assertEqual(self.client.get(reverse('transaction_list')).status_code, 401)
        self.assertEqual(self.client.post(reverse('refresh'), {'refresh': str(refresh)}).status_code, 401)
        self.assertEqual(self.verify(challenge_id).status_code, 400)

    def test_refresh_rotation_revokes_old_token(self):
        refresh = self.authenticated_token()
        self.assertEqual(self.client.post(reverse('refresh'), {'refresh': str(refresh)}).status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.post(reverse('refresh'), {'refresh': str(refresh)}).status_code, 401)

    def test_security_answer_is_hashed_and_not_serialized(self):
        from .serializers import UserCreateSerializer
        self.user.refresh_from_db()
        self.assertTrue(check_password('blue', self.user.security_answer))
        data = UserCreateSerializer(self.user).data
        self.assertNotIn('security_answer', data)
        self.assertNotIn('password', data)
