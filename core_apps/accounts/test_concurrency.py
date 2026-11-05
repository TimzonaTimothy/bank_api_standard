from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.hashers import make_password
from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core_apps.user_auth.models import User, OTPChallenge
from .models import BankAccount, Transaction
from .services import complete_transaction


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required')
class ConcurrentMoneyMovementTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(email='parallel@example.com', username='parallel', id_no=6001)
        self.other = User.objects.create(email='parallel2@example.com', username='parallel2', id_no=6002)
        self.account = BankAccount.objects.create(user=self.user, account_number='6000000001', account_type='savings',
            account_balance='100.00', fully_activated=True, kyc_verified=True)
        self.receiver = BankAccount.objects.create(user=self.other, account_number='6000000002', account_type='savings',
            fully_activated=True, kyc_verified=True)

    def challenge(self, purpose):
        payload = {'sender_account': self.account.account_number, 'amount': '75.00'}
        if purpose == 'transfer':
            payload['receiver_account'] = self.receiver.account_number
        return OTPChallenge.objects.create(
            user=self.user, purpose=purpose, code_hash=make_password('123456'), payload=payload,
            auth_version=0, expires_at=timezone.now() + timedelta(minutes=5),
        )

    def execute_parallel(self, operations):
        barrier = Barrier(2)
        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                challenge_id, purpose = operation
                try:
                    return str(complete_transaction(self.user, challenge_id, '123456', purpose).pk)
                except ValidationError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, operations))

    def test_parallel_spending_cannot_overdraw(self):
        transfer = self.challenge('transfer')
        withdrawal = self.challenge('withdrawal')
        results = self.execute_parallel([(transfer.pk, 'transfer'), (withdrawal.pk, 'withdrawal')])
        self.assertEqual(sum(result is not None for result in results), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.account_balance, Decimal('25.00'))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_parallel_retries_create_one_transaction(self):
        challenge = self.challenge('transfer')
        results = self.execute_parallel([(challenge.pk, 'transfer'), (challenge.pk, 'transfer')])
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0], results[1])
        self.assertEqual(Transaction.objects.count(), 1)
