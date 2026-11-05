from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import BankAccount, Transaction, SavingsInterest, SuspiciousActivityAlert
from .tasks import daily_savings_interest, detect_suspicious_activity


@override_settings(
    SAVINGS_ANNUAL_INTEREST_RATE="0.0365",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SUSPICIOUS_ACTIVITY_AMOUNT_THRESHOLDS={"naira": "1000"},
    SUSPICIOUS_ACTIVITY_TRANSACTION_COUNT=3,
    SUSPICIOUS_ACTIVITY_WINDOW_MINUTES=60,
)
class AccountTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create(
            email="interest@example.com", username="interest", id_no=3001,
        )
        cls.account = BankAccount.objects.create(
            user=cls.user, account_number="3000000001", account_type="savings",
            account_balance=Decimal("1000.00"), kyc_verified=True, fully_activated=True,
        )

    def outgoing(self, amount="1000", **kwargs):
        return Transaction.objects.create(
            user=self.user, sender=self.user, sender_account=self.account,
            amount=amount, transaction_type="withdrawal", status="completed", **kwargs,
        )

    def test_calculate_interest(self):
        self.assertEqual(self.account.calculate_interest(), Decimal("0.10"))
        self.assertEqual(self.account.calculate_interest(days=30), Decimal("3.00"))
        self.account.account_type = "current"
        self.assertEqual(self.account.calculate_interest(), Decimal("0.00"))
        with self.assertRaises(ValueError):
            self.account.calculate_interest(days=0)

    def test_daily_interest_is_credited_only_once(self):
        self.assertEqual(daily_savings_interest(), 1)
        self.assertEqual(daily_savings_interest(), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.account_balance, Decimal("1000.10"))
        credit = SavingsInterest.objects.get()
        self.assertEqual(credit.opening_balance, Decimal("1000.00"))
        self.assertEqual(credit.amount, Decimal("0.10"))
        self.assertEqual(credit.transaction.receiver_account, self.account)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_ineligible_accounts_receive_no_interest(self):
        for field, value in [
            ("account_type", "current"), ("account_status", "in-active"),
            ("kyc_verified", False), ("fully_activated", False),
            ("account_balance", Decimal("0.00")),
        ]:
            with self.subTest(field=field):
                BankAccount.objects.filter(pk=self.account.pk).update(**{field: value})
                self.assertEqual(daily_savings_interest(), 0)
                BankAccount.objects.filter(pk=self.account.pk).update(**{field: getattr(self.account, field)})
        self.assertFalse(SavingsInterest.objects.exists())

    def test_credit_failure_rolls_back_balance(self):
        with patch("core_apps.accounts.models.Transaction.objects.create", side_effect=RuntimeError("Failed")):
            with self.assertRaises(RuntimeError):
                daily_savings_interest()
        self.account.refresh_from_db()
        self.assertEqual(self.account.account_balance, Decimal("1000.00"))
        self.assertFalse(SavingsInterest.objects.exists())

    def test_low_balance_rounding_is_recorded_without_zero_transaction(self):
        BankAccount.objects.filter(pk=self.account.pk).update(account_balance="0.01")
        self.assertEqual(daily_savings_interest(), 1)
        self.assertEqual(SavingsInterest.objects.get().amount, Decimal("0.00"))
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(daily_savings_interest(), 0)

    def test_large_transaction_sends_one_alert(self):
        item = self.outgoing()
        self.assertEqual(detect_suspicious_activity(), 1)
        self.assertEqual(detect_suspicious_activity(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn(str(item.id), mail.outbox[0].body)
        self.assertNotIn(self.account.account_number, mail.outbox[0].body)
        self.assertIsNotNone(SuspiciousActivityAlert.objects.get().notified_at)

    def test_frequent_small_transactions_are_detected(self):
        for _ in range(3):
            self.outgoing(amount="10")
        self.assertEqual(detect_suspicious_activity(), 3)
        self.assertEqual(SuspiciousActivityAlert.objects.count(), 3)

    def test_normal_old_failed_and_incoming_transactions_are_ignored(self):
        self.outgoing(amount="10")
        old = self.outgoing()
        Transaction.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=2))
        failed = self.outgoing()
        Transaction.objects.filter(pk=failed.pk).update(status="failed")
        Transaction.objects.create(
            receiver_account=self.account, amount="10000", transaction_type="deposit", status="completed",
        )
        self.assertEqual(detect_suspicious_activity(), 0)
        self.assertFalse(SuspiciousActivityAlert.objects.exists())

    def test_failed_email_is_retried_even_after_detection_window(self):
        item = self.outgoing()
        with patch("core_apps.accounts.tasks.send_suspicious_activity_email", side_effect=RuntimeError("Email unavailable")):
            detect_suspicious_activity()
        alert = SuspiciousActivityAlert.objects.get()
        self.assertIsNone(alert.notified_at)
        Transaction.objects.filter(pk=item.pk).update(created_at=timezone.now() - timedelta(days=1))
        detect_suspicious_activity()
        alert.refresh_from_db()
        self.assertIsNotNone(alert.notified_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_beat_schedule_and_scheduler(self):
        self.assertEqual(settings.CELERY_BEAT_SCHEDULER, "django_celery_beat.schedulers:DatabaseScheduler")
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["daily-savings-interest"]["task"], daily_savings_interest.name)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["detect-suspicious-activity"]["task"], detect_suspicious_activity.name)
