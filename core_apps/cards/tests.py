from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from core_apps.accounts.models import BankAccount, Transaction
from .models import VirtualCard
from .utils import create_virtual_card


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CardEndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create(email="cards@example.com", username="cards", id_no=2001)
        cls.other = User.objects.create(email="other@example.com", username="other", id_no=2002)
        cls.account = BankAccount.objects.create(
            user=cls.user, account_number="2000000001", account_type="savings",
            account_balance="100.00", fully_activated=True, kyc_verified=True,
        )
        cls.other_account = BankAccount.objects.create(
            user=cls.other, account_number="2000000002", account_type="savings",
            fully_activated=True, kyc_verified=True,
        )
        cls.card = create_virtual_card(cls.user, cls.account.account_number)
        cls.other_card = create_virtual_card(cls.other, cls.other_account.account_number)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def top_up(self, amount="25.00"):
        return self.client.post(reverse("cards:card_top_up", args=[self.card.pk]), {"amount": amount})

    def assert_balances_unchanged(self):
        self.account.refresh_from_db()
        self.card.refresh_from_db()
        self.assertEqual(self.account.account_balance, Decimal("100.00"))
        self.assertEqual(self.card.balance, Decimal("0.00"))
        self.assertFalse(Transaction.objects.exists())

    def test_create_card(self):
        response = self.client.post(reverse("cards:card_list_create"), {
            "bank_account": self.account.account_number,
        })
        self.assertEqual(response.status_code, 201)
        card = VirtualCard.objects.get(pk=response.json()["cards"]["id"])
        self.assertEqual(len(card.card_number), 16)
        self.assertNotEqual(card.card_number, self.card.card_number)
        self.assertGreater(card.expiry_date, timezone.localdate())
        self.assertEqual(response.json()["cards"]["card_number"], card.masked_card_number)

    def test_create_rejects_another_users_account(self):
        response = self.client.post(reverse("cards:card_list_create"), {
            "bank_account": self.other_account.account_number,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(VirtualCard.objects.count(), 2)

    def test_create_requires_verified_active_account(self):
        self.account.kyc_verified = False
        self.account.save()
        response = self.client.post(reverse("cards:card_list_create"), {
            "bank_account": self.account.account_number,
        })
        self.assertEqual(response.status_code, 400)

    def test_list_is_paginated_and_owned(self):
        create_virtual_card(self.user, self.account.account_number)
        response = self.client.get(reverse("cards:card_list_create"), {"page_size": 1})
        data = response.json()["cards"]
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNotNone(data["next"])

    def test_detail_and_status(self):
        response = self.client.get(reverse("cards:card_detail", args=[self.card.pk]))
        self.assertEqual(response.status_code, 200)
        for is_active in [False, True]:
            response = self.client.patch(
                reverse("cards:card_status", args=[self.card.pk]),
                {"is_active": is_active}, format="json",
            )
            self.assertEqual(response.status_code, 200)
            self.card.refresh_from_db()
            self.assertEqual(self.card.is_active, is_active)

    def test_top_up_updates_balances_records_transaction_and_sends_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.top_up()
        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db()
        self.card.refresh_from_db()
        self.assertEqual(self.account.account_balance, Decimal("75.00"))
        self.assertEqual(self.card.balance, Decimal("25.00"))
        record = Transaction.objects.get()
        self.assertEqual(record.sender_account, self.account)
        self.assertEqual(record.amount, Decimal("25.00"))
        self.assertEqual(record.status, "completed")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn(self.card.masked_card_number, mail.outbox[0].body)
        self.assertNotIn(self.card.card_number, mail.outbox[0].body)

    def test_invalid_amounts_do_not_change_balances(self):
        for amount in ["0", "-1", "1.001", "NaN", "101.00"]:
            with self.subTest(amount=amount):
                self.assertEqual(self.top_up(amount).status_code, 400)
                self.assert_balances_unchanged()

    def test_frozen_and_expired_cards_cannot_be_topped_up(self):
        self.card.is_active = False
        self.card.save()
        self.assertEqual(self.top_up().status_code, 400)
        self.assert_balances_unchanged()
        self.card.is_active = True
        self.card.expiry_date = timezone.localdate() - timezone.timedelta(days=1)
        self.card.save()
        self.assertEqual(self.top_up().status_code, 400)
        self.assert_balances_unchanged()

    def test_transaction_failure_rolls_back_both_balances(self):
        with patch("core_apps.cards.utils.Transaction.objects.create", side_effect=RuntimeError("Failed")):
            with self.assertRaises(RuntimeError):
                self.top_up()
        self.assert_balances_unchanged()

    def test_other_users_cannot_access_or_modify_cards(self):
        for name, method, data in [
            ("card_detail", self.client.get, {}),
            ("card_status", self.client.patch, {"is_active": False}),
            ("card_top_up", self.client.post, {"amount": "25.00"}),
        ]:
            with self.subTest(name=name):
                response = method(reverse(f"cards:{name}", args=[self.other_card.pk]), data)
                self.assertEqual(response.status_code, 404)

    def test_anonymous_requests_are_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(reverse("cards:card_list_create")).status_code, 401)
        self.assertEqual(self.top_up().status_code, 401)
