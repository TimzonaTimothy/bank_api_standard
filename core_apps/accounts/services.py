import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core_apps.user_auth.models import User, OTPChallenge
from core_apps.user_auth.security import verify_challenge
from .models import BankAccount, Transaction, IdempotencyRecord


def validate_account(account):
    if (not account.fully_activated or not account.kyc_verified
            or account.account_status != BankAccount.AccountStatus.ACTIVE):
        raise serializers.ValidationError({"account": "Account must be active and fully verified."})


def validate_outgoing_limit(account, amount):
    limit = Decimal(str(settings.TRANSACTION_LIMITS[account.currency]))
    today = timezone.localdate()
    spent = Transaction.objects.filter(
        sender_account=account, status="completed", created_at__date=today,
        transaction_type__in=["withdrawal", "transfer"],
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    if amount > limit or spent + amount > limit:
        raise serializers.ValidationError({"amount": "Daily outgoing transaction limit exceeded."})


def execute_idempotently(request, scope, callback):
    key = request.headers.get('Idempotency-Key', '')
    if not key or len(key) > 128:
        raise serializers.ValidationError({"idempotency_key": "Provide an Idempotency-Key header of 1–128 characters."})
    fingerprint = hashlib.sha256(json.dumps(
        {'path': request.path, 'data': request.data}, sort_keys=True, default=str,
    ).encode()).hexdigest()
    with transaction.atomic():
        # Also serializes simultaneous retries before the unique key exists.
        User.objects.select_for_update().get(pk=request.user.pk)
        previous = IdempotencyRecord.objects.filter(user=request.user, scope=scope, key=key).first()
        if previous:
            if previous.fingerprint != fingerprint:
                raise serializers.ValidationError({"idempotency_key": "This key was used for different request data."})
            return Response(previous.response, status=previous.status_code)
        response = callback()
        if 200 <= response.status_code < 300:
            IdempotencyRecord.objects.create(
                user=request.user, scope=scope, key=key, fingerprint=fingerprint,
                response=response.data, status_code=response.status_code,
            )
        return response


def complete_transaction(user, challenge_id, code, purpose):
    # Failed attempts must commit independently of failed financial operations.
    existing = OTPChallenge.objects.filter(pk=challenge_id, user=user, purpose=purpose).first()
    if (existing and existing.result_id and existing.auth_version == user.auth_version
            and check_password(code, existing.code_hash)):
        return existing.result
    if not verify_challenge(challenge_id, code, purpose, user):
        # A concurrent retry may have completed between the initial read and verification.
        completed = OTPChallenge.objects.filter(pk=challenge_id, user=user, purpose=purpose, result__isnull=False).first()
        if (completed and completed.auth_version == user.auth_version
                and check_password(code, completed.code_hash)):
            return completed.result
        raise serializers.ValidationError({"otp": "Invalid or expired challenge."})
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if not user.is_active or user.is_locked_out:
            raise PermissionDenied('Account unavailable.')
        challenge = OTPChallenge.objects.select_for_update().get(pk=challenge_id)
        if challenge.result_id:
            return challenge.result
        if (challenge.consumed_at or challenge.expires_at <= timezone.now()
                or challenge.auth_version != user.auth_version):
            raise serializers.ValidationError({"otp": "Invalid or expired challenge."})
        payload = challenge.payload
        numbers = [payload['sender_account']]
        if purpose == 'transfer':
            numbers.append(payload['receiver_account'])
        accounts = list(BankAccount.objects.select_for_update().filter(account_number__in=numbers).order_by('pk'))
        by_number = {account.account_number: account for account in accounts}
        sender = by_number.get(payload['sender_account'])
        receiver = by_number.get(payload.get('receiver_account'))
        if sender is None or sender.user_id != user.pk:
            raise PermissionDenied('Account unavailable.')
        validate_account(sender)
        amount = Decimal(payload['amount'])
        validate_outgoing_limit(sender, amount)
        if sender.account_balance < amount:
            raise serializers.ValidationError({"amount": "Insufficient funds."})
        if purpose == 'transfer':
            if receiver is None or receiver.pk == sender.pk or receiver.currency != sender.currency:
                raise serializers.ValidationError({"receiver_account": "Invalid recipient account."})
            validate_account(receiver)
            if receiver.account_balance + amount > Decimal('9999999999.99'):
                raise serializers.ValidationError({"amount": "Recipient balance limit exceeded."})
            BankAccount.objects.filter(pk=receiver.pk).update(account_balance=receiver.account_balance + amount, updated_at=timezone.now())
        BankAccount.objects.filter(pk=sender.pk).update(account_balance=sender.account_balance - amount, updated_at=timezone.now())
        record = Transaction.objects.create(
            user=user, performed_by=user, sender=user, sender_account=sender,
            receiver=receiver.user if receiver else None, receiver_account=receiver,
            amount=amount, description=payload.get('description', ''),
            transaction_type=purpose, status='completed',
        )
        challenge.consumed_at = timezone.now()
        challenge.result = record
        challenge.save(update_fields=['consumed_at', 'result'])
        from .emails import send_withdrawal_email, send_transfer_email
        from functools import partial
        if receiver:
            transaction.on_commit(partial(
                send_transfer_email, sender_name=user.full_name, sender_email=user.email,
                receiver_name=receiver.user.full_name, receiver_email=receiver.user.email,
                amount=amount, currency=sender.currency,
                sender_new_balance=sender.account_balance - amount,
                receiver_new_balance=receiver.account_balance + amount,
                sender_account_number=sender.account_number, receiver_account_number=receiver.account_number,
            ))
        else:
            transaction.on_commit(partial(
                send_withdrawal_email, user, user.email, amount, sender.currency,
                sender.account_balance - amount, sender.account_number,
            ))
        return record
