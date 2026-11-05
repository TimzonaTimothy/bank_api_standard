from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from core_apps.user_auth.models import OTPChallenge
from core_apps.user_auth.security import issue_challenge
from .models import BankAccount, Transaction, StaffAuditLog
from .services import complete_transaction


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MoneyMovementSecurityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create(email='payer@example.com', username='payer', id_no=5001)
        cls.receiver = get_user_model().objects.create(email='recipient@example.com', username='recipient', id_no=5002)
        cls.teller = get_user_model().objects.create(email='teller@example.com', username='teller', id_no=5003, role='teller')
        cls.sender_account = BankAccount.objects.create(user=cls.user, account_number='5000000001', account_type='savings',
            account_balance='100.00', fully_activated=True, kyc_verified=True)
        cls.receiver_account = BankAccount.objects.create(user=cls.receiver, account_number='5000000002', account_type='savings',
            account_balance='0.00', fully_activated=True, kyc_verified=True)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def challenge(self, purpose='transfer', amount='25.00'):
        payload = {'sender_account': self.sender_account.account_number, 'amount': amount}
        if purpose == 'transfer':
            payload['receiver_account'] = self.receiver_account.account_number
        with patch('core_apps.user_auth.security.generate_otp', return_value='123456'):
            challenge, _ = issue_challenge(self.user, purpose, payload)
        return challenge

    def balances(self):
        self.sender_account.refresh_from_db()
        self.receiver_account.refresh_from_db()
        return self.sender_account.account_balance, self.receiver_account.account_balance

    def test_transfer_is_bound_to_payload_and_retry_is_idempotent(self):
        challenge = self.challenge()
        data = {'challenge_id': challenge.pk, 'otp': '123456', 'amount': '99.00'}
        first = self.client.post(reverse('verify_otp'), data)
        second = self.client.post(reverse('verify_otp'), data)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data, second.data)
        self.assertEqual(self.balances(), (Decimal('75.00'), Decimal('25.00')))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_transfer_rolls_back_if_ledger_fails(self):
        challenge = self.challenge()
        with patch('core_apps.accounts.services.Transaction.objects.create', side_effect=RuntimeError('Failed')):
            with self.assertRaises(RuntimeError):
                complete_transaction(self.user, challenge.pk, '123456', 'transfer')
        self.assertEqual(self.balances(), (Decimal('100.00'), Decimal('0.00')))
        challenge.refresh_from_db()
        self.assertIsNone(challenge.consumed_at)

    def test_account_status_is_rechecked_at_execution(self):
        challenge = self.challenge()
        BankAccount.objects.filter(pk=self.sender_account.pk).update(account_status='in-active')
        response = self.client.post(reverse('verify_otp'), {'challenge_id': challenge.pk, 'otp': '123456'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_other_user_cannot_complete_challenge(self):
        challenge = self.challenge()
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.client.post(reverse('verify_otp'), {'challenge_id': challenge.pk, 'otp': '123456'}).status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_username_is_not_withdrawal_authorization(self):
        self.assertEqual(self.client.post(reverse('verify_username_and_withdraw'), {'username': self.user.username}).status_code, 400)
        challenge = self.challenge('withdrawal')
        response = self.client.post(reverse('verify_username_and_withdraw'), {'challenge_id': challenge.pk, 'otp': '123456'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.balances()[0], Decimal('75.00'))

    @override_settings(TRANSACTION_LIMITS={'naira': '20.00'})
    def test_outgoing_limits_are_enforced(self):
        challenge = self.challenge()
        response = self.client.post(reverse('verify_otp'), {'challenge_id': challenge.pk, 'otp': '123456'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_deposit_has_ledger_audit_and_idempotency(self):
        self.client.force_authenticate(self.teller)
        payload = {'account_number': self.sender_account.account_number, 'amount': '10.00'}
        url = reverse('account_deposit')
        self.assertEqual(self.client.post(url, payload).status_code, 400)
        for _ in range(2):
            self.assertEqual(self.client.post(url, payload, HTTP_IDEMPOTENCY_KEY='deposit-1').status_code, 200)
        self.assertEqual(self.balances()[0], Decimal('110.00'))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(Transaction.objects.get().performed_by, self.teller)
        self.assertEqual(StaffAuditLog.objects.get().actor, self.teller)
        payload['amount'] = '20.00'
        self.assertEqual(self.client.post(url, payload, HTTP_IDEMPOTENCY_KEY='deposit-1').status_code, 400)

    def test_database_rejects_negative_balance(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BankAccount.objects.filter(pk=self.sender_account.pk).update(account_balance='-1.00')
