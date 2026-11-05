from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied, Throttled

from .models import OTPChallenge, User
from .utils import generate_otp


def enforce_csrf(request):
    check = CSRFCheck(lambda request: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise PermissionDenied("CSRF verification failed.")


@transaction.atomic
def issue_challenge(user, purpose, payload=None):
    user = User.objects.select_for_update().get(pk=user.pk)
    now = timezone.now()
    if OTPChallenge.objects.filter(user=user, purpose=purpose, created_at__gt=now - timedelta(seconds=60)).exists():
        raise Throttled(wait=60, detail="Please wait before requesting another code.")
    OTPChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(consumed_at=now)
    code = generate_otp()
    challenge = OTPChallenge.objects.create(
        user=user, purpose=purpose, payload=payload or {}, code_hash=make_password(code),
        auth_version=user.auth_version, expires_at=now + settings.OTP_EXPIRATION,
    )
    return challenge, code


def verify_challenge(challenge_id, code, purpose, user=None):
    # Persist failed attempts even when the caller subsequently rejects the request.
    with transaction.atomic():
        challenge = OTPChallenge.objects.select_for_update().filter(pk=challenge_id, purpose=purpose).first()
        if challenge is None or (user is not None and challenge.user_id != user.pk):
            return False
        if challenge.consumed_at or challenge.expires_at <= timezone.now() or challenge.attempts >= 5:
            return False
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        return check_password(code, challenge.code_hash)
