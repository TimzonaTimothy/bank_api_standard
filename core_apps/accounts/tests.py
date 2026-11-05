from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse, resolve
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import BankAccount, Transaction
from .views import InitiateTransferView, VerifySecurityQuestionView, VerifyOTPView


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TransactionEndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create(
            email="customer@example.com", username="customer", id_no=1001,
        )
        cls.other = User.objects.create(
            email="other@example.com", username="other", id_no=1002,
        )
        cls.account = BankAccount.objects.create(
            user=cls.user, account_number="1000000001", account_type="savings",
        )
        cls.other_account = BankAccount.objects.create(
            user=cls.other, account_number="1000000002", account_type="savings",
            fully_activated=True, kyc_verified=True,
        )
        cls.outgoing = Transaction.objects.create(
            user=cls.user, sender=cls.user, sender_account=cls.account,
            amount="25.00", transaction_type="withdrawal", status="completed",
        )
        cls.incoming = Transaction.objects.create(
            user=cls.other, sender=cls.other, sender_account=cls.other_account,
            receiver_account=cls.account, amount="50.00", transaction_type="transfer",
        )
        cls.unrelated = Transaction.objects.create(
            user=cls.other, sender_account=cls.other_account,
            amount="10.00", transaction_type="withdrawal",
        )

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_transfer_urls_resolve(self):
        for name, view in [
            ("initiate_transfer", InitiateTransferView),
            ("verify_security_question", VerifySecurityQuestionView),
            ("verify_otp", VerifyOTPView),
        ]:
            with self.subTest(name=name):
                self.assertIs(resolve(reverse(name)).func.view_class, view)

    def test_list_includes_incoming_and_outgoing_transactions_only(self):
        response = self.client.get(reverse("transaction_list"))
        self.assertEqual(response.status_code, 200)
        data = response.json()["transactions"]
        self.assertEqual(data["count"], 2)
        self.assertEqual(
            {item["id"] for item in data["results"]},
            {str(self.outgoing.id), str(self.incoming.id)},
        )

    def test_initiate_transfer_stores_pending_transfer(self):
        self.account.account_balance = "100.00"
        self.account.fully_activated = True
        self.account.kyc_verified = True
        self.account.save()
        response = self.client.post(reverse("initiate_transfer"), {
            "sender_account": self.account.account_number,
            "receiver_account": self.other_account.account_number,
            "amount": "25.00",
            "description": "Test transfer",
        })
        self.assertEqual(response.status_code, 200)
        from core_apps.user_auth.models import OTPChallenge
        self.assertEqual(OTPChallenge.objects.get(pk=response.json()["transaction"]["challenge_id"]).payload["amount"], "25.00")
        self.account.refresh_from_db()
        self.assertEqual(str(self.account.account_balance), "100.00")

    def test_security_questions_are_retired(self):
        response = self.client.post(reverse("verify_security_question"), {"security_answer": "blue"})
        self.assertEqual(response.status_code, 410)

    def test_verify_otp_requires_challenge(self):
        response = self.client.post(reverse("verify_otp"), {"otp": "123456"})
        self.assertEqual(response.status_code, 400)

    def test_list_pagination(self):
        response = self.client.get(reverse("transaction_list"), {"page_size": 1})
        data = response.json()["transactions"]
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNotNone(data["next"])
        second = self.client.get(data["next"]).json()["transactions"]
        self.assertNotEqual(data["results"][0]["id"], second["results"][0]["id"])
        self.assertIsNone(second["next"])

    def test_pdf_download(self):
        for instance in [self.outgoing, self.incoming]:
            with self.subTest(transaction=instance.id):
                response = self.client.get(reverse("transaction_pdf", args=[instance.id]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertIn(f"transaction-{instance.id}.pdf", response["Content-Disposition"])
                self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
                response.close()

    def test_pdf_rejects_unrelated_and_missing_transactions(self):
        for pk in [self.unrelated.id, uuid4()]:
            with self.subTest(pk=pk):
                response = self.client.get(reverse("transaction_pdf", args=[pk]))
                self.assertEqual(response.status_code, 404)

    def test_authentication_required(self):
        self.client.force_authenticate(user=None)
        for url in [reverse("transaction_list"), reverse("transaction_pdf", args=[self.outgoing.id])]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, [401, 403])
